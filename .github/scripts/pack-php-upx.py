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


def verify_candidate(candidate, is_micro, expected, arch):
    if is_micro:
        verify_micro(candidate, expected)
    else:
        # Repeat native ARM starts to catch address-layout dependent failures.
        for _ in range(20 if arch == "aarch64" else 1):
            assert metadata(candidate) == expected, "UPX changed the CLI version/extensions"


def roundtrip(upx, candidate, original_digest):
    restored = candidate.with_name(candidate.name + ".roundtrip")
    shutil.copyfile(candidate, restored)
    subprocess.run([str(upx), "-d", str(restored)], check=True)
    assert hashlib.sha256(restored.read_bytes()).hexdigest() == original_digest, "UPX did not restore the original bytes"
    restored.unlink()


def restore_reused(candidate, binary, is_micro, original_digest, expected, arch, upx):
    root = Path("reused")
    base = os.environ.get("PACKAGE_BASE", "")
    sidecar = root / (base + ".json")
    if not sidecar.exists():
        return None
    info = json.loads(sidecar.read_text())
    assert info["packing"] == "upx" and info["upx_version"] == UPX_VERSION
    assert info["php_version"] == expected["version"] and info["extensions"] == expected["extensions"]
    record = info["micro"] if is_micro else info
    assert record["unpacked_sha256"] == original_digest, "Reused artifact came from a different plain build"
    if is_micro:
        branch = ".".join(expected["version"].split(".")[:2])
        candidate.write_bytes((root / f"php{branch}.micro.sfx").read_bytes())
    else:
        with tarfile.open(root / (base + ".tar.gz")) as bundle:
            assert bundle.getnames() == ["php"]
            candidate.write_bytes(bundle.extractfile("php").read())
    candidate.chmod(0o755)
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == record["sha256"]
    assert candidate.stat().st_size == record["binary_bytes"] < record["unpacked_bytes"]
    if not is_micro:
        roundtrip(upx, candidate, original_digest)
    verify_candidate(candidate, is_micro, expected, arch)
    print("Reused and reverified UPX artifact:", base, binary.name, flush=True)
    result = {key: record[key] for key in ("unpacked_bytes", "unpacked_sha256", "binary_bytes", "sha256")}
    result["upx_options"] = record.get("upx_options", ["--best"])
    return result


def save_failure(candidate, index, error):
    output = Path("validation")
    output.mkdir(exist_ok=True)
    prefix = output / f"failed-upx-{candidate.name}-{index}"
    if candidate.exists():
        shutil.copyfile(candidate, prefix)
    prefix.with_suffix(".json").write_text(json.dumps({"error": str(error)}, indent=2))
    if shutil.which("gdb"):
        with prefix.with_suffix(".gdb.log").open("w") as log:
            try:
                subprocess.run(["gdb", "--batch", "-ex", "run", "-ex", "x/12i $pc-16", "-ex", "bt", "--args", str(candidate), "-n", "-r", "echo PHP_VERSION;"], stdout=log, stderr=subprocess.STDOUT, timeout=30)
            except subprocess.TimeoutExpired:
                pass


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
            original = binary.read_bytes()
            original_digest = hashlib.sha256(original).hexdigest()
            reused = restore_reused(candidate, binary, binary == micro, original_digest, expected, arch, upx)
            options = ["--best"]
            if reused is None:
                variants = [["--best", "--no-filter"], ["--best", "--lzma"]] if arch == "aarch64" and os.environ.get("TARGET_SUFFIX") == "-glibc" else [["--best"]]
                for index, options in enumerate(variants):
                    candidate.write_bytes(original)
                    candidate.chmod(0o755)
                    try:
                        subprocess.run([str(upx), *options, str(candidate)], check=True)
                        subprocess.run([str(upx), "-t", str(candidate)], check=True)
                        roundtrip(upx, candidate, original_digest)
                        if binary == micro:
                            trim_micro(candidate)
                        verify_candidate(candidate, binary == micro, expected, arch)
                        break
                    except (subprocess.CalledProcessError, AssertionError) as error:
                        save_failure(candidate, index, error)
                        print("Rejected UPX settings:", options, str(error), flush=True)
                        if index == len(variants) - 1:
                            raise
            assert candidate.stat().st_size < len(original), "UPX did not reduce the file size"
            records[binary.name] = {
                "unpacked_bytes": len(original),
                "unpacked_sha256": original_digest,
                "binary_bytes": candidate.stat().st_size,
                "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                "upx_options": options if reused is None else reused["upx_options"],
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
