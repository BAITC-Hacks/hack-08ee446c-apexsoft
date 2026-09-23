"""Small deterministic shortcuts for browsing, never for buying or technical sizing."""
import re


def is_overview(message):
    text=message.strip().casefold().rstrip('.!? ')
    return bool(re.fullmatch(
        r'(?:а\s+)?(?:что (?:вообще )?у вас есть|что есть в (?:каталоге|наличии)|'
        r'какие (?:у вас есть )?товары(?: у вас есть)?|покажи(?:те)? (?:весь )?(?:каталог|ассортимент|варианты)|'
        r'сіздерде не бар|қандай тауарлар бар)',text))


def named_tool_query(message):
    # A named tool type is enough to browse cards. Selection/compatibility still needs data.
    # Restrict to a request beginning with the product, excluding advice like cable sizing.
    text=message.strip()
    pattern=(r'(?:(?:а|мне|я|нужен|нужна|нужно|хочу|подбери|покажи|найди|купить|'
             r'аккумуляторный|аккумуляторную|сетевой|сетевую|электрический|электрическую)\s+)*'
             r'(?:шурупов[её]рт\w*|дрел[ьи]\w*|перфоратор\w*|болгарк\w*)\b')
    return text if re.match(pattern,text,re.I) else None


BUDGET = re.compile(
    r'(?P<label>бюджет(?:ом)?(?:\s+до)?|цен[а-я]*\s+до|не\s+(?:дороже|больше)|до)\s*'
    r'(?P<amount>\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:\s*)'
    r'(?P<currency>₸|тенге|тг\b|теңге)?', re.I)


def budget_from_message(message):
    for match in BUDGET.finditer(message):
        if match['label'].casefold()=='до' and not match['currency']: continue
        amount=float(re.sub(r'\s','',match['amount']))
        if amount>0: return amount
    return None


def without_budget(query, amount):
    query=BUDGET.sub(lambda m: m[0] if m['label'].casefold()=='до' and not m['currency'] else '',query)
    # The model may omit the budget label but retain its value in the search query.
    digits=str(int(amount))
    value=r'[ \u00a0]*'.join(digits)
    query=re.sub(r'(?<![\w.,])'+value+r'(?![\w.,])\s*(?:₸|тенге|тг\b|теңге)?','',query,flags=re.I)
    return re.sub(r'\s+',' ',query).strip(' ,.;')


def search_followup(message):
    return is_overview(message) or bool(re.match(
        r'^(?:а\s+|для\s+(?:дома|работы)|аккумуляторн|сетев|бюджет|не дороже|до\s+\d)',
        message.strip(),re.I))


def prefer_named_tool_search(result,message):
    query=named_tool_query(message)
    if query and result.get('intent') in {'clarify','other'}:
        return {**result,'intent':'search','query':query,'product_id':None,'quantity':None,'clarification':None}
    return result
