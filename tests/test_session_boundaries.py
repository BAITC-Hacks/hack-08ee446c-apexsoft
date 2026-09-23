import asyncio
import io
import time

import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.errors import AppError


@pytest.fixture
def client(monkeypatch):
    for name in ('EKT_API_USERNAME', 'EKT_API_PASSWORD', 'OPENAI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    with TestClient(create_app()) as c:
        c.headers['X-CSRF-Token'] = c.get('/api/session').json()['csrf_token']
        yield c


def upload(c):
    document = Document(); document.add_paragraph('DEMO-LAMP-10W-B')
    data = io.BytesIO(); document.save(data)
    response = c.post('/api/attachments', files={'file': ('spec.docx', data.getvalue())})
    assert response.status_code == 200, response.text
    return response.json()['attachment_id']


def propose(c):
    response = c.post('/api/cart/propose', json={'product_id': '900002', 'quantity': 2})
    assert response.status_code == 200, response.text
    return response.json()['proposal']['confirmation_id']


@pytest.mark.parametrize('path', ['/api/cart/confirm', '/api/cart/cancel'])
def test_unicode_confirmation_rejected_without_destroying_proposal(client, path):
    token = propose(client)
    response = client.post(path, json={'confirmation_id': 'я' * 10, 'confirmed': True})
    assert response.status_code == 422
    assert client.get('/api/cart').json()['count'] == 0
    assert client.post('/api/cart/confirm', json={'confirmation_id': token, 'confirmed': True}).status_code == 200


def test_non_ascii_csrf_is_a_structured_rejection(client):
    response = client.post('/api/chat', json={'message': 'Привет'}, headers={b'x-csrf-token': b'\xff'})
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'csrf'


def test_removed_uploads_release_session_capacity(client):
    for _ in range(9):
        aid = upload(client)
        result = client.post('/api/attachments/remove', json={'attachment_ids': [aid]})
        assert result.status_code == 200
    assert client.post('/api/chat', json={'message': 'Найди', 'attachment_ids': [aid]}).status_code == 404


def test_success_consumes_upload_but_failed_chat_keeps_it(client):
    aid = upload(client)
    catalog = client.app.state.catalog
    original = catalog.search

    async def unavailable(*args):
        raise AppError('upstream_unavailable', 'Test outage', 503)

    catalog.search = unavailable
    body = {'message': 'DEMO-LAMP-10W-B', 'attachment_ids': [aid]}
    assert client.post('/api/chat', json=body).status_code == 503
    catalog.search = original
    assert client.post('/api/chat', json=body).status_code == 200
    assert client.post('/api/chat', json=body).status_code == 404


def test_reset_clears_context_and_pending_uploads_but_preserves_cart(client):
    first = propose(client)
    assert client.post('/api/cart/confirm', json={'confirmation_id': first, 'confirmed': True}).status_code == 200
    client.post('/api/chat', json={'message': 'Найди DEMO-LAMP-10W-B'})
    pending = propose(client); aid = upload(client)
    session = next(iter(client.app.state.sessions.values()))
    assert session.history and session.last_products and session.attachments
    result = client.post('/api/chat/reset', json={})
    assert result.status_code == 200 and result.json()['cart']['count'] == 2
    assert not session.history and not session.last_products and not session.attachments and session.pending is None
    assert client.post('/api/cart/confirm', json={'confirmation_id': pending, 'confirmed': True}).status_code == 403
    assert client.post('/api/chat', json={'message': 'Найди', 'attachment_ids': [aid]}).status_code == 404
    # A lost earlier response can still be reconciled after a context reset.
    assert client.post('/api/cart/confirm', json={'confirmation_id': first, 'confirmed': True}).json()['cart']['count'] == 2


def test_foreign_cancel_and_remove_do_not_damage_owner_session(client):
    token = propose(client); aid = upload(client)
    owner_cookies = dict(client.cookies); owner_csrf = client.headers['X-CSRF-Token']
    client.cookies.clear()
    client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
    assert client.post('/api/cart/cancel', json={'confirmation_id': token}).status_code == 200
    assert client.post('/api/attachments/remove', json={'attachment_ids': [aid]}).status_code == 200
    assert client.post('/api/chat', json={'message': 'Найди', 'attachment_ids': [aid]}).status_code == 404
    client.cookies = owner_cookies; client.headers['X-CSRF-Token'] = owner_csrf
    assert client.post('/api/cart/confirm', json={'confirmation_id': token, 'confirmed': True}).status_code == 200
    assert client.post('/api/chat', json={'message': 'Найди DEMO-LAMP-10W-B', 'attachment_ids': [aid]}).status_code == 200


def test_expired_session_can_reconnect_without_old_authority(client):
    token = propose(client); aid = upload(client)
    next(iter(client.app.state.sessions.values())).touched = time.time() - 7201
    assert client.post('/api/cart/confirm', json={'confirmation_id': token, 'confirmed': True}).status_code == 403
    client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
    assert client.post('/api/chat', json={'message': 'Найди', 'attachment_ids': [aid]}).status_code == 404
    assert client.post('/api/cart/confirm', json={'confirmation_id': token, 'confirmed': True}).status_code == 403
    assert client.post('/api/chat', json={'message': 'Условия доставки'}).status_code == 200
    assert client.get('/api/cart').json()['count'] == 0


def test_concurrent_confirmations_and_lost_response_add_only_once(monkeypatch):
    for name in ('EKT_API_USERNAME', 'EKT_API_PASSWORD', 'OPENAI_API_KEY'):
        monkeypatch.delenv(name, raising=False)

    async def scenario():
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as c:
                c.headers['X-CSRF-Token'] = (await c.get('/api/session')).json()['csrf_token']
                response = await c.post('/api/cart/propose', json={'product_id': '900002', 'quantity': 2})
                token = response.json()['proposal']['confirmation_id']
                original = app.state.catalog.detail
                entered = asyncio.Event(); release = asyncio.Event()

                async def blocked_detail(*args, **kwargs):
                    entered.set(); await release.wait()
                    return await original(*args, **kwargs)

                app.state.catalog.detail = blocked_detail
                payload = {'confirmation_id': token, 'confirmed': True}
                first = asyncio.create_task(c.post('/api/cart/confirm', json=payload))
                await asyncio.wait_for(entered.wait(), 1)
                second = asyncio.create_task(c.post('/api/cart/confirm', json=payload))
                await asyncio.sleep(0)
                release.set()
                results = await asyncio.wait_for(asyncio.gather(first, second), 2)
                assert all(r.status_code == 200 for r in results)
                assert results[0].json() == results[1].json()
                # Discard both responses as if delivery was lost, then reconcile and retry.
                cart = (await c.get('/api/cart')).json()
                assert cart['count'] == 2 and cart['version'] == 1
                assert (await c.post('/api/cart/confirm', json=payload)).json()['cart'] == cart

    asyncio.run(scenario())
