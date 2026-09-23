import asyncio
import copy
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from .errors import AppError

NOTICE='Демонстрационная корзина прототипа. Корзина ekt.kz не изменяется; заказ и оплата не оформляются.'

@dataclass
class Session:
    id: str=field(default_factory=lambda:secrets.token_urlsafe(32))
    csrf: str=field(default_factory=lambda:secrets.token_urlsafe(32))
    touched: float=field(default_factory=time.time)
    items: dict=field(default_factory=dict)
    version: int=0
    pending: dict|None=None
    receipts: dict=field(default_factory=dict)
    attachments: dict=field(default_factory=dict)
    history: list=field(default_factory=list)
    last_products: list=field(default_factory=list)
    calls: list=field(default_factory=list)
    lock: asyncio.Lock=field(default_factory=asyncio.Lock)

    def cart(self):
        items=[{'product':copy.deepcopy(v['product']),'quantity':v['quantity'],
          'line_total':round(v['quantity']*v['product']['price'],2)} for v in self.items.values()]
        return {'mode':'demo','items':items,'total':round(sum(x['line_total'] for x in items),2),
            'currency':'KZT','count':sum(x['quantity'] for x in items),'version':self.version,'url':'/cart','notice':NOTICE}

    def limit(self):
        current=time.time(); self.calls=[t for t in self.calls if t>current-60]
        if len(self.calls)>=30: raise AppError('rate_limit','Слишком много запросов. Подождите минуту.',429)
        self.calls.append(current)

def validate_quantity(product,quantity,resulting):
    try:
        q=Decimal(str(quantity)); total=Decimal(str(resulting)); step=Decimal(str(product['quantity_step']))
        if not q.is_finite() or q<=0 or q>100000 or q%step or q<Decimal(str(product['min_quantity'])):
            raise InvalidOperation
    except (InvalidOperation,ValueError,TypeError):
        raise AppError('invalid_quantity',f"Укажите положительное количество, кратное {product['quantity_step']}, не меньше {product['min_quantity']}.",422)
    if product['stock'] is None or product['price'] is None:
        raise AppError('upstream_unavailable','Цена или остаток не определены. Добавление недоступно.',503)
    if total>Decimal(str(product['stock'])):
        raise AppError('stock_changed',f"Доступно {product['stock']:g}. С учётом корзины запрошено {resulting:g}. Уменьшите количество.",409)

async def propose(session,catalog,pid,quantity):
    product=await catalog.detail(pid,fresh=True)
    existing=session.items.get(str(pid),{}).get('quantity',0)
    resulting=float(Decimal(str(existing))+Decimal(str(quantity)))
    validate_quantity(product,quantity,resulting)
    expires=time.time()+300
    proposal={'confirmation_id':secrets.token_urlsafe(24),'operation':'add','product':product,
        'quantity':float(quantity),'existing_quantity':existing,'resulting_quantity':resulting,
        'expires_at':datetime.fromtimestamp(expires,timezone.utc).isoformat()}
    session.pending={'proposal':proposal,'expires':expires,'version':session.version}
    return copy.deepcopy(proposal)

async def confirm(session,catalog,confirmation_id,confirmed):
    if confirmed is not True: raise AppError('confirmation_required','Нужно явное подтверждение добавления.',403)
    if confirmation_id in session.receipts:
        return copy.deepcopy(session.receipts[confirmation_id])
    pending=session.pending
    if not pending or not secrets.compare_digest(pending['proposal']['confirmation_id'].encode('utf-8'),confirmation_id.encode('utf-8')):
        raise AppError('confirmation_invalid','Предложение не найдено в этой сессии. Создайте новое.',403)
    if time.time()>pending['expires']:
        session.pending=None
        raise AppError('confirmation_expired','Предложение истекло. Проверьте товар ещё раз.',409)
    if pending['version']!=session.version:
        session.pending=None
        raise AppError('cart_changed','Корзина изменилась. Создайте новое предложение.',409)
    proposal=pending['proposal']; pid=proposal['product']['id']
    fresh=await catalog.detail(pid,fresh=True)
    try:
        validate_quantity(fresh,proposal['quantity'],proposal['resulting_quantity'])
        if fresh['price']!=proposal['product']['price']:
            raise AppError('price_changed','Цена изменилась. Подтвердите новое предложение с актуальной ценой.',409)
    except AppError:
        session.pending=None
        raise
    session.items[pid]={'product':fresh,'quantity':proposal['resulting_quantity']}
    session.version+=1; session.pending=None
    response={'cart':session.cart(),'text':f"Добавлено {proposal['quantity']:g}: {fresh['name']}. Откройте демонстрационную корзину."}
    session.receipts[confirmation_id]=copy.deepcopy(response)
    if len(session.receipts)>100: session.receipts.pop(next(iter(session.receipts)))
    return response
