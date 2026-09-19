import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cups_backend as backend
import cups_queue as queue

TEXT = b"TERMINE\nTestperson Alpha\nTerminzeitpunkt Termintyp\nSa. 19.09.2026, 09:00 Kontrolle\n"


class BackendTests(unittest.TestCase):
    def execute(self, args, data=TEXT):
        output, error = io.StringIO(), io.StringIO()
        stdin = Mock(buffer=io.BytesIO(data))
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(output))
            stack.enter_context(contextlib.redirect_stderr(error))
            stack.enter_context(patch.object(sys, "stdin", stdin))
            drop = stack.enter_context(patch.object(backend, "drop_privileges"))
            stack.enter_context(patch.object(backend.signal, "signal"))
            stack.enter_context(patch.object(backend.app, "ensure_runtime"))
            stack.enter_context(patch.object(backend.app, "load_config", return_value={}))
            send = stack.enter_context(patch.object(backend.app, "send_cups"))
            status = backend.main(args)
        return status, output.getvalue(), error.getvalue(), send, drop

    def test_discovery_contains_only_fixed_device_name(self):
        status, out, err, send, drop = self.execute([])
        self.assertEqual(status, 0)
        self.assertIn('direct terminzettel:/', out)
        self.assertEqual(err, "")
        send.assert_not_called()
        drop.assert_not_called()

    def test_stdin_receipt_and_copy_count(self):
        status, out, err, send, drop = self.execute(["1", "Private User", "Private Title", "2", ""])
        self.assertEqual((status, out, err), (0, "", ""))
        self.assertIn(b"Testperson Alpha", send.call_args.args[0])
        self.assertTrue(send.call_args.args[0].endswith(b"\x1dV\x01"))
        self.assertEqual(send.call_args.kwargs, {"copies": 2})
        drop.assert_called_once()

    def test_file_is_consumed_without_deleting_cups_owned_input(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "job"
            source.write_bytes(TEXT)
            result = self.execute(["1", "u", "t", "1", "", str(source)])
            self.assertEqual(result[0], 0)
            self.assertEqual(source.read_bytes(), TEXT)

    def test_parse_failure_never_logs_title_or_content(self):
        result = self.execute(["1", "Private User", "Private Title", "1", ""], b"Private Contents")
        self.assertEqual(result[0], 1)
        self.assertEqual(result[1], "")
        self.assertNotIn("Private", result[2])
        result[3].assert_not_called()

    def test_invalid_copy_count_never_prints(self):
        for count in ("0", "-1", "100", "Private Title"):
            with self.subTest(count=count):
                result = self.execute(["1", "u", "t", count, ""])
                self.assertEqual(result[0], 1)
                result[3].assert_not_called()

    def test_privileges_are_dropped_before_parsing(self):
        account = Mock(pw_gid=123, pw_uid=456)
        with patch.object(backend.pwd, "getpwnam", return_value=account), \
                patch.object(backend.os, "geteuid", side_effect=[0, 456]), \
                patch.object(backend.os, "setgroups") as groups, \
                patch.object(backend.os, "setgid") as gid, \
                patch.object(backend.os, "setuid") as uid, \
                patch.object(backend.os, "umask"):
            backend.drop_privileges()
        groups.assert_called_once_with([])
        gid.assert_called_once_with(123)
        uid.assert_called_once_with(456)


class QueueTests(unittest.TestCase):
    def test_absent_queue(self):
        conn = Mock()
        conn.getPrinters.return_value = {"TMm10": {}}
        conn.getClasses.return_value = {}
        with patch.object(queue, "connection", return_value=conn):
            self.assertIsNone(queue.inspect_queue(False))

    def test_foreign_printer_or_class_is_not_overwritten(self):
        for printer, classes in (({"terminzettel": {}}, {}), ({}, {"TERMINZETTEL": {}})):
            conn = Mock()
            conn.getPrinters.return_value, conn.getClasses.return_value = printer, classes
            with patch.object(queue, "connection", return_value=conn), self.assertRaises(RuntimeError):
                queue.inspect_queue(False)

    def test_changed_destination_is_not_overwritten(self):
        conn = Mock()
        conn.getPrinters.return_value = {"Terminzettel": {}}
        conn.getClasses.return_value = {}
        conn.getPrinterAttributes.return_value = {"device-uri": "usb://existing"}
        with patch.object(queue, "connection", return_value=conn), self.assertRaises(RuntimeError):
            queue.inspect_queue(True)

    def test_shared_queue_is_required(self):
        conn = Mock()
        conn.getPrinterAttributes.return_value = {"device-uri": queue.URI, "printer-is-shared": False}
        with patch.object(queue, "connection", return_value=conn), self.assertRaises(RuntimeError):
            queue.verify_queue()


if __name__ == "__main__":
    unittest.main()
