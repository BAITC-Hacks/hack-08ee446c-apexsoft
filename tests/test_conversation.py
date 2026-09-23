"""Conversation boundaries; model choices are scripted, not live-model evaluation."""
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app


@pytest.fixture
def client(monkeypatch):
    for name in ('EKT_API_USERNAME', 'EKT_API_PASSWORD', 'OPENAI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    with TestClient(create_app()) as c:
        c.headers['X-CSRF-Token'] = c.get('/api/session').json()['csrf_token']
        yield c


def choice(intent='clarify', *, questions=(), acknowledgement='none', **kwargs):
    return {'intent': intent, 'query': '', 'product_id': None, 'quantity': None,
            'reply': 'INVENTED costs 1 KZT; stock 500; guaranteed compatible.',
            'clarification': {'topic': 'cable', 'acknowledgement': acknowledgement,
                              'question_keys': list(questions)}, **kwargs}


def post(client, message):
    response = client.post('/api/chat', json={'message': message})
    assert response.status_code == 200, response.text
    return response.json()


def scripted(client, choices):
    seen = []
    iterator = iter(choices)

    async def interpret(message, session, attachments):
        seen.append(copy.deepcopy(session.history))
        return next(iterator), []

    client.app.state.ai.interpret = interpret
    return seen


def test_cable_without_article_progresses_and_records_displayed_questions(client):
    seen = scripted(client, [
        choice(questions=['application', 'installation']),
        choice(questions=['connection', 'marking']),
        choice(questions=['connection', 'rating', 'length'], acknowledgement='no_article'),
    ])
    messages = ['Помогите подобрать кабель. Какие параметры нужно указать?',
                'Кабель для лампы нужен', 'У меня нету артикула']
    replies = [post(client, message) for message in messages]
    assert 'подключ' in replies[0]['text'].lower()
    assert 'розетк' in replies[1]['text'].lower()
    assert 'Артикул не обязателен' in replies[2]['text']
    assert replies[2]['text'].count('?') == 1
    assert 'Здравствуйте' not in ''.join(r['text'] for r in replies)
    assert all(r['cart']['count'] == 0 and r['proposal'] is None for r in replies)
    assert seen[2] == [
        {'role': 'user', 'text': messages[0]}, {'role': 'assistant', 'text': replies[0]['text']},
        {'role': 'user', 'text': messages[1]}, {'role': 'assistant', 'text': replies[1]['text']},
    ]


def test_short_answer_has_previous_question_and_unknown_parameters_offer_photo(client):
    seen = scripted(client, [choice(questions=['length']), choice(questions=['rating']),
                            choice(questions=['marking'], acknowledgement='unknown_parameters')])
    first = post(client, 'Нужен провод для лампы')
    second = post(client, 'Два метра')
    third = post(client, 'Не знаю мощность, могу прислать фото')
    assert seen[1][-1] == {'role': 'assistant', 'text': first['text']}
    assert seen[2][-2]['text'] == 'Два метра'
    assert 'длин' not in second['text'].lower()
    assert 'фото' in third['text'].lower() and third['products'] == []
    assert all(post_result['cart']['count'] == 0 for post_result in (first, second, third))


def test_clarification_does_not_repeat_connection_as_installation():
    from backend.clarification import render_clarification
    reply = render_clarification({'topic': 'cable', 'acknowledgement': 'none',
                                  'question_keys': ['installation', 'connection', 'length']})
    assert reply.count('?') == 2
    assert 'Нужен шнур от розетки' in reply and 'длина' in reply
    assert 'стационарная прокладка' not in reply


def test_model_cannot_repeat_explicitly_unavailable_photo_or_parameters(client):
    ai = client.app.state.ai
    ai.key = 'test-only'
    ai.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'output': [{'content': [{'type': 'output_text', 'text': json.dumps(choice(
            questions=['rating', 'cable_spec', 'marking', 'connection'], acknowledgement='unknown_parameters'))}]}]})))
    state = next(iter(client.app.state.sessions.values()))
    state.history = [{'role': 'user', 'text': 'Мощность и сечение не знаю.'},
                     {'role': 'assistant', 'text': 'Можете прислать фото?'}]
    result = post(client, 'Фото маркировки пока нет.')
    assert 'Нужен шнур' in result['text']
    assert not any(word in result['text'].lower() for word in ('фото', 'мощност', 'сечени'))
    assert result['cart']['count'] == 0 and result['proposal'] is None


def test_guard_does_not_treat_assistant_words_as_user_facts():
    from backend.clarification import respect_unavailable_parameters
    parsed = choice(questions=['rating', 'marking'])
    history = [{'role': 'assistant', 'text': 'Если фото нет и мощность не знаю...'}]
    assert respect_unavailable_parameters(parsed, 'Продолжим', history) == parsed


def test_known_cable_application_is_not_asked_again():
    from backend.clarification import respect_unavailable_parameters, render_clarification
    result = respect_unavailable_parameters(choice(questions=['application']),
                                             'Нужен кабель для настольной лампы. Артикула нет.', [])
    assert 'Нужен шнур от розетки' in render_clarification(result['clarification'])


def test_clarification_only_renders_allowed_questions(client):
    scripted(client, [choice(questions=['rating', 'INVENTED is in stock', 'rating', 'length', 'installation', 'marking'])])
    reply = post(client, 'Подбери кабель')
    assert 'INVENTED' not in reply['text'] and '500' not in reply['text']
    assert reply['text'].count('?') <= 3
    assert reply['products'] == [] and reply['proposal'] is None


def test_selection_then_quantity_uses_context_but_requires_new_confirmation(client):
    seen = scripted(client, [choice(questions=['marking']),
                            choice('search', query='DEMO-LAMP-10W-B'),
                            choice('add', product_id='900002'),
                            choice('add', product_id='900002', quantity=2)])
    post(client, 'Нужна лампа')
    product = post(client, 'Нашёл маркировку DEMO-LAMP-10W-B')
    assert product['products'][0]['price'] == 1200
    quantity_question = post(client, 'Добавь её')
    assert 'Сколько' in quantity_question['text']
    proposal = post(client, 'Две штуки')
    assert seen[3][-1]['text'] == quantity_question['text']
    assert proposal['cart']['count'] == 0 and proposal['proposal']['quantity'] == 2
    confirmed = post(client, 'да, добавь')
    assert confirmed['cart']['count'] == 2
    session = next(iter(client.app.state.sessions.values()))
    assert session.history[-1]['text'] == confirmed['text']


def test_clarification_yes_cannot_confirm_and_history_is_session_scoped(client):
    scripted(client, [choice(questions=['connection']), choice(questions=['length']), choice(questions=['application'])])
    proposal = client.post('/api/cart/propose', json={'product_id': '900002', 'quantity': 2}).json()['proposal']
    post(client, 'Подбери кабель')
    assert post(client, 'да')['cart']['count'] == 0
    assert client.post('/api/cart/confirm', json={'confirmation_id': proposal['confirmation_id'], 'confirmed': True}).status_code == 403
    client.cookies.clear()
    client.headers['X-CSRF-Token'] = client.get('/api/session').json()['csrf_token']
    seen = scripted(client, [choice(questions=['application'])])
    post(client, 'Помоги с подбором')
    assert seen == [[]]


def test_shortcuts_keep_six_complete_history_pairs(client):
    for i in range(7):
        message = 'Показать корзину' if i % 2 else 'отмена'
        result = post(client, message)
    history = next(iter(client.app.state.sessions.values())).history
    assert len(history) == 12
    assert [entry['role'] for entry in history] == ['user', 'assistant'] * 6
    assert history[-1]['text'] == result['text']


def test_ai_request_includes_both_roles_and_all_six_pairs(client):
    for _ in range(6):
        post(client, 'Показать корзину')
    ai = client.app.state.ai
    ai.key = 'test-only'
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'output': [{'content': [{'type': 'output_text',
                    'text': json.dumps(choice(questions=['length']))}]}]})

    ai.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    post(client, 'Дальше')
    history = captured[0]['input'][1:-1]
    assert len(history) == 12
    assert [entry['role'] for entry in history] == ['user', 'assistant'] * 6
    assert history[-1]['content'].startswith('Откройте демонстрационную корзину')
    context = json.loads(captured[0]['input'][-1]['content'][0]['text'])
    assert context['message'] == 'Дальше'


def test_fallback_no_article_has_useful_next_step(client):
    result = post(client, 'У меня нету артикула')
    assert 'Артикул не обязателен' in result['text']
    assert result['warnings'] and result['cart']['count'] == 0


def test_fallback_selection_with_known_article_still_searches(client):
    result = post(client, 'Подбери DEMO-LAMP-10W-B')
    assert result['products'][0]['id'] == '900002'
    assert result['proposal'] is None


@pytest.mark.parametrize('index_error', [None, 'Index failed'])
def test_empty_live_index_is_not_reported_as_a_missing_product(client, index_error):
    catalog = client.app.state.catalog
    catalog.live = True
    catalog.rows = {}
    catalog.index_error = index_error
    response = client.post('/api/chat', json={'message': 'ПВС'})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'upstream_unavailable'
    assert 'товар не найден' not in response.json()['error']['message']
