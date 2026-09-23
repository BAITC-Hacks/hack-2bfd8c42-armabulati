from app.speech import transcription_options
from scripts.check_speech import metrics

def test_kazakh_and_code_switching_use_distinct_modes():
    assert transcription_options('kk')['language']=='kk'
    mixed=transcription_options('mixed')
    assert mixed['language'] is None and mixed['multilingual'] is True
    assert transcription_options('mixed',True)['beam_size']==1
    assert transcription_options('kk')['beam_size']==3

def test_metrics_preserve_kazakh_letters_and_count_errors():
    assert metrics('Қазақша сөз. Русский текст!','қазақша сөз русский текст')['wer']==0
    assert metrics('Ертең есеп дайындаңыз','Ертең есеп')['wer']==1/3
    assert metrics('Қазақша','Казакша')['cer']>0
    assert metrics('','')['wer'] is None
