"""Plan builds and compare official stable PHP releases with published packages."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from php_binary import UPX_VERSION, current_jit_profile, current_linux_profile

BRANCHES = ("8.2", "8.3", "8.4", "8.5")
MANIFEST = Path(__file__).resolve().parents[1] / "php-releases.json"
PUBLIC_URL = "https://download.workerman.net/php/"


def version_number(version, branch):
    if not isinstance(version, str) or not re.fullmatch(re.escape(branch) + r"\.(0|[1-9][0-9]*)", version):
        raise ValueError(f"Invalid stable PHP {branch} version: {version!r}")
    return tuple(map(int, version.split(".")))


def validate_manifest(releases):
    if not isinstance(releases, list) or len(releases) != len(BRANCHES):
        raise ValueError("Manifest must contain PHP 8.2, 8.3, 8.4 and 8.5 exactly once")
    if any(not isinstance(item, dict) for item in releases):
        raise ValueError("Invalid release entry")
    if [item.get("branch") for item in releases] != list(BRANCHES):
        raise ValueError("Unexpected or duplicate PHP branch")
    for item in releases:
        version_number(item.get("version"), item["branch"])
        if not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError(f"Invalid SHA-256 for PHP {item['branch']}")
    return releases


def build_targets(include_glibc=True):
    targets = [
        dict(runner="ubuntu-24.04", os="linux", arch="x86_64", suffix="", triple="x86_64-linux-musl"),
        dict(runner="ubuntu-24.04-arm", os="linux", arch="aarch64", suffix="", triple="aarch64-linux-musl"),
        dict(runner="macos-15-intel", os="macos", arch="x86_64", suffix="", triple="native-macos"),
        dict(runner="macos-15", os="macos", arch="aarch64", suffix="", triple="native-macos"),
    ]
    if include_glibc:
        targets += [
            dict(runner="ubuntu-24.04", os="linux", arch="x86_64", suffix="-glibc", triple="x86_64-linux-gnu.2.17"),
            dict(runner="ubuntu-24.04-arm", os="linux", arch="aarch64", suffix="-glibc", triple="aarch64-linux-gnu.2.17"),
        ]
    return targets


def fetch_json(url, allow_missing=False):
    request = Request(url, headers={"User-Agent": "workerman-static-php-updater", "Cache-Control": "no-cache"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError(f"Oversized JSON response: {url}")
            return json.loads(data)
        except HTTPError as error:
            if allow_missing and error.code == 404:
                return None
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def official_release(branch, payload):
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid PHP official response for {branch}")
    version = payload.get("version")
    version_number(version, branch)
    filename = f"php-{version}.tar.gz"
    sources = [item for item in payload.get("source", []) if item.get("filename") == filename]
    if len(sources) != 1:
        raise ValueError(f"Missing or duplicate official source archive: {filename}")
    checksum = sources[0].get("sha256")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError(f"Invalid official SHA-256 for {filename}")
    return dict(branch=branch, version=version, sha256=checksum)


def package_name(branch, target):
    return f"php-{branch}-{target['os']}-{target['arch']}{target['suffix']}"


def decide_updates(current, latest, published):
    """Published metadata, rather than the last bot commit, determines completion."""
    validate_manifest(current)
    validate_manifest(latest)
    pending = []
    for old, new in zip(current, latest):
        branch = old["branch"]
        expected = version_number(new["version"], branch)
        if expected < version_number(old["version"], branch):
            raise ValueError(f"Official version would downgrade PHP {branch}")
        if new["version"] == old["version"] and new["sha256"] != old["sha256"]:
            raise ValueError(f"Official checksum changed for PHP {new['version']}")
        for target in build_targets():
            name = package_name(branch, target)
            metadata = published[name]
            if metadata is None:  # Missing package: retry an incomplete publication.
                pending.append(name + ": missing")
                continue
            if not isinstance(metadata, dict):
                raise ValueError(f"Invalid published metadata for {name}")
            actual = version_number(metadata.get("php_version"), branch)
            if actual > expected:
                raise ValueError(f"Refusing to downgrade published package {name}")
            if actual < expected:
                pending.append(f"{name}: {metadata['php_version']} -> {new['version']}")
            elif "intl" in metadata.get("extensions", []):
                pending.append(f"{name}: replace the obsolete intl/ICU build")
            elif target["os"] == "linux" and not current_linux_profile(metadata, target):
                pending.append(f"{name}: publish the UPX {UPX_VERSION} profile")
            elif not current_jit_profile(metadata):
                pending.append(f"{name}: publish the compatible JIT profile")
    return pending


def check_updates(current, fetch=fetch_json):
    # Finish and validate all network reads before changing the release manifest.
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda branch: fetch(f"https://www.php.net/releases/index.php?json&version={branch}"), BRANCHES))
        latest = [official_release(branch, payload) for branch, payload in zip(BRANCHES, responses)]
        names = [package_name(branch, target) for branch in BRANCHES for target in build_targets()]
        # A unique query avoids an old CDN response hiding an incomplete upload.
        stamp = time.time_ns()
        metadata = list(pool.map(lambda name: fetch(f"{PUBLIC_URL}{name}.json?check={stamp}", allow_missing=True), names))
    pending = decide_updates(current, latest, dict(zip(names, metadata)))
    return latest, pending


def write_outputs(values):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            for key, value in values.items():
                output.write(f"{key}={value}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "check"))
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    current = validate_manifest(json.loads(args.manifest.read_text()))
    if args.command == "plan":
        targets = build_targets(os.environ.get("INCLUDE_GLIBC", "true") == "true")
        if os.environ.get("VALIDATION_ONLY") == "true":
            current = [item for item in current if item["branch"] == "8.3"]
            targets = targets[:1]
        write_outputs({
            "php": json.dumps(current, separators=(",", ":")),
            "targets": json.dumps(targets, separators=(",", ":")),
            "count": str(len(current) * len(targets)),
        })
        print(f"Validated build plan: {len(current)} PHP versions, {len(current) * len(targets)} packages")
        return

    latest, pending = check_updates(current)
    changed = latest != current
    if changed:
        temporary = args.manifest.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(latest, indent=2) + "\n")
        temporary.replace(args.manifest)
    write_outputs({"needed": str(bool(pending)).lower(), "manifest-changed": str(changed).lower()})
    lines = ["PHP release check", ""]
    lines += [f"PHP {item['branch']}: official stable {item['version']}" for item in latest]
    lines += [""] + (pending if pending else ["All 24 published packages are current. No build or upload needed."])
    summary = "\n".join(lines) + "\n"
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as output:
            output.write(summary)


if __name__ == "__main__":
    main()
