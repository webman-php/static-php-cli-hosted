"""Create canonical download files after native runtime checks."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

from php_binary import UPX_VERSION, current_linux_profile, verify_micro, verify_runtime

version = os.environ["EXPECTED_PHP_VERSION"]
branch = ".".join(version.split(".")[:2])
target_os, arch, suffix = (os.environ.get(key, "") for key in ("TARGET_OS", "TARGET_ARCH", "TARGET_SUFFIX"))
assert target_os in ("linux", "macos") and arch in ("x86_64", "aarch64") and suffix in ("", "-glibc")
assert suffix != "-glibc" or target_os == "linux"
base = f"php-{branch}-{target_os}-{arch}{suffix}"
cli = Path("buildroot/bin/php").resolve()
micro = Path("buildroot/bin/micro.sfx").resolve()
actual = verify_runtime(cli, version)
output = Path("dist")
output.mkdir(exist_ok=True)
info = dict(php_version=version, extensions=actual["extensions"], packing="none", binary_bytes=cli.stat().st_size)
if target_os == "linux":
    report = json.loads(Path("validation/upx-pack.json").read_text())
    assert current_linux_profile(report, dict(arch=arch, suffix=suffix))
    assert report["binaries"]["php"]["sha256"] == hashlib.sha256(cli.read_bytes()).hexdigest()
    info.update(packing=report["packing"], upx_version=UPX_VERSION, **report["binaries"]["php"])
    if "packing_reason" in report:
        info["packing_reason"] = report["packing_reason"]
    if "micro.sfx" in report["binaries"]:
        info["micro"] = report["binaries"]["micro.sfx"]
(output / (base + ".json")).write_text(json.dumps(info, indent=2) + "\n")
(output / (base + ".extensions.txt")).write_bytes(subprocess.check_output([str(cli), "-n", "-m"]))
archive = output / (base + ".tar.gz")
with tarfile.open(archive, "w:gz", compresslevel=6) as bundle:
    bundle.add(cli, arcname="php")
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(output / (archive.name + ".sha256")).write_text(digest + "  " + archive.name + "\n")
if target_os == "macos":
    shutil.copyfile(archive, output / f"php-{branch}-mac-{arch}.tar.gz")
if target_os == "linux" and arch == "x86_64" and not suffix:
    verify_micro(micro, actual)
    for binary, name in [(cli, f"php{branch}"), (micro, f"php{branch}.micro.sfx")]:
        shutil.copyfile(binary, output / name)
        with zipfile.ZipFile(output / (name + ".zip"), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            bundle.write(binary, arcname=name)
print("Packaged", base, json.dumps(info), flush=True)
