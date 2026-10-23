"""Pack native Linux CLI/micro copies, checking both sides of the conversion."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import tarfile
import tempfile
from urllib.request import urlopen

from php_binary import UPX_VERSION, metadata, verify_glibc, verify_micro, verify_runtime, verify_unpacked

ASSETS = {
    "x86_64": ("amd64", "402162aad30af47e60dbd767fb2e64ca394ace9727ba1f40283641f1d1b91657"),
    "aarch64": ("arm64", "a72d112c5970a904a31da0b9c84f919bc16b9a311787c12245508544a78c7d36"),
}


def trim_micro(path):
    # Match SPC's patchMicroUpxPackedBinary: second LOAD/GNU_STACK p_filesz.
    data = path.read_bytes()
    assert data[:6] == b"\x7fELF\x02\x01", "Expected little-endian ELF64"
    offset = struct.unpack_from("<Q", data, 32)[0]
    width, count = struct.unpack_from("<HH", data, 54)
    assert width == 56 and 1 <= count <= 128 and offset + width * count <= len(data)
    sizes = []
    for index in range(count):
        entry = offset + index * width
        if struct.unpack_from("<I", data, entry)[0] in (1, 0x6474e551):
            sizes.append(struct.unpack_from("<Q", data, entry + 32)[0])
    assert len(sizes) >= 2 and 0 < sizes[1] <= len(data), sizes
    path.write_bytes(data[:sizes[1]])


def main():
    assert platform.system() == "Linux"
    arch = platform.machine()
    assert arch == os.environ["TARGET_ARCH"], (arch, os.environ["TARGET_ARCH"])
    cli = Path("buildroot/bin/php").resolve()
    micro = Path("buildroot/bin/micro.sfx").resolve()
    expected = verify_runtime(cli, os.environ["EXPECTED_PHP_VERSION"])
    binaries = [cli] + ([micro] if micro.exists() else [])
    for binary in binaries:
        verify_unpacked(binary)
    if os.environ.get("TARGET_SUFFIX") == "-glibc":
        verify_glibc(cli)
    if micro.exists():
        verify_micro(micro, expected)
    records = {}
    with tempfile.TemporaryDirectory(prefix="php-upx-") as temporary:
        temporary = Path(temporary)
        asset_arch, digest = ASSETS[arch]
        asset = f"upx-{UPX_VERSION}-{asset_arch}_linux.tar.xz"
        archive = temporary / asset
        with urlopen(f"https://github.com/upx/upx/releases/download/v{UPX_VERSION}/{asset}", timeout=120) as response:
            archive.write_bytes(response.read(10 * 1024 * 1024))
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest, "UPX asset checksum mismatch"
        upx = temporary / "upx"
        with tarfile.open(archive) as bundle:
            members = [m for m in bundle if m.isfile() and m.name.endswith("/upx")]
            assert len(members) == 1
            upx.write_bytes(bundle.extractfile(members[0]).read())
        upx.chmod(0o755)
        for binary in binaries:
            candidate = temporary / binary.name
            shutil.copyfile(binary, candidate)
            candidate.chmod(0o755)
            original = binary.read_bytes()
            subprocess.run([str(upx), "--best", str(candidate)], check=True)
            subprocess.run([str(upx), "-t", str(candidate)], check=True)
            if binary == micro:
                trim_micro(candidate)
                verify_micro(candidate, expected)
            else:
                assert metadata(candidate) == expected, "UPX changed the CLI version/extensions"
            assert candidate.stat().st_size < len(original), "UPX did not reduce the file size"
            records[binary.name] = {
                "unpacked_bytes": len(original),
                "unpacked_sha256": hashlib.sha256(original).hexdigest(),
                "binary_bytes": candidate.stat().st_size,
                "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            }
            shutil.copyfile(candidate, binary)
            binary.chmod(0o755)
    verify_runtime(cli, os.environ["EXPECTED_PHP_VERSION"])
    if micro.exists():
        verify_micro(micro, expected)
    result = dict(packing="upx", upx_version=UPX_VERSION, binaries=records)
    output = Path("validation")
    output.mkdir(exist_ok=True)
    (output / "upx-pack.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write("### Verified Linux UPX conversion\n\n```json\n" + json.dumps(result, indent=2) + "\n```\n")


if __name__ == "__main__":
    main()
