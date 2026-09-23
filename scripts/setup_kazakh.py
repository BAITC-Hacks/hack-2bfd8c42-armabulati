"""Provision pinned Kazakh weights and convert to CPU INT8; never reads audio."""
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.environ.pop('HF_HUB_OFFLINE', None)
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    spec = json.loads((ROOT / 'models.lock.json').read_text())['whisper_kk']
    target = ROOT / 'models/whisper-kk'
    marker = target / 'provision.json'
    if marker.exists() and json.loads(marker.read_text()) == spec and all(
            (target / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json')):
        print('Kazakh CPU model is ready.', flush=True)
        return
    from huggingface_hub import snapshot_download
    source = ROOT / 'models/whisper-kk-source'
    snapshot_download(spec['repo'], revision=spec['revision'], local_dir=source,
                      allow_patterns=['*.json', 'model.safetensors'], max_workers=2)
    environment = ROOT / 'runtime/asr-convert'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        venv.create(environment, with_pip=True)
    subprocess.run([str(python), '-m', 'pip', 'install', 'torch==2.9.1',
                    '--index-url', 'https://download.pytorch.org/whl/cpu'], check=True)
    subprocess.run([str(python), '-m', 'pip', 'install', 'transformers==5.9.0',
                    'ctranslate2==4.8.2', 'safetensors==0.6.2'], check=True)
    # Only safetensors are downloaded; remote model code is never enabled.
    converter = environment / ('Scripts/ct2-transformers-converter.exe' if os.name == 'nt' else 'bin/ct2-transformers-converter')
    staging = ROOT / 'models/whisper-kk-converting'
    subprocess.run([str(converter), '--model', str(source), '--output_dir', str(staging),
                    '--force', '--quantization', 'int8', '--copy_files',
                    'tokenizer.json', 'preprocessor_config.json'], check=True)
    staging.joinpath('provision.json').write_text(json.dumps(spec, indent=2))
    target.mkdir(parents=True, exist_ok=True)
    # Publish only after conversion succeeds. Run provisioning with the app stopped.
    for path in staging.iterdir():
        path.replace(target / path.name)
    staging.rmdir()
    print('Kazakh INT8 model ready. Runtime remains offline.', flush=True)


if __name__ == '__main__':
    main()
