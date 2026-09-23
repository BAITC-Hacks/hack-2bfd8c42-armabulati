"""Evaluate local speech with the same ASR settings as the application. No downloads."""
import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import DATA
from app.speech import transcribe_audio


def normalize(text):
    return re.sub(r'[^\w\s]', ' ', unicodedata.normalize('NFC', text).lower()).split()


def distance(a,b):
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        row=[i]
        for j,y in enumerate(b,1):
            row.append(min(row[-1]+1,previous[j]+1,previous[j-1]+(x!=y)))
        previous=row
    return previous[-1]


def metrics(reference,hypothesis):
    ref,hyp=normalize(reference),normalize(hypothesis)
    chars=''.join(ref)
    return {'reference_words':len(ref), 'word_errors':distance(ref,hyp),
            'wer':distance(ref,hyp)/len(ref) if ref else None,
            'cer':distance(chars,''.join(hyp))/len(chars) if chars else None}


def main():
    parser=argparse.ArgumentParser(description='Local Kazakh/Russian ASR check; does not evaluate summaries or diarization')
    parser.add_argument('audio',type=Path)
    parser.add_argument('--language',choices=['kk','ru','mixed','auto'],default='kk')
    parser.add_argument('--reference',type=Path,help='Manually verified UTF-8 transcript, optional')
    parser.add_argument('--fast',action='store_true')
    parser.add_argument('--output',type=Path,default=DATA/'speech-check.json')
    args=parser.parse_args()
    from faster_whisper.audio import decode_audio
    started=time.perf_counter()
    audio=decode_audio(str(args.audio),sampling_rate=16000)
    segments,info=transcribe_audio(audio,args.language,args.fast)
    rows=[{k:s[k] for k in ('start','end','text')} for s in segments]
    hypothesis=' '.join(row['text'] for row in rows)
    report={'language_mode':args.language,'detected_language':info['language'],'speech_quality':info,'audio_seconds':len(audio)/16000,
            'processing_seconds':round(time.perf_counter()-started,2),'transcript':hypothesis,'segments':rows,
            'metrics':metrics(args.reference.read_text(encoding='utf-8-sig'),hypothesis) if args.reference else None}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('transcript','segments')},ensure_ascii=True))
    print('Local report:',args.output)


if __name__=='__main__':main()
