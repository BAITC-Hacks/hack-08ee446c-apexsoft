"""Endpoint regressions using synthetic credentials, without provider calls."""
import io
from unittest.mock import AsyncMock

import pytest
from docx import Document
from fastapi.testclient import TestClient

from backend.app import create_app


@pytest.fixture
def client(monkeypatch):
    for name in ('EKT_API_USERNAME', 'EKT_API_PASSWORD', 'OPENAI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    app = create_app()
    app.state.ai.interpret = AsyncMock(wraps=app.state.ai.interpret)
    with TestClient(app) as client:
        client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
        yield client


def state(client):
    return next(iter(client.app.state.sessions.values()))


@pytest.mark.parametrize('message', [
    'Моя карта 4242 4242 4242 4242, срок 12/30. Как оплатить?',
    'CVV: 123', 'Код безопасности: 123',
])
def test_payment_chat_rejected_before_ai_history_or_retry_cache(client, message):
    response = client.post('/api/chat', json={'message': message, 'request_id': 'privacy-test-request'})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'payment_data'
    assert message not in response.text
    client.app.state.ai.interpret.assert_not_awaited()
    session = state(client)
    assert session.history == [] and session.chat_receipts == {}
    assert session.pending is None and session.attachments == {}
    assert client.get('/api/cart').json()['count'] == 0


@pytest.mark.parametrize('filename,text', [
    ('payment-test.docx', 'Моя карта 4242 4242 4242 4242, срок 12/30, CVV 123.'),
    ('CVV 123.docx', 'Найди DEMO-LAMP-10W-B'),
])
def test_payment_docx_rejected_before_pending_storage_without_echo(client, filename, text):
    document = Document(); document.add_paragraph(text)
    stream = io.BytesIO(); document.save(stream)
    response = client.post('/api/attachments', files={'file': (filename, stream.getvalue())})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'payment_data'
    assert filename not in response.text and text not in response.text
    assert '4242' not in response.text and '123' not in response.text
    assert state(client).attachments == {}
    assert state(client).history == [] and state(client).chat_receipts == {}
    client.app.state.ai.interpret.assert_not_awaited()


def test_explicit_numeric_article_still_reaches_search(client):
    catalog = client.app.state.catalog
    article = '4242424242424242'
    catalog.rows['900002']['article'] = article
    catalog.details['900002']['article'] = article
    response = client.post('/api/chat', json={'message': 'Артикул: ' + article})
    assert response.status_code == 200, response.text
    assert [product['id'] for product in response.json()['products']] == ['900002']
    client.app.state.ai.interpret.assert_awaited_once()
    assert response.json()['cart']['count'] == 0


def test_rejected_payment_message_preserves_existing_quote_and_cart(client):
    quote = client.post('/api/cart/propose', json={'product_id': '900002', 'quantity': 2}).json()['proposal']
    response = client.post('/api/chat', json={'message': 'CVV 123'})
    assert response.status_code == 422
    assert state(client).pending['proposal']['confirmation_id'] == quote['confirmation_id']
    assert client.get('/api/cart').json()['count'] == 0
    client.app.state.ai.interpret.assert_not_awaited()
