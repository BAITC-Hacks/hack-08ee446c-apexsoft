"""Read-only EKT adapter. Credentials never leave this server or enter cache files."""
import asyncio
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, unquote

import httpx
from .errors import AppError

DATA = Path(__file__).parent / 'data' / 'catalog_snapshot.json'
LABELS = {'TORGOVAYA_MARKA':'Бренд','NOMINALNYY_TOK':'Номинальный ток (поле каталога)',
 'NOMINALNOE_NAPRYAZHENIE':'Напряжение','KOLICHESTVO_POLYUSOV':'Полюсов',
 'NOMINALNAYA_OTKLYUCHAYUSHCHAYA_SPOSOBNOST':'Отключающая способность',
 'TIP_USTANOVKI':'Монтаж','OBYEM':'Тип товара','ARTIKULPOSTAVSHCHIKA':'Артикул производителя',
 'MOSHCHNOST':'Мощность','STEPEN_ZASHCHITY':'Степень защиты','TSVET':'Цвет',
 'SECHENIE':'Сечение','DLINA':'Длина','MATERIAL':'Материал'}

def now():
    return datetime.now(timezone.utc).isoformat()

def number(value):
    try:
        n = float(str(value).replace(',', '.'))
        return n if math.isfinite(n) and n >= 0 else None
    except (ValueError, TypeError):
        return None

def clean(value):
    return re.sub('<[^>]*>', '', str(value or '')).strip()

def safe_url(value):
    if not isinstance(value, str): return None
    if value.startswith('/'): value = 'https://ekt.kz' + value
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme == 'https' and parsed.hostname and not parsed.username else None
    except ValueError:
        return None

def normalize(raw, source='live', checked_at=None):
    props = raw.get('properties')
    if not isinstance(props, dict): props = {}
    name = clean(raw.get('name'))
    url = safe_url(raw.get('url')) or 'https://ekt.kz/'
    category = unquote(urlsplit(url).path.strip('/').split('/')[-2]) if '/' in urlsplit(url).path.strip('/') else ''
    specs = [{'name': LABELS[k], 'value': clean(v)} for k,v in props.items() if k in LABELS and isinstance(v,(str,int,float)) and str(v).strip()]
    certificates = []
    for key,value in props.items():
        if any(term in key.lower() for term in ('cert','sert','сертиф','паспорт')):
            for entry in value if isinstance(value,list) else [value]:
                if isinstance(entry,dict): entry = entry.get('url') or entry.get('SRC') or entry.get('VALUE')
                link = safe_url(entry)
                if link: certificates.append({'name':'Документ из каталога', 'url':link})
    warnings=[]
    stores=raw.get('stores')
    if not isinstance(stores,list): stores=[]
    warehouses=[{'name':clean(s.get('name')), 'stock':number(s.get('quantity'))} for s in stores if isinstance(s,dict)]
    if (raw.get('stores') is not None and not isinstance(raw.get('stores'),list)
            or len(warehouses)!=len(stores) or any(s['stock'] is None for s in warehouses)):
        warnings.append('Данные по отдельным складам неполные. Неизвестный остаток не означает отсутствие товара; уточните его у менеджера.')
    name_amp = re.search(r'(?<![\d.])(\d+(?:[.,]\d+)?)\s*[АA](?![A-Za-zА-Яа-я])', name)
    prop_amp = re.search(r'\d+(?:[.,]\d+)?', str(props.get('NOMINALNYY_TOK','')))
    if name_amp and prop_amp and number(name_amp[1]) != number(prop_amp[0]):
        warnings.append(f'Расхождение данных: в названии {name_amp[1]} А, в поле каталога {prop_amp[0]} А. Уточните характеристику у менеджера до выбора аналога.')
    step = number(props.get('KRATNOST_MIN')) or 1
    if source == 'snapshot': warnings.append('Синтетическая демонстрационная карточка: это не реальная цена и наличие товара ekt.kz.')
    return {'id':str(raw['id']), 'article':clean(raw.get('article')), 'name':name,
        'description':clean(raw.get('description')), 'category':category,
        'price':number(raw.get('price')), 'currency':'KZT', 'stock':number(raw.get('quantity')),
        'min_quantity':step, 'quantity_step':step, 'image_url':safe_url(raw.get('image')),
        'product_url':url, 'specifications':specs, 'certificates':certificates,
        'warehouses':warehouses,
        'warnings':warnings, 'source':source, 'checked_at':checked_at or now(), 'analogue_reason':None}

def tokens(text):
    text=clean(text).lower().replace('ё','е')
    # Equate common descriptions to catalogue naming without changing technical ratings.
    for a,b in [('автоматический выключатель','ав'),('автоматы','ав'),('автомат','ав'),('светодиод','led'),('лампочка','лампа')]:
        text=text.replace(a,b)
    return re.findall(r'[a-zа-я0-9_]+',text)

def code_pattern(value):
    # Keep letters/digits of a model, allowing GL1004D and GL 1004D formatting.
    parts=re.findall(r'[a-zа-я]+|\d+|_+',value)
    start=r'(?<!\d)' if value[0].isdigit() else r'(?<!\w)'
    end=r'(?!\d)' if value.isdigit() else r'(?!\w)'
    return start+r'\s*'.join(re.escape(part) for part in parts)+end

class Catalog:
    def __init__(self):
        user,password=os.getenv('EKT_API_USERNAME'),os.getenv('EKT_API_PASSWORD')
        self.live=bool(user and password)
        self.client=httpx.AsyncClient(base_url='https://ekt.kz',auth=(user,password) if self.live else None,
            timeout=12,follow_redirects=False,limits=httpx.Limits(max_connections=5))
        self.rows={}; self.details={}; self.checked={}; self.checked_clock={}; self.complete=False; self.index_error=None
        self.snapshot_time=''; self.task=None
        if DATA.exists() and not self.live:
            snapshot=json.loads(DATA.read_text(encoding='utf-8'))
            self.snapshot_time=snapshot.get('captured_at','')
            self.rows={str(r['id']):r for r in snapshot.get('items',[])}
            self.details={str(r['id']):r for r in snapshot.get('details',[])}
            self.rows.update(self.details)
        self.gate=asyncio.Semaphore(4)

    async def request(self,path,params):
        try:
            async with self.gate:
                r=await self.client.get(path,params=params)
            if path=='/api/products/detail' and r.status_code==404:
                raise AppError('not_found','Товар с этим ID не найден в каталоге.',404)
            r.raise_for_status()
            data=r.json()
            if not isinstance(data,dict): raise ValueError('not object')
            return data
        except (httpx.HTTPError,ValueError):
            raise AppError('upstream_unavailable','Каталог ekt.kz сейчас недоступен. Цена и наличие не подтверждены; повторите запрос позже.',503)

    async def index(self):
        if not self.live: return
        try:
            max_pages=max(1,min(1000,int(os.getenv('EKT_INDEX_PAGES','100'))))
            # Leave capacity for customer requests while the background index loads.
            for start in range(1,max_pages+1,2):
                pages=await asyncio.gather(*(self.request('/api/products',{'page':p}) for p in range(start,min(start+2,max_pages+1))))
                for page in pages:
                    items=page.get('items')
                    if not isinstance(items,list): raise ValueError('invalid items')
                    self.rows.update({str(r['id']):r for r in items if isinstance(r,dict) and 'id' in r})
                    if len(items)<int(page.get('per_page',20)):
                        self.complete=True; return
                await asyncio.sleep(.08)
        except (AppError,ValueError,TypeError):
            self.index_error='Индекс каталога загружен частично. Поиск по ID доступен отдельно.'

    async def detail(self,pid,fresh=False):
        pid=str(pid)
        if not re.fullmatch(r'\d{1,12}',pid): raise AppError('not_found','Некорректный идентификатор товара.',404)
        if self.live and (fresh or time.monotonic()-self.checked_clock.get(pid,0)>30):
            raw=await self.request('/api/products/detail',{'id':pid})
            if str(raw.get('id'))!=pid: raise AppError('not_found','Товар не найден в каталоге.',404)
            self.details[pid]=raw; self.rows[pid]=raw; self.checked[pid]=now(); self.checked_clock[pid]=time.monotonic()
        if pid not in self.details:
            raise AppError('not_found','Карточки нет в доступной выборке каталога. Уточните артикул или ID.',404)
        source='live' if pid in self.checked else 'snapshot'
        return normalize(self.details[pid],source,self.checked.get(pid,self.snapshot_time))

    async def search(self,query,limit=6):
        query=query.strip(); ts=[t for t in tokens(query) if t not in {'есть','ли','найди','нужен','нужно','мне','купить','покажи','товар','наличие','сколько','стоит','пожалуйста','для','на','в','и','с','по'}]
        # Model numbers and ratings (GL 1004D, 4000 К) are not internal catalogue IDs.
        marked_id=re.search(r'(?<!\w)(?:id|ид|идентификатор)(?:\s+товара)?\s*[:#№]?\s*(\d{1,12})(?!\w)',query,re.I)
        numeric=marked_id or re.fullmatch(r'(\d{1,12})',query)
        scores=[]; exact=[]
        identifiers=[t for t in ts if len(t)>=4 and any(char.isdigit() for char in t)]
        for pid,row in self.rows.items():
            article=str(row.get('article','')).lower(); name=str(row.get('name','')).lower()
            words=tokens(name+' '+article); hay=' '.join(words)
            article_key=article.rstrip('_')
            if article_key and re.search(r'(?<![\w-])'+re.escape(article_key)+r'_?(?![\w-])',query.lower()):
                exact.append(pid)
            # A model/rating explicitly named by the buyer must occur in a candidate.
            if any(not re.search(code_pattern(t),hay) for t in identifiers): continue
            # Short model prefixes such as GL must not match unrelated names such as GLOSSA.
            score=sum(3 if t in article else 1 for t in ts if
                      (bool(re.search(code_pattern(t),hay)) if t in identifiers else (t in words if len(t)<4 else t in hay)))
            if score or not query: scores.append((score,pid))
        scores.sort(key=lambda x:-x[0])
        pids=exact[:limit] or [pid for _,pid in scores[:limit]]
        if numeric and (marked_id or not exact):
            try:
                return [await self.detail(numeric[1],fresh=True)]
            except AppError as e:
                if e.code=='not_found': return []
                raise
        if self.live and not self.rows:
            message=('Каталог ekt.kz сейчас недоступен. Цена и наличие не подтверждены; повторите запрос позже.'
                     if self.index_error else 'Каталог ещё загружается. Поиск по названию и артикулу пока недоступен; повторите позже или укажите ID товара.')
            raise AppError('upstream_unavailable',message,503)
        out=[]
        for pid in pids:
            try: out.append(await self.detail(pid))
            except AppError as e:
                if e.code=='upstream_unavailable': raise
        return out

    async def alternatives(self,pid):
        target=await self.detail(pid,fresh=self.live)
        if any('Расхождение' in w for w in target['warnings']):
            return [],['Подбор безопасного аналога требует уточнения противоречивых характеристик исходного товара у менеджера.']
        candidates=[]
        for rid,row in self.rows.items():
            if rid==str(pid): continue
            category=normalize(row)['category']
            if category==target['category'] and category:
                shared=set(tokens(row.get('name',''))) & set(tokens(target['name']))
                candidates.append((len(shared),rid))
        candidates.sort(reverse=True)
        result=[]
        critical=('Полюсов','Номинальный ток (поле каталога)','Напряжение','Мощность','Сечение')
        left={s['name']:s['value'].lower().replace(' ','') for s in target['specifications']}
        for _,rid in candidates[:16]:
            item=await self.detail(rid,fresh=self.live)
            if not item['stock'] or any('Расхождение' in w for w in item['warnings']): continue
            right={s['name']:s['value'].lower().replace(' ','') for s in item['specifications']}
            if any(k in left and k in right and left[k]!=right[k] for k in critical): continue
            shared=[k for k in critical if k in left and right.get(k)==left[k]]
            item['analogue_reason']='Та же категория каталога' + (', совпадают: '+', '.join(shared) if shared else ', близкое наименование') + '. Кандидат на замену: перед монтажом уточните совместимость у специалиста.'
            result.append(item)
            if len(result)==3: break
        warnings=[] if result else ['В доступной выборке не найден подтверждённый подходящий аналог с остатком. Обратитесь к менеджеру; неподходящую замену не предлагаем.']
        return result,warnings

    async def close(self):
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
        await self.client.aclose()
