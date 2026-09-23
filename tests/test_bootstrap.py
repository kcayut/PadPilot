"""Exercise downloads and archive boundaries without network or installation."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


BOOTSTRAP = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.sh"


class BootstrapTests(unittest.TestCase):
    def test_download_reuse_failure_and_archive_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / "tools"
            tools.mkdir()
            (tools / "uname").write_text("#!/bin/sh\necho Darwin\n")
            (tools / "curl").write_text(
                '#!/bin/sh\n[ "${FAIL_DOWNLOAD:-}" != 1 ] || exit 22\n'
                'echo download >> "$DOWNLOAD_LOG"\n'
                'while [ "$1" != --output ]; do shift; done\n'
                'cp "$TEST_ARCHIVE" "$2"\n'
            )
            for tool in tools.iterdir():
                tool.chmod(0o755)
            archive = root / "source.tar.gz"
            calls = root / "calls"
            environment = dict(
                os.environ, PATH=f"{tools}:{os.environ['PATH']}",
                TEST_ARCHIVE=str(archive), DOWNLOAD_LOG=str(root / "downloads"),
                INSTALL_LOG=str(calls), TMPDIR=str(root),
            )

            def make_archive(extra=None):
                with tarfile.open(archive, "w:gz") as tar:
                    for name, body in (
                        ("scripts/install.sh", 'printf "%s\\n" "$*" >> "$INSTALL_LOG"\n'),
                        ("scripts/uninstall.sh", "exit 0\n"),
                    ):
                        entry = tarfile.TarInfo(f"SidecarSwitch-main/{name}")
                        payload = body.encode()
                        entry.size, entry.mode = len(payload), 0o755
                        tar.addfile(entry, io.BytesIO(payload))
                    if extra:
                        tar.addfile(extra)

            def run(home, *arguments, **overrides):
                home.mkdir(exist_ok=True)
                return subprocess.run(
                    ["/bin/bash", str(BOOTSTRAP), *arguments],
                    env=dict(environment, HOME=str(home), **overrides),
                    text=True, capture_output=True,
                )

            make_archive()
            home = root / "valid"
            result = run(home, "--python", "/a path/python3", "--yes")
            self.assertEqual(result.returncode, 0, result.stderr)
            source = home / "Applications" / "SidecarSwitch-source"
            receipt = source / ".sidecarswitch-install.json"
            data = json.loads(receipt.read_text())
            self.assertEqual(data, {"schema": 1, "managed_source": True, "dependencies": []})
            data["dependencies"] = ["keep-existing-record"]
            receipt.write_text(json.dumps(data))
            result = run(home, "--check", FAIL_DOWNLOAD="1")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(receipt.read_text()), data)
            self.assertEqual(calls.read_text().splitlines(), ["--python /a path/python3 --yes", "--check"])
            self.assertEqual((root / "downloads").read_text().splitlines(), ["download"])

            # macOS Bash 3.2 treats empty array expansion as unbound under set -u.
            result = run(home, FAIL_DOWNLOAD="1")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = run(root / "default-install")
            self.assertEqual(result.returncode, 0, result.stderr)

            for label, arguments, overrides in (
                ("failed-download", (), {"FAIL_DOWNLOAD": "1"}),
                ("check-only", ("--check",), {}),
                ("invalid-option", ("--unknown",), {}),
                ("removed-option", ("--headless",), {}),
            ):
                result = run(root / label, *arguments, **overrides)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse((root / label / "Applications").exists())

            for label, entry in (
                ("traversal", tarfile.TarInfo("SidecarSwitch-main/../../escape")),
                ("wrong-root", tarfile.TarInfo("Elsewhere/install.sh")),
                ("symlink", tarfile.TarInfo("SidecarSwitch-main/linked")),
                ("hardlink", tarfile.TarInfo("SidecarSwitch-main/hardlinked")),
            ):
                with self.subTest(label=label):
                    if label in {"symlink", "hardlink"}:
                        entry.type = tarfile.SYMTYPE if label == "symlink" else tarfile.LNKTYPE
                        entry.linkname = "../../escape"
                    make_archive(entry)
                    result = run(root / label)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertFalse((root / label / "Applications").exists())
            self.assertEqual(len(calls.read_text().splitlines()), 4)

            unmanaged = root / "unmanaged"
            existing = unmanaged / "Applications" / "SidecarSwitch-source"
            existing.mkdir(parents=True)
            result = run(unmanaged)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(existing.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
