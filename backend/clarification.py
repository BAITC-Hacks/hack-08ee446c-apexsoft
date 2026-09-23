"""Model selects missing parameters; only server-owned questions reach the client."""
import re

TOPICS = {
    'cable': 'Подберём кабель по задаче.',
    'lamp': 'Уточним параметры лампы.',
    'breaker': 'Уточним требования к автомату.',
    'general': 'Помогу с подбором по описанию.',
}
QUESTIONS = {
    'application': 'Что нужно подключить или заменить?',
    'installation': 'Где и как будет использоваться кабель: в помещении или на улице, подвижное подключение или стационарная прокладка?',
    'connection': 'Нужен шнур от розетки к прибору или кабель для стационарной проводки до него?',
    'rating': 'Какие напряжение питания и мощность указаны на приборе или его маркировке?',
    'length': 'Какая длина кабеля нужна?',
    'cable_spec': 'Известны ли требуемые марка, число жил и сечение по проекту или маркировке заменяемого кабеля?',
    'lamp_base': 'Какой цоколь указан на лампе или светильнике?',
    'lamp_light': 'Какие мощность и цветовая температура нужны для лампы?',
    'breaker_spec': 'Какие номинал, число полюсов и характеристика срабатывания указаны в проекте или на заменяемом автомате?',
    'description': 'Что за товар нужен и для какой задачи?',
    'marking': 'Можете прислать фото маркировки или переписать обозначения с товара?',
}
ACKNOWLEDGEMENTS = {
    'no_article': 'Артикул не обязателен — подберём по назначению и параметрам.',
    'unknown_parameters': 'Если параметры неизвестны, можно начать с фото маркировки. Не будем их угадывать.',
}


def respect_unavailable_parameters(result, message, history):
    """Suppress repeated questions, without inferring any electrical values.

    Only recent user statements count; generated replies cannot establish facts.
    This narrow guard supplements model context for explicit unavailable inputs.
    """
    if result.get('intent') != 'clarify' or not isinstance(result.get('clarification'), dict):
        return result
    recent = [entry['text'] for entry in history if entry.get('role') == 'user'][-2:] + [message]
    text = ' '.join(recent).casefold()
    blocked = set()
    unknown = r'(?:не знаю|неизвест\w*|білмеймін|белгісіз)'
    for names, key in [(r'(?:мощност\w*|кернеу\w*|қуат\w*)', 'rating'),
                       (r'(?:сечени\w*|қима\w*)', 'cable_spec')]:
        if re.search(names + r'[^.!?]{0,35}' + unknown + '|' + unknown + r'[^.!?]{0,35}' + names, text):
            blocked.add(key)
    no_photo = re.search(r'(?:фото|маркировк\w*|таңбалау\w*)[^.!?]{0,25}(?:нет|жоқ)|'
                         r'(?:нет|жоқ)[^.!?]{0,25}(?:фото|маркировк\w*|таңбалау\w*)', text)
    if no_photo:
        blocked.add('marking')
    cable_application = re.search(r'(?:кабел\w*|провод\w*|шнур\w*)\s+для\s+(?:\w+\s+)?(?:ламп\w*|светильник\w*|насос\w*)', text)
    if cable_application:
        blocked.update(('application', 'description'))
    if not blocked:
        return result
    clarification = dict(result['clarification'])
    clarification['question_keys'] = [key for key in clarification['question_keys'] if key not in blocked]
    if cable_application and not clarification['question_keys']:
        clarification['topic'] = 'cable'
        clarification['question_keys'] = ['connection']
    if no_photo and clarification.get('acknowledgement') == 'unknown_parameters':
        clarification['acknowledgement'] = 'none'
    return {**result, 'clarification': clarification}


def render_clarification(value):
    value = value if isinstance(value, dict) else {}
    intro = ACKNOWLEDGEMENTS.get(value.get('acknowledgement')) or TOPICS.get(value.get('topic'), TOPICS['general'])
    keys = value.get('question_keys')
    keys = keys if isinstance(keys, list) else []
    if 'connection' in keys and 'installation' in keys:
        keys = [key for key in keys if key != 'installation']
    limit = 1 if value.get('acknowledgement') in ACKNOWLEDGEMENTS else 2
    questions = list(dict.fromkeys(QUESTIONS[key] for key in keys if isinstance(key, str) and key in QUESTIONS))[:limit]
    return intro + ' ' + ' '.join(questions or [QUESTIONS['description']])
