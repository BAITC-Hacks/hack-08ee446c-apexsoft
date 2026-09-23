"""Synthetic credentials only; these checks do not contact a provider."""
import pytest

from backend.errors import AppError
from backend.privacy import contains_payment_data, reject_payment_data


@pytest.mark.parametrize('text', [
    'Моя карта 4242 4242 4242 4242', '4242-4242-4242-4242',
    '4242424242424242', '3782 822463 10005', '4222222222222',
    '4000000000000000006', 'Карта 4242 4242 4242 4242 12/30',
    '4242 4242 4242 4242 123',
    'CVV: 123', 'CVC2=1234', 'код безопасности 123', 'Қауіпсіздік коды: 123',
    'Карта, артикул: 4242424242424242',
])
def test_recognisable_payment_credentials_are_rejected_without_echo(text):
    assert contains_payment_data(text)
    with pytest.raises(AppError) as failure:
        reject_payment_data(text)
    assert failure.value.code == 'payment_data' and failure.value.status == 422
    assert text not in failure.value.message


@pytest.mark.parametrize('text', [
    'артикул: 4242424242424242', 'SKU 4242424242424242',
    'EAN: 4222222222222', 'код товара 4242424242424242',
    'Артикул ABC-4242424242424242', 'GL 1004D 220 В 40 Вт',
    'LED ДВО ECO-PRISMA 36W 3240Lm 595x595x17 6500K IP20',
    'Нужно 12 штук, ток 16 А, мощность 3500 Вт', '150200334_',
    'Можно оплатить картой?', 'Что такое CVV?', 'CVV товара не указан',
    '1234567890123456', '0000000000000000',
])
def test_product_identifiers_ratings_and_general_payment_questions_remain_valid(text):
    assert not contains_payment_data(text)
    reject_payment_data(text)
