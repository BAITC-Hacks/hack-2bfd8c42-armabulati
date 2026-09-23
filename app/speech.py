"""Offline multilingual ASR and acoustic speaker clustering in a child process."""
import json
import sys
from pathlib import Path
import numpy as np
from .config import WHISPER, SPEAKER, THREADS, MAX_SECONDS


def diarize(audio, segments, requested=0):
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


def run(mid):
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
    from . import store
    from .config import DATA
    item = store.get(mid)
    audio = decode_audio(str(DATA / item['audio_file']), sampling_rate=16000)
    duration = len(audio) / 16000
    if duration < .5 or duration > MAX_SECONDS:
        raise ValueError('Продолжительность должна быть от 0,5 секунды до 2 часов.')
    item.update(duration=round(duration, 2), stage='Загрузка модели распознавания', progress=8)
    store.save(item)
    model = WhisperModel(str(WHISPER), device='cpu', compute_type='int8', cpu_threads=THREADS, local_files_only=True)
    language = item['language'] if item['language'] in ('ru', 'kk') else None
    iterator, info = model.transcribe(audio, language=language, beam_size=3, vad_filter=True, word_timestamps=True, condition_on_previous_text=False, multilingual=item['language'] == 'mixed')
    segments = []
    for s in iterator:
        if not s.text.strip():
            continue
        segments.append({'id': len(segments) + 1, 'start': round(s.start, 2), 'end': round(s.end, 2), 'text': s.text.strip(), 'confidence': round(float(np.exp(s.avg_logprob)), 3), 'words': [{'start': round(w.start, 2), 'end': round(w.end, 2), 'text': w.word} for w in (s.words or [])]})
        item.update(stage=f'Распознавание: {int(s.end)} / {int(duration)} сек.', progress=min(65, 10 + int(55 * s.end / duration)))
        store.save(item)
    if not segments:
        raise ValueError('Речь не обнаружена. Проверьте запись и уровень громкости.')
    del model
    import gc
    gc.collect()
    item.update(stage='Различение голосов участников', progress=68)
    store.save(item)
    segments, speakers, warnings = diarize(audio, segments, item.get('speaker_count', 0))
    item.update(segments=segments, speakers=speakers, warnings=warnings, detected_language=info.language, stage='Речь распознана', progress=75)
    store.save(item)


if __name__ == '__main__':
    run(sys.argv[1])
