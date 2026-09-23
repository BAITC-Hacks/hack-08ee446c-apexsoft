# EKT Assistant API v1

Стек приложения: FastAPI + React/Vite/TypeScript.

## Транспорт и сессия

Все пути относительно одного origin. Dev Vite проксирует /api в http://127.0.0.1:8000. В production FastAPI раздаёт frontend/dist. fetch credentials: include. GET /api/session создаёт HttpOnly SameSite=Lax cookie и возвращает {session_id, csrf_token, cart, integrations}. Для ВСЕХ POST заголовок X-CSRF-Token из этого ответа. Не сохранять токен или chat в localStorage. Сессия живёт 2 часа в памяти; рестарт сбрасывает данные.

## Типы (JSON)

Product: {id: string, article: string, name: string, description: string, category: string, price: number|null, currency: 'KZT', stock: number|null, min_quantity: number, quantity_step: number, image_url: string|null, product_url: string|null, specifications: [{name: string,value: string}], certificates: [{name: string,url: string}], warehouses: [{name: string,stock: number|null}], warnings: string[], source: 'live'|'snapshot', checked_at: string, analogue_reason: string|null}.

Cart: {mode:'demo', items:[{product:Product,quantity:number,line_total:number}], total:number, currency:'KZT', count:number, version:number, url:'/cart', notice:string}.

Proposal: {confirmation_id:string, operation:'add', product:Product, quantity:number, existing_quantity:number, resulting_quantity:number, expires_at:string}. Ничего не изменяет. Показывать полное название, количество добавления, итоговое количество и кнопку «Да, добавить N …». Не подтверждать автоматически и не делать optimistic updates.

Integrations: {catalog:'live'|'snapshot'|'unavailable', ai:'openai'|'fallback', cart:'demo', indexed_products:number, index_complete:boolean, notice:string}.

ChatResponse: {message_id:string, text:string, products:Product[], proposal:Proposal|null, cart:Cart, sources:[{title:string,url:string}], warnings:string[], suggestions:string[], integrations:Integrations}.

## Методы

Язык ответа определяется по сообщению (`ru` / `kk`) и сохраняется в сессии для коротких продолжений. В историю попадает показанный пользователю перевод. Казахские точные команды «иә, қос» / «қосыңыз» подтверждают текущее предложение; простое «иә» не подтверждает. «қоспаңыз» отменяет предложение, «Себетті көрсету» открывает ответ о корзине. Сервер переводит свои фразы, предупреждения и известные ошибки; названия и характеристики из каталога сохраняются. Фиксированные подписи интерфейса остаются русскими.

- GET /api/health → {status:'ok',integrations}.
- GET /api/session → тип выше.
- POST /api/chat JSON {message:string,attachment_ids?:string[],request_id?:string} → ChatResponse. message: 1–3000 символов, до 4 attachment_ids из той же сессии. Клиент удерживает request_id (10–100 ASCII букв, цифр, `_` или `-`) до успешного ответа. Повтор возвращает тот же ответ без повторной обработки вложения/добавления; состояние корзины при этом актуальное. Иной payload с тем же ID — 409. В памяти сессии хранятся последние 32 результата; ошибки не кешируются. Язык ответа определяется по сообщению и сохраняется в сессии; название товара, ID, цена и остаток сохраняются из каталога. Точное «да, добавь» или казахское «иә, қос» при текущем предложении подтверждает его; простое «да»/«иә» не является согласием на изменение корзины.
- POST /api/chat/reset JSON {} → {cart:Cart}. Сбрасывает историю, найденные товары, предложение, вложения и кеш ответов чата текущей сессии. Корзина и квитанции выполненных подтверждений сохраняются.
- GET /api/products?q=... → {products:Product[],index_complete:boolean} (до 6 результатов).
- GET /api/products/{id} → Product.
- GET /api/products/{id}/alternatives → {products:Product[],warnings:string[]}.
- POST /api/cart/propose JSON {product_id:string,quantity:number} → {proposal:Proposal,cart:Cart}. quantity = ДОБАВИТЬ к текущему количеству. Свежие цена/остаток; сервер проверяет кратность/наличие.
- POST /api/cart/confirm JSON {confirmation_id:string,confirmed:true} → {cart:Cart,text:string}. Одноразовое подтверждение, повтор возвращает прежний результат без повторного добавления. Свежие остаток и цена перепроверяются, при изменениях 409 и требуется новое предложение. Идентификатор привязан к сессии.
- POST /api/cart/cancel JSON {confirmation_id:string} → {cart:Cart}. Аннулирует текущее предложение этой сессии, если идентификатор совпадает. Не меняет состав корзины; повтор безопасен.
- POST /api/cart/remove JSON {product_id:string,version:integer,confirmed:true} → {cart:Cart}. Явное нажатие «Удалить [название] из корзины» удаляет всю позицию и пересчитывает итог. CSRF и принадлежность сессии проверяются. Неактуальная версия корзины — 409; повтор при уже отсутствующем товаре безопасен. Удаление аннулирует ожидающее предложение добавления. Квитанция старого подтверждения не возвращает удалённые позиции: её cart отражает актуальное состояние.
- GET /api/cart → Cart. Маршрут UI /cart отображает актуальную корзину этой сессии. Заказ/оплата не реализованы и реальную корзину ekt.kz не изменяют.
- POST /api/attachments multipart file → {attachment_id:string,name:string,extracted_text:string,kind:'document'|'image',warnings:string[]}. JPEG/PNG/PDF/DOCX/XLSX/XLS, до 8 MiB; хранятся только в памяти сессии. Изображение распознаёт OpenAI. Legacy .doc возвращает понятную ошибку преобразования в .docx.
- POST /api/attachments/remove JSON {attachment_ids:string[]} → {removed:true}. До 8 идентификаторов. Освобождает загрузки только текущей сессии, повтор безопасен. Успешный /api/chat также освобождает использованные вложения; при ошибке они остаются доступны для повторного запроса.

## Ошибки

Неуспешный HTTP: {error:{code:string,message:string}}. 400 invalid_request, 403 csrf/confirmation, 404 not_found, 409 stock_changed/price_changed/cart_changed/confirmation_expired, 413 attachment_too_large, 422 invalid_quantity, 429 rate_limit, 503 upstream_unavailable. Показывать message и предлагать повторить; старое предложение после 409 не подтверждать.

## Достоверность

Отсутствующий остаток/цена → null, не 0. В режиме live перед предложением и добавлением в демо-корзину обращаемся к detail API; при недоступности fail closed. Удаление своей позиции не требует доступности каталога. В snapshot режиме видимая подпись «Демонстрационные данные; не актуальная цена/наличие». Сертификаты только из проверенных URL каталога, отсутствие обозначается честно. AI не имеет write-инструмента корзины. OpenAI получает лишь запрос/вложение/контекст поиска, store:false. Секреты только в окружении серверного процесса.
