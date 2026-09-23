"""Build an allowlisted source distribution; never include local meeting data."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('app', 'web', 'scripts', 'tests', 'examples', 'docs')
FILES = ('README.md', 'CHANGELOG.md', '.gitignore', '.env.example', 'requirements.txt', 'requirements.lock.txt',
         'models.lock.json', 'run.ps1', 'setup.ps1', 'start.cmd', 'VERSION')


def build(output=None):
    output = Path(output or ROOT / 'dist')
    output.mkdir(parents=True, exist_ok=True)
    version = (ROOT / 'VERSION').read_text().strip()
    archive = output / f'dauys-hunt-{version}.zip'
    files = [ROOT / file for file in FILES if (ROOT / file).is_file()]
    for directory in DIRECTORIES:
        files += [p for p in (ROOT / directory).rglob('*') if p.is_file()
                  and '__pycache__' not in p.parts and p.suffix in ('.py', '.js', '.cjs', '.css', '.html', '.svg', '.md', '.txt', '.json')]
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(files):
            zipped.write(path, 'dauys-hunt/' + path.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = output / 'SHA256SUMS.txt'
    checksum.write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(json.dumps({'archive': str(archive), 'files': len(files), 'sha256': digest}))
    return archive


if __name__ == '__main__':
    build()
