"""Conservative ASR guards; confidence alone does not detect decoder loops."""
import re
import unicodedata


def readable_text(text):
    # Whisper's byte tokens can occasionally end in an incomplete Unicode word.
    # Mark that word as unclear instead of presenting broken characters as text.
    return re.sub(r'\S*[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]\S*', '[неразборчиво]', text)


def repetition_reason(text):
    text = unicodedata.normalize('NFC', text).lower()
    # Catch loops inside a single Kazakh word, e.g. «қаңаңаңа...».
    for match in re.finditer(r'(\w{1,12})\1{5,}', text):
        if len(match.group()) >= 20:
            return 'Повторяющиеся слоги'
    words = re.findall(r'\w+', text)
    for size in range(1, 5):
        for start in range(max(0, len(words) - size * 4 + 1)):
            phrase = words[start:start + size]
            if words[start:start + size * 4] == phrase * 4:
                return 'Зацикливание распознавания'
    return None


def choose_language(probabilities, requested):
    """Never let unrelated language detection override the RU/KZ task."""
    if requested in ('ru', 'kk'):
        return requested
    if requested == 'mixed':
        # A fixed transcribe token still permits Russian words in Kazakh speech.
        return 'kk'
    scores = dict(probabilities)
    # Kazakh is often misclassified as Turkish/English by the base model.
    # Only positively identified Russian selects the generic Russian decoder.
    return 'ru' if scores.get('ru', 0) >= .65 and scores.get('kk', 0) < .1 else 'kk'


def needs_review(segments, duration, rejected=0):
    covered = sum(max(0, row['end'] - row['start']) for row in segments)
    return bool(not segments or rejected > 0 or (duration >= 30 and covered / duration < .12))
