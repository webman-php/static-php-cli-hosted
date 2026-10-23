"""Reject stale profiles or inconsistent raw/ZIP/canonical files before upload."""
import hashlib
import json
import os
from pathlib import Path
import tarfile
import zipfile

from php_binary import current_linux_profile
from php_releases import MANIFEST, build_targets, package_name

root = Path(os.environ.get("RELEASE_DIR", "release"))
releases = json.loads(MANIFEST.read_text())
expected_count = int(os.environ["EXPECTED_PACKAGES"])
targets = build_targets(expected_count == 24)
assert expected_count in (16, 24)
assert len(list(root.glob("*.json"))) == expected_count
for release in releases:
    for target in targets:
        base = package_name(release["branch"], target)
        info = json.loads((root / (base + ".json")).read_text())
        assert info["php_version"] == release["version"], base + ": stale PHP version"
        assert "intl" not in info["extensions"], base + ": obsolete intl profile"
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
                raw = (root / name).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == record["sha256"]
                with zipfile.ZipFile(root / (name + ".zip")) as bundle:
                    assert bundle.namelist() == [name] and bundle.read(name) == raw
        print("Release profile verified:", base, flush=True)
