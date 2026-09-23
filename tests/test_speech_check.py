from app.speech import transcription_options
from scripts.check_speech import metrics

def test_kazakh_and_code_switching_use_distinct_modes():
    assert transcription_options('kk')['language']=='kk'
    mixed=transcription_options('mixed')
    assert mixed['language'] == 'kk' and mixed['multilingual'] is False
    assert transcription_options('mixed',True)['beam_size']==1
    assert transcription_options('kk')['beam_size']==5


def test_wrong_language_and_syllable_loop_regressions():
    from app.speech_quality import choose_language, repetition_reason, needs_review, readable_text
    assert choose_language([('tr',.8),('en',.15),('ru',.02),('kk',.001)],'auto') == 'kk'
    assert choose_language([('ru',.96),('kk',.01)],'auto') == 'ru'
    assert choose_language([('ru',.96)],'mixed') == 'kk'
    assert choose_language([('ru',.96)],'kk') == 'kk'
    assert repetition_reason('Қа'+'ңа'*40)
    assert repetition_reason('Әрі'+'ңіздің'*20)
    assert repetition_reason('есеп дайын '*8)
    assert not repetition_reason('Ертең отчёт дайындап, маған жіберіңіз. Да, хорошо.')
    assert not repetition_reason('Иә, иә, түсіндім.')
    assert not repetition_reason('Жүректі ұрладың ооо ооо')
    assert needs_review([{'start':0,'end':3}],223)
    assert needs_review([{'start':0,'end':30}],30,rejected=1)
    assert not needs_review([{'start':0,'end':28}],30)
    assert readable_text('Жүрек д�үріс соғады') == 'Жүрек [неразборчиво] соғады'
    assert readable_text('Есепті завтра жіберіңіз.') == 'Есепті завтра жіберіңіз.'


def test_silence_is_rejected_before_loading_whisper():
    import numpy as np
    import pytest
    from app.speech import transcribe_audio
    with pytest.raises(ValueError,match='Речь не обнаружена'):
        transcribe_audio(np.zeros(16000*2,dtype=np.float32),'mixed')


def test_auto_routes_to_kazakh_and_sparse_audio_keeps_full_signal(tmp_path, monkeypatch):
    import json
    import numpy as np
    from types import SimpleNamespace
    from app import speech
    import faster_whisper
    import faster_whisper.vad
    for name in ('base','kazakh'):
        path=tmp_path/name
        path.mkdir()
        (path/'model.bin').touch()
    monkeypatch.setattr(speech,'WHISPER',tmp_path/'base')
    monkeypatch.setattr(speech,'WHISPER_KK',tmp_path/'kazakh')
    monkeypatch.setattr(faster_whisper.vad,'get_speech_timestamps',lambda *args: [{'start':0,'end':16000*3}])
    loaded=[]
    class Model:
        def __init__(self,path,**kwargs):
            loaded.append(path)
        def detect_language(self,**kwargs):
            return 'tr',.9,[('tr',.9),('ru',.02),('kk',.001)]
        def transcribe(self,audio,**kwargs):
            assert len(audio)==16000*40 and kwargs['language']=='kk'
            assert not kwargs['multilingual'] and not kwargs['vad_filter']
            row=SimpleNamespace(start=np.float64(0),end=np.float64(3),text='Ертең отчёт дайындаңыз.',avg_logprob=-.2,words=[])
            return iter([row]),SimpleNamespace(duration_after_vad=40)
    monkeypatch.setattr(faster_whisper,'WhisperModel',Model)
    rows,info=speech.transcribe_audio(np.zeros(16000*40,dtype=np.float32))
    assert loaded==[str(tmp_path/'base'),str(tmp_path/'kazakh')]
    assert info['needs_review'] and info['vad_fallback']
    assert rows[0]['text']=='Ертең отчёт дайындаңыз.'
    json.dumps({'segments':rows,'info':info})  # Numpy bools must never reach SQLite/JSON.

def test_metrics_preserve_kazakh_letters_and_count_errors():
    assert metrics('Қазақша сөз. Русский текст!','қазақша сөз русский текст')['wer']==0
    assert metrics('Ертең есеп дайындаңыз','Ертең есеп')['wer']==1/3
    assert metrics('Қазақша','Казакша')['cer']>0
    assert metrics('','')['wer'] is None
