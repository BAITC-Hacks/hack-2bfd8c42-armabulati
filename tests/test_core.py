import io
import zipfile
from datetime import date
from app.dates import resolve_deadline, task_state
from app.analysis import clean_result
from app.export import anonymize, docx_bytes, pdf_bytes


def sample():
    item = {'id': 'test', 'title': 'Тест қазақша', 'date': '2026-09-23',
            'speakers': {'S1': 'Айдана'}, 'segments': [{'id': 1, 'speaker': 'S1', 'start': 0, 'end': 3,
             'text': 'Айдана подготовит отчёт до пятницы.'}]}
    result = {'summary': 'Айдана подготовит отчёт.', 'decisions': ['Подготовить отчёт.'], 'tasks': [
        {'title': 'Подготовить отчёт', 'assignee': 'Айдана', 'speaker_id': 'S1',
         'deadline_text': 'до пятницы', 'evidence_ids': [1], 'priority': 'normal', 'category': 'Отчёты'}]}
    item.update(clean_result(result, item))
    return item


def test_deadlines():
    assert resolve_deadline('до 15 октября', '2026-09-23') == ('2026-10-15', True)
    assert resolve_deadline('завтра', '2026-09-23') == ('2026-09-24', False)
    assert resolve_deadline('ертең', '2026-09-23') == ('2026-09-24', False)
    assert resolve_deadline('до пятницы', '2026-09-23') == ('2026-09-25', True)
    assert resolve_deadline('31 февраля', '2026-09-23') == (None, True)
    assert resolve_deadline('', '2026-09-23') == (None, True)


def test_completion_wins_over_deadline():
    assert task_state({'status': 'done', 'due_date': '2020-01-01'}, date(2026, 9, 23)) == 'done'
    assert task_state({'status': 'todo', 'due_date': '2020-01-01'}, date(2026, 9, 23)) == 'overdue'


def test_rejects_missing_evidence():
    assert clean_result({'tasks': [{'title': 'Выдуманное поручение', 'evidence_ids': [999]}]}, sample())['tasks'] == []


def test_anonymization_does_not_mutate_original():
    original = sample()
    cleaned = anonymize(original)
    assert original['speakers']['S1'] == 'Айдана'
    assert 'Айдана' not in str(cleaned)


def test_export_documents():
    item = sample()
    pdf = pdf_bytes(item)
    assert pdf.startswith(b'%PDF-') and len(pdf) > 10000
    with zipfile.ZipFile(io.BytesIO(docx_bytes(item))) as archive:
        xml = archive.read('word/document.xml').decode()
        assert 'Тест қазақша' in xml and 'Подготовить отчёт' in xml and 'Айдана' in xml
