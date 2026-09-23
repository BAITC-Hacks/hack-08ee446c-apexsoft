"""Offline regressions for malformed upstream data and valid upload names."""
import asyncio
import io
import json

import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient

from backend.ai import AI
from backend.app import create_app
from backend.attachments import parse_file
from backend.catalog import normalize, tokens
from backend.errors import AppError
from backend.state import Session


@pytest.fixture
def client(monkeypatch):
    for name in ('EKT_API_USERNAME', 'EKT_API_PASSWORD', 'OPENAI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    with TestClient(create_app()) as client:
        client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
        yield client


@pytest.mark.parametrize('field,value', [
    ('stores', None), ('stores', 'unknown'), ('stores', [None, 'unknown', 1]),
    ('properties', ['unknown']), ('properties', 'unknown'),
    ('url', 'https://[broken'), ('image', 'https://[broken'),
    ('properties', {'CERTIFICATE': 'https://[broken'}),
])
def test_bad_optional_catalog_fields_do_not_hide_known_product_facts(client, field, value):
    client.app.state.catalog.details['900002'][field] = value
    response = client.get('/api/products/900002')
    assert response.status_code == 200
    product = response.json()
    assert product['id'] == '900002' and product['price'] == 1200 and product['stock'] == 12
    assert isinstance(product['warehouses'], list) and isinstance(product['specifications'], list)
    if field == 'url':
        assert product['product_url'] is None
    else:
        assert product['product_url'].startswith('https://')
    assert product['image_url'] != 'https://[broken'
    assert all(certificate['url'] != 'https://[broken' for certificate in product['certificates'])


def test_unknown_stock_is_not_reported_as_zero_or_guessed_from_warehouses():
    product = normalize({'id': 21, 'quantity': None, 'stores': [
        {'name': 'Unknown', 'quantity': None}, {'name': 'Invalid', 'quantity': 'unknown'},
        {'name': 'Empty', 'quantity': 0}, {'name': 'Available', 'quantity': 3}, None,
    ]})
    assert product['stock'] is None
    assert [(warehouse['name'], warehouse['stock']) for warehouse in product['warehouses']] == [
        ('Unknown', None), ('Invalid', None), ('Empty', 0), ('Available', 3),
    ]
    assert product['warnings']


def test_null_name_does_not_break_catalog_matching():
    assert tokens(None) == []


@pytest.mark.parametrize('first_article,second_article,message', [
    ('', 'TARGET', 'TARGET'), ('TARGET', 'TARGET-B', 'TARGET-B'),
    ('FIRST', 'SECOND', 'ID: 221'),
])
def test_fallback_does_not_select_an_empty_or_partial_identifier(client, first_article, second_article, message):
    catalog = client.app.state.catalog
    rows = {'21': {'id': 21, 'article': first_article, 'name': 'First', 'price': 1, 'quantity': 2},
            '221': {'id': 221, 'article': second_article, 'name': 'Second', 'price': 2, 'quantity': 3}}
    catalog.rows = rows.copy()
    catalog.details = rows.copy()
    next(iter(client.app.state.sessions.values())).last_products = [normalize(row) for row in rows.values()]
    response = client.post('/api/chat', json={'message': message})
    assert response.status_code == 200
    assert [product['id'] for product in response.json()['products']] == ['221']
    assert response.json()['cart']['count'] == 0


@pytest.mark.parametrize('message,expected', [('Добавь 21 шт TARGET', '221'), ('PART-21', '221'), ('ID: 21', '21')])
def test_fallback_distinguishes_quantity_article_digits_and_explicit_id(message, expected):
    session = Session(last_products=[{'id': '21', 'article': 'FIRST'},
                                     {'id': '221', 'article': 'PART-21' if message == 'PART-21' else 'TARGET'}])
    parsed = AI.__new__(AI).fallback(message, session)
    assert parsed['product_id'] == expected
    if 'шт' in message: assert parsed['quantity'] == 21


@pytest.mark.parametrize('message', ['Добавь NEW-22', 'Найди аналог NEW-22', 'Добавь ID: 22', 'Добавь другую лампу'])
def test_fallback_does_not_reuse_last_product_when_user_names_a_new_one(message):
    session = Session(last_products=[{'id': '21', 'article': 'ONLY-11'}])
    assert AI.__new__(AI).fallback(message, session)['product_id'] is None


@pytest.mark.parametrize('message,quantity', [('Добавь его', None), ('Добавь этот товар в корзину', None),
    ('Добавь 2 шт', 2), ('Добавь 2 штуки', 2), ('Добавь 2 метра', 2), ('Найди аналог этого товара', None)])
def test_fallback_keeps_unambiguous_reference_to_the_only_product(message, quantity):
    session = Session(last_products=[{'id': '21', 'article': 'ONLY-11'}])
    result = AI.__new__(AI).fallback(message, session)
    assert result['product_id'] == '21' and result['quantity'] == quantity


def intent(**changes):
    return {'intent': 'search', 'query': 'TARGET', 'product_id': None, 'quantity': None,
            'reply': '', 'clarification': None, **changes}


def envelope(result):
    return {'output': [{'content': [{'type': 'output_text', 'text': json.dumps(result)}]}]}


def interpret_response(body):
    async def run():
        ai = AI.__new__(AI)
        ai.key = 'test-only'; ai.model = 'test-only'
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=json.dumps(body).encode()))) as ai.client:
            return await ai.interpret('TARGET', Session(), [])
    return asyncio.run(run())


@pytest.mark.parametrize('body', [None, [], {'output': None}, {'output': ['bad']},
                                {'output': [{'content': [None]}]}])
def test_malformed_provider_envelope_uses_safe_fallback(body):
    result, warnings = interpret_response(body)
    assert warnings and result == intent()


@pytest.mark.parametrize('result', [
    [], intent(query=['TARGET']), intent(product_id=['21']), intent(quantity='2'),
    intent(quantity=True), intent(quantity=float('inf')), intent(reply=None),
    intent(clarification={'topic': 'cable', 'acknowledgement': 'none', 'question_keys': 'length'}),
    intent(clarification={'topic': [], 'acknowledgement': 'none', 'question_keys': ['length']}),
    intent(clarification={'topic': 'cable', 'acknowledgement': 'none', 'question_keys': ['unknown']}),
    {'intent': 'search'},
])
def test_invalid_ai_field_types_cannot_escape_into_catalog_or_cart(result):
    result, warnings = interpret_response(envelope(result))
    assert warnings and result == intent()


@pytest.mark.parametrize('result', [intent(), intent(intent='add', product_id='21', quantity=2),
    intent(intent='clarify', clarification={'topic': 'cable', 'acknowledgement': 'no_article',
                                         'question_keys': ['length']})])
def test_valid_ai_selection_quantity_and_clarification_are_preserved(result):
    parsed, warnings = interpret_response(envelope(result))
    assert parsed == result and warnings == []


def test_long_document_filename_preserves_format_and_extracted_content():
    document = Document(); document.add_paragraph('TARGET 2')
    data = io.BytesIO(); document.save(data)
    short = parse_file('spec.docx', data.getvalue())
    long = parse_file('folder/' + 'x' * 160 + '.docx', data.getvalue())
    assert long['extracted_text'] == short['extracted_text'] == 'TARGET 2'
    assert len(long['name']) <= 160 and long['name'].endswith('.docx')
    with pytest.raises(AppError) as error:
        parse_file('x' * 160 + '.png', data.getvalue())
    assert error.value.code == 'invalid_attachment'
