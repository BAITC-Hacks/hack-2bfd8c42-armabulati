"""Explicit provisioning only; never reads meeting data or runs during inference."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / 'models'
MODELS.mkdir(exist_ok=True)
os.environ['HF_HUB_DISABLE_XET'] = '1'
os.environ.pop('HF_HUB_OFFLINE', None)


def download(url, target):
    if target.exists():
        print('Present:', target.name, flush=True)
        return
    print('Download:', target.name, flush=True)
    tmp = target.with_suffix(target.suffix + '.part')
    req = urllib.request.Request(url, headers={'User-Agent': 'AlemMinutes/1.0'})
    with urllib.request.urlopen(req, timeout=120) as response, tmp.open('wb') as f:
        shutil.copyfileobj(response, f, 1024 * 1024)
    tmp.replace(target)


def main():
    from huggingface_hub import snapshot_download, hf_hub_download
    # Pin to immutable revisions resolved on first provision and record in manifest.
    specs = [
        ('whisper', 'mobiuslabsgmbh/faster-whisper-large-v3-turbo', None),
        ('speaker', 'Wespeaker/wespeaker-voxceleb-resnet34-LM', 'voxceleb_resnet34_LM.onnx'),
        ('llm', 'Qwen/Qwen3-4B-GGUF', 'Qwen3-4B-Q4_K_M.gguf'),
    ]
    manifest_path = MODELS / 'manifest.json'
    lock_path = ROOT / 'models.lock.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else json.loads(lock_path.read_text()) if lock_path.exists() else {}
    from huggingface_hub import HfApi
    for key, repo, filename in specs:
        rev = manifest.get(key, {}).get('revision') or HfApi().model_info(repo).sha
        manifest[key] = {'repo': repo, 'revision': rev}
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print('Provision', key, repo, rev, flush=True)
        if filename:
            target = MODELS / ('speaker.onnx' if key == 'speaker' else 'qwen.gguf')
            if not target.exists():
                cached = hf_hub_download(repo, filename, revision=rev, local_dir=MODELS / 'downloads')
                shutil.move(cached, target)
        else:
            snapshot_download(repo, revision=rev, local_dir=MODELS / 'whisper', allow_patterns=['*.json', '*.bin', '*.txt'])
    if os.name == 'nt':
        runtime = ROOT / 'runtime'
        runtime.mkdir(exist_ok=True)
        if not (runtime / 'llama-server.exe').exists():
            release = json.load(urllib.request.urlopen('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b11120'))
            candidates = [a for a in release['assets'] if 'win' in a['name'] and 'x64' in a['name'] and 'cpu' in a['name'] and a['name'].endswith('.zip')]
            if not candidates:
                raise RuntimeError('No CPU asset: ' + str([a['name'] for a in release['assets']]))
            asset = candidates[0]
            archive = runtime / 'llama.zip'
            download(asset['browser_download_url'], archive)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            expected = asset.get('digest')
            if expected and expected != 'sha256:' + digest:
                raise RuntimeError('llama.cpp archive checksum mismatch')
            with zipfile.ZipFile(archive) as z:
                for member in z.infolist():
                    if not member.is_dir() and Path(member.filename).suffix.lower() in ('.exe', '.dll'):
                        with z.open(member) as src, (runtime / Path(member.filename).name).open('wb') as dst:
                            shutil.copyfileobj(src, dst)
            manifest['llama'] = {'release': 'b11120', 'asset': asset['name'], 'sha256': digest}
            manifest_path.write_text(json.dumps(manifest, indent=2))
    from setup_kazakh import main as setup_kazakh
    setup_kazakh()
    print('Models ready. Inference is offline.', flush=True)


if __name__ == '__main__':
    main()
