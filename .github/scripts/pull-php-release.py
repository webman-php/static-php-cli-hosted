"""Send a short-lived GitHub artifact URL over the existing restricted SSH key."""
import json
import os
import subprocess
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from php_releases import MANIFEST


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


artifact_id = os.environ['ARTIFACT_ID']
assert artifact_id.isdecimal()
base = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/artifacts/{artifact_id}"
headers = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'User-Agent': 'workerman-php-publisher', 'Accept': 'application/vnd.github+json'}
with urlopen(Request(base, headers=headers), timeout=30) as response:
    artifact = json.load(response)
assert not artifact['expired'] and artifact['workflow_run']['id'] == int(os.environ['GITHUB_RUN_ID'])
digest = os.environ['ARTIFACT_SHA256'].removeprefix('sha256:')
assert artifact['digest'] == 'sha256:' + digest
try:
    build_opener(NoRedirect).open(Request(base + '/zip', headers=headers), timeout=30)
except HTTPError as error:
    assert error.code == 302, 'GitHub did not supply an artifact download redirect'
    download_url = error.headers['Location']
else:
    raise RuntimeError('Expected a signed GitHub artifact redirect')
manifest = dict(run_id=artifact['workflow_run']['id'], artifact_id=int(artifact_id), sha256=digest,
                size=artifact['size_in_bytes'], expected_packages=int(os.environ['EXPECTED_PACKAGES']),
                versions={release['branch']: release['version'] for release in json.loads(MANIFEST.read_text())},
                download_url=download_url)
# Never print the signed URL or put it into shell arguments/process listings.
subprocess.run(['ssh', '-F', '.github/php-deploy-ssh-config', 'php-origin',
                '/usr/local/libexec/receive-static-php-rsync --pull'],
               input=json.dumps(manifest), text=True, check=True, timeout=45 * 60)
