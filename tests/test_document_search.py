import pytest

from backend.document_search import document_matches


ROWS = {'20330': {'article': '150200334_'}, '10': {'article': 'A'},
        '11': {'article': 'A-B'}, '12': {'article': 'AB.12/7'},
        '13': {'article': 'UNKNOWN-ID-NAME'}}


def doc(text, **changes):
    return {'kind': 'document', 'extracted_text': text, **changes}


@pytest.mark.parametrize('text', ['150200334_', '150200334',
                                'Артикул: 150200334_ | Лампа | 2 штуки',
                                '1. Светильник, 150200334; количество 3.'])
def test_article_in_specification_is_preserved_exactly(text):
    assert document_matches(ROWS, [doc(text)]) == ['20330']


@pytest.mark.parametrize('text', ['A-B', 'a-b', 'Артикул: A-B; 2 шт'])
def test_short_article_never_matches_prefix_of_long_article(text):
    assert document_matches(ROWS, [doc(text)]) == ['11']


@pytest.mark.parametrize('text', ['A-BCD', 'A-B-X', '150200334_EXTRA',
                                '1150200334', '1502003340', '-A', 'XXA', 'A__'])
def test_substrings_and_other_markings_are_not_articles(text):
    assert document_matches(ROWS, [doc(text)]) == []


def test_numeric_internal_id_is_not_inferred_from_document():
    assert document_matches(ROWS, [doc('ID: 20330; 10; 13')]) == []


def test_multiple_articles_keep_document_order_and_deduplicate():
    assert document_matches(ROWS, [doc('A-B | 150200334_ | A-B'), doc('A | 150200334')]) == ['11', '20330', '10']


def test_only_document_text_is_searched_never_image_placeholder_or_filename():
    assert document_matches(ROWS, [doc('A', kind='image'),
                                   {'kind': 'document', 'name': '150200334_.docx', 'extracted_text': ''}]) == []


def test_article_with_dot_and_slash_matches_full_token():
    assert document_matches(ROWS, [doc('Артикул AB.12/7, цена уточняется')]) == ['12']
    assert document_matches(ROWS, [doc('AB.12/70')]) == []


def test_duplicate_catalogue_articles_are_not_arbitrarily_resolved():
    rows = {'1': {'article': 'ABC'}, '2': {'article': 'ABC_'}, '3': {'article': None}}
    assert document_matches(rows, [doc('ABC')]) == ['1', '2']


def test_oversized_or_unknown_text_has_bounded_processing():
    assert document_matches(ROWS, [doc(' ' * 16000 + '150200334_')]) == []
    assert document_matches(ROWS, [doc(None), doc('Лампа с фотографии')]) == []


@pytest.fixture
def document_client(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import create_app

    for key in ('EKT_API_USERNAME', 'EKT_API_PASSWORD', 'OPENAI_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    app = create_app()

    async def forbidden_ai(*args, **kwargs):
        pytest.fail('Known articles in documents must bypass generative interpretation')

    app.state.ai.interpret = forbidden_ai
    with TestClient(app) as client:
        client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
        yield client


def upload_docx(client, text):
    import io
    from docx import Document

    document = Document()
    document.add_paragraph(text)
    stream = io.BytesIO()
    document.save(stream)
    response = client.post('/api/attachments', files={'file': (
        'specification.docx', stream.getvalue(),
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert response.status_code == 200, response.text
    return response.json()['attachment_id']


def test_single_known_docx_article_returns_only_that_product_without_ai(document_client):
    aid = upload_docx(document_client, 'Спецификация: DEMO-LAMP-10W-B | Количество: 2 шт')
    response = document_client.post('/api/chat', json={
        'message': 'Найди товар из спецификации', 'attachment_ids': [aid]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert [item['id'] for item in result['products']] == ['900002']
    assert result['proposal'] is None
    assert document_client.get('/api/cart').json()['count'] == 0


def test_multiple_known_docx_articles_require_choice_and_do_not_change_cart(document_client):
    aid = upload_docx(document_client, 'DEMO-LAMP-10W-B 2 шт\nDEMO-CABLE 5 м')
    response = document_client.post('/api/chat', json={
        'message': 'Добавь всё из спецификации', 'attachment_ids': [aid]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert [item['id'] for item in result['products']] == ['900002', '900003']
    assert 'Выберите' in result['text']
    assert result['proposal'] is None
    assert document_client.get('/api/cart').json()['count'] == 0
