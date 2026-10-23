"""Check the actual unpacked CLI/micro content, never the archive size."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

expected = os.environ["EXPECTED_PHP_VERSION"]
cli = Path("buildroot/bin/php").resolve()
micro = Path("buildroot/bin/micro.sfx").resolve()
probe = '''<?php echo json_encode(["version"=>PHP_VERSION,"extensions"=>get_loaded_extensions(),"icu"=>defined("INTL_ICU_VERSION")]);'''
metadata = json.loads(subprocess.check_output([str(cli), "-n", "-r", probe.removeprefix("<?php ")], text=True))
assert metadata["version"] == expected, metadata
assert "intl" not in metadata["extensions"] and not metadata["icu"], metadata
loaded = {name.lower() for name in metadata["extensions"]}
for extension in os.environ["EXTENSIONS"].split(","):
    extension = {"opcache": "zend opcache", "mbregex": "mbstring"}.get(extension, extension)
    if extension.startswith("swoole-hook-"):
        extension = "swoole"
    assert extension in loaded, "Missing requested extension: " + extension

for binary in (cli, micro):
    data = binary.read_bytes()
    assert len(data) < 80 * 1024 * 1024, f"{binary.name}: exceeds the 80 MiB unpacked size limit"
    # ICU's common-data header has a magic signature plus the CmnD data format.
    start = 0
    while True:
        offset = data.find(b"CmnD", start)
        if offset < 0:
            break
        header = offset - 12
        assert header < 0 or data[header + 2:header + 4] != b"\xda\x27", f"{binary.name}: ICU data is still linked"
        start = offset + 4
    if data[:4] == b"\x7fELF":
        sections = subprocess.check_output(["readelf", "-SW", str(binary)], text=True)
        assert ".text " in sections and ".rodata " in sections, "Packed ELF binary is forbidden"
        assert ".debug_info" not in sections, "Debug data was not stripped"
    print(f"Unpacked {binary.name}: {len(data)} bytes; no intl/ICU, no executable packing")

with tempfile.TemporaryDirectory() as temporary:
    packaged = Path(temporary) / "micro-check"
    packaged.write_bytes(micro.read_bytes() + probe.encode())
    packaged.chmod(0o755)
    actual = json.loads(subprocess.check_output([str(packaged)], text=True, timeout=30))
    assert actual == metadata, (actual, metadata)
print("CLI and micro versions/extensions match; all requested extensions are present")
