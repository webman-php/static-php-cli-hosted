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

# SPC provides the removed PHP 8.6 macros to phpize builds after installation.
# Apply the same header before make so bundled PECL sources can use it too.
path = Path('src/Package/Target/php/unix.php')
text = path.read_text()
patches = {
    '''        logger()->info('cleaning up php-src build files');''':
        '''        $this->installRemovedMacroCompatHeader($package->getSourceDir() . '/main/php.h');
        logger()->info('cleaning up php-src build files');''',
    'private function installRemovedMacroCompatHeader(): void':
        'private function installRemovedMacroCompatHeader(?string $header = null): void',
    "$header = BUILD_ROOT_PATH . '/include/php/main/php.h';":
        "$header ??= BUILD_ROOT_PATH . '/include/php/main/php.h';",
}
for before, after in patches.items():
    if text.count(before) != 1:
        raise RuntimeError('Unexpected static-php-cli PHP 8.6 compatibility layout')
    text = text.replace(before, after, 1)
path.write_text(text)
