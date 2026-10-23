"""Require every source build to pass and its original publisher to stop."""
import json
import os
import sys
import time
from urllib.request import Request, urlopen
from php_releases import MANIFEST, build_targets

run_id = os.environ["SOURCE_RUN_ID"]
assert run_id.isdecimal()
url = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}"
deadline = time.monotonic() + 3 * 60 * 60
while True:
    request = Request(url, headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "User-Agent": "workerman-upx-repack"})
    with urlopen(request, timeout=30) as response:
        run = json.load(response)
    assert run["path"] == ".github/workflows/build-php-unix.yml", "Source must be the PHP Unix build workflow"
    print("Source build:", run_id, run["head_sha"], run["status"], run["conclusion"], flush=True)
    if run["status"] == "completed":
        request = Request(url + '/jobs?per_page=100', headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "User-Agent": "workerman-upx-repack"})
        with urlopen(request, timeout=30) as response:
            jobs = json.load(response)["jobs"]
        expected = {f"PHP {release['version']} / {target['os']}-{target['arch']}{target['suffix']}" for release in json.loads(MANIFEST.read_text()) for target in build_targets()}
        passed = {job['name'] for job in jobs if job['conclusion'] == 'success'}
        assert expected <= passed, "Source PHP build jobs did not all succeed: " + str(sorted(expected - passed))
        print('All 24 source builds passed; original publisher stopped.', flush=True)
        break
    if "--check-only" in sys.argv:
        break
    if time.monotonic() >= deadline:
        raise TimeoutError("Source PHP build did not finish")
    time.sleep(30)
