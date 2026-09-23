import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from . import store
from .config import ROOT, DATA
from .analysis import analyze
from . import cache

executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='alem')
active = set()
lock = threading.Lock()


def submit(mid, speech=True):
    with lock:
        if mid in active:
            return False
        active.add(mid)
    executor.submit(process, mid, speech)
    return True


def process(mid, speech):
    started = time.perf_counter()
    try:
        item = store.get(mid)
        item.update(status='processing', stage='Подготовка записи', progress=3, error=None,
                    started_at=datetime.now(timezone.utc).isoformat(), timings={})
        store.save(item)
        if cache.restore(item):
            item['timings'] = {'total_seconds': round(time.perf_counter() - started, 3)}
            store.save(item, 'Повторная запись: использован локальный кэш')
            return
        if speech:
            with (DATA / f'{mid}.log').open('w', encoding='utf-8') as log:
                result = subprocess.run([sys.executable, '-m', 'app.speech', mid], cwd=ROOT,
                    stdout=log, stderr=log, timeout=14400,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            if result.returncode:
                # Detailed diagnostic stays local, no transcript copied into HTTP error messages.
                raise RuntimeError('Не удалось распознать запись. Проверьте формат и модели. Диагностика: data/' + mid + '.log')
        item = store.get(mid)
        analysis_started = time.perf_counter()
        def progress(stage, percent):
            item.update(stage=stage, progress=percent)
            store.save(item)
        item.update(analyze(item, progress))
        item.setdefault('timings', {}).update(analysis_seconds=round(time.perf_counter() - analysis_started, 2),
                                            total_seconds=round(time.perf_counter() - started, 2))
        item.update(status='ready', stage='Протокол готов к проверке', progress=100)
        cache.save(item)
        store.save(item, 'Протокол сформирован локально')
    except Exception as error:
        item = store.get(mid)
        if item:
            item.update(status='error', stage='Не удалось завершить обработку', error=str(error)[:500])
            store.save(item, 'Ошибка обработки')
    finally:
        with lock:
            active.discard(mid)
