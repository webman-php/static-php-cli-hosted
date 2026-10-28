#!/usr/bin/env python3
"""Validate the exact public CLI/micro downloads, including on real WSL2."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from php_binary import current_jit_profile
from php_releases import MANIFEST, validate_manifest

base = 'https://download.workerman.net/php/'
stamp = time.time_ns()
results = Path('validation/public-jit')
results.mkdir(parents=True, exist_ok=True)


def fetch(name, limit=80 * 1024 * 1024):
    request = Request(base + name + '?jit-verify=' + str(stamp), headers={'Cache-Control': 'no-cache'})
    with urlopen(request, timeout=180) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError('Oversized public download: ' + name)
    return data


with tempfile.TemporaryDirectory(prefix='published-php-jit-') as temporary:
    root = Path(temporary)
    for release in validate_manifest(json.loads(MANIFEST.read_text())):
        branch, version = release['branch'], release['version']
        name = f'php-{branch}-linux-x86_64'
        info = json.loads(fetch(name + '.json', 128 * 1024))
        assert info['php_version'] == version and current_jit_profile(info), name + ': stale JIT profile'
        archive = name + '.tar.gz'
        expected = fetch(archive + '.sha256', 1024).decode().split()
        data = fetch(archive)
        assert expected == [hashlib.sha256(data).hexdigest(), archive], name + ': archive checksum mismatch'
        with tarfile.open(fileobj=io.BytesIO(data)) as bundle:
            assert bundle.getnames() == ['php']
            member = bundle.getmember('php')
            assert member.isfile() and member.size < 80 * 1024 * 1024
            binary = bundle.extractfile(member).read()
        assert hashlib.sha256(binary).hexdigest() == info['sha256'] and len(binary) == info['binary_bytes']
        cli = root / ('php' + branch)
        cli.write_bytes(binary)
        cli.chmod(0o755)
        cli_report = results / (branch + '-cli.json')
        subprocess.run(['python3', str(Path(__file__).with_name('run_checks.py')), '--php', str(cli),
                        '--expect-jit', 'yes', '--output', str(cli_report)], check=True)
        assert json.loads(cli_report.read_text())['tracing']['php'] == version
        if branch == '8.5':
            subprocess.run(['python3', str(Path(__file__).with_name('run_checks.py')), '--php', str(cli),
                            '--fixture', str(Path(__file__).with_name('repro-php85-jit.php')),
                            '--jit-modes', 'tracing', '--expect-jit', 'yes',
                            '--output', str(results / (branch + '-original-repro.json'))], check=True)
        micro_data = fetch('php' + branch + '.micro.sfx')
        assert hashlib.sha256(micro_data).hexdigest() == info['micro']['sha256']
        assert len(micro_data) == info['micro']['binary_bytes']
        micro = root / ('php' + branch + '.micro.sfx')
        micro.write_bytes(micro_data)
        micro_report = results / (branch + '-micro.json')
        subprocess.run(['python3', str(Path(__file__).with_name('run_micro_checks.py')), '--micro', str(micro),
                        '--output', str(micro_report)], check=True)
        assert json.loads(micro_report.read_text())['disable']['php'] == version
        print('PUBLIC DOWNLOAD PASS:', name, version, flush=True)
