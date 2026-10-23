#!/usr/bin/python3
"""Root-owned forced SSH receiver: validate and publish files, never execute them."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
import zipfile

PUBLIC = Path('/home/www/download.workerman.net/public/php')
BACKUPS = Path('/home/www/php-release-backups')
LIMIT = 2 * 1024 ** 3
REQUIRED = {'curl', 'event', 'fileinfo', 'mbstring', 'openssl', 'pcntl', 'pdo_mysql', 'posix', 'sockets', 'sqlite3', 'zlib'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def validate_request(info):
    assert set(info) == {'run_id', 'artifact_id', 'sha256', 'size', 'expected_packages', 'versions', 'download_url'}
    assert all(type(info[key]) is int and 0 < info[key] < 10 ** 14 for key in ('run_id', 'artifact_id'))
    assert re.fullmatch('[a-f0-9]{64}', info['sha256'])
    assert type(info['size']) is int and 0 < info['size'] <= LIMIT
    assert info['expected_packages'] in (16, 24)
    assert set(info['versions']) == {'8.2', '8.3', '8.4', '8.5'}
    for branch, version in info['versions'].items():
        assert re.fullmatch(re.escape(branch) + r'\.\d+', version)
    url = urlsplit(info['download_url'])
    assert url.scheme == 'https' and not url.username and not url.password and url.port in (None, 443)
    assert re.fullmatch(r'productionresults[a-z0-9]+\.blob\.core\.windows\.net', url.hostname or '')
    assert url.path.startswith('/actions-results/') and url.path.endswith('.zip') and not url.fragment


def expected_files(info):
    targets = ['linux-x86_64', 'linux-aarch64', 'macos-x86_64', 'macos-aarch64']
    if info['expected_packages'] == 24:
        targets += ['linux-x86_64-glibc', 'linux-aarch64-glibc']
    bases = [f'php-{branch}-{target}' for branch in info['versions'] for target in targets]
    files = {base + suffix for base in bases for suffix in ('.tar.gz', '.tar.gz.sha256', '.json', '.extensions.txt')}
    files |= {f'php-{branch}-mac-{arch}.tar.gz' for branch in info['versions'] for arch in ('x86_64', 'aarch64')}
    files |= {f'php{branch}{suffix}' for branch in info['versions'] for suffix in ('', '.zip', '.micro.sfx', '.micro.sfx.zip')}
    return bases, files


def unpack(archive, destination, expected):
    with zipfile.ZipFile(archive) as bundle:
        records = bundle.infolist()
        assert len(records) == len(expected) and {item.filename for item in records} == expected, 'Unexpected artifact files'
        assert sum(item.file_size for item in records) <= LIMIT
        for item in records:
            assert '/' not in item.filename and '\\' not in item.filename
            assert not item.is_dir() and not stat.S_ISLNK(item.external_attr >> 16)
            assert 0 < item.file_size < 150 * 1024 ** 2
            with bundle.open(item) as source, (destination / item.filename).open('wb') as target:
                shutil.copyfileobj(source, target)


def verify_files(root, info, bases):
    for base in bases:
        meta = json.loads((root / (base + '.json')).read_text())
        branch = base.split('-')[1]
        assert meta['php_version'] == info['versions'][branch], base + ': PHP version mismatch'
        extensions = {value.lower() for value in meta['extensions']}
        assert 'intl' not in extensions and REQUIRED <= extensions, base + ': invalid extensions'
        listed = (root / (base + '.extensions.txt')).read_text().lower().splitlines()
        assert 'intl' not in listed and REQUIRED <= set(listed)
        archive = root / (base + '.tar.gz')
        assert (root / (base + '.tar.gz.sha256')).read_text().split() == [digest(archive), archive.name]
        with tarfile.open(archive) as bundle:
            members = bundle.getmembers()
            assert len(members) == 1 and members[0].name == 'php' and members[0].isfile()
            assert 0 < members[0].size < 80 * 1024 ** 2
            binary = bundle.extractfile(members[0]).read()
        if '-linux-' in base:
            assert meta['packing'] == 'upx' or (base.endswith('aarch64-glibc') and meta['packing'] == 'none' and meta.get('packing_reason') == 'upx-5.2.1-arm64-hatch')
            assert hashlib.sha256(binary).hexdigest() == meta['sha256'] and len(binary) == meta['binary_bytes']
            assert len(binary) <= meta['unpacked_bytes'] < 80 * 1024 ** 2
            if meta['packing'] == 'none':
                assert meta['sha256'] == meta['unpacked_sha256'] and len(binary) == meta['unpacked_bytes']
            if base.endswith('linux-x86_64'):
                for name, record in [(f'php{branch}', meta), (f'php{branch}.micro.sfx', meta['micro'])]:
                    raw = (root / name).read_bytes()
                    assert digest(root / name) == record['sha256'] and len(raw) == record['binary_bytes']
                    with zipfile.ZipFile(root / (name + '.zip')) as zipped:
                        assert zipped.namelist() == [name] and zipped.read(name) == raw
        else:
            alias = root / (base.replace('-macos-', '-mac-') + '.tar.gz')
            assert digest(alias) == digest(archive)
        current = PUBLIC / (base + '.json')
        if current.exists():
            previous = json.loads(current.read_text())['php_version']
            assert tuple(map(int, previous.split('.'))) <= tuple(map(int, meta['php_version'].split('.'))), 'Refusing PHP downgrade'


def main():
    payload = sys.stdin.read(65537)
    assert len(payload) <= 65536
    info = json.loads(payload)
    validate_request(info)
    bases, files = expected_files(info)
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    with (BACKUPS / '.publish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert shutil.disk_usage(BACKUPS).free > info['size'] * 3, 'Insufficient staging space'
        with tempfile.TemporaryDirectory(prefix='.incoming-', dir=BACKUPS) as temporary:
            stage = Path(temporary)
            archive = stage / 'release.zip'
            # Suppress URL-containing exception messages: the SAS credential stays private.
            try:
                with build_opener(NoRedirect).open(info['download_url'], timeout=90) as source, archive.open('wb') as target:
                    downloaded = 0
                    next_progress = 100 * 1024 ** 2
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        assert downloaded <= LIMIT
                        target.write(chunk)
                        if downloaded >= next_progress:
                            print(f'HTTPS download: {downloaded // (1024 ** 2)} MiB', flush=True)
                            next_progress += 100 * 1024 ** 2
            except Exception:
                raise RuntimeError('GitHub artifact HTTPS transfer failed') from None
            assert archive.stat().st_size == info['size'] and digest(archive) == info['sha256'], 'Artifact checksum mismatch'
            unpack(archive, stage, files)
            verify_files(stage, info, bases)
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            backup = BACKUPS / (stamp + '-' + str(os.getpid()))
            subprocess.run(['cp', '-al', str(PUBLIC), str(backup)], check=True)
            # Metadata last: weekly checks cannot declare completion before binaries land.
            for name in sorted(files, key=lambda value: (value.endswith('.json'), value.endswith('.sha256'), value)):
                path = stage / name
                path.chmod(0o755 if re.fullmatch(r'php8\.[2-5](\.micro\.sfx)?', name) else 0o644)
                os.replace(path, PUBLIC / name)
            ledger = {key: value for key, value in info.items() if key != 'download_url'}
            ledger['backup'] = str(backup)
            (BACKUPS / ('published-' + str(info['run_id']) + '.json')).write_text(json.dumps(ledger, indent=2) + '\n')
            print(f'Published {len(bases)} PHP packages / {len(files)} files; backup: {backup}', flush=True)


if __name__ == '__main__':
    main()
