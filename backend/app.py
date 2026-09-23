import asyncio
import copy
import hashlib
import io
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool
from .ai import AI
from .clarification import render_clarification
from .body_limit import BodyLimit
from .attachments import MAX_BYTES, parse_file
from .catalog import Catalog
from .errors import AppError
from .knowledge import SOURCES, TERMS
from .state import Session, propose, confirm
from .language import detect_language, localize_response, localize_text, normalize_command
from .browsing import is_overview, budget_from_message, without_budget, search_followup, named_tool_query
from .visual import image_inputs, valid_visual, photo_query, photo_reply
from .privacy import reject_payment_data
from .document_search import document_matches

ROOT=Path(__file__).resolve().parents[1]

class ChatIn(BaseModel):
    message: str=Field(min_length=1,max_length=3000)
    attachment_ids: list[str]=Field(default_factory=list,max_length=4)
    request_id: str|None=Field(default=None,pattern=r'^[A-Za-z0-9_-]{10,100}$')

class ProposalIn(BaseModel):
    product_id: str=Field(pattern=r'^\d{1,12}$')
    quantity: float=Field(gt=0,le=100000,allow_inf_nan=False)

class ConfirmIn(BaseModel):
    confirmation_id: str=Field(pattern=r'^[A-Za-z0-9_-]{10,100}$')
    confirmed: StrictBool=False

class CancelIn(BaseModel):
    confirmation_id: str=Field(pattern=r'^[A-Za-z0-9_-]{10,100}$')

class RemoveAttachmentsIn(BaseModel):
    attachment_ids: list[str]=Field(max_length=8)

class RemoveCartIn(BaseModel):
    product_id: str=Field(pattern=r'^\d{1,12}$')
    confirmed: StrictBool=False
    version: int=Field(ge=0,strict=True)

def create_app(catalog=None,ai=None):
    catalog=catalog or Catalog(); ai=ai or AI(); sessions={}

    @asynccontextmanager
    async def lifespan(app):
        catalog.task=asyncio.create_task(catalog.index())
        yield
        await catalog.close(); await ai.client.aclose()

    app=FastAPI(title='EKT Assistant',version='1.0.0',lifespan=lifespan)
    app.add_middleware(BodyLimit)
    app.state.sessions=sessions; app.state.catalog=catalog; app.state.ai=ai

    @app.exception_handler(AppError)
    async def app_error(request,error):
        current=sessions.get(request.cookies.get('ekt_session'))
        text=localize_text(error.message,current.language if current else 'ru')
        return JSONResponse({'error':{'code':error.code,'message':text}},status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,error):
        return JSONResponse({'error':{'code':'invalid_request','message':'Проверьте текст, идентификатор и положительное количество.'}},status_code=422)

    @app.middleware('http')
    async def protections(request,call_next):
        if request.method=='POST':
            try: content_length=int(request.headers.get('content-length','0'))
            except ValueError: content_length=MAX_BYTES+65537
            limit=MAX_BYTES+65536 if request.url.path=='/api/attachments' else 50000
            if content_length>limit:
                return JSONResponse({'error':{'code':'attachment_too_large','message':'Запрос слишком большой.'}},status_code=413)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    def session(request,create=False):
        current=time.time()
        for sid in list(sessions):
            if sessions[sid].touched<current-7200: del sessions[sid]
        s=sessions.get(request.cookies.get('ekt_session'))
        if s is None:
            if not create: raise AppError('session_required','Обновите страницу, чтобы начать новую сессию.',403)
            if len(sessions)>=500: raise AppError('rate_limit','Сервер занят. Повторите позже.',429)
            s=Session(); sessions[s.id]=s
        s.touched=current
        if request.method=='POST':
            if not secrets.compare_digest(request.headers.get('x-csrf-token','').encode('utf-8'),s.csrf.encode('utf-8')):
                raise AppError('csrf','Сессия не подтверждена. Обновите страницу.',403)
            s.limit()
        return s

    def integrations():
        return {'catalog':'live' if catalog.live else ('snapshot' if catalog.rows else 'unavailable'),
            'ai':'openai' if ai.key else 'fallback','cart':'demo','indexed_products':len(catalog.rows),
            'index_complete':catalog.complete,
            'notice':'Живой каталог ekt.kz; корзина демонстрационная.' if catalog.live else 'Синтетические демонстрационные товары. Это не актуальные цены и наличие ekt.kz.'}

    def chat_result(s,text='',products=None,proposal=None,sources=None,warnings=None):
        return {'message_id':secrets.token_hex(12),'text':text,'products':products or [],'proposal':proposal,
            'cart':s.cart(),'sources':sources or [],'warnings':warnings or [],
            'suggestions':['Условия доставки и оплаты','Найти аналог','Показать корзину'], 'integrations':integrations()}

    @app.get('/api/health')
    async def health(): return {'status':'ok','integrations':integrations()}

    @app.get('/api/session')
    async def get_session(request:Request):
        s=session(request,True)
        response=JSONResponse(localize_response({'session_id':s.id,'csrf_token':s.csrf,'cart':s.cart(),'integrations':integrations()},s.language))
        response.set_cookie('ekt_session',s.id,httponly=True,samesite='lax',secure=os.getenv('EKT_SECURE_COOKIE','false').lower()=='true',max_age=7200)
        return response

    @app.get('/api/products')
    async def search(q:str=''):
        if len(q)>300: raise AppError('invalid_request','Слишком длинный поисковый запрос.')
        return {'products':await catalog.search(q),'index_complete':catalog.complete}

    @app.get('/api/products/{pid}/alternatives')
    async def alternatives(pid:str):
        products,warnings=await catalog.alternatives(pid)
        return {'products':products,'warnings':warnings}

    @app.get('/api/products/{pid}')
    async def detail(pid:str): return await catalog.detail(pid,fresh=catalog.live)

    @app.get('/api/cart')
    async def get_cart(request:Request):
        s=session(request)
        return localize_response({'cart':s.cart()},s.language)['cart']

    @app.post('/api/cart/propose')
    async def cart_propose(body:ProposalIn,request:Request):
        s=session(request)
        async with s.lock: return localize_response({'proposal':await propose(s,catalog,body.product_id,body.quantity),'cart':s.cart()},s.language)

    @app.post('/api/cart/confirm')
    async def cart_confirm(body:ConfirmIn,request:Request):
        s=session(request)
        async with s.lock: return localize_response(await confirm(s,catalog,body.confirmation_id,body.confirmed),s.language)

    @app.post('/api/cart/cancel')
    async def cart_cancel(body:CancelIn,request:Request):
        s=session(request)
        async with s.lock:
            if s.pending and secrets.compare_digest(s.pending['proposal']['confirmation_id'],body.confirmation_id): s.pending=None
            return localize_response({'cart':s.cart()},s.language)

    @app.post('/api/cart/remove')
    async def cart_remove(body:RemoveCartIn,request:Request):
        s=session(request)
        async with s.lock:
            if body.confirmed is not True:
                raise AppError('confirmation_required','Подтвердите удаление товара из корзины.',403)
            # A retry is harmless, and a stale view cannot delete a re-added item.
            if body.product_id not in s.items: return localize_response({'cart':s.cart()},s.language)
            if body.version!=s.version:
                raise AppError('cart_changed','Корзина изменилась. Обновите её и повторите удаление.',409)
            del s.items[body.product_id]
            s.version+=1; s.pending=None
            return localize_response({'cart':s.cart()},s.language)

    @app.post('/api/attachments')
    async def attach(request:Request):
        s=session(request)
        async with s.lock:
            if len(s.attachments)>=8: raise AppError('attachment_too_large','В сессии допускается 8 вложений. Начните новую сессию.',413)
            data=bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data)>MAX_BYTES+65536: raise AppError('attachment_too_large','Максимум 8 МБ на файл.',413)
            from python_multipart.multipart import create_form_parser
            files=[]; opened=[]
            def on_file(f):
                f.file_object.seek(0)
                files.append(((f.file_name or b'file').decode('utf-8',errors='replace'),f.file_object.read(MAX_BYTES+1)))
                opened.append(f)
            try:
                parser=create_form_parser({'Content-Type':request.headers.get('content-type','').encode()},None,on_file,
                    config={'MAX_MEMORY_FILE_SIZE':MAX_BYTES+65536,'MAX_BODY_SIZE':MAX_BYTES+65536})
                parser.write(bytes(data)); parser.finalize(); parser.close()
            except Exception: raise AppError('invalid_attachment','Не удалось прочитать загрузку файла.',422)
            finally:
                for f in opened: f.close()
            if len(files)!=1: raise AppError('invalid_attachment','Загрузите один файл за раз.',422)
            attachment=await asyncio.to_thread(parse_file,*files[0])
            reject_payment_data(attachment['name'])
            reject_payment_data(attachment['extracted_text'])
            aid=secrets.token_urlsafe(16)
            s.attachments[aid]=attachment
            return {'attachment_id':aid,**{k:v for k,v in attachment.items() if k not in {'image','images'}}}

    @app.post('/api/attachments/remove')
    async def remove_attachments(body:RemoveAttachmentsIn,request:Request):
        s=session(request)
        async with s.lock:
            # Only this session's pending uploads are affected; repeated removal is safe.
            for aid in body.attachment_ids: s.attachments.pop(aid,None)
            return {'removed':True}

    @app.post('/api/chat/reset')
    async def reset_chat(request:Request):
        s=session(request)
        async with s.lock:
            s.history.clear(); s.last_products.clear(); s.attachments.clear(); s.pending=None
            s.last_search_query=''
            s.last_visual=None
            s.search_max_price=None
            s.chat_receipts.clear()
            return localize_response({'cart':s.cart()},s.language)

    @app.post('/api/chat')
    async def chat(body:ChatIn,request:Request):
        s=session(request)
        async with s.lock:
            message=body.message.strip()
            if not message: raise AppError('invalid_request','Напишите вопрос о товаре.')
            reject_payment_data(message)
            fingerprint=hashlib.sha256(json.dumps([message,body.attachment_ids],ensure_ascii=False).encode()).hexdigest()
            cached=s.chat_receipts.get(body.request_id)
            if cached:
                if cached['fingerprint']!=fingerprint:
                    raise AppError('request_conflict','Этот идентификатор уже использован для другого сообщения.',409)
                response=copy.deepcopy(cached['response'])
                response['cart']=localize_response({'cart':s.cart()},s.language)['cart']
                if response['proposal'] and (not s.pending or s.pending['proposal']['confirmation_id']!=response['proposal']['confirmation_id']):
                    response['proposal']=None
                return response
            s.language=detect_language(message,s.language)
            command=normalize_command(message)
            for aid in body.attachment_ids:
                if aid not in s.attachments: raise AppError('not_found','Вложение не найдено в этой сессии.',404)
            def respond(text='',products=None,proposal=None,sources=None,warnings=None):
                response=localize_response(chat_result(s,text,products,proposal,sources,warnings),s.language)
                # Record completed exchanges, including deterministic cart replies, exactly as displayed.
                s.history.extend([{'role':'user','text':message},{'role':'assistant','text':response['text']}])
                s.history=s.history[-12:]
                # The UI consumes uploads after a successful answer. Failed requests retain them for retry.
                for aid in body.attachment_ids: s.attachments.pop(aid,None)
                if body.request_id:
                    s.chat_receipts[body.request_id]={'fingerprint':fingerprint,'response':copy.deepcopy(response)}
                    if len(s.chat_receipts)>32: s.chat_receipts.pop(next(iter(s.chat_receipts)))
                return response
            affirmative=re.fullmatch(r'(?:да[,!\s]+)?добавь(?:те)?[.!\s]*',command,re.I)
            if affirmative and s.pending and not body.attachment_ids:
                result=await confirm(s,catalog,s.pending['proposal']['confirmation_id'],True)
                return respond(result['text'])
            s.pending=None  # A new request supersedes any previous quote, including refusal.
            if re.fullmatch(r'(?:нет|отмена|не добавляй|не добавлять)[.!\s]*',command,re.I):
                return respond('Добавление отменено. Корзина не изменилась.')
            if re.fullmatch(r'(?:показать |покажи |открыть |открой )?корзин[ау][.!\s]*',command,re.I):
                return respond('Откройте демонстрационную корзину по ссылке /cart. '+s.cart()['notice'])
            attachments=[s.attachments[aid] for aid in body.attachment_ids]
            document_ids=document_matches(catalog.rows,attachments)
            if len(document_ids)>1:
                products=await asyncio.gather(*(catalog.detail(pid,fresh=catalog.live) for pid in document_ids[:6]))
                s.last_products=products
                return respond('В документе найдены несколько артикулов. Выберите карточку товара для продолжения; корзина не менялась.',products,
                    warnings=['Показаны первые 6 совпадений из документа.'] if len(document_ids)>6 else [])
            if document_ids:
                intent={'intent':'search','query':'ID: '+document_ids[0],'product_id':None,'quantity':None}
                warnings=[]
            elif is_overview(message) and not attachments:
                query='' if re.search(r'весь|вообще',message,re.I) else s.last_search_query
                intent={'intent':'search' if query else 'overview','query':query,'product_id':None,'quantity':None}
                warnings=[]
            else:
                intent,warnings=await ai.interpret(message,s,attachments)
            if image_inputs(attachments) and (not ai.key or warnings):
                return respond('Фото не удалось распознать. Напишите маркировку или артикул текстом.',warnings=warnings)
            if any(a['kind']=='image' for a in attachments):
                visual=intent.get('visual')
                if not valid_visual(visual):
                    return respond('Фото не удалось распознать. Напишите маркировку или артикул текстом.',warnings=warnings)
                products=[]
                s.last_visual=None; s.last_search_query=''
                if visual['status']=='product' and visual['product_type']!='other':
                    query=photo_query(visual)
                    products=await catalog.search(query,visual=visual)
                    s.last_search_query=query; s.search_max_price=None
                    s.last_visual=visual
                s.last_products=products
                # The picture can suggest candidates, never authorize/select a cart line.
                warnings+=list(dict.fromkeys(w for p in products for w in p['warnings']))
                if not catalog.complete: warnings.append('Поиск охватывает загруженную выборку, не весь каталог. Точное наличие проверяется по карточке.')
                return respond(photo_reply(visual,bool(products),s.language),products,
                    sources=[{'title':p['name'],'url':p['product_url']} for p in products if p.get('product_url')],warnings=warnings)
            action=intent['intent']; pid=intent.get('product_id'); query=intent.get('query') or message
            budget=budget_from_message(message)
            if budget is not None and action in {'search','detail','clarify','other'}:
                query=without_budget(query,budget)
                if s.last_search_query and not named_tool_query(message) and not named_tool_query(query):
                    query=s.last_search_query+' '+without_budget(message,budget)
                s.search_max_price=budget
                action='search'; pid=None
                if not query.strip(): return respond('Напишите, какой товар подобрать в этом бюджете.',warnings=warnings)
            elif action in {'search','detail'} and not search_followup(message) and query!=s.last_search_query:
                s.search_max_price=None
            if action=='search' and s.search_max_price is not None:
                query=without_budget(query,s.search_max_price)
            if action=='terms': return respond(TERMS,sources=SOURCES,warnings=warnings)
            if action=='overview':
                overview=await catalog.overview()
                products=overview['products']
                s.last_products=products; s.last_search_query=''; s.search_max_price=None
                if not catalog.complete: warnings.append('Поиск охватывает загруженную выборку, не весь каталог. Точное наличие проверяется по карточке.')
                return respond('Вот примеры товаров из доступного каталога. Напишите, какой товар или задача вас интересует.',products,
                    sources=[{'title':p['name'],'url':p['product_url']} for p in products if p.get('product_url')],warnings=warnings)
            if action=='clarify': return respond(render_clarification(intent.get('clarification')),warnings=warnings)
            if action=='other': return respond('Здравствуйте! Помогу с товарами и условиями покупки. Опишите задачу, название или артикул товара. Цены и наличие проверю по каталогу.',warnings=warnings)
            if pid:
                # AI may select only visible session products or an ID literally present in the user text.
                allowed={p['id'] for p in s.last_products}
                if pid not in allowed: pid=None
            if action in {'search','detail','alternatives'}:
                s.last_search_query=query
            search_options={'max_price':s.search_max_price} if action=='search' and s.search_max_price is not None else {}
            if action=='search' and s.last_visual and search_followup(message):
                search_options['visual']=s.last_visual
            elif action in {'search','detail'}:
                s.last_visual=None
            products=[await catalog.detail(pid,fresh=catalog.live)] if pid else await catalog.search(query,**search_options)
            if action=='alternatives':
                target=products[0] if len(products)==1 else next((p for p in products if p['id']==pid),None)
                if target is None: return respond('Уточните исходный товар для подбора аналога: укажите название, маркировку или выберите карточку.',products,warnings=warnings)
                products,extra=await catalog.alternatives(target['id']); warnings+=extra
                text='Кандидаты на замену: сравните характеристики и подтвердите совместимость у специалиста.' if products else 'Подходящий аналог пока не подтверждён.'
            elif action=='add':
                if len(products)!=1:
                    s.last_products=products
                    return respond('Уточните, какой товар добавить: выберите карточку. Корзина пока не менялась.',products,warnings=warnings)
                qty=intent.get('quantity')
                if qty is None:
                    s.last_products=products
                    return respond('Сколько единиц добавить? Укажите количество или выберите его в карточке.',products,warnings=warnings)
                proposal=await propose(s,catalog,products[0]['id'],qty); s.last_products=products
                return respond(f"Подтвердите добавление {qty:g}: {products[0]['name']}. До подтверждения корзина не меняется.",products,proposal,warnings=warnings)
            else:
                if not products:
                    if action=='search' and s.search_max_price is not None:
                        return respond(f'В доступном каталоге не нашёл товары по этим условиям в бюджете до {s.search_max_price:g} ₸. Можно изменить бюджет или требования.',warnings=warnings)
                    return respond('В доступной выборке товар не найден. Попробуйте название, маркировку или другое описание; отсутствие в поиске не означает отсутствие в магазине.',warnings=warnings)
                text='Нашёл товары по каталогу. В карточках — цена, наличие, характеристики и доступные документы.'
                if len(products)==1:
                    p=products[0]
                    stock='остаток не указан' if p['stock'] is None else f"в наличии {p['stock']:g}"
                    price='цена не указана' if p['price'] is None else f"{p['price']:g} ₸"
                    text=f"{p['name']}: {price}, {stock}. "
                    text+=('Сертификат доступен в карточке.' if p['certificates'] else 'Ссылка на сертификат в данных каталога отсутствует.')
                    if p['stock']==0:
                        related,extra=await catalog.alternatives(p['id']); products+=related; warnings+=extra
                        if s.search_max_price is not None:
                            products=[item for item in products if item['price'] is not None and item['price']<=s.search_max_price]
                        text+=' Ниже — доступные кандидаты на замену.' if related else ' Подтверждённый аналог не найден.'
            s.last_products=products
            warnings+=list(dict.fromkeys(w for p in products for w in p['warnings']))
            if not catalog.complete: warnings.append('Поиск охватывает загруженную выборку, не весь каталог. Точное наличие проверяется по карточке.')
            return respond(text,products,sources=[{'title':p['name'],'url':p['product_url']} for p in products if p.get('product_url')],warnings=warnings)

    dist=ROOT/'frontend'/'dist'
    if (dist/'assets').exists(): app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')

    @app.get('/{path:path}')
    async def frontend(path:str):
        if path.startswith('api/'): raise AppError('not_found','Метод API не найден.',404)
        index=dist/'index.html'
        if index.exists(): return FileResponse(index)
        return JSONResponse({'message':'Сервер готов. Соберите интерфейс: cd frontend && npm ci && npm run build.','api':'/docs'})

    return app

app=create_app()
