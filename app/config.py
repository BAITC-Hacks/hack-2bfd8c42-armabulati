import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv('ALEM_DATA', str(ROOT / 'data'))).resolve()
MODELS = Path(os.getenv('ALEM_MODELS', str(ROOT / 'models'))).resolve()
WHISPER = MODELS / 'whisper'
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
