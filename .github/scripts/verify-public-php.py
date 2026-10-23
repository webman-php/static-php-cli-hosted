import hashlib, json, os, re, time, urllib.request
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

# build:bin downloads the raw micro or ZIP rather than the canonical CLI tar.
for binary in sorted(root.iterdir()):
    if not re.fullmatch(r"php8\.[2-5](?:\.micro\.sfx)?(?:\.zip)?", binary.name):
        continue
    expected = hashlib.sha256(binary.read_bytes()).hexdigest()
    for attempt in range(4):
        try:
            digest = hashlib.sha256()
            request = urllib.request.Request('https://download.workerman.net/php/' + binary.name + '?verify=' + str(time.time_ns()), headers={'Cache-Control': 'no-cache'})
            with urllib.request.urlopen(request, timeout=120) as response:
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    digest.update(block)
            assert digest.hexdigest() == expected, binary.name + ': stale public raw/ZIP file'
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2)
    print('Public raw/ZIP verified:', binary.name, flush=True)
