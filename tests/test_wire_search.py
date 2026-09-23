import asyncio

import pytest

from backend.catalog import Catalog


def search(monkeypatch, query, rows):
    for key in ('EKT_API_USERNAME', 'EKT_API_PASSWORD'):
        monkeypatch.delenv(key, raising=False)
    async def run():
        catalog = Catalog()
        catalog.rows = catalog.details = {str(i): dict(row, id=i) for i, row in enumerate(rows, 1)}
        try:
            return await catalog.search(query)
        finally:
            await catalog.close()
    return asyncio.run(run())


@pytest.mark.parametrize('query', ['Есть провод?', 'Нужны провода', 'Нужен кабель'])
def test_wire_request_rejects_wireless_devices_and_accessories(monkeypatch, query):
    rows = [{'name': name, 'quantity': 2} for name in [
        'Звонок беспроводной', 'Звонок проводной', 'Шуруповерт беспроводной',
        'Полупроводниковый модуль', 'Маркер для провода', 'Съемник изоляции кабеля',
        'Клещи для кабеля', 'Нож для кабеля', 'Провод ПВС 3х1.5',
        'Кабель ВВГнг 3х2.5', 'ШВВП 2х0.75', 'ПУГВ 1х1.5']]
    products = search(monkeypatch, query, rows)
    assert {p['id'] for p in products} == {'9', '10', '11', '12'}


def test_generic_wire_query_prefers_available_relevant_cables(monkeypatch):
    products = search(monkeypatch, 'Есть провод?', [
        {'name': 'Провод ПВС 3х1.5', 'quantity': 0},
        {'name': 'Кабель ВВГнг 3х1.5', 'quantity': 7},
        {'name': 'Звонок беспроводной', 'quantity': 100}])
    assert [p['id'] for p in products] == ['2', '1']


@pytest.mark.parametrize('query', ['Провод артикул BELL-42', 'ID: 2', 'BELL-42'])
def test_exact_article_and_explicit_id_keep_priority(monkeypatch, query):
    products = search(monkeypatch, query, [
        {'name': 'Провод ПВС', 'article': 'WIRE-11'},
        {'name': 'Звонок беспроводной', 'article': 'BELL-42'}])
    assert [p['id'] for p in products] == ['2']


def test_explicit_cable_tool_request_is_not_misinterpreted_as_wire(monkeypatch):
    products = search(monkeypatch, 'Съемник кабеля', [
        {'name': 'Съемник кабеля'}, {'name': 'Провод ПВС'}])
    assert products[0]['name'] == 'Съемник кабеля'


def test_cable_glands_outlets_and_genitive_references_are_not_wire_products(monkeypatch):
    rows = [{'name': name, 'quantity': 4} for name in [
        'Кабельный ввод 54367', 'Вывод кабеля 507698', 'Сальник для кабеля',
        'Ввод под провод', 'Держатель провода ПВС', 'Устройство для кабеля',
        'Провод монтажный ПВС 3х1.5']]
    assert [p['id'] for p in search(monkeypatch, 'Электрический провод', rows)] == ['7']


def test_electrical_wire_prefers_stock_when_relevance_is_equal(monkeypatch):
    products = search(monkeypatch, 'Электрический провод', [
        {'name': 'Провод ПВС 3х1.5', 'quantity': 0},
        {'name': 'Провод ПВС 3х2.5', 'quantity': 8}])
    assert [p['id'] for p in products] == ['2', '1']


def test_specific_wire_relevance_is_not_sacrificed_for_stock(monkeypatch):
    products = search(monkeypatch, 'Медный провод', [
        {'name': 'Провод медный ПВС', 'quantity': 0},
        {'name': 'Провод алюминиевый', 'quantity': 50}])
    assert [p['id'] for p in products] == ['1', '2']
