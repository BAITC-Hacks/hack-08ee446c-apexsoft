"""Kazakh wording must never change catalogue facts or authorize a bare yes."""
import copy
import re

import pytest

from backend.clarification import render_clarification
from backend.knowledge import TERMS
from backend.language import detect_language, localize_response, localize_text, normalize_command


@pytest.mark.parametrize('message,previous,expected', [
    ('Маған кабель керек', 'ru', 'kk'), ('Сәлем', 'ru', 'kk'),
    ('900002', 'kk', 'kk'), ('2', 'kk', 'kk'), ('иә', 'kk', 'kk'),
    ('На русском, пожалуйста', 'kk', 'ru'), ('Орысша жауап бер', 'kk', 'ru'),
    ('Нужен кабель', 'kk', 'ru'), ('На казахском', 'ru', 'kk'),
])
def test_language_switch_and_short_followup(message, previous, expected):
    assert detect_language(message, previous) == expected


@pytest.mark.parametrize('message,expected', [
    ('Иә, қос', 'да, добавь'), ('Қосыңыз!', 'да, добавь'),
    ('жоқ', 'нет'), ('қоспаңыз', 'нет'), ('Себетті көрсет', 'показать корзину'),
    ('иә', 'иә'), ('«иә, қос» деп жазылған', '«иә, қос» деп жазылған'),
    ('иә, қоспа', 'иә, қоспа'), ('не говори «қос»', 'не говори «қос»'),
])
def test_only_exact_explicit_commands_are_normalized(message, expected):
    assert normalize_command(message) == expected


def test_localization_preserves_product_facts_and_does_not_mutate_input():
    product = {'id': '900002', 'article': 'DEMO-LAMP-10W-B', 'name': 'Лампа 10 Вт',
               'price': 1200, 'stock': 23, 'unit': 'шт',
               'properties': {'Мощность': '10 Вт'},
               'warehouses': [{'name': 'Алматы', 'stock': None}],
               'warnings': ['остаток не указан']}
    response = {'text': 'Добавлено Лампа 10 Вт × 2. Откройте демонстрационную корзину по ссылке /cart. ',
                'products': [product], 'proposal': {'product': product, 'quantity': 2,
                    'confirmation_id': 'opaque-token'},
                'cart': {'items': [{'product': product, 'quantity': 2}], 'count': 2,
                         'total': 2400, 'version': 3, 'url': '/cart'},
                'sources': [{'title': 'Доставка и оплата — ekt.kz', 'url': 'https://ekt.kz/delivery'}]}
    original = copy.deepcopy(response)
    translated = localize_response(response, 'kk')
    assert response == original
    assert translated['text'].startswith('Қосылды: Лампа 10 Вт × 2.')
    assert translated['proposal']['confirmation_id'] == 'opaque-token'
    assert translated['cart']['count'] == 2 and translated['cart']['total'] == 2400
    for key, value in product.items():
        if key != 'warnings':
            assert translated['products'][0][key] == value
            assert translated['cart']['items'][0]['product'][key] == value
    assert translated['products'][0]['warnings'] == ['қалдық саны көрсетілмеген']
    assert translated['sources'][0]['url'] == response['sources'][0]['url']


def test_clarification_questions_and_terms_are_localized_without_changing_numbers():
    question = render_clarification({'topic': 'cable', 'acknowledgement': 'no_article',
                                    'question_keys': ['connection']})
    translated = localize_text(question, 'kk')
    assert 'Артикул міндетті емес' in translated and 'Розеткадан' in translated
    assert 'Нужен' not in translated and translated.count('?') == 1
    assert re.findall(r'\d+', localize_text(TERMS, 'kk')) == re.findall(r'\d+', TERMS)


def test_russian_and_unrecognized_catalogue_text_are_preserved():
    response = {'text': 'Неизвестное обозначение XYZ-10'}
    assert localize_response(response, 'ru') == response
    assert localize_text(response['text'], 'kk') == response['text']


@pytest.mark.parametrize('message,intent,quantity,pid', [
    ('Жеткізу және төлем шарттары', 'terms', None, None),
    ('Сәлеметсіз бе', 'other', None, None),
    ('Маған кабель керек', 'clarify', None, None),
    ('Артикул жоқ', 'clarify', None, None),
    ('Осы тауардан 2 дана қос', 'add', 2, '21'),
    ('Оны себетке қосыңыз', 'add', None, '21'),
    ('NEW-22 тауарын қос', 'add', None, None),
    ('Осы тауардың баламасын тап', 'alternatives', None, None),
])
def test_kazakh_fallback_understands_common_intents_without_guessing_quantity(message, intent, quantity, pid):
    from backend.ai import AI
    from backend.state import Session
    session = Session(last_products=[{'id': '21', 'article': 'ONLY-11'}])
    result = AI.__new__(AI).fallback(message, session)
    assert result['intent'] == intent
    assert result['quantity'] == quantity and result['product_id'] == pid


def test_kazakh_quantity_cannot_be_mistaken_for_product_identifier():
    from backend.ai import AI
    from backend.state import Session
    session = Session(last_products=[{'id': '21', 'article': 'FIRST'}, {'id': '22', 'article': 'TARGET'}])
    result = AI.__new__(AI).fallback('TARGET 21 дана қос', session)
    assert result['quantity'] == 21 and result['product_id'] == '22'
