"""Reject stale profiles or inconsistent raw/ZIP/canonical files before upload."""
import hashlib
import json
import os
from pathlib import Path
import tarfile
import zipfile

from php_binary import current_jit_profile, current_linux_profile, matches_swoole_profile
from php_releases import MANIFEST, build_targets, package_name, select_releases, validate_manifest

root = Path(os.environ.get("RELEASE_DIR", "release"))
releases = select_releases(validate_manifest(json.loads(MANIFEST.read_text())), os.environ.get("PHP_BRANCH"))
expected_count = int(os.environ["EXPECTED_PACKAGES"])
targets = build_targets(expected_count == len(releases) * len(build_targets()))
assert expected_count == len(releases) * len(targets)
assert len(list(root.glob("*.json"))) == expected_count
for release in releases:
    for target in targets:
        base = package_name(release["branch"], target)
        info = json.loads((root / (base + ".json")).read_text())
        assert info["php_version"] == release["version"], base + ": stale PHP version"
        assert "intl" not in info["extensions"], base + ": obsolete intl profile"
        assert current_jit_profile(info), base + ": incompatible JIT profile"
        assert matches_swoole_profile(info["extensions"], release["version"]), base + ": unexpected Swoole extension"
        if target["os"] != "linux":
            continue
        assert current_linux_profile(info, target), base + ": obsolete UPX profile"
        archive = root / (base + ".tar.gz")
        with tarfile.open(archive) as bundle:
            assert bundle.getnames() == ["php"]
            binary = bundle.extractfile("php").read()
        assert hashlib.sha256(binary).hexdigest() == info["sha256"], base + ": binary digest mismatch"
        assert len(binary) == info["binary_bytes"] <= info["unpacked_bytes"] < 80 * 1024 * 1024
        if info["packing"] == "none":
            assert info["binary_bytes"] == info["unpacked_bytes"] and info["sha256"] == info["unpacked_sha256"]
        if target["arch"] == "x86_64" and not target["suffix"]:
            for name, record in [("php" + release["branch"], info), ("php" + release["branch"] + ".micro.sfx", info["micro"])]:
                binary_path = root / name
                raw = binary_path.read_bytes()
                assert hashlib.sha256(raw).hexdigest() == record["sha256"]
                with zipfile.ZipFile(root / (name + ".zip")) as bundle:
                    assert bundle.namelist() == [name] and bundle.read(name) == raw
                binary_path.chmod(0o755)
        print("Release profile verified:", base, flush=True)
