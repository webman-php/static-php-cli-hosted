#!/usr/bin/env python3
"""Apply an isolated profile to the pinned compiler, without editing its outputs."""
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--profile', choices=['stdext-off'], required=True)
args = p.parse_args()
path = Path('src/Package/Extension/swoole.php')
before = "$arg .= ' --enable-swoole-stdext';"
text = path.read_text()
if text.count(before) != 1:
    raise RuntimeError('Unexpected static-php-cli stdext configure layout')
path.write_text(text.replace(before, "$arg .= ' --disable-swoole-stdext';", 1))
