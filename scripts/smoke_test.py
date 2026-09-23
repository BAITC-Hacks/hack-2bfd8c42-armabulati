"""Opt-in real local audio check. Run only with a recording you may process."""
import argparse
import json
import time
from pathlib import Path
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('audio', type=Path)
    parser.add_argument('--date', required=True)
    parser.add_argument('--language', default='auto', choices=['auto','ru','kk','mixed'])
    parser.add_argument('--mode', default='accurate', choices=['accurate','fast'])
    parser.add_argument('--speakers', type=int, default=0)
    parser.add_argument('--repeat', action='store_true', help='Verify duplicate import uses the cache')
    args = parser.parse_args()
    with httpx.Client(base_url='http://127.0.0.1:8765', timeout=120, trust_env=False) as client:
        client.headers['X-Alem-Token'] = client.get('/api/bootstrap').json()['token']
        reports = []
        for run in range(2 if args.repeat else 1):
            started = time.perf_counter()
            with args.audio.open('rb') as file:
                response = client.post('/api/meetings', data={
                    'title':f'Проверка v0.2 · {args.audio.stem}' + (' · повтор' if run else ''),
                    'meeting_date':args.date, 'language':args.language, 'processing_mode':args.mode,
                    'speaker_count':args.speakers, 'consent':'true'},
                    files={'file':(args.audio.name,file,'application/octet-stream')})
            response.raise_for_status()
            mid = response.json()['id']
            print('Meeting',mid,flush=True)
            previous, heartbeat = None, time.monotonic()
            while True:
                item = client.get('/api/meetings/'+mid).json()
                phase = item['status'], item['progress']
                if phase != previous or time.monotonic() - heartbeat >= 20:
                    print(item['status'],item['progress'],item['stage'],flush=True)
                    previous, heartbeat = phase, time.monotonic()
                if item['status'] in ('ready','error'):
                    break
                if time.perf_counter() - started > 7200:
                    raise TimeoutError('Processing exceeded two hours')
                time.sleep(2)
            if item['status'] != 'ready':
                raise RuntimeError(item['error'])
            for kind, prefix in [('pdf',b'%PDF-'),('docx',b'PK')]:
                export = client.get(f'/api/meetings/{mid}/export/{kind}')
                export.raise_for_status()
                assert export.content.startswith(prefix)
            if run:
                assert item.get('cache_hit'), 'Repeated import did not hit cache'
            report = {'meeting_id':mid,'seconds':round(time.perf_counter()-started,2),'timings':item.get('timings'),
                      'tasks':len(item['tasks']),'segments':len(item['segments']),'cache_hit':item.get('cache_hit',False)}
            reports.append(report)
            print(json.dumps(report,ensure_ascii=False),flush=True)
        output=Path(__file__).resolve().parents[1]/'data'/'smoke-latest.json'
        output.write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
