from datetime import date
from app.insights import insights, search_segments, followup_agenda, calendar
from test_core import sample


def test_radar_does_not_flag_finished_tasks():
    item = sample()
    item['source'] = 'audio'
    item['tasks'][0].update(assignee='', due_date=None)
    info = insights(item)
    assert 'Не назначен ответственный' in info['risks'][0]['reasons']
    assert info['speaking'][0]['percent'] == 100
    item['tasks'][0]['status'] = 'done'
    assert insights(item)['risks'] == []


def test_text_import_has_no_fake_timing():
    item = sample()
    item['source'] = 'text'
    assert not insights(item)['has_audio_timing']


def test_search_returns_only_matching_sources_and_neighbors():
    item = sample()
    item['segments'].append({'id':2, 'start':3, 'end':5, 'speaker':'S1', 'text':'Бюджет проекта требует обсуждения.'})
    matches = search_segments(item, 'бюджет')
    assert [m['id'] for m in matches] == [2]
    assert matches[0]['context'][0]['id'] == 1
    assert search_segments(item, 'несуществующий') == []
    assert search_segments(item, 'и в что') == []


def test_agenda_excludes_done_tasks():
    item = sample()
    assert 'Подготовить отчёт' in followup_agenda(item)
    item['tasks'][0]['status'] = 'done'
    assert 'Подготовить отчёт' not in followup_agenda(item)


def test_calendar_requires_review_and_exact_date_and_escapes_injection():
    item = sample()
    assert b'BEGIN:VEVENT' not in calendar(item)
    item['tasks'][0].update(reviewed=True, date_uncertain=False, due_date='2026-10-01', title='Отчёт\nBEGIN:VEVENT;,' * 30)
    data = calendar(item)
    assert data.replace(b'\r\n ', b'').split(b'\r\n').count(b'BEGIN:VEVENT') == 1
    assert b'DTSTART;VALUE=DATE:20261001' in data
    assert b'DTEND;VALUE=DATE:20261002' in data
    for line in data.split(b'\r\n'):
        assert len(line) <= 75
        line.decode('utf-8')
    item['tasks'][0]['status'] = 'done'
    assert b'BEGIN:VEVENT' not in calendar(item)
