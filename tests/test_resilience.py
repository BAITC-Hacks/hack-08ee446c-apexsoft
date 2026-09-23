"""Offline failures at the boundary between a quote and a cart mutation."""
import asyncio

import httpx
import pytest
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


def quote(c):
    response = c.post('/api/cart/propose', json={'product_id': '900002', 'quantity': 2})
    assert response.status_code == 200
    return {'confirmation_id': response.json()['proposal']['confirmation_id'], 'confirmed': True}


def test_catalog_outage_during_confirmation_recovers_exactly_once(client, monkeypatch):
    body = quote(client)
    catalog = client.app.state.catalog
    original = catalog.detail
    async def outage(*args, **kwargs):
        raise AppError('upstream_unavailable', 'Каталог временно недоступен.', 503)
    monkeypatch.setattr(catalog, 'detail', outage)
    assert client.post('/api/cart/confirm', json=body).status_code == 503
    assert client.get('/api/cart').json()['count'] == 0
    monkeypatch.setattr(catalog, 'detail', original)
    first = client.post('/api/cart/confirm', json=body)
    assert first.status_code == 200
    assert client.post('/api/cart/confirm', json=body).json() == first.json()
    cart = client.get('/api/cart').json()
    assert (cart['count'], cart['version']) == (2, 1)


def test_product_disappearing_after_quote_cannot_be_added(client, monkeypatch):
    body = quote(client)
    async def missing(*args, **kwargs):
        raise AppError('not_found', 'Товар больше не доступен.', 404)
    monkeypatch.setattr(client.app.state.catalog, 'detail', missing)
    for _ in range(2):
        response = client.post('/api/cart/confirm', json=body)
        assert response.status_code == 404
        assert response.json()['error']['code'] == 'not_found'
    cart = client.get('/api/cart').json()
    assert (cart['items'], cart['total'], cart['version']) == ([], 0, 0)


def test_partial_search_does_not_hide_an_upstream_outage(client, monkeypatch):
    catalog = client.app.state.catalog
    original = catalog.detail
    visited = []
    async def partial(pid, **kwargs):
        visited.append(pid)
        if len(visited) == 2:
            raise AppError('upstream_unavailable', 'Вторая карточка недоступна.', 503)
        return await original(pid, **kwargs)
    monkeypatch.setattr(catalog, 'detail', partial)
    response = client.post('/api/chat', json={'message': 'лампа'})
    assert response.status_code == 503
    assert len(visited) == 2
    assert 'products' not in response.json()
    assert client.get('/api/cart').json()['count'] == 0
    monkeypatch.setattr(catalog, 'detail', original)
    assert client.post('/api/chat', json={'message': 'лампа'}).status_code == 200


@pytest.mark.parametrize('failure', ['503', 'timeout'])
def test_openai_failure_never_grants_cart_authority(client, failure):
    ai = client.app.state.ai
    calls = []
    async def fail(request):
        calls.append(request.url.path)
        if failure == 'timeout':
            raise httpx.ReadTimeout('offline simulated timeout', request=request)
        return httpx.Response(503)
    asyncio.run(ai.client.aclose())
    ai.key = 'offline-test-placeholder'
    ai.client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    response = client.post('/api/chat', json={'message': 'Добавь DEMO-LAMP-10W-B 2 шт'})
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert response.json()['warnings']
    assert response.json()['proposal'] is not None
    assert client.get('/api/cart').json()['count'] == 0
