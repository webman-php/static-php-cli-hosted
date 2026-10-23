"""Exercise webman/console build:bin and its HTTP server with the new micro SAPI."""
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen

version = os.environ["EXPECTED_PHP_VERSION"]
branch = ".".join(version.split(".")[:2])
cli = Path("buildroot/bin/php").resolve()
micro = Path("buildroot/bin/micro.sfx").resolve()
results = Path("validation").resolve()
results.mkdir(exist_ok=True)
records = []
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]


def process_memory(pid):
    pending, seen, pss = [pid], set(), 0
    while pending:
        child = pending.pop()
        if child in seen:
            continue
        seen.add(child)
        try:
            pending.extend(map(int, Path(f"/proc/{child}/task/{child}/children").read_text().split()))
            for line in Path(f"/proc/{child}/smaps_rollup").read_text().splitlines():
                if line.startswith("Pss:"):
                    pss += int(line.split()[1])
        except FileNotFoundError:
            continue
    return dict(processes=len(seen), pss_kib=pss)


def run_server(binary, label, fixture):
    with (results / f"{label}.log").open("w") as log:
        process = subprocess.Popen([str(binary), "start"], cwd=fixture, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            response = None
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError(f"{label} exited: {(results / f'{label}.log').read_text()[-6000:]}")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/php-build-check", timeout=1) as stream:
                        response = json.load(stream)
                    break
                except OSError:
                    time.sleep(0.2)
            assert response and response["version"] == version, response
            if label == "lean":
                assert response["intl"] is False, response
            else:
                assert response["intl"] is True, response
            # Measure the complete idle webman process tree using proportional memory.
            time.sleep(1)
            metrics = dict(label=label, binary_bytes=binary.stat().st_size, response=response, **process_memory(process.pid))
            print(json.dumps(metrics), flush=True)
            records.append(metrics)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)


with tempfile.TemporaryDirectory(prefix="webman-bin-check-", dir=os.environ.get("RUNNER_TEMP")) as temporary:
    fixture = Path(temporary) / "app"
    subprocess.run(["composer", "create-project", "workerman/webman", str(fixture), "--no-install", "--no-interaction", "--prefer-dist"], check=True)
    subprocess.run(["composer", "config", "platform.php", version], cwd=fixture, check=True)
    subprocess.run(["composer", "require", "webman/console", "--no-interaction", "--prefer-dist"], cwd=fixture, check=True)
    shutil.copyfile(fixture / "composer.lock", results / "composer.lock")
    (fixture / "config/route.php").write_text('''<?php
use Webman\\Route;
Route::get('/php-build-check', function () {
    return json(['version'=>PHP_VERSION, 'intl'=>extension_loaded('intl'), 'sapi'=>PHP_SAPI]);
});
''')
    # Keep the same one-worker workload for both binaries.
    server = fixture / "config/process.php"
    import re
    content = server.read_text().replace("http://0.0.0.0:8787", f"http://127.0.0.1:{port}")
    assert f"http://127.0.0.1:{port}" in content, "webman fixture's HTTP listener changed"
    server.write_text(re.sub(r"(['\"]count['\"]\s*=>)[^\n]+", r"\1 1,", content))
    build = fixture / "build"
    build.mkdir(exist_ok=True)
    shutil.copyfile(micro, build / f"php{branch}.micro.sfx")
    subprocess.run([str(cli), "-n", "-d", "phar.readonly=0", "webman", "build:bin", branch], cwd=fixture, check=True)
    packaged = build / "webman.bin"
    run_server(packaged, "lean", fixture)
    if os.environ.get("COMPARE_PUBLIC") == "true":
        baseline = build / "baseline.bin"
        with urlopen(f"https://download.workerman.net/php/php{branch}.micro.sfx", timeout=120) as response:
            baseline_micro = response.read(150 * 1024 * 1024)
        baseline.write_bytes(baseline_micro + packaged.read_bytes()[micro.stat().st_size:])
        baseline.chmod(0o755)
        run_server(baseline, "previous-intl", fixture)
        assert packaged.stat().st_size < baseline.stat().st_size, "No actual unpacked size reduction"
    report = dict(php_version=version, micro_bytes=micro.stat().st_size, cli_bytes=cli.stat().st_size, measurements=records)
    (results / "webman-bin-check.json").write_text(json.dumps(report, indent=2) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write("### webman build:bin verification\n\n```json\n" + json.dumps(report, indent=2) + "\n```\n")
