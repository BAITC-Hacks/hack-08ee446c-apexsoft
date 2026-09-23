"""Conservative analogue candidates, using only facts present in catalogue cards.

This is a candidate filter, not an installation/compatibility certification.
Missing target characteristics cannot establish equality with another product.
"""
import re


CRITICAL = ('Полюсов', 'Номинальный ток (поле каталога)', 'Напряжение',
            'Мощность', 'Сечение', 'Материал', 'Монтаж', 'Степень защиты',
            'Отключающая способность', 'Цоколь', 'Количество жил',
            'Характеристика срабатывания', 'Цветовая температура')
FAMILIES = (
    ('rcbo', r'\b(?:дифавтомат\w*|дифференциальн\w*\s+автомат\w*|авдт)\b'),
    ('rcd', r'\b(?:узо|вдт|выключатель\s+дифференциальн\w*)\b'),
    ('breaker', r'\b(?:ав|автомат\w*|автоматическ\w*\s+выключатель\w*)\b'),
    ('luminaire', r'\b(?:светильник\w*|прожектор\w*|дво|дпо)\b'),
    ('lamp', r'\bламп(?:а|ы|очка|очки)\b'),
    ('cable', r'\bкабел\w*\b'),
    ('wire', r'\bпровод(?:а|ы|ом)?\b'),
    ('socket', r'\bрозетк\w*\b'),
    ('switch', r'\bвыключател\w*\b'),
    ('screwdriver', r'\bшуруповерт\w*\b'),
    ('drill', r'\bдрел\w*\b'),
)


def _text(value):
    return re.sub(r'\s+', '', str(value).lower().replace('ё', 'е').replace(',', '.'))


def _value(label, value):
    value = _text(value)
    units = {'Мощность': ('вт', 'w'), 'Напряжение': ('в', 'v'),
             'Номинальный ток (поле каталога)': ('а', 'a'),
             'Отключающая способность': ('а', 'a'), 'Сечение': ('мм²', 'мм2', 'mm2')}
    if label in units:
        match = re.fullmatch(r'(\d+(?:\.\d+)?)([kк]?)(?:' + '|'.join(units[label]) + r')?', value)
        if match:
            return str(float(match[1]) * (1000 if match[2] else 1))
    if label == 'Полюсов':
        value = re.sub(r'[pр]$', '', value)
    return value


def _facts(product):
    facts = {}
    for spec in product.get('specifications', []):
        label, value = spec.get('name'), spec.get('value')
        if label in CRITICAL and str(value or '').strip():
            normalized = _value(label, value)
            if normalized in {'-', '—', 'неуказано', 'нетданных', 'n/a', 'unknown'}:
                continue
            if label in facts and facts[label] != normalized:
                return None
            facts[label] = normalized
    # Markings on the catalogue title are evidence too, and must agree with fields.
    name = str(product.get('name', '')).lower().replace('ё', 'е')
    markings = (
        ('Мощность', r'(?<![\w.])(\d+(?:[.,]\d+)?\s*(?:квт|kw|вт|w))(?!\w)'),
        ('Напряжение', r'(?<![\w.])(\d+(?:[.,]\d+)?\s*[вv])(?!\w)'),
        ('Номинальный ток (поле каталога)', r'(?<![\w.])(\d+(?:[.,]\d+)?\s*[аa])(?!\w)'),
        ('Цоколь', r'\b([eе]\s*(?:14|27|40)|gu\s*10|g\s*(?:4|9|13))\b'),
        ('Степень защиты', r'\b(ip\s*\d{2})\b'),
        ('Цветовая температура', r'(?<!\w)(\d{3,5})\s*[kк](?!\w)'),
    )
    for label, pattern in markings:
        values = {_value(label, match) for match in re.findall(pattern, name)}
        if len(values) > 1:
            return None
        if values:
            value = values.pop()
            if label == 'Цоколь':
                value = value.replace('е', 'e')
            if label in facts and facts[label] != value:
                return None
            facts[label] = value
    # Distinct pole counts, trip curves, or conductor counts must not disappear
    # just because the upstream API omitted their separate properties.
    additional = {}
    family = _family(product)
    if family in {'breaker', 'rcd', 'rcbo'}:
        pole = re.search(r'(?<!\w)([1-4])\s*[pр](?!\w)', name)
        if pole:
            additional['Полюсов'] = pole[1]
        curve = re.search(r'(?<!\w)([bсcd])\s*(\d{1,3})(?:\s*[аa])?(?!\w)', name)
        if curve:
            additional['Характеристика срабатывания'] = curve[1].replace('с', 'c')
            additional['Номинальный ток (поле каталога)'] = _value('Номинальный ток (поле каталога)', curve[2])
    if family in {'cable', 'wire'}:
        size = re.search(r'(?<!\d)(\d{1,2})\s*[xх×]\s*(\d+(?:[.,]\d+)?)(?![\d.,])', name)
        if size:
            additional['Количество жил'] = size[1]
            additional['Сечение'] = _value('Сечение', size[2])
    for label, value in additional.items():
        if label in facts and facts[label] != value:
            return None
        facts[label] = value
    return facts


def _family(product):
    name = str(product.get('name', '')).lower().replace('ё', 'е')
    for family, pattern in FAMILIES:
        if re.search(pattern, name):
            return family
    return None


def analogue_reason(target, candidate):
    """Return an evidence-based reason, or None when a replacement is unproven."""
    if (not target.get('category') or target['category'] != candidate.get('category')
            or str(target.get('id')) == str(candidate.get('id'))):
        return None
    stock = candidate.get('stock')
    if not isinstance(stock, (int, float)) or not stock > 0:
        return None
    if any('расхождение' in str(w).lower()
           for product in (target, candidate) for w in product.get('warnings', [])):
        return None
    family = _family(target)
    if not family or family != _family(candidate):
        return None
    left, right = _facts(target), _facts(candidate)
    if not left or right is None:
        return None
    # Compare every known target requirement: a missing candidate field is unknown,
    # never a match. A shared category or brand alone proves no compatibility.
    if any(right.get(label) != value for label, value in left.items()):
        return None
    return ('Та же категория и тип товара; совпадают: ' + ', '.join(left)
            + '. Кандидат на замену: перед монтажом уточните совместимость у специалиста.')
