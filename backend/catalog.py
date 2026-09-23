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
from .visual import photo_candidate, photo_score
from .analogue_matching import analogue_reason

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
    url = safe_url(raw.get('url'))
    path = urlsplit(url).path.strip('/') if url else ''
    # A home/catalog page is not a link to this product. Keep missing links absent.
    if path in ('', 'catalog'): url = None
    category = unquote(path.split('/')[-2]) if '/' in path else ''
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
        self.complete=False; self.index_error=None
        try:
            max_pages=max(1,min(1000,int(os.getenv('EKT_INDEX_PAGES','1000'))))
            # per_page is supported by EKT; q/search/page_size/limit are ignored.
            # A high page number can wrap to page one instead of returning empty.
            page_size=100
            seen_ids=set()
            # Leave capacity for customer requests while the background index loads.
            for start in range(1,max_pages+1,2):
                pages=await asyncio.gather(*(self.request('/api/products',{'page':p,'per_page':page_size}) for p in range(start,min(start+2,max_pages+1))))
                for page in pages:
                    items=page.get('items')
                    if not isinstance(items,list): raise ValueError('invalid items')
                    actual_size=int(page.get('per_page',page_size))
                    if actual_size<1: raise ValueError('invalid page size')
                    if any(not isinstance(r,dict) or not re.fullmatch(r'\d{1,12}',str(r.get('id',''))) for r in items):
                        raise ValueError('invalid product in index')
                    ids={str(r['id']) for r in items}
                    if ids and not (ids-seen_ids):
                        # Repetition is not proof of completeness: the API might
                        # have ignored pagination or changed while we loaded it.
                        raise ValueError('repeating page')
                    seen_ids.update(ids)
                    self.rows.update({str(r['id']):r for r in items})
                    if len(items)<actual_size:
                        self.complete=True; return
                await asyncio.sleep(.08)
            self.index_error='Достигнут предел загрузки каталога. Поиск пока охватывает только загруженные товары.'
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

    async def overview(self,limit=6):
        """Examples from loaded categories, with the same verified facts as search.

        Category values are identifiers supplied by product URLs, not a claim
        that we know every department or every product sold by the store.
        """
        limit=max(1,min(12,int(limit)))
        rows=list(self.rows.items())
        first=[]; remaining=[]; categories=[]; seen=set()
        for pid,row in rows:
            category=normalize(row)['category']
            if category and category not in seen:
                seen.add(category); categories.append(category); first.append(pid)
            else:
                remaining.append(pid)
        candidates=(first+remaining)[:limit*3]
        products=[]
        # Limit parallel calls; a removed example must not hide another category.
        for start in range(0,len(candidates),limit):
            results=await asyncio.gather(*(self.detail(pid,fresh=self.live)
                for pid in candidates[start:start+limit]),return_exceptions=True)
            for result in results:
                if isinstance(result,AppError) and result.code=='not_found': continue
                if isinstance(result,BaseException): raise result
                products.append(result)
            if len(products)>=limit: break
        if self.live and not rows:
            raise AppError('upstream_unavailable','Каталог ещё загружается. Повторите запрос позже или укажите ID товара.',503)
        return {'products':products[:limit], 'categories':categories[:24],
                'indexed_products':len(self.rows), 'index_complete':self.complete}

    async def search(self,query,limit=6,max_price=None,visual=None):
        if max_price is not None:
            max_price=number(max_price)
            if max_price is None: raise AppError('invalid_request','Укажите корректный бюджет.')
        query=query.strip(); ts=[t for t in tokens(query) if t not in {'есть','ли','найди','нужен','нужно','мне','купить','покажи','товар','наличие','сколько','стоит','пожалуйста','для','на','в','и','с','по'}]
        # Model numbers and ratings (GL 1004D, 4000 К) are not internal catalogue IDs.
        marked_id=re.search(r'(?<!\w)(?:id|ид|идентификатор)(?:\s+товара)?\s*[:#№]?\s*(\d{1,12})(?!\w)',query,re.I)
        numeric=marked_id or re.fullmatch(r'(\d{1,12})',query)
        scores=[]; exact=[]
        # A use case ("for home") must not turn a named drill into a home siren.
        tool_types=(r'\bшуруповерт\w*',r'\bдрел[ьи]\w*',r'\bперфоратор\w*',r'\bболгарк\w*')
        required_types=[pattern for pattern in tool_types if re.search(pattern,' '.join(ts))]
        identifiers=[t for t in ts if len(t)>=4 and any(char.isdigit() for char in t)]
        wire_word=r'\b(?:провод(?:а|ы|ов|ом|у|е)?|кабел(?:ь|я|и|ей|ем|ю))\b'
        wire_product=r'\b(?:провод|провода|проводы|кабель|кабели)\b'
        wire_mark=r'\b(?:ввг[а-яa-z]*|пвс|шввп|пугв)\b'
        accessory=r'\b(?:маркер\w*|съемник\w*|стриппер\w*|клещ\w*|нож\w*|инструмент\w*|звонок|звонк\w*|наконечник\w*|соединител\w*|держател\w*|зажим\w*|канал\w*|кабельканал\w*|муфт\w*|бирк\w*|(?:ввод|вывод)(?:а|ы|ов|ом)?|сальник\w*)\b'
        query_name=query.lower().replace('ё','е')
        wire_match=re.search(wire_word,query_name)
        accessory_match=re.search(accessory,query_name)
        wire_requested=bool(wire_match and not (accessory_match and accessory_match.start()<wire_match.start()))
        generic_wire=wire_requested and not identifiers and all(re.fullmatch(wire_word,t) for t in ts)
        for pid,row in self.rows.items():
            if visual and not photo_candidate(row,visual): continue
            article=str(row.get('article','')).lower(); name=str(row.get('name','')).lower()
            words=tokens(name+' '+article); hay=' '.join(words)
            article_key=article.rstrip('_')
            if article_key and re.search(r'(?<![\w-])'+re.escape(article_key)+r'_?(?![\w-])',query.lower()):
                exact.append(pid)
            if wire_requested:
                wire_name=name.replace('ё','е')
                # A cable noun/model is required; "wireless" and cable tools are
                # not cables. Exact known articles above retain their priority.
                if re.search(accessory,wire_name) or not (re.search(wire_product,wire_name) or re.search(wire_mark,wire_name)):
                    continue
            if required_types and not any(re.search(pattern,' '.join(tokens(name))) for pattern in required_types): continue
            # A model/rating explicitly named by the buyer must occur in a candidate.
            if any(not re.search(code_pattern(t),hay) for t in identifiers): continue
            # Short model prefixes such as GL must not match unrelated names such as GLOSSA.
            score=sum(3 if t in article else 1 for t in ts if
                      (bool(re.search(code_pattern(t),hay)) if t in identifiers else (t in words if len(t)<4 else t in hay)))
            if wire_requested: score+=1
            if visual: score+=photo_score(row,visual)
            if score or not query or visual: scores.append((score,pid))
        def rank(item):
            score,pid=item
            unavailable=0 if (number(self.rows[pid].get('quantity')) or 0)>0 else 1
            if generic_wire: return (unavailable,-score)
            return (-score,unavailable if wire_requested else 0)
        scores.sort(key=rank)
        pids=exact or [pid for _,pid in scores]
        if numeric and (marked_id or not exact):
            try:
                item=await self.detail(numeric[1],fresh=True)
                return [item] if max_price is None or item['price'] is not None and item['price']<=max_price else []
            except AppError as e:
                if e.code=='not_found': return []
                raise
        if self.live and not self.rows:
            message=('Каталог ekt.kz сейчас недоступен. Цена и наличие не подтверждены; повторите запрос позже.'
                     if self.index_error else 'Каталог ещё загружается. Поиск по названию и артикулу пока недоступен; повторите позже или укажите ID товара.')
            raise AppError('upstream_unavailable',message,503)
        if max_price is not None:
            # Index prices only select candidates; fresh detail is authoritative.
            # This can reach an affordable match beyond the first six names.
            def price_bucket(pid):
                price=number(self.rows[pid].get('price'))
                return 1 if price is None else (0 if price<=max_price else 2)
            pids.sort(key=price_bucket)
        pids=pids[:limit if max_price is None else max(limit*4,24)]
        out=[]
        for start in range(0,len(pids),limit):
            results=await asyncio.gather(*(self.detail(pid,fresh=self.live and max_price is not None)
                for pid in pids[start:start+limit]),return_exceptions=True)
            for item in results:
                if isinstance(item,AppError) and item.code=='not_found': continue
                if isinstance(item,BaseException): raise item
                if max_price is None or item['price'] is not None and item['price']<=max_price:
                    out.append(item)
            if len(out)>=limit: break
        return out[:limit]

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
        for _,rid in candidates[:16]:
            try: item=await self.detail(rid,fresh=self.live)
            except AppError as error:
                if error.code=='not_found': continue
                raise
            reason=analogue_reason(target,item)
            if not reason: continue
            item['analogue_reason']=reason
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
