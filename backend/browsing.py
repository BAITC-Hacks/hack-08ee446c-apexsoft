"""Small deterministic shortcuts for browsing, never for buying or technical sizing."""
import re


def is_overview(message):
    text=message.strip().casefold().rstrip('.!? ')
    return bool(re.fullmatch(
        r'(?:а\s+)?(?:что (?:вообще )?у вас есть|что есть в (?:каталоге|наличии)|'
        r'какие (?:у вас есть )?товары(?: у вас есть)?|покажи(?:те)? (?:весь )?(?:каталог|ассортимент)|'
        r'сіздерде не бар|қандай тауарлар бар)',text))


def named_tool_query(message):
    # A named tool type is enough to browse cards. Selection/compatibility still needs data.
    # Restrict to a request beginning with the product, excluding advice like cable sizing.
    text=message.strip()
    pattern=(r'(?:(?:а|мне|я|нужен|нужна|нужно|хочу|подбери|покажи|найди|купить|'
             r'аккумуляторный|аккумуляторную|сетевой|сетевую|электрический|электрическую)\s+)*'
             r'(?:шурупов[её]рт\w*|дрел[ьи]\w*|перфоратор\w*|болгарк\w*)\b')
    return text if re.match(pattern,text,re.I) else None


def prefer_named_tool_search(result,message):
    query=named_tool_query(message)
    if query and result.get('intent') in {'clarify','other'}:
        return {**result,'intent':'search','query':query,'product_id':None,'quantity':None,'clarification':None}
    return result
