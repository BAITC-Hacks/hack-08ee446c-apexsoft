import asyncio

import httpx
import pytest

from backend.catalog import Catalog
from backend.errors import AppError


def run_catalog(monkeypatch, scenario, upstream):
    monkeypatch.setenv('EKT_API_USERNAME', 'test')
    monkeypatch.setenv('EKT_API_PASSWORD', 'test')

    async def run():
        catalog = Catalog()
        await catalog.client.aclose()
        catalog.client = httpx.AsyncClient(base_url='https://ekt.kz', transport=httpx.MockTransport(upstream))
        try:
            await scenario(catalog)
        finally:
            await catalog.close()

    asyncio.run(run())


@pytest.mark.parametrize('model', ['GL 1004D', 'GL1004', 'GL 1004', '4000К'])
def test_model_or_rating_is_never_guessed_to_be_internal_id(monkeypatch, model):
    calls = []
    row = {'id': 515291, 'name': 'Светильник Elektrostandard ' + model, 'quantity': 3}

    async def upstream(request):
        pid = request.url.params['id']
        calls.append(pid)
        return httpx.Response(200, json=row) if pid == '515291' else httpx.Response(404)

    async def scenario(catalog):
        catalog.rows = {'515291': row}
        products = await catalog.search('Светильник Elektrostandard ' + model)
        assert [p['id'] for p in products] == ['515291']
        assert calls == ['515291']

    run_catalog(monkeypatch, scenario, upstream)


@pytest.mark.parametrize('query', ['515291', 'ID: 515291', 'Найди товар с ID 515291'])
def test_explicit_id_works_outside_loaded_index(monkeypatch, query):
    async def upstream(request):
        assert request.url.params['id'] == '515291'
        return httpx.Response(200, json={'id': 515291, 'name': 'Товар', 'quantity': 3})

    async def scenario(catalog):
        assert (await catalog.search(query))[0]['id'] == '515291'

    run_catalog(monkeypatch, scenario, upstream)


def test_missing_detail_is_not_reported_as_service_outage(monkeypatch):
    async def upstream(request):
        return httpx.Response(404, text='Not found')

    async def scenario(catalog):
        with pytest.raises(AppError) as error:
            await catalog.detail('1004', fresh=True)
        assert error.value.code == 'not_found' and error.value.status == 404

    run_catalog(monkeypatch, scenario, upstream)


def test_short_model_prefix_does_not_match_unrelated_brand(monkeypatch):
    calls = []
    async def upstream(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={'id': 30075, 'name': 'GLOSSA выключатель', 'quantity': 2})

    async def scenario(catalog):
        catalog.rows = {'30075': {'id': 30075, 'name': 'GLOSSA выключатель'}}
        assert await catalog.search('Elektrostandard GL 1004D') == []
        assert await catalog.search('Elektrostandard GL') == []
        assert calls == []

    run_catalog(monkeypatch, scenario, upstream)


def test_known_article_is_prioritized_over_partial_similar_products(monkeypatch):
    rows = {'21': {'id': 21, 'article': 'DEMO-LAMP-10W-B', 'name': 'Лампа B'},
            '22': {'id': 22, 'article': 'DEMO-LAMP-10W-A', 'name': 'Лампа A'}}
    async def upstream(request):
        return httpx.Response(200, json=rows[request.url.params['id']])

    async def scenario(catalog):
        catalog.rows = rows
        products = await catalog.search('Найди DEMO-LAMP-10W-B')
        assert [p['id'] for p in products] == ['21']

    run_catalog(monkeypatch, scenario, upstream)


def test_explicit_id_takes_priority_over_another_products_numeric_article(monkeypatch):
    async def upstream(request):
        pid = request.url.params['id']
        return httpx.Response(200, json={'id': int(pid), 'name': 'Товар'})

    async def scenario(catalog):
        catalog.rows = {'42': {'id': 42, 'article': '515291', 'name': 'Другой товар'}}
        assert (await catalog.search('ID: 515291'))[0]['id'] == '515291'
        # A bare number that exactly matches an article retains article lookup.
        assert (await catalog.search('515291'))[0]['id'] == '42'

    run_catalog(monkeypatch, scenario, upstream)


@pytest.mark.parametrize('query,name', [
    ('Lamp 4000 K', 'Lamp 4000K'),
    ('Elektrostandard GL1004D', 'Elektrostandard GL 1004D'),
    ('Elektrostandard GL 1004D', 'Elektrostandard GL1004D'),
])
def test_model_formatting_spaces_do_not_hide_a_match(monkeypatch, query, name):
    row = {'id': 515291, 'name': name}
    async def upstream(request):
        assert request.url.params['id'] == '515291'
        return httpx.Response(200, json=row)

    async def scenario(catalog):
        catalog.rows = {'515291': row}
        assert (await catalog.search(query))[0]['id'] == '515291'

    run_catalog(monkeypatch, scenario, upstream)


@pytest.mark.parametrize('name', ['Elektrostandard GL 1004A', 'Elektrostandard GL 10045D'])
def test_different_model_suffix_or_digits_are_not_substituted(monkeypatch, name):
    async def upstream(request):
        pytest.fail('An unrelated model must not be fetched')

    async def scenario(catalog):
        catalog.rows = {'21': {'id': 21, 'name': name}}
        assert await catalog.search('Elektrostandard GL1004D') == []

    run_catalog(monkeypatch, scenario, upstream)


def test_one_deleted_candidate_does_not_hide_other_matches(monkeypatch):
    rows = {'21': {'id': 21, 'name': 'Лампа настольная'}, '22': {'id': 22, 'name': 'Лампа настольная'}}
    async def upstream(request):
        pid = request.url.params['id']
        return httpx.Response(404) if pid == '21' else httpx.Response(200, json=rows[pid])

    async def scenario(catalog):
        catalog.rows = rows
        assert [p['id'] for p in await catalog.search('Лампа настольная')] == ['22']

    run_catalog(monkeypatch, scenario, upstream)


@pytest.mark.parametrize('failure', [401, 403, 429, 503, 'timeout', 'invalid_json'])
def test_actual_upstream_failures_are_never_treated_as_missing_products(monkeypatch, failure):
    async def upstream(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('test timeout', request=request)
        if failure == 'invalid_json':
            return httpx.Response(200, text='not json')
        return httpx.Response(failure)

    async def scenario(catalog):
        with pytest.raises(AppError) as error:
            await catalog.search('515291')
        assert error.value.code == 'upstream_unavailable' and error.value.status == 503

    run_catalog(monkeypatch, scenario, upstream)
