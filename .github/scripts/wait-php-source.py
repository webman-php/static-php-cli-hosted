"""Do not publish a repack until its complete source build has succeeded."""
import json
import os
import sys
import time
from urllib.request import Request, urlopen

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
        assert run["conclusion"] == "success", "Source build did not succeed"
        break
    if "--check-only" in sys.argv:
        break
    if time.monotonic() >= deadline:
        raise TimeoutError("Source PHP build did not finish")
    time.sleep(30)
