"""Check the actual unpacked CLI/micro content before optional UPX packing."""
import os
from pathlib import Path

from php_binary import metadata, verify_glibc, verify_micro, verify_unpacked

expected = os.environ["EXPECTED_PHP_VERSION"]
cli = Path("buildroot/bin/php").resolve()
micro = Path("buildroot/bin/micro.sfx").resolve()
actual = metadata(cli)
assert actual["version"] == expected, actual
assert "intl" not in actual["extensions"] and not actual["icu"], actual
loaded = {name.lower() for name in actual["extensions"]}
for extension in os.environ["EXTENSIONS"].split(","):
    extension = {"opcache": "zend opcache", "mbregex": "mbstring"}.get(extension, extension)
    if extension.startswith("swoole-hook-"):
        extension = "swoole"
    assert extension in loaded, "Missing requested extension: " + extension
for binary in (cli, micro):
    verify_unpacked(binary)
if os.environ.get("TARGET_SUFFIX") == "-glibc":
    verify_glibc(cli)
verify_micro(micro, actual)
print("CLI and micro versions/extensions match; all requested extensions are present")
