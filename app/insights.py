"""Deterministic meeting tools: no additional model calls or external services."""
import math
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from .dates import task_state


def insights(item):
    durations = Counter()
    counts = Counter()
    for segment in item.get('segments', []):
        durations[segment['speaker']] += max(0, segment['end'] - segment['start'])
        counts[segment['speaker']] += 1
    total = sum(durations.values())
    risks = []
    for task in item.get('tasks', []):
        if task['status'] == 'done':
            continue
        reasons = []
        if not task.get('assignee', '').strip():
            reasons.append('Не назначен ответственный')
        if not task.get('due_date'):
            reasons.append('Не определён срок')
        elif task.get('date_uncertain'):
            reasons.append('Срок требует подтверждения')
        if task_state(task) == 'overdue':
            reasons.append('Срок истёк')
        if not task.get('reviewed'):
            reasons.append('Не проверено по записи')
        if reasons:
            risks.append({'task_id': task['id'], 'title': task['title'], 'reasons': reasons})
    return {'speaking': [{'speaker': sid, 'name': name, 'seconds': round(durations[sid], 1),
             'percent': round(100 * durations[sid] / total, 1) if total else 0,
             'segments': counts[sid]} for sid, name in item.get('speakers', {}).items()],
            'has_audio_timing': item.get('source') == 'audio' and total > 0,
            'risks': risks,
            'reviewed': sum(t.get('reviewed', False) for t in item.get('tasks', [])),
            'total_tasks': len(item.get('tasks', []))}


STOP = set('и в на по к до от с за у это что как где кто а но для мы вы он она они когда какой какие'.split())


def terms(text):
    # Prefix matching handles common Russian/Kazakh inflections without claiming semantic QA.
    return [w[:6] if len(w) > 6 else w for w in re.findall(r'[^\W\d_]+', text.lower().replace('ё', 'е')) if len(w) > 1 and w not in STOP]


def search_segments(item, query):
    query_terms = set(terms(query))
    if not query_terms:
        return []
    results = []
    for index, segment in enumerate(item['segments']):
        words = set(terms(segment['text']))
        overlap = words & query_terms
        if overlap:
            score = len(overlap) / len(query_terms) + len(overlap) / max(1, math.sqrt(len(words)))
            # Show adjoining context so an isolated deadline remains understandable.
            context = item['segments'][max(0, index - 1):index + 2]
            results.append({'id': segment['id'], 'start': segment['start'], 'speaker': segment['speaker'],
                            'text': segment['text'], 'score': round(score, 3),
                            'context': [{'id': s['id'], 'text': s['text']} for s in context]})
    return sorted(results, key=lambda row: (-row['score'], row['id']))[:12]


def followup_agenda(item):
    tasks = [t for t in item['tasks'] if t['status'] != 'done']
    tasks.sort(key=lambda t: (0 if task_state(t) == 'overdue' else 1, t.get('due_date') or '9999'))
    lines = ['# Повестка следующей встречи', '', f"Источник: {item['title']} ({item['date']})", '',
             'Сформировано из открытых поручений. Проверьте список перед отправкой.', '']
    for index, t in enumerate(tasks, 1):
        lines += [f"## {index}. {t['title']}", f"- Ответственный: {t['assignee'] or 'назначить на встрече'}",
                  f"- Срок: {t.get('due_date') or 'согласовать'}" + (' (требует подтверждения)' if t.get('date_uncertain') else ''),
                  '- Обсудить: что сделано, что мешает, какое решение требуется.', '']
    if not tasks:
        lines.append('Все поручения выполнены. Новых пунктов из открытых поручений нет.')
    return '\n'.join(lines)


def ics_escape(value):
    return str(value).replace('\\', '\\\\').replace('\r', '').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def fold_ics(line):
    # RFC 5545: at most 75 octets per physical line, never split a UTF-8 character.
    output, chunk, size = [], '', 0
    for char in line:
        length = len(char.encode('utf-8'))
        if size + length > 75:
            output.append(chunk)
            chunk, size = ' ', 1
        chunk += char
        size += length
    output.append(chunk)
    return '\r\n'.join(output)


def calendar(item):
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Dauys Hunt//Meeting tasks//RU', 'CALSCALE:GREGORIAN']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for t in item['tasks']:
        # Ambiguous dates must not silently create misleading reminders.
        if t['status'] == 'done' or not t.get('due_date') or t.get('date_uncertain') or not t.get('reviewed'):
            continue
        due = date.fromisoformat(t['due_date'])
        lines += ['BEGIN:VEVENT', f"UID:{item['id']}-{t['id']}@alem.local", f'DTSTAMP:{stamp}',
                  f'DTSTART;VALUE=DATE:{due:%Y%m%d}', f'DTEND;VALUE=DATE:{due + timedelta(days=1):%Y%m%d}',
                  'SUMMARY:' + ics_escape(t['title']),
                  'DESCRIPTION:' + ics_escape(f"Ответственный: {t['assignee']}\nСовещание: {item['title']}\n{t['evidence']}"),
                  'END:VEVENT']
    lines += ['END:VCALENDAR']
    return ('\r\n'.join(fold_ics(line) for line in lines) + '\r\n').encode('utf-8')
