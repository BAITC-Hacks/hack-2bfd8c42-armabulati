"""Offline multilingual ASR and acoustic speaker clustering in a child process."""
import sys
import time
import numpy as np
from .config import WHISPER, WHISPER_KK, SPEAKER, THREADS, MAX_SECONDS
from .speech_quality import choose_language, repetition_reason, needs_review, readable_text


def diarize(audio, segments, requested=0):
    if requested == 1:
        for segment in segments:
            segment['speaker'] = 'S1'
            segment.pop('words', None)
        return segments, {'S1': 'Участник 1'}, ['Указан один говорящий; разделение голосов не требуется.']
    import kaldi_native_fbank as knf
    import onnxruntime as ort
    from sklearn.cluster import AgglomerativeClustering
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = THREADS
    session = ort.InferenceSession(str(SPEAKER), sess_options=opts, providers=['CPUExecutionProvider'])
    embeddings, windows = [], []
    # Fixed overlapping acoustic windows catch speaker changes within ASR segments.
    for segment in segments:
        start, end = segment['start'], segment['end']
        for a in np.arange(start, max(start + .01, end - .4), 1.5):
            b = min(a + 3, end)
            if b - a < .4:
                continue
            wave = audio[int(a * 16000):int(b * 16000)]
            if len(wave) < 6400:
                continue
            config = knf.FbankOptions()
            config.frame_opts.dither = 0
            config.frame_opts.samp_freq = 16000
            config.frame_opts.window_type = 'hamming'
            config.mel_opts.num_bins = 80
            config.mel_opts.low_freq = 20
            fbank = knf.OnlineFbank(config)
            fbank.accept_waveform(16000, (wave * 32768).tolist())
            fbank.input_finished()
            features = np.stack([fbank.get_frame(i) for i in range(fbank.num_frames_ready)])
            features -= features.mean(axis=0, keepdims=True)
            embedding = session.run(None, {session.get_inputs()[0].name: features[None].astype(np.float32)})[0].reshape(-1)
            embedding /= max(np.linalg.norm(embedding), 1e-9)
            embeddings.append(embedding)
            windows.append((float(a), float(b)))
    if not embeddings:
        for s in segments:
            s['speaker'] = 'S1'
        return segments, {'S1': 'Участник 1'}, ['Недостаточно речи для уверенной диаризации.']
    if len(embeddings) == 1 or requested == 1:
        labels = np.zeros(len(embeddings), dtype=int)
    else:
        options = {'metric': 'cosine', 'linkage': 'average'}
        if requested:
            options['n_clusters'] = min(requested, len(embeddings))
        else:
            options.update(n_clusters=None, distance_threshold=.55)
        labels = AgglomerativeClustering(**options).fit_predict(np.stack(embeddings))
    mapping, speakers, output = {}, {}, []
    def speaker_at(a, b):
        center = (a + b) / 2
        distances = [abs((x + y) / 2 - center) for x, y in windows]
        label = int(labels[int(np.argmin(distances))])
        if label not in mapping:
            sid = f'S{len(mapping) + 1}'
            mapping[label] = sid
            speakers[sid] = f'Участник {len(mapping)}'
        return mapping[label]
    for segment in segments:
        words = segment.pop('words', [])
        if not words:
            segment['speaker'] = speaker_at(segment['start'], segment['end'])
            output.append(segment)
            continue
        current = None
        for word in words:
            sid = speaker_at(word['start'], word['end'])
            if current and current['speaker'] == sid:
                current['text'] += word['text']
                current['end'] = word['end']
            else:
                current = {'start': word['start'], 'end': word['end'], 'speaker': sid, 'text': word['text'], 'confidence': segment['confidence']}
                output.append(current)
    for index, segment in enumerate(output):
        segment['id'] = index + 1
        segment['text'] = segment['text'].strip()
    return output, speakers, ['Группы голосов определены автоматически. Подтвердите имена участников; короткие и одновременные реплики могут быть разделены неточно.']


def transcription_options(language, fast=False):
    return {'language': 'ru' if language == 'ru' else 'kk', 'task': 'transcribe',
            'beam_size': 1 if fast else 5, 'temperature': 0, 'vad_filter': True,
            'word_timestamps': True, 'condition_on_previous_text': False,
            'multilingual': False, 'repetition_penalty': 1.1, 'no_repeat_ngram_size': 4,
            'vad_parameters': {'threshold': .25, 'min_silence_duration_ms': 700,
                               'speech_pad_ms': 400, 'max_speech_duration_s': 25},
            'without_timestamps': language != 'ru'}


def transcribe_audio(audio, language='auto', fast=False, progress=None):
    """Shared offline recognizer used by the app and the quality-check CLI."""
    import gc
    from faster_whisper import WhisperModel
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    def load(path):
        if not (path / 'model.bin').is_file():
            raise ValueError('Модель речи отсутствует. Выполните scripts/setup_models.py.')
        return WhisperModel(str(path), device='cpu', compute_type='int8',
                            cpu_threads=THREADS, local_files_only=True)
    speech = get_speech_timestamps(audio, VadOptions(threshold=.25, speech_pad_ms=400))
    if not speech:
        raise ValueError('Речь не обнаружена. Проверьте запись и уровень громкости.')
    probabilities, warnings, model = [], [], None
    if language == 'auto':
        model = load(WHISPER)
        # Detection uses actual voice, not a silent intro or background music.
        probe = np.concatenate([audio[row['start']:row['end']] for row in speech])[:16000 * 90]
        _, _, probabilities = model.detect_language(audio=probe, language_detection_segments=3,
                                                     language_detection_threshold=.8)
    resolved = choose_language(probabilities, language)
    if resolved == 'kk':
        del model
        gc.collect()
        model = load(WHISPER_KK)
    elif model is None:
        model = load(WHISPER)
    if language == 'auto' and probabilities and probabilities[0][0] not in ('ru', 'kk'):
        warnings.append('Автоопределение языка неуверенное. Использован казахский режим; проверьте текст или выберите язык явно.')
    duration = len(audio) / 16000
    voice_seconds = sum(row['end'] - row['start'] for row in speech) / 16000
    sparse = duration >= 30 and voice_seconds / duration < .25
    options = transcription_options(resolved, fast)
    if sparse:
        # Soft speech/singing can be discarded by VAD. Keep the original audio,
        # but do not pretend that this fallback is a verified meeting transcript.
        options.update(vad_filter=False, chunk_length=25)
        warnings.append('Детектор выделил мало речи. Запись обработана целиком без удаления пауз; музыка, пение и шум могут давать ошибки. Проверьте транскрипт.')
    iterator, info = model.transcribe(audio, **options)
    rows, rejected = [], []
    for segment in iterator:
        text = segment.text.strip()
        if not text:
            continue
        reason = repetition_reason(text)
        if reason:
            rejected.append({'start': round(float(segment.start), 2), 'end': round(float(segment.end), 2), 'reason': reason})
            continue
        cleaned = readable_text(text)
        if cleaned != text:
            rejected.append({'start': round(float(segment.start), 2), 'end': round(float(segment.end), 2),
                             'reason': 'Нечитаемое слово помечено как неразборчивое'})
            text = cleaned
        rows.append({'id': len(rows) + 1, 'start': round(float(segment.start), 2), 'end': round(float(segment.end), 2),
                     'text': text, 'confidence': round(float(np.exp(segment.avg_logprob)), 3),
                     'words': [{'start': round(float(w.start), 2), 'end': round(float(w.end), 2), 'text': readable_text(w.word)}
                               for w in (segment.words or [])]})
        if progress:
            progress(rows, segment.end)
    del model
    gc.collect()
    if rejected:
        warnings.append('Часть аудио не распознана надёжно: повторы исключены, нечитаемые слова помечены. Прослушайте отмеченные интервалы и исправьте транскрипт.')
    review = bool(sparse or needs_review(rows, duration, len(rejected)))
    if review:
        warnings.append('Качество транскрипта требует проверки. Автоматическое создание поручений остановлено, чтобы не придумывать содержание.')
    if not rows:
        raise ValueError('Не удалось надёжно распознать речь. Выберите язык явно или используйте более чистую запись.')
    metadata = {'requested_language': language, 'language': resolved,
                'model': 'kazakh-whisper-large-v3-turbo-int8' if resolved == 'kk' else 'whisper-large-v3-turbo',
                'speech_seconds': round(float(voice_seconds), 2), 'vad_fallback': bool(sparse), 'rejected_intervals': rejected,
                'needs_review': review, 'warnings': warnings}
    return rows, metadata


def run(mid):
    from faster_whisper.audio import decode_audio
    from . import store
    from .config import DATA
    item = store.get(mid)
    started = time.perf_counter()
    audio = decode_audio(str(DATA / item['audio_file']), sampling_rate=16000)
    duration = len(audio) / 16000
    if duration < .5 or duration > MAX_SECONDS:
        raise ValueError('Продолжительность должна быть от 0,5 секунды до 2 часов.')
    item.update(duration=round(duration, 2), stage='Загрузка модели распознавания', progress=8)
    store.save(item)
    def progress(segments, end):
        item.update(stage=f'Распознавание: {int(end)} / {int(duration)} сек.', progress=min(65, 10 + int(55 * end / duration)),
                    preview=[{k: v for k, v in row.items() if k != 'words'} for row in segments])
        store.save(item)
    segments, recognition = transcribe_audio(audio, item['language'], item.get('processing_mode') == 'fast', progress)
    item.update(stage='Различение голосов участников', progress=68)
    item.setdefault('timings', {})['speech_seconds'] = round(time.perf_counter() - started, 2)
    store.save(item)
    diarization_started = time.perf_counter()
    segments, speakers, warnings = diarize(audio, segments, item.get('speaker_count', 0))
    item.update(segments=segments, speakers=speakers, warnings=recognition['warnings'] + warnings,
                speech_quality=recognition, detected_language=recognition['language'], stage='Речь распознана', progress=75)
    item['timings']['diarization_seconds'] = round(time.perf_counter() - diarization_started, 2)
    item.pop('preview', None)
    store.save(item)


if __name__ == '__main__':
    run(sys.argv[1])
