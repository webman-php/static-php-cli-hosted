#!/usr/bin/env python3
"""Apply an isolated profile to the pinned compiler, without editing its outputs."""
import argparse
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--profile', choices=['stdext-off', 'legacy-exit-hook'], required=True)
args = p.parse_args()
if args.profile == 'legacy-exit-hook':
    patch = Path(__file__).with_name('spc-swoole-jit.patch').resolve()
    subprocess.run(['git', 'apply', '--check', str(patch)], check=True)
    subprocess.run(['git', 'apply', str(patch)], check=True)
else:
    path = Path('src/Package/Extension/swoole.php')
    before = "$arg .= ' --enable-swoole-stdext';"
    text = path.read_text()
    if text.count(before) != 1:
        raise RuntimeError('Unexpected static-php-cli stdext configure layout')
    path.write_text(text.replace(before, "$arg .= ' --disable-swoole-stdext';", 1))
