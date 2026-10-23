import copy
import json
import os
from pathlib import Path
import runpy
import struct
import tempfile
import unittest
from unittest.mock import patch

import php_releases as releases
from php_binary import UPX_ARM_GLIBC_FALLBACK


class ReleaseChecksTest(unittest.TestCase):
    def setUp(self):
        self.current = json.loads(releases.MANIFEST.read_text())
        self.published = {
            releases.package_name(item["branch"], target): {"php_version": item["version"], **({"packing": "upx", "upx_version": releases.UPX_VERSION} if target["os"] == "linux" else {})}
            for item in self.current for target in releases.build_targets()
        }

    def test_current_downloads_do_not_build(self):
        self.assertEqual([], releases.decide_updates(self.current, self.current, self.published))

    def test_new_patch_builds(self):
        latest = copy.deepcopy(self.current)
        parts = latest[-1]["version"].split(".")
        latest[-1]["version"] = ".".join(parts[:2] + [str(int(parts[-1]) + 1)])
        latest[-1]["sha256"] = "a" * 64
        pending = releases.decide_updates(self.current, latest, self.published)
        self.assertEqual(6, len(pending))
        self.assertTrue(all("php-8.5-" in name for name in pending))

    def test_unpublished_commit_retries(self):
        published = copy.deepcopy(self.published)
        published["php-8.5-linux-x86_64-glibc"]["php_version"] = "8.5.0"
        self.assertEqual(1, len(releases.decide_updates(self.current, self.current, published)))

    def test_missing_package_retries(self):
        self.published["php-8.4-macos-aarch64"] = None
        self.assertEqual(["php-8.4-macos-aarch64: missing"], releases.decide_updates(self.current, self.current, self.published))

    def test_same_version_with_obsolete_intl_build_retries(self):
        self.published["php-8.3-linux-x86_64"]["extensions"] = ["intl", "curl"]
        self.assertEqual(["php-8.3-linux-x86_64: replace the obsolete intl/ICU build"], releases.decide_updates(self.current, self.current, self.published))

    def test_same_version_with_missing_upx_profile_retries(self):
        self.published["php-8.3-linux-x86_64"].pop("packing")
        self.assertEqual(["php-8.3-linux-x86_64: publish the UPX " + releases.UPX_VERSION + " profile"], releases.decide_updates(self.current, self.current, self.published))

    def test_macos_does_not_need_upx_metadata(self):
        self.assertNotIn("packing", self.published["php-8.3-macos-aarch64"])
        self.assertEqual([], releases.decide_updates(self.current, self.current, self.published))

    def test_native_verified_arm_glibc_hatch_fallback_does_not_rebuild_weekly(self):
        info = self.published["php-8.4-linux-aarch64-glibc"]
        info.update(packing="none", packing_reason=UPX_ARM_GLIBC_FALLBACK)
        self.assertEqual([], releases.decide_updates(self.current, self.current, self.published))
        self.published["php-8.4-linux-x86_64"].update(info)
        pending = releases.decide_updates(self.current, self.current, self.published)
        self.assertEqual(1, len(pending))
        self.assertTrue(pending[0].startswith("php-8.4-linux-x86_64:"))

    def test_arm_hatch_guard_matches_the_native_php84_failure(self):
        check = runpy.run_path(str(Path(__file__).with_name("pack-php-upx.py")))["lacks_arm_hatch"]
        header = bytearray(120)
        header[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", header, 18, 183)
        struct.pack_into("<Q", header, 32, 64)
        struct.pack_into("<HH", header, 54, 56, 1)
        # Actual executable PT_LOAD values from the failing PHP 8.4.27 build.
        struct.pack_into("<IIQQQQQQ", header, 64, 1, 5, 29015936, 29081472, 29081472, 36585600, 36585600, 65536)
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "php"
            binary.write_bytes(header)
            with patch("os.sysconf", return_value=4096):
                self.assertTrue(check(binary))
                # Eight available bytes are sufficient for the two ARM instructions.
                struct.pack_into("<Q", header, 64 + 40, 36585600 - 8)
                binary.write_bytes(header)
                self.assertFalse(check(binary))

    def test_manifest_and_public_downloads_never_downgrade(self):
        latest = copy.deepcopy(self.current)
        latest[0]["version"] = "8.2.0"
        with self.assertRaisesRegex(ValueError, "downgrade"):
            releases.decide_updates(self.current, latest, self.published)
        self.published["php-8.2-linux-x86_64"]["php_version"] = "8.2.999"
        with self.assertRaisesRegex(ValueError, "downgrade"):
            releases.decide_updates(self.current, self.current, self.published)

    def test_changed_checksum_for_same_version_is_rejected(self):
        latest = copy.deepcopy(self.current)
        latest[0]["sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "checksum changed"):
            releases.decide_updates(self.current, latest, self.published)

    def test_release_api_accepts_only_correct_stable_archive(self):
        payload = {"version": "8.5.99", "source": [{"filename": "php-8.5.99.tar.gz", "sha256": "b" * 64}]}
        self.assertEqual("8.5.99", releases.official_release("8.5", payload)["version"])
        for version in ("8.5.99RC1", "8.5.99-dev", "8.6.0", "8.1.99", "8.5.99\n", "8.5.099"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                releases.official_release("8.5", dict(payload, version=version))
        payload["source"][0]["sha256"] = "invalid"
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            releases.official_release("8.5", payload)
        payload["source"] = [{"filename": "php-8.5.99.tar.xz", "sha256": "b" * 64}]
        with self.assertRaisesRegex(ValueError, "source archive"):
            releases.official_release("8.5", payload)

    def test_manifest_cannot_reintroduce_php81(self):
        for branch in ("8.1", "8.6", "8.2"):
            manifest = copy.deepcopy(self.current)
            manifest[-1]["branch"] = branch
            with self.assertRaises(ValueError):
                releases.validate_manifest(manifest)

    def test_check_reads_all_official_and_public_versions(self):
        calls = []

        def fetch(url, allow_missing=False):
            calls.append(url)
            if url.startswith("https://www.php.net/"):
                item = next(item for item in self.current if url.endswith("=" + item["branch"]))
                return {"version": item["version"], "source": [{"filename": f"php-{item['version']}.tar.gz", "sha256": item["sha256"]}]}
            self.assertTrue(allow_missing)
            name = url.split("/")[-1].split(".json")[0]
            return self.published[name]

        latest, pending = releases.check_updates(self.current, fetch)
        self.assertEqual(self.current, latest)
        self.assertEqual([], pending)
        self.assertEqual(28, len(calls))

    def test_cli_plan_both_platform_sets(self):
        for include_glibc, expected in (("true", 24), ("false", 16)):
            with self.subTest(include_glibc=include_glibc), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "output"
                with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output), "INCLUDE_GLIBC": include_glibc}), patch("sys.argv", ["php_releases.py", "plan"]):
                    releases.main()
                values = dict(line.split("=", 1) for line in output.read_text().splitlines())
                self.assertEqual(str(expected), values["count"])
                self.assertEqual(self.current, json.loads(values["php"]))
                self.assertEqual(expected // 4, len(json.loads(values["targets"])))

    def test_failed_network_check_does_not_change_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "php-releases.json"
            original = releases.MANIFEST.read_text()
            manifest.write_text(original)
            with patch("sys.argv", ["php_releases.py", "check", "--manifest", str(manifest)]), patch.object(releases, "check_updates", side_effect=ValueError("Invalid official response")):
                with self.assertRaises(ValueError):
                    releases.main()
            self.assertEqual(original, manifest.read_text())

    def test_validation_plan_never_builds_full_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output), "VALIDATION_ONLY": "true"}), patch("sys.argv", ["php_releases.py", "plan"]):
                releases.main()
            values = dict(line.split("=", 1) for line in output.read_text().splitlines())
            self.assertEqual("1", values["count"])
            self.assertEqual(["8.3"], [item["branch"] for item in json.loads(values["php"])])
            self.assertEqual("x86_64-linux-musl", json.loads(values["targets"])[0]["triple"])

    def test_cli_no_new_release_preserves_manifest_and_skips_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "php-releases.json"
            output = Path(temporary) / "output"
            original = releases.MANIFEST.read_bytes()
            manifest.write_bytes(original)
            before = manifest.stat().st_mtime_ns
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(Path(temporary) / "summary")}), patch("sys.argv", ["php_releases.py", "check", "--manifest", str(manifest)]), patch.object(releases, "check_updates", return_value=(self.current, [])):
                releases.main()
            self.assertEqual(original, manifest.read_bytes())
            self.assertEqual(before, manifest.stat().st_mtime_ns)
            self.assertEqual("needed=false\nmanifest-changed=false\n", output.read_text())

    def test_cli_only_changes_manifest_after_successful_check(self):
        latest = copy.deepcopy(self.current)
        latest[-1]["version"] = "8.5.999"
        latest[-1]["sha256"] = "f" * 64
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "php-releases.json"
            output = Path(temporary) / "output"
            manifest.write_text(json.dumps(self.current))
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(Path(temporary) / "summary")}), patch("sys.argv", ["php_releases.py", "check", "--manifest", str(manifest)]), patch.object(releases, "check_updates", return_value=(latest, ["new PHP release"])):
                releases.main()
            self.assertEqual(latest, json.loads(manifest.read_text()))
            self.assertIn("needed=true\n", output.read_text())
            self.assertIn("manifest-changed=true\n", output.read_text())


if __name__ == "__main__":
    unittest.main()
