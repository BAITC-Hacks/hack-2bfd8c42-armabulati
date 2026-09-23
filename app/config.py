import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# A deliberately small KEY=VALUE format, no shell expansion or executable content.
if (ROOT / '.env').is_file():
    for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if sep and key.strip().startswith('DAUYS_'):
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)
DATA = Path(os.getenv('DAUYS_DATA', os.getenv('ALEM_DATA', str(ROOT / 'data')))).resolve()
MODELS = Path(os.getenv('ALEM_MODELS', str(ROOT / 'models'))).resolve()
WHISPER = MODELS / 'whisper'
WHISPER_KK = MODELS / 'whisper-kk'
SPEAKER = MODELS / 'speaker.onnx'
LLM = MODELS / 'qwen.gguf'
LLAMA = Path(os.getenv('ALEM_LLAMA', str(ROOT / 'runtime' / ('llama-server.exe' if os.name == 'nt' else 'llama-server'))))
MAX_UPLOAD = 250 * 1024 * 1024
MAX_SECONDS = 7200
THREADS = max(1, min(6, (os.cpu_count() or 4) // 2))
# Runtime is offline. Model downloads are an explicit, separate setup operation.
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['DO_NOT_TRACK'] = '1'
