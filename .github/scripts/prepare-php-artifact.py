"""Restore only validated files from an existing PHP build artifact."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile

from php_binary import metadata

base = os.environ["PACKAGE_BASE"]
source = Path("source")
archive = source / (base + ".tar.gz")
expected = json.loads((source / (base + ".json")).read_text())
assert expected["php_version"] == os.environ["EXPECTED_PHP_VERSION"]
assert "intl" not in expected["extensions"] and expected.get("packing", "none") == "none"
assert (source / (base + ".tar.gz.sha256")).read_text().split() == [hashlib.sha256(archive.read_bytes()).hexdigest(), archive.name]
directory = Path("buildroot/bin")
directory.mkdir(parents=True, exist_ok=True)
cli = directory / "php"
with tarfile.open(archive) as bundle:
    assert bundle.getnames() == ["php"]
    member = bundle.getmember("php")
    assert member.isfile() and member.size < 80 * 1024 * 1024
    cli.write_bytes(bundle.extractfile(member).read())
cli.chmod(0o755)
actual = metadata(cli.resolve())
assert actual["version"] == expected["php_version"] and actual["extensions"] == expected["extensions"]
branch = ".".join(expected["php_version"].split(".")[:2])
if base == f"php-{branch}-linux-x86_64":
    assert (source / f"php{branch}").read_bytes() == cli.read_bytes(), "Raw CLI and canonical archive disagree"
    shutil.copyfile(source / f"php{branch}.micro.sfx", directory / "micro.sfx")
    (directory / "micro.sfx").chmod(0o755)
print("Restored verified source artifact:", base, expected["php_version"])
