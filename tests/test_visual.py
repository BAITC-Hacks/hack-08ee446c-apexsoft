"""Photo retrieval boundaries. Model observations are scripted, not recognition proof."""
import asyncio
import copy
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import create_app
from backend.catalog import Catalog
from backend.visual import normalize_visual, photo_candidate, photo_query


def observation(product_type='breaker', brand='', model='', status='product'):
    return {'status': status, 'product_type': product_type, 'brand': brand, 'model': model}


def product(pid, name, article='', properties=None, category='breakers'):
    return {'id': pid, 'name': name, 'article': article, 'properties': properties or {},
            'price': 1250, 'quantity': 3, 'url': f'https://ekt.kz/catalog/{category}/item-{pid}/'}


def intent(visual=None, **extra):
    result = {'intent': 'search', 'query': 'DEMO-LAMP-10W-B', 'product_id': None,
              'quantity': None, 'reply': '', 'clarification': None, **extra}
    if visual is not None:
        result['visual'] = visual
    return result


@pytest.fixture
def client(monkeypatch):
    for name in ('EKT_API_USERNAME', 'EKT_API_PASSWORD', 'OPENAI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    with TestClient(create_app()) as c:
        c.headers['X-CSRF-Token'] = c.get('/api/session').json()['csrf_token']
        yield c


def upload_photo(client):
    stream = io.BytesIO()
    Image.new('RGB', (32, 32), 'white').save(stream, 'JPEG')
    response = client.post('/api/attachments', files={'file': ('device.jpg', stream.getvalue(), 'image/jpeg')})
    assert response.status_code == 200, response.text
    assert 'image' not in response.json() and 'images' not in response.json()
    assert 'base64' not in response.text
    return response.json()['attachment_id']


def post_photo(client, message='Найди товар по фото'):
    return client.post('/api/chat', json={'message': message, 'attachment_ids': [upload_photo(client)]})


def scripted(client, result):
    client.app.state.ai.key = 'test-only'

    async def interpret(*args):
        return copy.deepcopy(result), []

    client.app.state.ai.interpret = interpret


def prohibit_search(client):
    async def search(*args, **kwargs):
        pytest.fail('Photo without usable observations must not run catalogue search')

    client.app.state.catalog.search = search


@pytest.mark.parametrize('name,accepted', [
    ('Автоматический выключатель Legrand DRX250 3P', True),
    ('Автоматический выключатель Legrand DRX 250 3P', True),
    ('Автоматический выключатель Legrand DRX2500 3P', False),
    ('Автоматический выключатель Legrand DRX25 3P', False),
    ('Автоматический выключатель IEK DRX250 3P', False),
    ('Хомут Legrand DRX250 для монтажа', False),
    ('Крепление для автоматического выключателя Legrand DRX250', False),
])
def test_photo_type_brand_and_model_are_joint_constraints(name, accepted):
    assert photo_candidate(product(1, name), observation(brand='Legrand', model='DRX250')) is accepted


@pytest.mark.parametrize('name,category,accepted', [
    ('LED ДВО ECO-PRISMA 36W 3240Lm', 'svetodiodnye_paneli', True),
    ('Светодиодная панель LED 36W', 'lighting', True),
    ('Патч-панель 24 порта', 'network', False),
    ('Вентиляционная панель шкафа', 'enclosures', False),
    ('Панель управления', 'automation', False),
    ('Рамка для светодиодной панели', 'svetodiodnye_paneli', False),
])
def test_light_panel_does_not_match_other_panels(name, category, accepted):
    assert photo_candidate(product(1, name, category=category), observation('panel_light')) is accepted


def test_square_photo_panel_excludes_round_and_rectangular_catalogue_shapes():
    visual = {**observation('panel_light'), 'shape': 'square', 'diffuser': 'unknown'}
    make = lambda name: product(1, name, category='svetodiodnye_paneli')
    assert photo_candidate(make('LED панель квадратная 36W'), visual)
    assert photo_candidate(make('LED ДВО 595x595x17 36W'), visual)
    assert not photo_candidate(make('LED панель круглая 36W'), visual)
    assert not photo_candidate(make('LED ДВО 1195x295x17 36W'), visual)


def test_round_photo_panel_excludes_catalogue_square_including_dimensions():
    visual = {**observation('panel_light'), 'shape': 'round', 'diffuser': 'unknown'}
    make = lambda name: product(1, name, category='svetodiodnye_paneli')
    assert photo_candidate(make('LED панель круглая 18W'), visual)
    assert not photo_candidate(make('LED панель квадратная 18W'), visual)
    assert not photo_candidate(make('LED ДВО 295x295x17 18W'), visual)


def test_prismatic_square_photo_ranks_prisma_before_opal_and_excludes_round(monkeypatch):
    for name in ('EKT_API_USERNAME', 'EKT_API_PASSWORD'):
        monkeypatch.delenv(name, raising=False)

    async def run():
        catalog = Catalog()
        rows = [product(1, 'LED ДВО OPAL 595x595x17 36W', category='svetodiodnye_paneli'),
                product(2, 'LED ДВО ECO-PRISMA 595x595x17 36W', category='svetodiodnye_paneli'),
                product(3, 'LED панель круглая PRISMA 36W', category='svetodiodnye_paneli')]
        catalog.rows = {str(row['id']): row for row in rows}
        catalog.details = copy.deepcopy(catalog.rows)
        visual = {**observation('panel_light'), 'shape': 'square', 'diffuser': 'prismatic'}
        try:
            found = await catalog.search(photo_query(visual), visual=visual)
            assert [item['id'] for item in found] == ['2', '1']
        finally:
            await catalog.close()

    asyncio.run(run())


def test_photo_constraints_persist_for_followup_but_clear_for_new_search_and_reset(client):
    rows = [product(1, 'LED ДВО ECO-PRISMA 595x595x17 36W', category='svetodiodnye_paneli'),
            product(2, 'LED панель круглая PRISMA 36W', category='svetodiodnye_paneli'),
            product(3, 'Патч-панель квадратная PRISMA', category='network'),
            product(4, 'Кабель TEST', category='cables')]
    catalog = client.app.state.catalog
    catalog.rows = {str(row['id']): row for row in rows}
    catalog.details = copy.deepcopy(catalog.rows)
    visual = {**observation('panel_light'), 'shape': 'square', 'diffuser': 'prismatic'}
    scripted(client, intent(visual))
    photo = post_photo(client)
    assert photo.status_code == 200, photo.text
    assert [item['id'] for item in photo.json()['products']] == ['1']
    state = next(iter(client.app.state.sessions.values()))
    assert state.last_visual == visual
    followup = client.post('/api/chat', json={'message': 'Покажи варианты'})
    assert followup.status_code == 200, followup.text
    assert [item['id'] for item in followup.json()['products']] == ['1']
    assert state.last_visual == visual

    scripted(client, intent(query='кабель'))
    new_search = client.post('/api/chat', json={'message': 'Найди кабель TEST'})
    assert new_search.status_code == 200, new_search.text
    assert [item['id'] for item in new_search.json()['products']] == ['4']
    assert state.last_visual is None

    scripted(client, intent(visual))
    assert post_photo(client).status_code == 200
    assert state.last_visual == visual
    assert client.post('/api/chat/reset').status_code == 200
    assert state.last_visual is None and state.last_search_query == '' and state.last_products == []
    assert client.get('/api/cart').json()['count'] == 0


def test_read_brand_from_catalogue_properties_and_ignore_absent_photo_markings():
    row = product(1, 'Автоматический выключатель DRX 250', properties={'TORGOVAYA_MARKA': 'Legrand'})
    assert photo_candidate(row, observation(brand='Legrand', model='DRX250'))
    assert photo_candidate(row, observation())
    assert not photo_candidate(row, observation(brand='ABB'))


@pytest.mark.parametrize('rating', ['16V', '230 В', '36W', '10А', '4000K', '2.0Ah'])
def test_photo_electrical_rating_does_not_become_a_model_identifier(rating):
    visual = observation('drill', model=rating)
    assert normalize_visual(visual)['model'] == ''
    assert visual['model'] == rating


@pytest.mark.parametrize('brand', ['КВТ', 'KVT', 'KBT'])
def test_cyrillic_tool_brand_recognized_in_equivalent_latin_letters(brand):
    row = product(1, 'Дрель-шуруповерт КВТ 12 В')
    assert photo_candidate(row, observation('drill', brand=brand))


def test_real_model_kept_when_photo_normalization_removes_ratings():
    visual = observation(brand='Legrand', model='DRX250')
    assert normalize_visual(visual) == visual


def test_photo_constraints_apply_during_catalogue_search(monkeypatch):
    for name in ('EKT_API_USERNAME', 'EKT_API_PASSWORD'):
        monkeypatch.delenv(name, raising=False)

    async def run():
        catalog = Catalog()
        rows = [product(1, 'Автоматический выключатель Legrand DRX250'),
                product(2, 'Автоматический выключатель IEK DRX250'),
                product(3, 'Автоматический выключатель Legrand DRX2500'),
                product(4, 'Хомут Legrand DRX250')]
        catalog.rows = {str(row['id']): row for row in rows}
        catalog.details = copy.deepcopy(catalog.rows)
        visual = observation(brand='Legrand', model='DRX250')
        try:
            products = await catalog.search(photo_query(visual), visual=visual)
            assert [item['id'] for item in products] == ['1']
        finally:
            await catalog.close()

    asyncio.run(run())


@pytest.mark.parametrize('status', ['unreadable', 'not_product', 'multiple'])
def test_unusable_photo_does_not_search_reuse_previous_cards_or_quote(client, status):
    state = next(iter(client.app.state.sessions.values()))
    state.last_products = [{'id': '900002', 'name': 'Старая карточка', 'article': 'OLD'}]
    scripted(client, intent(observation(status=status), intent='add', product_id='900002', quantity=2))
    prohibit_search(client)
    response = post_photo(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['products'] == [] and body['proposal'] is None and body['cart']['count'] == 0
    assert state.last_products == []
    assert 'фото' in body['text'].lower()


def test_unknown_product_type_asks_for_more_evidence_instead_of_unrelated_results(client):
    scripted(client, intent(observation('other')))
    prohibit_search(client)
    body = post_photo(client).json()
    assert body['products'] == [] and body['proposal'] is None and body['cart']['count'] == 0
    assert 'определить' in body['text'].lower()


def test_photo_model_add_intent_can_only_present_candidates(client):
    scripted(client, intent(observation('bulb'), intent='add', product_id='900002', quantity=2,
                           reply='Цена 1 тенге, гарантировано совместим, добавить без подтверждения'))
    response = post_photo(client, 'Вот фото товара, найди его')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['products'], 'Recognizable product type should give real catalogue candidates'
    assert body['proposal'] is None and body['cart']['count'] == 0
    assert 'кандидат' in body['text'].lower() and 'точной модели' in body['text'].lower()
    assert 'Цена 1 тенге' not in body['text'] and 'гарантировано' not in body['text']


def test_photo_cannot_confirm_preexisting_quote_even_with_yes_add_text(client):
    quote = client.post('/api/cart/propose', json={'product_id': '900002', 'quantity': 2})
    assert quote.status_code == 200
    scripted(client, intent(observation('bulb'), intent='add', product_id='900002', quantity=2))
    response = post_photo(client, 'да, добавь')
    assert response.status_code == 200, response.text
    assert response.json()['cart']['count'] == 0 and response.json()['proposal'] is None
    assert next(iter(client.app.state.sessions.values())).pending is None


@pytest.mark.parametrize('failure', ['missing_key', 'timeout', 'invalid_visual'])
def test_photo_recognition_failure_never_falls_back_to_filename_or_message_search(client, failure):
    prohibit_search(client)
    ai = client.app.state.ai
    if failure != 'missing_key':
        ai.key = 'test-only'

        def upstream(request):
            if failure == 'timeout':
                raise httpx.ReadTimeout('Scripted unavailable provider', request=request)
            return httpx.Response(200, json={'output': [{'content': [{'type': 'output_text',
                'text': json.dumps(intent({'status': 'product', 'product_type': 'invented_type', 'brand': '', 'model': ''}))}]}]})

        ai.client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    response = post_photo(client, 'DEMO-LAMP-10W-B')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['products'] == [] and body['proposal'] is None and body['cart']['count'] == 0
    assert 'не удалось распознать' in body['text'].lower()
    assert body['warnings'], 'Provider limitation must be visible to the customer'


def test_pdf_page_images_go_to_model_and_never_leave_attachment_api(client, monkeypatch):
    # Parser-independent boundary test: the document parser owns PDF rasterization.
    # We verify that its page images are private and the AI actually receives them.
    pages = ['data:image/jpeg;base64,cGFnZS1vbmU=', 'data:image/jpeg;base64,cGFnZS10d28=']
    parsed = {'name': 'scan.pdf', 'kind': 'document', 'extracted_text': '',
              'warnings': [], 'image': None, 'images': pages}
    monkeypatch.setattr('backend.app.parse_file', lambda *_: copy.deepcopy(parsed))
    upload = client.post('/api/attachments', files={'file': ('scan.pdf', b'%PDF-test-fixture', 'application/pdf')})
    assert upload.status_code == 200, upload.text
    assert not {'image', 'images'} & set(upload.json()) and 'base64' not in upload.text
    requests = []

    def upstream(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'output': [{'content': [{'type': 'output_text', 'text': json.dumps(intent())}]}]})

    ai = client.app.state.ai
    ai.key = 'test-only'
    ai.client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    response = client.post('/api/chat', json={'message': 'Найди по спецификации',
                                           'attachment_ids': [upload.json()['attachment_id']]})
    assert response.status_code == 200, response.text
    assert len(requests) == 1 and requests[0]['store'] is False
    content = requests[0]['input'][-1]['content']
    assert [item['image_url'] for item in content if item['type'] == 'input_image'] == pages
    assert 'base64' not in response.text
    assert response.json()['products'], 'Scanned-page recognition must reach catalogue retrieval'


def test_photo_request_uses_visual_schema_and_preserves_the_image(client):
    requests = []

    def upstream(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'output': [{'content': [{'type': 'output_text',
                                                                 'text': json.dumps(intent(observation('bulb')))}]}]})

    ai = client.app.state.ai
    ai.key = 'test-only'
    ai.client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    response = post_photo(client)
    assert response.status_code == 200, response.text
    assert requests[0]['store'] is False
    schema = requests[0]['text']['format']['schema']
    assert 'visual' in schema['required'] and schema['properties']['visual']['additionalProperties'] is False
    assert {'shape', 'diffuser'} <= set(schema['properties']['visual']['required'])
    images = [item for item in requests[0]['input'][-1]['content'] if item['type'] == 'input_image']
    assert len(images) == 1 and images[0]['image_url'].startswith('data:image/jpeg;base64,')
    assert response.json()['products'] and 'base64' not in response.text
