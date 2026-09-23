"""Reject recognisable payment credentials before retaining or forwarding text.

This is a narrow guard for PAN/CVV, not a general personal-data classifier.
Keep the browser storage guard in frontend/src/privacy.ts in sync.
"""
import re

from .errors import AppError

_PAN = re.compile(r'(?<![\w-])[0-9](?:[ \t\u00a0-]*[0-9]){12,18}(?![\w-])')
_CVV = re.compile(
    r'\b(?:cvv2?|cvc2?|код\s+безопасности|защитный\s+код|қауіпсіздік\s+коды)'
    r'\s*[:=№-]?\s*[0-9]{3,4}(?![0-9])', re.I)
_PRODUCT_CODE = re.compile(r'(?:артикул|код\s+товара|sku|ean|gtin)\s*[:#№=-]?\s*$', re.I)
_PAYMENT_CONTEXT = re.compile(r'\b(?:карт[аыуые]|карточк\w*|card|visa|mastercard|cvv2?|cvc2?|pan)\b', re.I)


def _luhn(digits):
    if len(set(digits)) == 1:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        value = int(digit)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def contains_payment_data(text):
    if _CVV.search(text):
        return True
    payment_context = bool(_PAYMENT_CONTEXT.search(text))
    for match in _PAN.finditer(text):
        candidate = match.group()
        # Do not let a following expiry month/CVV joined by spaces hide a
        # complete PAN. Only stop at a separator, never inside a digit group.
        endings = [end.end() for end in re.finditer(r'[0-9](?=[ \t\u00a0-]|$)', candidate)]
        candidates = [re.sub(r'[^0-9]', '', candidate[:end]) for end in endings]
        if not any(13 <= len(digits) <= 19 and _luhn(digits) for digits in candidates):
            continue
        # An explicitly labelled catalogue code must remain searchable. A
        # payment context takes precedence over a misleading article label.
        if not payment_context and _PRODUCT_CODE.search(text[max(0, match.start()-40):match.start()]):
            continue
        return True
    return False


def reject_payment_data(text):
    if contains_payment_data(text):
        raise AppError('payment_data',
            'Не отправляйте номер банковской карты или код CVV/CVC. '
            'Удалите платёжные реквизиты и повторите запрос о товаре.', 422)
