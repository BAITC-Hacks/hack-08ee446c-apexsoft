import asyncio

import httpx

from backend.catalog import Catalog


def test_background_index_leaves_capacity_for_customer_detail(monkeypatch):
    monkeypatch.setenv('EKT_API_USERNAME', 'test')
    monkeypatch.setenv('EKT_API_PASSWORD', 'test')
    monkeypatch.setenv('EKT_INDEX_PAGES', '4')

    async def scenario():
        catalog = Catalog()
        await catalog.client.aclose()
        started = asyncio.Event()
        release = asyncio.Event()
        page_calls = 0

        async def upstream(request):
            nonlocal page_calls
            if request.url.path == '/api/products':
                page_calls += 1
                if page_calls == 2:
                    started.set()
                await release.wait()
                return httpx.Response(200, json={'items': [], 'per_page': 20})
            return httpx.Response(200, json={'id': 515291, 'name': 'Test', 'quantity': 3})

        catalog.client = httpx.AsyncClient(
            base_url='https://ekt.kz', transport=httpx.MockTransport(upstream))
        catalog.task = asyncio.create_task(catalog.index())
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            # Pages are deliberately blocked: a foreground card must still complete.
            product = await asyncio.wait_for(catalog.detail('515291', fresh=True), timeout=1)
            assert product['stock'] == 3
            assert page_calls == 2
        finally:
            release.set()
            await catalog.close()

    asyncio.run(scenario())
