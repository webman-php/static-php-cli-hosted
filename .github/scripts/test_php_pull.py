"""Exercise the forced receiver's network and archive trust boundaries."""
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('php_pull_receiver', Path(__file__).with_name('receive-static-php-pull.py'))
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)


class PullBoundaryTests(unittest.TestCase):
    def manifest(self):
        return dict(run_id=1, artifact_id=2, sha256='a' * 64, size=100, expected_packages=24,
                    versions={branch: branch + '.1' for branch in ('8.2', '8.3', '8.4', '8.5')},
                    download_url='https://productionresultssa15.blob.core.windows.net/actions-results/release.zip?sig=test')

    def test_official_signed_blob_and_package_sets(self):
        info = self.manifest()
        receiver.validate_request(info)
        self.assertEqual(tuple(map(len, receiver.expected_files(info))), (24, 120))
        info['expected_packages'] = 16
        self.assertEqual(tuple(map(len, receiver.expected_files(info))), (16, 88))

    def test_reject_ssrf_and_host_spoofing(self):
        for url in ('http://productionresultssa15.blob.core.windows.net/actions-results/a.zip',
                    'https://127.0.0.1/actions-results/a.zip',
                    'https://productionresultssa15.blob.core.windows.net.evil.com/actions-results/a.zip',
                    'https://user@productionresultssa15.blob.core.windows.net/actions-results/a.zip',
                    'https://productionresultssa15.blob.core.windows.net:444/actions-results/a.zip',
                    'https://productionresultssa15.blob.core.windows.net/private/a.zip'):
            with self.subTest(url=url), self.assertRaises(AssertionError):
                info = self.manifest()
                info['download_url'] = url
                receiver.validate_request(info)

    def test_no_extra_files_traversal_or_symlinks(self):
        for name, symlink in (('../php', False), ('php', True), ('unexpected', False)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with zipfile.ZipFile(root / 'bundle.zip', 'w') as bundle:
                    entry = zipfile.ZipInfo(name)
                    if symlink:
                        entry.create_system = 3
                        entry.external_attr = 0o120777 << 16
                    bundle.writestr(entry, 'target')
                with self.assertRaises(AssertionError):
                    receiver.unpack(root / 'bundle.zip', root, {'php'})

    def test_parallel_ranges_reassemble_without_holes(self):
        content = bytes(range(256)) * 65537

        class Opener:
            def open(self, request, timeout):
                start, end = map(int, request.get_header('Range').removeprefix('bytes=').split('-'))
                response = io.BytesIO(content[start:end + 1])
                response.status = 206
                response.headers = {'Content-Range': f'bytes {start}-{end}/{len(content)}'}
                return response

        with tempfile.TemporaryDirectory() as temporary, patch.object(receiver, 'build_opener', return_value=Opener()):
            archive = Path(temporary) / 'release.zip'
            receiver.download({'size': len(content), 'download_url': self.manifest()['download_url']}, archive)
            self.assertEqual(archive.read_bytes(), content)

    def test_server_ignoring_ranges_cannot_publish(self):
        response = io.BytesIO(b'wrong')
        response.status = 200
        with tempfile.TemporaryDirectory() as temporary, patch.object(receiver, 'build_opener') as opener:
            opener.return_value.open.return_value = response
            with self.assertRaisesRegex(RuntimeError, 'range transfer failed'):
                receiver.download({'size': 5, 'download_url': self.manifest()['download_url']}, Path(temporary) / 'release.zip')


if __name__ == '__main__':
    unittest.main()
