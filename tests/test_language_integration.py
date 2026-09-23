"""Session and API integration of Kazakh server replies; no external services."""
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app


@pytest.fixture
def client(monkeypatch):
    for key in ('EKT_API_USERNAME','EKT_API_PASSWORD','OPENAI_API_KEY'):
        monkeypatch.delenv(key,raising=False)
    with TestClient(create_app()) as c:
        c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf_token']
        yield c


def test_kazakh_catalog_reply_preserves_facts_and_language_across_short_followup(client):
    expected=client.get('/api/products/900002').json()
    body={'message':'DEMO-LAMP-10W-B бар ма?','request_id':'request-kazakh-product'}
    response=client.post('/api/chat',json=body)
    assert response.status_code==200
    data=response.json()
    assert 'қоймада бар: 12' in data['text'] and '1200 ₸' in data['text']
    assert 'в наличии' not in data['text']
    for key in ('id','article','name','price','stock','quantity_step','specifications'):
        assert data['products'][0][key]==expected[key]
    state=next(iter(client.app.state.sessions.values()))
    assert state.language=='kk'
    assert state.history[-1]['text']==data['text']
    assert client.post('/api/chat',json=body).json()==data
    followup=client.post('/api/chat',json={'message':'DEMO-LAMP-10W-B'}).json()
    assert 'қоймада бар: 12' in followup['text']
    russian=client.post('/api/chat',json={'message':'Найди DEMO-LAMP-10W-B, на русском'}).json()
    assert 'в наличии 12' in russian['text']


@pytest.mark.parametrize('message,expected',[('Сәлем','Сәлеметсіз бе'),('Жеткізу шарттары қандай?','Жеткізу:'),('Кабель керек','Кабельді')])
def test_kazakh_intents_render_in_kazakh_and_store_displayed_history(client,monkeypatch,message,expected):
    # Isolate response localization from the AI classifier, which has its own tests.
    kind='terms' if 'Жеткізу' in message else 'clarify' if 'Кабель' in message else 'other'
    async def intent(*args):
        return {'intent':kind,'query':'','product_id':None,'quantity':None,'reply':'',
                'clarification':{'topic':'cable','acknowledgement':'none','question_keys':['application']}},[]
    monkeypatch.setattr(client.app.state.ai,'interpret',intent)
    data=client.post('/api/chat',json={'message':message}).json()
    assert expected in data['text']
    state=next(iter(client.app.state.sessions.values()))
    assert state.history[-1]['text']==data['text']


def test_kazakh_confirmation_is_explicit_and_replay_is_safe(client):
    client.post('/api/chat',json={'message':'DEMO-LAMP-10W-B бар ма?'})
    def proposal():
        return client.post('/api/cart/propose',json={'product_id':'900002','quantity':2}).json()['proposal']
    proposal()
    assert client.post('/api/chat',json={'message':'иә'}).json()['cart']['count']==0
    proposal()
    body={'message':'иә, қос','request_id':'kazakh-confirmation'}
    result=client.post('/api/chat',json=body).json()
    assert result['text'].startswith('Қосылды:')
    assert result['cart']['count']==2
    assert client.post('/api/chat',json=body).json()==result
    assert client.get('/api/cart').json()['count']==2
    assert 'демонстрациялық' in client.get('/api/cart').json()['notice']
    proposal()
    cancelled=client.post('/api/chat',json={'message':'қоспаңыз'}).json()
    assert cancelled['text']=='Қосу тоқтатылды. Себет өзгерген жоқ.'
    assert cancelled['cart']['count']==2


def test_kazakh_cart_button_confirmation_and_errors_are_localized(client):
    client.post('/api/chat',json={'message':'Қазақша жауап беріңіз'})
    data=client.post('/api/cart/propose',json={'product_id':'900002','quantity':2}).json()
    token=data['proposal']['confirmation_id']
    assert 'демонстрациялық' in data['cart']['notice']
    rejected=client.post('/api/cart/confirm',json={'confirmation_id':token,'confirmed':False})
    assert rejected.status_code==403
    assert rejected.json()['error']['message']=='Қосуға нақты растау қажет.'
    result=client.post('/api/cart/confirm',json={'confirmation_id':token,'confirmed':True}).json()
    assert result['text'].startswith('Қосылды:')
    assert result['cart']['count']==2
