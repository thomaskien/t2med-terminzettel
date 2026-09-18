import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ticket_runtime_test", ROOT / "terminzettel.py")
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)
TEXT = "TERMINE\nTestperson Alpha\nTerminzeitpunkt              Termintyp\nDo. 17.09.2026, 09:00 Kontrolle\n"


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spool = self.root / "spool"
        self.spool.mkdir()
        for name, value in [("SPOOL", self.spool), ("WORK", self.root), ("ensure_runtime", Mock())]:
            item = patch.object(app, name, value)
            item.start()
            self.addCleanup(item.stop)
        self.source = self.spool / "job"
        self.source.write_text(TEXT)
        self.config = self.root / "config.toml"
        self.config.write_text('[output]\nqueue="TMm10"\n')

    def main(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["terminzettel", "--config", str(self.config), *args]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = app.main()
        return result, stdout.getvalue(), stderr.getvalue()

    def test_success_consumes_spool_without_content_logging(self):
        with patch.object(app, "send_cups") as send:
            status, out, err = self.main(str(self.source))
        self.assertEqual(status, 0)
        self.assertFalse(self.source.exists())
        self.assertEqual(out + err, "")
        self.assertIn(b"Testperson Alpha", send.call_args.args[0])

    def test_failure_consumes_spool_and_sanitizes_exception(self):
        with patch.object(app, "send_cups", side_effect=RuntimeError("Testperson Alpha secret")):
            status, out, err = self.main(str(self.source))
        self.assertEqual(status, 1)
        self.assertFalse(self.source.exists())
        self.assertNotIn("Testperson", out + err)
        self.assertNotIn("secret", out + err)

    def test_bad_config_still_consumes_spool(self):
        self.config.write_text("broken [Testperson Alpha")
        status, out, err = self.main(str(self.source))
        self.assertEqual(status, 1)
        self.assertFalse(self.source.exists())
        self.assertNotIn("Testperson", out + err)

    def test_runtime_failure_still_consumes_spool(self):
        app.ensure_runtime.side_effect = app.TicketError("RAM-Dateisystem fehlt.")
        self.assertEqual(self.main(str(self.source))[0], 1)
        self.assertFalse(self.source.exists())

    def test_check_keeps_user_file_and_prints_no_content(self):
        with patch.object(app, "send_cups") as send:
            status, out, err = self.main("--check", str(self.source))
        self.assertEqual(status, 0)
        self.assertTrue(self.source.exists())
        self.assertEqual(out, "Belegprüfung erfolgreich.\n")
        self.assertEqual(err, "")
        send.assert_not_called()

    def test_self_test_does_not_print_or_require_runtime(self):
        with patch.object(app, "send_cups") as send:
            self.assertEqual(self.main("--self-test")[0], 0)
        send.assert_not_called()
        app.ensure_runtime.assert_not_called()

    def test_outside_file_is_not_deleted(self):
        outside = self.root / "outside"
        outside.write_text(TEXT)
        self.assertEqual(self.main(str(outside))[0], 1)
        self.assertTrue(outside.exists())

    def test_symlink_is_not_followed_or_deleted(self):
        linked = self.spool / "linked"
        linked.symlink_to(self.source)
        self.assertEqual(self.main(str(linked))[0], 1)
        self.assertTrue(self.source.exists())
        self.assertTrue(linked.is_symlink())

    def test_oversized_spool_is_removed(self):
        with patch.object(app, "MAX_INPUT", 10):
            self.assertEqual(self.main(str(self.source))[0], 1)
        self.assertFalse(self.source.exists())

    def test_no_exports_or_debug_function(self):
        self.assertFalse(hasattr(app, "maybe_save_debug"))
        for flag in ("--extract", "--render"):
            result = subprocess.run([sys.executable, "-B", str(ROOT / "terminzettel.py"), flag], capture_output=True)
            self.assertEqual(result.returncode, 2)

    def test_converter_stderr_never_in_exception(self):
        failed = subprocess.CompletedProcess([], 1, b"", b"Testperson Alpha")
        with patch.object(app.subprocess, "run", return_value=failed) as run:
            with self.assertRaises(app.TicketError) as exc:
                app.run_checked(["converter"])
        self.assertNotIn("Testperson", str(exc.exception))
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_postscript_tempfiles_cleaned_on_failure(self):
        with patch.object(app, "run_checked", side_effect=app.TicketError("Konvertierung fehlgeschlagen.")):
            with self.assertRaises(app.TicketError):
                app.extract_text(b"%!PS\nsynthetic", {})
        self.assertEqual(list(self.root.glob("job-*")), [])

    def test_pdf_is_piped_without_tempfile(self):
        with patch.object(app, "run_checked", return_value=TEXT.encode()) as convert:
            self.assertEqual(app.extract_text(b"%PDF-synthetic", {}), TEXT)
        self.assertEqual(convert.call_args.args[0], ["pdftotext", "-layout", "-", "-"])
        self.assertEqual(convert.call_args.kwargs["input_bytes"], b"%PDF-synthetic")

    def test_disabled_header_and_footer_in_both_formats(self):
        ticket = app.parse_t2med(TEXT)
        for fmt in ("text", "escpos"):
            cfg = {"output": {"format": fmt}, "header": {"enabled": False, "text": "DISABLED"},
                   "footer": {"enabled": False, "text": "DISABLED"}}
            self.assertNotIn(b"DISABLED", app.render(ticket, cfg))

    def test_text_cannot_inject_printer_command(self):
        ticket = app.ParsedTicket("Testperson", [app.Appointment("Do.", "17.09.2026", "09:00", "Kontrolle\x1b@")])
        for fmt in ("text", "escpos"):
            with self.assertRaises(app.TicketError):
                app.render(ticket, {"output": {"format": fmt}})

    def test_cp858_and_one_cut(self):
        ticket = app.parse_t2med(TEXT.replace("Alpha", "Ä Ö Ü ß €"))
        raw = app.render(ticket, {})
        self.assertIn("Ä Ö Ü ß €".encode("cp858"), raw)
        self.assertEqual(raw.count(b"\x1dV\x01"), 1)
        self.assertTrue(raw.endswith(b"\x1dV\x01"))

    def test_cleanup_removes_only_old_owned_jobs_and_keeps_active_conversion(self):
        import fcntl
        old = self.root / "job-old"
        active = self.root / "job-active"
        for directory in (old, active):
            directory.mkdir()
            (directory / ".lock").touch()
            (directory / "input").write_text("synthetic")
            os.utime(directory, (1, 1))
        os.utime(self.source, (1, 1))
        recent = self.spool / "recent"
        recent.write_text("synthetic")
        conn = Mock()
        conn.getJobs.return_value = {1: {"job-name": "Terminzettel", "time-at-creation": 1},
                                    2: {"job-name": "Other", "time-at-creation": 1},
                                    3: {"job-name": "Terminzettel", "time-at-creation": app.time.time()}}
        with open(active / ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with patch.object(app, "cups_connection", return_value=(None, conn)):
                app.cleanup()
        self.assertFalse(old.exists())
        self.assertTrue(active.exists())
        self.assertFalse(self.source.exists())
        self.assertTrue(recent.exists())
        conn.cancelJob.assert_called_once_with(1, purge_job=True)


class RuntimeMountTests(unittest.TestCase):
    def runtime(self, mount_type, mount_options, directories_exist=True):
        fixture = "24 23 0:23 / /run/terminzettel rw - " + mount_type + " tmpfs " + mount_options + "\n"

        def read_text(path):
            self.assertEqual(path, Path("/proc/self/mountinfo"))
            return fixture

        with patch.object(Path, "read_text", autospec=True, side_effect=read_text), patch.object(Path, "is_dir", return_value=directories_exist), patch.object(app.resource, "setrlimit"):
            app.ensure_runtime()

    def test_disk_spool_is_rejected(self):
        with self.assertRaises(app.TicketError):
            self.runtime("ext4", "rw")

    def test_standard_tmpfs_works_without_cgroup_or_swap_checks(self):
        self.runtime("tmpfs", "rw")

    def test_missing_runtime_directories_are_rejected(self):
        with self.assertRaises(app.TicketError):
            self.runtime("tmpfs", "rw", directories_exist=False)

    def test_existing_noswap_mount_remains_compatible(self):
        self.runtime("tmpfs", "rw,noswap")


class CupsTests(unittest.TestCase):
    def setUp(self):
        class IPPError(Exception):
            pass
        self.cups = types.SimpleNamespace(IPPError=IPPError, IPP_NOT_FOUND=0x406)
        self.conn = Mock()
        self.conn.createJob.return_value = 17
        self.conn.startDocument.return_value = 100
        self.conn.writeRequestData.return_value = 100
        self.conn.finishDocument.return_value = 0
        self.conn.getJobAttributes.return_value = {"job-state": 9}
        patcher = patch.object(app, "cups_connection", return_value=(self.cups, self.conn))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_streaming_fixed_metadata_and_purge(self):
        app.send_cups(b"Testperson Alpha", {})
        self.conn.createJob.assert_called_once_with("TMm10", "Terminzettel", {"job-cancel-after": "60"})
        self.conn.startDocument.assert_called_once_with("TMm10", 17, "Terminzettel", "application/vnd.cups-raw", 1)
        self.conn.writeRequestData.assert_called_once_with(b"Testperson Alpha", 16)
        self.conn.cancelJob.assert_called_once_with(17, purge_job=True)

    def test_failed_upload_is_purged(self):
        self.conn.writeRequestData.side_effect = RuntimeError("synthetic failure")
        with self.assertRaises(RuntimeError):
            app.send_cups(b"x", {})
        self.conn.cancelJob.assert_called_once_with(17, purge_job=True)

    def test_aborted_job_is_error_and_purged(self):
        self.conn.getJobAttributes.return_value = {"job-state": 8}
        with self.assertRaises(app.TicketError):
            app.send_cups(b"x", {})
        self.conn.cancelJob.assert_called_once_with(17, purge_job=True)

    def test_timeout_is_purged(self):
        self.conn.getJobAttributes.return_value = {"job-state": 3}
        with patch.object(app.time, "monotonic", side_effect=[0, 61]):
            with self.assertRaises(app.TicketError):
                app.send_cups(b"x", {})
        self.conn.cancelJob.assert_called_once_with(17, purge_job=True)

    def test_deleted_history_is_accepted(self):
        self.conn.getJobAttributes.side_effect = self.cups.IPPError(self.cups.IPP_NOT_FOUND, "not found")
        app.send_cups(b"x", {})

    def test_recursive_queue_is_rejected(self):
        with self.assertRaises(app.TicketError):
            app.send_cups(b"x", {"output": {"queue": "Terminzettel"}})
        self.conn.createJob.assert_not_called()


if __name__ == "__main__":
    unittest.main()
