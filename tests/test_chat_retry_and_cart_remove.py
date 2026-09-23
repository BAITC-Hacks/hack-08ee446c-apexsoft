import asyncio
import io

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
    doc = Document(); doc.add_paragraph('DEMO-LAMP-10W-B')
    buffer = io.BytesIO(); doc.save(buffer)
    r = c.post('/api/attachments', files={'file': ('spec.docx', buffer.getvalue())})
    assert r.status_code == 200
    return r.json()['attachment_id']


def add(c):
    p = c.post('/api/cart/propose', json={'product_id':'900002','quantity':2}).json()['proposal']
    body = {'confirmation_id':p['confirmation_id'],'confirmed':True}
    assert c.post('/api/cart/confirm', json=body).status_code == 200
    return body


def test_lost_response_can_replay_consumed_attachment_without_duplicate_history(client):
    body = {'message':'Найди DEMO-LAMP-10W-B','attachment_ids':[upload(client)],'request_id':'request-lost-response'}
    original = client.post('/api/chat', json=body)
    assert original.status_code == 200
    # The client never received original; the server already freed the upload.
    state = next(iter(client.app.state.sessions.values()))
    assert not state.attachments
    repeated = client.post('/api/chat', json=body)
    assert repeated.status_code == 200
    assert repeated.json() == original.json()
    assert len(state.history) == 2
    assert client.post('/api/chat', json={**body,'message':'Другой вопрос'}).status_code == 409


def test_chat_confirmation_retry_cannot_confirm_a_later_proposal(client):
    client.post('/api/cart/propose', json={'product_id':'900002','quantity':2})
    body = {'message':'да, добавь','request_id':'request-cart-confirm'}
    first = client.post('/api/chat', json=body)
    assert first.json()['cart']['count'] == 2
    next_quote = client.post('/api/cart/propose', json={'product_id':'900002','quantity':3}).json()['proposal']
    assert client.post('/api/chat', json=body).json()['cart']['count'] == 2
    state = next(iter(client.app.state.sessions.values()))
    assert state.pending['proposal']['confirmation_id'] == next_quote['confirmation_id']


def test_failed_chat_is_retried_and_cache_is_bounded_and_reset(client, monkeypatch):
    state = next(iter(client.app.state.sessions.values()))
    original = client.app.state.ai.interpret
    async def fail(*args):
        raise AppError('upstream_unavailable','Ошибка проверки.',503)
    monkeypatch.setattr(client.app.state.ai,'interpret',fail)
    body = {'message':'Привет','request_id':'request-after-failure'}
    assert client.post('/api/chat',json=body).status_code == 503
    assert not state.chat_receipts
    monkeypatch.setattr(client.app.state.ai,'interpret',original)
    assert client.post('/api/chat',json=body).status_code == 200
    for i in range(34):
        state.calls.clear()  # Exercise memory bound without turning this into a rate-limit test.
        assert client.post('/api/chat',json={'message':'Привет','request_id':f'request-bound-{i}'}).status_code == 200
    assert len(state.chat_receipts) == 32
    add(client)
    assert client.post('/api/chat/reset',json={}).json()['cart']['count'] == 2
    assert not state.chat_receipts and not state.history


def test_concurrent_attachment_retries_and_foreign_session(client):
    body = {'message':'Найди DEMO-LAMP-10W-B','attachment_ids':[upload(client)],'request_id':'request-concurrent'}
    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app),base_url='http://testserver',cookies=client.cookies,headers=dict(client.headers)) as c:
            return await asyncio.gather(c.post('/api/chat',json=body),c.post('/api/chat',json=body))
    responses = asyncio.run(send())
    assert [r.status_code for r in responses] == [200,200]
    assert responses[0].json() == responses[1].json()
    client.cookies.clear()
    client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
    assert client.post('/api/chat',json=body).status_code == 404


def test_remove_requires_explicit_consent_recalculates_and_invalidates_quote(client):
    old_confirm = add(client)
    pending = client.post('/api/cart/propose',json={'product_id':'900002','quantity':1}).json()['proposal']
    body = {'product_id':'900002','version':1,'confirmed':True}
    assert client.post('/api/cart/remove',json={**body,'confirmed':False}).status_code == 403
    assert client.post('/api/cart/remove',json={**body,'confirmed':'true'}).status_code == 422
    assert client.get('/api/cart').json()['count'] == 2
    response = client.post('/api/cart/remove',json=body)
    assert response.status_code == 200
    cart = response.json()['cart']
    assert (cart['items'],cart['total'],cart['count'],cart['version']) == ([],0,0,2)
    assert client.post('/api/cart/remove',json=body).json()['cart'] == cart
    assert client.post('/api/cart/confirm',json={'confirmation_id':pending['confirmation_id'],'confirmed':True}).status_code == 403
    # A delayed confirmation receipt must not visually restore a removed item.
    assert client.post('/api/cart/confirm',json=old_confirm).json()['cart'] == cart
    add(client)
    assert client.post('/api/cart/remove',json=body).status_code == 409
    assert client.get('/api/cart').json()['count'] == 2


def test_remove_is_csrf_protected_and_session_scoped(client):
    add(client)
    owner_cookies = dict(client.cookies); owner_token = client.headers['X-CSRF-Token']
    body = {'product_id':'900002','version':1,'confirmed':True}
    assert client.post('/api/cart/remove',json=body,headers={'X-CSRF-Token':'invalid'}).status_code == 403
    client.cookies.clear()
    client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
    assert client.post('/api/cart/remove',json=body).json()['cart']['count'] == 0
    client.cookies = owner_cookies; client.headers['X-CSRF-Token'] = owner_token
    assert client.get('/api/cart').json()['count'] == 2


def test_removing_one_product_preserves_another_product_and_its_quantity(client):
    catalog=client.app.state.catalog
    catalog.details['900005']={**catalog.details['900002'],'id':900005,
                              'name':'Другая модель тестового товара','price':2300}
    add(client)
    proposal=client.post('/api/cart/propose',json={'product_id':'900005','quantity':3}).json()['proposal']
    response=client.post('/api/cart/confirm',json={'confirmation_id':proposal['confirmation_id'],'confirmed':True})
    before=response.json()['cart']
    assert {item['product']['id'] for item in before['items']}=={'900002','900005'}
    assert before['count']==5
    remove={'product_id':'900002','version':before['version'],'confirmed':True}
    after=client.post('/api/cart/remove',json=remove).json()['cart']
    assert [item['product']['id'] for item in after['items']]==['900005']
    assert after['items'][0]['quantity']==3 and after['total']==6900 and after['count']==3
    assert client.post('/api/cart/remove',json=remove).json()['cart']==after
    assert client.get('/api/cart').json()==after
