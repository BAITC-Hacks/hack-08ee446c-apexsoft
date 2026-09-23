"""Catalogue coverage regressions using bounded, synthetic upstream fixtures."""
import asyncio

import httpx
import pytest

from backend.catalog import Catalog, normalize
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


@pytest.mark.parametrize('url',[None,'','https://ekt.kz/','https://ekt.kz/catalog/','javascript:alert(1)'])
def test_missing_product_link_is_not_replaced_with_store_home(url):
    product=normalize({'id':1,'url':url})
    assert product['product_url'] is None


def test_real_photo_description_and_deep_link_are_preserved():
    product=normalize({'id':1,'url':'/catalog/tools/drill/', 'image':'/upload/drill.jpg',
                       'description':'<p>Описание дрели</p>'})
    assert product['product_url']=='https://ekt.kz/catalog/tools/drill/'
    assert product['image_url']=='https://ekt.kz/upload/drill.jpg'
    assert product['description']=='Описание дрели'


def test_index_reaches_products_beyond_original_2000_and_reports_completion(monkeypatch):
    monkeypatch.delenv('EKT_INDEX_PAGES',raising=False)
    calls=[]
    async def upstream(request):
        if request.url.path=='/api/products/detail':
            return httpx.Response(200,json=row(2001,'Дрель-шуруповерт TEST',price=12500,quantity=3))
        page=int(request.url.params['page']); size=int(request.url.params['per_page'])
        calls.append((page,size))
        assert size==100
        begin=(page-1)*size+1
        items=[row(i,'Дрель-шуруповерт TEST' if i==2001 else 'Кабель') for i in range(begin,min(begin+size,2002))]
        return httpx.Response(200,json={'items':items,'page':page,'per_page':size,'count':len(items)})
    async def scenario(catalog):
        await catalog.index()
        assert catalog.complete and not catalog.index_error
        assert len(catalog.rows)==2001
        products=await catalog.search('шуруповёрт')
        assert [p['id'] for p in products]==['2001'] and products[0]['stock']==3
        assert max(p for p,_ in calls)<=22
    run_catalog(monkeypatch,scenario,upstream)


def test_wrapping_page_stops_without_claiming_complete_catalog(monkeypatch):
    calls=[]
    async def upstream(request):
        page=int(request.url.params['page']);calls.append(page)
        # EKT reports the requested page even when its contents wrap to page one.
        ids=[1,2] if page in (1,3) else [3,4]
        return httpx.Response(200,json={'items':[row(i) for i in ids],'page':page,'per_page':2})
    async def scenario(catalog):
        await catalog.index()
        assert len(catalog.rows)==4 and not catalog.complete
        assert catalog.index_error and max(calls)==4
    run_catalog(monkeypatch,scenario,upstream)


def test_explicit_page_limit_is_respected_and_not_mislabeled_complete(monkeypatch):
    monkeypatch.setenv('EKT_INDEX_PAGES','2')
    calls=[]
    async def upstream(request):
        page=int(request.url.params['page']);calls.append(page)
        return httpx.Response(200,json={'items':[row(page)],'per_page':1})
    async def scenario(catalog):
        await catalog.index()
        assert calls==[1,2] and len(catalog.rows)==2
        assert not catalog.complete and catalog.index_error
    run_catalog(monkeypatch,scenario,upstream)


def test_index_failure_preserves_loaded_products_without_false_completion(monkeypatch):
    async def upstream(request):
        page=int(request.url.params['page'])
        if page>2:return httpx.Response(503)
        return httpx.Response(200,json={'items':[row(page)],'per_page':1})
    async def scenario(catalog):
        await catalog.index()
        assert set(catalog.rows)=={'1','2'} and not catalog.complete and catalog.index_error
    run_catalog(monkeypatch,scenario,upstream)


def test_named_tool_for_home_does_not_return_home_sirens(monkeypatch):
    rows={'1':row(1,'Дрель-шуруповерт TEST'), '2':row(2,'Сирена домашняя')}
    async def upstream(request):
        return httpx.Response(200,json=rows[request.url.params['id']])
    async def scenario(catalog):
        catalog.rows=rows
        assert [p['id'] for p in await catalog.search('шуруповёрт для дома')]==['1']
    run_catalog(monkeypatch,scenario,upstream)


def test_budget_reaches_affordable_candidate_beyond_first_six_names(monkeypatch):
    rows={str(i):row(i,'Дрель-шуруповерт TEST',price=80000 if i<8 else 30000) for i in range(1,9)}
    calls=[]
    async def upstream(request):
        pid=request.url.params['id'];calls.append(pid)
        return httpx.Response(200,json=rows[pid])
    async def scenario(catalog):
        catalog.rows=rows
        products=await catalog.search('шуруповерт',max_price=50000)
        assert [p['id'] for p in products]==['8']
        assert calls[0]=='8'
    run_catalog(monkeypatch,scenario,upstream)


@pytest.mark.parametrize('actual_price',[60000,None])
def test_budget_never_trusts_stale_or_unknown_detail_price(monkeypatch,actual_price):
    async def upstream(request):
        return httpx.Response(200,json=row(1,'Дрель-шуруповерт TEST',price=actual_price))
    async def scenario(catalog):
        catalog.rows={'1':row(1,'Дрель-шуруповерт TEST',price=10000)}
        catalog.details=dict(catalog.rows)
        # A freshly cached old card still must be rechecked for budget selection.
        import time
        catalog.checked_clock['1']=time.monotonic()
        assert await catalog.search('шуруповерт',max_price=50000)==[]
    run_catalog(monkeypatch,scenario,upstream)


def test_explicit_id_respects_budget_without_changing_id_semantics(monkeypatch):
    async def upstream(request):
        return httpx.Response(200,json=row(1,'Дрель-шуруповерт TEST',price=60000))
    async def scenario(catalog):
        assert await catalog.search('ID:1',max_price=50000)==[]
        assert [p['id'] for p in await catalog.search('ID:1')]==['1']
    run_catalog(monkeypatch,scenario,upstream)
