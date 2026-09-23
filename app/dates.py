"""Conservative date resolution: retain original text and flag ambiguity."""
import re
from datetime import date, timedelta

MONTHS = ['январ|қаңтар', 'феврал|ақпан', 'март|наурыз', 'апрел|сәуір', 'ма[йя]|мамыр', 'июн|маусым', 'июл|шілде', 'август|тамыз', 'сентябр|қыркүйек', 'октябр|қазан', 'ноябр|қараша', 'декабр|желтоқсан']
ORDINALS = {'пятнадцатому': '15', 'пятнадцатого': '15', 'двадцатому': '20', 'тридцатому': '30', 'первому': '1'}
WEEKDAYS = ['понедельник|дүйсенбі', 'вторник|сейсенбі', 'сред[ауеы]|сәрсенбі', 'четверг|бейсенбі', 'пятниц|жұма', 'суббот|сенбі', 'воскресень|жексенбі']


def resolve_deadline(raw, meeting_date):
    base = date.fromisoformat(meeting_date)
    text = (raw or '').lower().strip()
    for word, number in ORDINALS.items():
        text = text.replace(word, number)
    if not text or text in ('не указан', 'не указано', 'null'):
        return None, True
    iso = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', text)
    if iso:
        try:
            return date.fromisoformat(iso[1]).isoformat(), False
        except ValueError:
            return None, True
    numeric = re.search(r'\b(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\b', text)
    if numeric:
        try:
            return date(int(numeric[3] or base.year), int(numeric[2]), int(numeric[1])).isoformat(), not bool(numeric[3])
        except ValueError:
            return None, True
    for month, pattern in enumerate(MONTHS, 1):
        match = re.search(r'(\d{1,2})(?:-?\w+)?\s+(?:' + pattern + r')\w*(?:\s+(20\d{2}))?', text)
        if match:
            try:
                return date(int(match[2] or base.year), month, int(match[1])).isoformat(), not bool(match[2])
            except ValueError:
                return None, True
    if re.search(r'послезавтра|бүрсігүні', text):
        return (base + timedelta(days=2)).isoformat(), False
    if re.search(r'завтра|ертең', text):
        return (base + timedelta(days=1)).isoformat(), False
    if re.search(r'сегодня|бүгін', text):
        return base.isoformat(), False
    delta = re.search(r'через\s+(\d+)\s+д|(?:за|через)\s+(\d+)\s+нед', text)
    if delta:
        return (base + timedelta(days=int(delta[1]) if delta[1] else 7 * int(delta[2]))).isoformat(), False
    for weekday, pattern in enumerate(WEEKDAYS):
        if re.search(pattern, text):
            return (base + timedelta(days=(weekday - base.weekday()) % 7)).isoformat(), True
    if re.search(r'следующ\w*\s+недел|келесі\s+апта', text):
        return (base + timedelta(days=13 - base.weekday())).isoformat(), True
    if re.search(r'(этой|текущ\w*|конца)\s+недел|осы\s+апта', text):
        return (base + timedelta(days=6 - base.weekday())).isoformat(), True
    return None, True


def task_state(task, today=None):
    if task.get('status') == 'done':
        return 'done'
    today = today or date.today()
    if task.get('due_date') and date.fromisoformat(task['due_date']) < today:
        return 'overdue'
    return task.get('status', 'todo')
