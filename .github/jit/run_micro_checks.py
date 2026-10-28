#!/usr/bin/env python3
"""Test a private micro executable using phpmicro's standard embedded INI header."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tempfile

p = argparse.ArgumentParser()
p.add_argument('--micro', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--enable-opcache-jit', action='store_true', help='Experimental: current and historical public micro binaries crash with OPcache enabled')
args = p.parse_args()
reports = {}
with tempfile.TemporaryDirectory(prefix='micro-jit-check-') as tmp:
    executable = Path(tmp) / 'probe'
    original = args.micro.read_bytes()
    body = Path(__file__).with_name('probe.php').read_bytes()
    (Path(tmp) / 'workload.php').write_bytes(Path(__file__).with_name('workload.php').read_bytes())
    modes = ('disable', 'tracing', 'function') if args.enable_opcache_jit else ('disable',)
    for mode in modes:
        enabled = int(args.enable_opcache_jit)
        ini = (f'opcache.enable={enabled}\nopcache.enable_cli={enabled}\nopcache.file_update_protection=0\n'
               'opcache.jit_buffer_size=64M\nopcache.jit_hot_func=2\nopcache.jit_hot_loop=2\n'
               'display_errors=1\nlog_errors=0\nerror_reporting=32767\n'
               f'opcache.jit={mode}\n').encode()
        # Identical to static-php-cli MicroCombineCommand's INI injection format.
        prefix = original + b'\xfd\xf6\x69\xe6' + struct.pack('>I', len(ini)) + ini
        executable.write_bytes(prefix + body)
        executable.chmod(0o755)
        result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=45)
        print(f'--- micro JIT {mode}, exit {result.returncode} ---\n{result.stdout}{result.stderr}', flush=True)
        if result.returncode or 'Warning' in result.stdout or result.stderr:
            raise RuntimeError('micro runtime check failed')
        lines = [s.removeprefix('JIT_REPORT:') for s in result.stdout.splitlines() if s.startswith('JIT_REPORT:')]
        if len(lines) != 1:
            raise RuntimeError('Missing micro report')
        report = json.loads(lines[0])
        expect = mode != 'disable'
        if bool(report['after']['on']) != expect:
            raise RuntimeError(f'Unexpected micro JIT state: {report}')
        if expect and report['machine_code_bytes'] <= 0:
            raise RuntimeError('micro JIT generated no machine code')
        reports[mode] = report
        executable.write_bytes(prefix + b'<?php exit(23);')
        plain = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
        if plain.returncode != 23:
            raise RuntimeError(f'micro exit status changed: {plain.returncode}')
for mode in modes[1:]:
    if reports[mode]['integer_result'] != reports['disable']['integer_result'] or abs(reports[mode]['float_result'] - reports['disable']['float_result']) > 1e-7:
        raise RuntimeError(f'micro JIT {mode} numeric results differ')
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(reports, indent=2) + '\n')
print('PASS: micro production defaults, numeric results, coroutines and exit status')
