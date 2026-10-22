import json, os, time, urllib.request
from pathlib import Path
root = Path(os.environ.get('RELEASE_DIR', 'release'))
checksums = sorted(root.glob('*.tar.gz.sha256'))
assert checksums, 'No release checksums found'
for checksum in checksums:
    base = checksum.name.removesuffix('.tar.gz.sha256')
    expected = json.loads((root / (base + '.json')).read_text())
    for attempt in range(4):
        try:
            with urllib.request.urlopen('https://download.workerman.net/php/' + checksum.name, timeout=30) as response:
                assert response.read().decode().strip() == checksum.read_text().strip(), base + ': public archive checksum is stale'
            with urllib.request.urlopen('https://download.workerman.net/php/' + base + '.json', timeout=30) as response:
                assert json.load(response) == expected, base + ': public PHP version metadata is stale'
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2)
    print('Public download verified:', base, expected['php_version'])
