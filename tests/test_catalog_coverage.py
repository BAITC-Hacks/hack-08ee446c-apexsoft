"""Catalogue coverage regressions using bounded, synthetic upstream fixtures."""
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


def row(pid, name='Товар', category='tools', **extra):
    return {'id':pid, 'name':name, 'url':f'https://ekt.kz/catalog/{category}/item-{pid}/', **extra}


def test_overview_samples_different_loaded_categories_with_fresh_facts(monkeypatch):
    rows={str(i):row(i, category='cables' if i<4 else 'tools', price=1, quantity=999) for i in range(1,5)}
    async def upstream(request):
        return httpx.Response(200,json={**rows[request.url.params['id']], 'price':123, 'quantity':2})
    async def scenario(catalog):
        catalog.rows=rows
        result=await catalog.overview(2)
        assert [p['id'] for p in result['products']]==['1','4']
        assert result['categories']==['cables','tools']
        assert result['indexed_products']==4 and result['index_complete'] is False
        assert all(p['price']==123 and p['stock']==2 and p['source']=='live' for p in result['products'])
    run_catalog(monkeypatch,scenario,upstream)


def test_overview_skips_deleted_examples(monkeypatch):
    async def upstream(request):
        pid=request.url.params['id']
        return httpx.Response(404) if pid=='1' else httpx.Response(200,json=row(int(pid)))
    async def scenario(catalog):
        catalog.rows={str(i):row(i) for i in range(1,4)}
        result=await catalog.overview(2)
        assert [p['id'] for p in result['products']]==['2','3']
    run_catalog(monkeypatch,scenario,upstream)


def test_overview_does_not_turn_upstream_outage_into_empty_catalog(monkeypatch):
    async def upstream(request):
        return httpx.Response(503)
    async def scenario(catalog):
        catalog.rows={'1':row(1)}
        with pytest.raises(AppError) as error:
            await catalog.overview()
        assert error.value.code=='upstream_unavailable'
    run_catalog(monkeypatch,scenario,upstream)


def test_empty_live_overview_reports_loading_not_absence(monkeypatch):
    async def scenario(catalog):
        with pytest.raises(AppError) as error:
            await catalog.overview()
        assert error.value.status==503
    run_catalog(monkeypatch,scenario,lambda _: httpx.Response(503))
