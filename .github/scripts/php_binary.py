"""Shared checks for plain builds and Linux UPX publication."""
import json
from pathlib import Path
import re
import subprocess
import tempfile

UPX_VERSION = "5.2.1"
PROBE = '<?php echo json_encode(["version"=>PHP_VERSION,"extensions"=>get_loaded_extensions(),"icu"=>defined("INTL_ICU_VERSION")]);'


def metadata(cli):
    return json.loads(subprocess.check_output([str(cli), "-n", "-r", PROBE.removeprefix("<?php ")], text=True, timeout=30))


def verify_unpacked(binary):
    data = binary.read_bytes()
    assert len(data) < 80 * 1024 * 1024, f"{binary.name}: exceeds the 80 MiB unpacked size limit"
    start = 0
    while True:
        offset = data.find(b"CmnD", start)
        if offset < 0:
            break
        assert offset < 12 or data[offset - 10:offset - 8] != b"\xda\x27", f"{binary.name}: ICU data is still linked"
        start = offset + 4
    if data[:4] == b"\x7fELF":
        sections = subprocess.check_output(["readelf", "-SW", str(binary)], text=True)
        assert ".text " in sections and ".rodata " in sections, "Expected an unpacked ELF binary"
        assert ".debug_info" not in sections, "Debug data was not stripped"
    print(f"Unpacked {binary.name}: {len(data)} bytes; no bundled ICU or executable packing", flush=True)


def verify_glibc(binary):
    symbols = subprocess.check_output(["readelf", "--version-info", str(binary)], text=True)
    versions = [tuple(map(int, x.split("."))) for x in re.findall(r"GLIBC_([0-9.]+)", symbols)]
    assert "GLIBC_PRIVATE" not in symbols, "Private glibc ABI dependency"
    assert versions and max(versions) <= (2, 17), f"glibc requirement exceeds 2.17: {max(versions) if versions else 'none'}"
    print("Unpacked binary: glibc 2.17 symbol baseline verified", flush=True)


def verify_micro(micro, expected):
    with tempfile.TemporaryDirectory() as temporary:
        packaged = Path(temporary) / "micro-check"
        packaged.write_bytes(micro.read_bytes() + PROBE.encode())
        packaged.chmod(0o755)
        actual = json.loads(subprocess.check_output([str(packaged)], text=True, timeout=30))
        assert actual == expected, (actual, expected)


def verify_runtime(cli, version):
    actual = metadata(cli)
    assert actual["version"] == version, actual
    assert "intl" not in actual["extensions"] and not actual["icu"], actual
    subprocess.run([str(cli), "-n", "-r", '''
foreach (["pcntl", "posix", "sockets", "openssl", "curl", "mbstring", "event", "redis", "apcu", "sodium", "gd", "imagick"] as $ext) {
    if (!extension_loaded($ext)) { throw new RuntimeException("Missing extension: " . $ext); }
}
$server = stream_socket_server("tcp://127.0.0.1:0", $errno, $error);
if (!$server) { throw new RuntimeException($error); }
$client = stream_socket_client("tcp://" . stream_socket_get_name($server, false));
$peer = stream_socket_accept($server, 5);
fwrite($client, "workerman\\n");
if (fgets($peer) !== "workerman\\n") { exit(1); }
echo "Socket smoke test passed\\n";
'''], check=True, timeout=30)
    return actual
