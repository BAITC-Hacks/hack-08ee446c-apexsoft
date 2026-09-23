import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.browsing import named_tool_query


@pytest.fixture
def client(monkeypatch):
    for key in ('EKT_API_USERNAME','EKT_API_PASSWORD','OPENAI_API_KEY'):
        monkeypatch.delenv(key,raising=False)
    with TestClient(create_app()) as c:
        c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf_token']
        yield c


def test_russian_catalogue_overview_leaves_kazakh_and_returns_real_examples(client):
    client.post('/api/chat',json={'message':'Сәлем'})
    assert next(iter(client.app.state.sessions.values())).language=='kk'
    result=client.post('/api/chat',json={'message':'что у вас есть'}).json()
    assert result['text'].startswith('Вот примеры товаров')
    assert result['products'] and result['cart']['count']==0
    assert all(p['source']=='snapshot' for p in result['products'])
    assert next(iter(client.app.state.sessions.values())).language=='ru'


def test_generic_followup_reuses_requested_category_and_reset_clears_it(client,monkeypatch):
    calls=[]
    original=client.app.state.catalog.search
    async def search(query,*args,**kwargs):
        calls.append(query)
        return await original(query,*args,**kwargs)
    monkeypatch.setattr(client.app.state.catalog,'search',search)
    client.post('/api/chat',json={'message':'шуруповёрт'})
    client.post('/api/chat',json={'message':'что у вас есть'})
    assert calls==['шуруповёрт','шуруповёрт']
    client.post('/api/chat/reset',json={})
    client.post('/api/chat',json={'message':'что у вас есть'})
    assert calls[-1]==''


def test_explicit_full_catalogue_leaves_previous_category(client):
    client.post('/api/chat',json={'message':'шуруповёрт'})
    result=client.post('/api/chat',json={'message':'Покажи весь каталог'}).json()
    assert result['text'].startswith('Вот примеры товаров') and result['products']


@pytest.mark.parametrize('message', ['Шуруповёрт','Мне нужен шуруповерт','Подбери аккумуляторный шуруповерт 18В Makita'])
def test_named_tool_search_preserves_requested_specs_when_model_overclarifies(client,monkeypatch,message):
    parsed={'intent':'clarify','query':'','product_id':None,'quantity':None,'reply':'',
            'clarification':{'topic':'general','acknowledgement':'none','question_keys':['description']}}
    ai=client.app.state.ai; ai.key='test-only'
    ai.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={
        'output':[{'content':[{'type':'output_text','text':json.dumps(parsed)}]}]})))
    calls=[]
    async def search(query,*args,**kwargs): calls.append(query); return []
    monkeypatch.setattr(client.app.state.catalog,'search',search)
    result=client.post('/api/chat',json={'message':message}).json()
    assert calls==[message]
    assert '?' not in result['text'] and result['cart']['count']==0


@pytest.mark.parametrize('message',['Какой кабель нужен для дрели?','Не нужен шуруповерт','Добавь шуруповерт','Почему дрель греется?'])
def test_shortcut_does_not_override_other_intents(message):
    assert named_tool_query(message) is None
