import asyncio
import copy

import pytest

from backend.analogue_matching import analogue_reason
from backend.catalog import Catalog, normalize


def lamp(pid=1, **changes):
    raw = {'id': pid, 'name': 'Лампа LED E27 10W 230V IP20', 'quantity': 3,
           'url': 'https://ekt.kz/catalog/lighting/lamp/',
           'properties': {'MOSHCHNOST': '10W', 'NOMINALNOE_NAPRYAZHENIE': '230В'}}
    raw.update(changes)
    return normalize(raw)


def test_verified_candidate_explains_actual_matching_parameters_without_mutation():
    target, candidate = lamp(quantity=0), lamp(2)
    before = copy.deepcopy((target, candidate))
    reason = analogue_reason(target, candidate)
    assert reason and 'Мощность' in reason and 'Цоколь' in reason
    assert 'Кандидат' in reason and 'специалиста' in reason
    assert (target, candidate) == before


@pytest.mark.parametrize('changes', [
    {'name': 'Лампа LED E14 10W 230V IP20'},
    {'name': 'Лампа LED E27 60W 230V IP20', 'properties': {'MOSHCHNOST': '60W', 'NOMINALNOE_NAPRYAZHENIE': '230В'}},
    {'name': 'Лампа LED E27 10W 12V IP20', 'properties': {'MOSHCHNOST': '10W', 'NOMINALNOE_NAPRYAZHENIE': '12В'}},
    {'name': 'Лампа LED E27 10W 230V IP65'},
    {'name': 'Светильник LED E27 10W 230V IP20'},
    {'quantity': 0},
    {'quantity': None},
])
def test_conflicting_or_unavailable_candidate_is_rejected(changes):
    assert analogue_reason(lamp(), lamp(2, **changes)) is None


def test_missing_critical_fields_cannot_count_as_equal():
    candidate = lamp(2, name='Лампа LED E27', properties={})
    assert analogue_reason(lamp(), candidate) is None


def test_name_and_catalogue_power_disagreement_blocks_both_sides():
    conflict = lamp(2, properties={'MOSHCHNOST': '60W', 'NOMINALNOE_NAPRYAZHENIE': '230В'})
    assert analogue_reason(lamp(), conflict) is None
    assert analogue_reason(conflict, lamp()) is None


def test_equal_unit_spellings_and_decimal_format_are_supported():
    candidate = lamp(2, name='Лампа LED E27 10Вт 230В IP20',
                     properties={'MOSHCHNOST': '10,0 Вт', 'NOMINALNOE_NAPRYAZHENIE': '230.0 V'})
    assert analogue_reason(lamp(), candidate)


def test_common_category_and_name_without_technical_data_is_insufficient():
    assert analogue_reason(lamp(name='Лампа Альфа', properties={}),
                           lamp(2, name='Лампа Бета', properties={})) is None


def test_different_electrical_device_types_are_not_analogues():
    common = {'NOMINALNYY_TOK': '16А', 'KOLICHESTVO_POLYUSOV': '2', 'NOMINALNOE_NAPRYAZHENIE': '230В'}
    target = lamp(name='Автомат 16А', properties=common)
    candidate = lamp(2, name='УЗО 16А', properties=common)
    assert analogue_reason(target, candidate) is None


@pytest.mark.parametrize('candidate_name', ['Автомат B16 1P', 'Автомат C16 3P', 'Автомат C32 1P'])
def test_breaker_markings_do_not_lose_curve_pole_or_current(candidate_name):
    props = {'NOMINALNYY_TOK': '16А', 'KOLICHESTVO_POLYUSOV': '1'}
    target = lamp(name='Автомат C16 1P', properties=props)
    candidate = lamp(2, name=candidate_name, properties=props)
    assert analogue_reason(target, candidate) is None


def test_cable_conductor_count_is_a_required_matching_fact():
    props = {'SECHENIE': '2,5'}
    target = lamp(name='Кабель 3x2.5', properties=props)
    assert analogue_reason(target, lamp(2, name='Кабель 5x2.5', properties=props)) is None
    assert analogue_reason(target, lamp(2, name='Кабель 3х2,5', properties=props))


def test_unknown_property_text_is_not_technical_evidence():
    unknown = {'MOSHCHNOST': 'Не указано'}
    assert analogue_reason(lamp(name='Лампа Альфа', properties=unknown),
                           lamp(2, name='Лампа Бета', properties=unknown)) is None


def test_colour_temperature_mismatch_is_not_silently_substituted():
    assert analogue_reason(lamp(name='Лампа E27 10W 4000K'),
                           lamp(2, name='Лампа E27 10W 6500K')) is None


@pytest.mark.parametrize('change', ['category', 'same_id', 'warning'])
def test_existing_data_boundaries_stay_enforced(change):
    candidate = lamp(2)
    if change == 'category': candidate['category'] = 'other'
    if change == 'same_id': candidate['id'] = '1'
    if change == 'warning': candidate['warnings'] = ['Расхождение данных: 16А / 63А']
    assert analogue_reason(lamp(), candidate) is None


@pytest.mark.parametrize('invalid', [
    {'name': 'Лампа LED E27', 'properties': {}},
    {'name': 'Лампа LED E14 10W 230V IP20'},
    {'name': 'Светильник LED E27 10W 230V IP20'},
])
def test_catalogue_integration_rejects_previous_false_analogues(monkeypatch, invalid):
    for key in ('EKT_API_USERNAME', 'EKT_API_PASSWORD'):
        monkeypatch.delenv(key, raising=False)
    base = {'id': 1, 'name': 'Лампа LED E27 10W 230V IP20', 'quantity': 0,
            'url': 'https://ekt.kz/catalog/lighting/lamp/',
            'properties': {'MOSHCHNOST': '10W', 'NOMINALNOE_NAPRYAZHENIE': '230В'}}
    wrong = dict(base, id=2, quantity=5, **invalid)

    async def scenario():
        catalog = Catalog()
        catalog.rows = catalog.details = {'1': base, '2': wrong}
        try:
            products, warnings = await catalog.alternatives('1')
            assert products == [], 'Missing specs or mismatched types must not be offered as analogues'
            assert warnings
        finally:
            await catalog.close()
    asyncio.run(scenario())
