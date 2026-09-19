from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import setup_config as cfg
spec = importlib.util.spec_from_file_location("ticket_install_test", ROOT / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ConfigTests(unittest.TestCase):
    def test_unmanaged_share_preserved_and_update_idempotent(self):
        original = "[global]\nworkgroup = PRAXIS\n[other]\npath = /srv/other\n"
        result = cfg.samba_config(original)
        self.assertIn(original.rstrip(), result)
        self.assertEqual(cfg.samba_config(result), result)

    def test_foreign_share_detected_case_insensitively(self):
        for heading in ("[terminzettel]", "[ TERMINZETTEL ]", "[Terminzettel] # fremd"):
            with self.assertRaises(ValueError):
                cfg.samba_config(heading + "\npath = /srv/other\n")

    def test_broken_markers_rejected(self):
        for text in (cfg.BEGIN + "\n[other]\n", cfg.END, cfg.END + "\n" + cfg.BEGIN,
                     cfg.BEGIN + "\n" + cfg.BEGIN + "\n" + cfg.END):
            with self.assertRaises(ValueError):
                cfg.remove_block(text)

    def test_removal_preserves_other_sections(self):
        self.assertEqual(cfg.remove_block("a\n" + cfg.BEGIN + "\nx\n" + cfg.END + "\nb\n"), "a\nb\n")

    def test_config_migration_preserves_layout_removes_credentials_and_debug(self):
        original = '[output]\nserver="localhost"\nshare="TMm10"\npassword="synthetic"\n[debug]\nsave_raw_dir="/tmp/raw"\n[header]\ntext="Praxis\\nTelefon"\nenabled=false\n'
        result = cfg.tomllib.loads(cfg.migrate_config(original))
        self.assertEqual(result["output"]["queue"], "TMm10")
        self.assertNotIn("password", result["output"])
        self.assertNotIn("debug", result)
        self.assertEqual(result["header"], {"text": "Praxis\nTelefon", "enabled": False})

    def test_remote_output_is_not_silently_redirected(self):
        with self.assertRaises(ValueError):
            cfg.migrate_config('[output]\nserver="remote-server"\n')

    def test_cups_storage_and_logs_are_configured(self):
        files = cfg.cups_files_config("# Existing CUPS config\n")
        for setting in ("RequestRoot /run/terminzettel/cups", "TempDir /run/terminzettel/cups/tmp", "CacheDir /run/terminzettel/cups-cache", "\nAccessLog /dev/null\n", "\nPageLog /dev/null\n", "\nErrorLog /dev/null\n"):
            self.assertIn(setting, files)
        daemon = cfg.cups_daemon_config("LogLevel warn\n")
        self.assertIn("PreserveJobHistory No", daemon)
        self.assertIn("PreserveJobFiles No", daemon)
        self.assertNotIn("MaxJobTime", daemon)
        self.assertNotIn("MaxHoldTime", daemon)
        self.assertNotIn("noswap", cfg.MOUNT)
        self.assertNotIn("MemorySwapMax", cfg.DROPIN + cfg.CLEANUP_SERVICE)
        self.assertIn("LimitCORE=0", cfg.DROPIN)

    def test_plan_reads_actual_source_instead_of_embedded_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("etc/samba/smb.conf", "etc/cups/cups-files.conf", "etc/cups/cupsd.conf"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# initial\n")
            result = cfg.plan(ROOT, root)
        self.assertEqual(result["/usr/local/lib/terminzettel/terminzettel.py"], (ROOT / "terminzettel.py").read_text())


class RuntimeSetupTests(unittest.TestCase):
    def prepare(self, directory, filesystem="tmpfs", mount_result=0):
        def path(name):
            self.assertEqual(name, "/run/terminzettel")
            return Path(directory)

        def run(*args, **kwargs):
            code = 1 if args[0] == "mountpoint" else mount_result if args[0] == "mount" else 0
            output = (filesystem + " rw,nosuid,nodev,noexec\n").encode() if args[0] == "findmnt" else b""
            return subprocess.CompletedProcess(args, code, output, b"")

        with patch.object(installer, "Path", side_effect=path), patch.object(installer, "run", side_effect=run) as commands:
            installer.prepare_runtime()
        return commands

    def test_standard_tmpfs_installation_needs_no_cgroup_files(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = self.prepare(directory)
        mount = next(call.args for call in commands.call_args_list if call.args[0] == "mount")
        self.assertEqual(mount[4], "size=128M,mode=0755,nosuid,nodev,noexec")

    def test_disk_directory_still_rejected(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(RuntimeError, "kein temporäres RAM-Dateisystem"):
            self.prepare(directory, filesystem="ext4")

    def test_mount_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(RuntimeError, "konnte nicht eingehängt"):
            self.prepare(directory, mount_result=1)


class TransactionTests(unittest.TestCase):
    def test_queue_failure_rolls_back_only_newly_created_queue(self):
        changes = {"/etc/terminzettel/config.toml": '[output]\nqueue="TMm10"\n'}
        for existing, failure in ((False, "create_queue"), (False, "verify_queue"), (True, "verify_queue")):
            with self.subTest(existing=existing, failure=failure), ExitStack() as stack:
                state = MagicMock()
                state.exists.return_value = existing
                state.read_text.return_value = json.dumps({"originals": {}, "cups_queue": existing})
                stack.enter_context(patch.object(installer, "STATE", state))
                stack.enter_context(patch.object(installer, "plan", return_value=changes))
                stack.enter_context(patch.object(installer, "snapshot", return_value=None))
                def run(*args, **kwargs):
                    return subprocess.CompletedProcess(args, 0, b"standalone server\n" if args[0] == "testparm" else b"", b"")
                stack.enter_context(patch.object(installer, "run", side_effect=run))
                for name in ("prepare_runtime", "validate", "check_idle", "atomic_write", "write_file", "start_previous", "restore"):
                    stack.enter_context(patch.object(installer, name))
                stack.enter_context(patch.object(installer.os, "chmod"))
                stack.enter_context(patch.object(installer.cups_queue, "inspect_queue", return_value={} if existing else None))
                create = stack.enter_context(patch.object(installer.cups_queue, "create_queue"))
                verify = stack.enter_context(patch.object(installer.cups_queue, "verify_queue"))
                delete = stack.enter_context(patch.object(installer.cups_queue, "delete_queue"))
                (create if failure == "create_queue" else verify).side_effect = RuntimeError("synthetic queue failure")
                with self.assertRaisesRegex(RuntimeError, "queue failure"):
                    installer.install()
                installer.restore.assert_called_once_with({name: None for name in changes})
                if existing:
                    create.assert_not_called()
                    delete.assert_not_called()
                else:
                    delete.assert_called_once_with(installer.run, optional=True)

    def test_failed_service_restart_rolls_back_and_does_not_report_success(self):
        changes = {"/etc/terminzettel/config.toml": '[output]\nqueue="TMm10"\n', "/usr/local/sbin/terminzettel-submit": "new"}

        def run(*args, **kwargs):
            if args[:2] == ("systemctl", "restart"):
                raise RuntimeError("synthetic restart failure")
            output = b"standalone server\n" if args[0] == "testparm" else b""
            return subprocess.CompletedProcess(args, 0, output, b"")

        with ExitStack() as stack:
            state = MagicMock()
            state.exists.return_value = False
            stack.enter_context(patch.object(installer, "STATE", state))
            stack.enter_context(patch.object(installer, "plan", return_value=changes))
            stack.enter_context(patch.object(installer.cups_queue, "inspect_queue", return_value=None))
            stack.enter_context(patch.object(installer, "snapshot", return_value=None))
            stack.enter_context(patch.object(installer, "run", side_effect=run))
            for name in ("prepare_runtime", "validate", "check_idle", "atomic_write", "write_file", "start_previous"):
                stack.enter_context(patch.object(installer, name))
            stack.enter_context(patch.object(installer.os, "chmod"))
            rollback = stack.enter_context(patch.object(installer, "restore"))
            with self.assertRaisesRegex(RuntimeError, "restart failure"):
                installer.install()
            rollback.assert_called_once_with({name: None for name in changes})
            installer.start_previous.assert_called_once()

    def test_uninstall_preserves_modified_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owned = root / "owned.conf"
            owned.write_text("user changes")
            state = root / "state.json"
            state.write_text(json.dumps({"installed": {str(owned): "different-checksum"}, "originals": {str(owned): None}}))
            with patch.object(installer, "STATE", state), patch.object(installer, "run") as run:
                with self.assertRaises(RuntimeError):
                    installer.uninstall()
            self.assertEqual(owned.read_text(), "user changes")
            run.assert_not_called()

    def test_atomic_file_update_preserves_selected_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file"
            installer.atomic_write(path, b"new", 0o600)
            self.assertEqual(path.read_bytes(), b"new")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_pending_jobs_block_installation(self):
        pending = subprocess.CompletedProcess([], 0, b"TMm10-123\n", b"")
        with patch.object(installer, "run", return_value=pending):
            with self.assertRaises(RuntimeError):
                installer.check_idle()


if __name__ == "__main__":
    unittest.main()
