"""Restore only the latest encrypted reading checkpoint using the job token."""
import io
import json
import os
from pathlib import Path
import subprocess
import zipfile


def api(path):
    result = subprocess.run(['gh', 'api', path], capture_output=True, check=True)
    return result.stdout


def restore():
    repo = os.environ['GITHUB_REPOSITORY']
    chosen = None
    for page in range(1, 101):
        data = json.loads(api(f'repos/{repo}/actions/artifacts?per_page=100&page={page}'))
        entries = data['artifacts']
        matching = [item for item in entries if item['name'].startswith('wxread-state-v1-') and not item['expired']]
        if matching:
            chosen = max(matching, key=lambda item: item['id'])
            break
        if len(entries) < 100:
            break
    if chosen is None:
        print('No previous encrypted checkpoint is available.')
        return
    archive = api(f'repos/{repo}/actions/artifacts/{chosen["id"]}/zip')
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        files = [item for item in bundle.infolist() if not item.is_dir()]
        if len(files) != 1 or Path(files[0].filename).name != 'checkpoint.enc' or files[0].file_size > 5_000_000:
            raise ValueError('Unexpected checkpoint artifact contents.')
        destination = Path('.reader-state/checkpoint.enc')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(bundle.read(files[0]))
        destination.chmod(0o600)
    print('Restored the latest encrypted checkpoint.')


if __name__ == '__main__':
    try:
        restore()
    except Exception:
        raise SystemExit('Checkpoint download failed; refusing to reset reading progress.') from None
