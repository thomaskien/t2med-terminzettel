import contextlib
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import calendar_qr as calendar
from escpos import page_image
from escpos_test_utils import decode_pages
from test_runtime import app, TEXT


def starts(count):
    return [calendar.CalendarAppointment(datetime(2026, 10, 5, 9) + timedelta(days=14 * i)) for i in range(count)]


def properties(payload, key):
    unfolded = payload.replace(b"\r\n ", b"").decode()
    return [line.split(":", 1)[1] for line in unfolded.split("\r\n") if line.startswith(key + ":")]


def receipt_ticket(count):
    times = ("09:00", "10:30", "12:15", "14:45", "16:00")
    appointments = [
        app.Appointment("Do.", "17.09.2026", value, f"Art {index}")
        for index, value in enumerate(times[:count], 1)
    ]
    return app.ParsedTicket("Beispielperson", appointments)


class CalendarTests(unittest.TestCase):
    def test_appointment_summary_uses_kind_and_normalizes_prefix(self):
        self.assertEqual(calendar.appointment_summary("Praxis ABC", "  Lufu  "), "Praxis ABC: Lufu")
        self.assertEqual(calendar.appointment_summary("Praxis ABC: ", "Lufu"), "Praxis ABC: Lufu")
        self.assertEqual(calendar.appointment_summary("", " Lufu\tKontrolle "), "Lufu Kontrolle")
        with self.assertRaises(ValueError):
            calendar.appointment_summary(None, "Lufu")

    def test_one_two_five_events(self):
        for count in (1, 2, 5):
            payload = calendar.build_icalendar(starts(count), {})
            self.assertEqual(payload.count(b"BEGIN:VCALENDAR"), 1)
            self.assertEqual(payload.count(b"BEGIN:VEVENT"), count)
            self.assertEqual(len(set(properties(payload, "UID"))), count)
            self.assertEqual(len(properties(payload, "DTSTAMP")), count)
            self.assertTrue(payload.endswith(b"END:VCALENDAR\r\n"))
            self.assertNotIn(b"\n", payload.replace(b"\r\n", b""))

    def test_unsorted_and_duplicate(self):
        data = starts(2)
        payload = calendar.build_icalendar([data[1], data[0], data[0]], {})
        self.assertEqual(properties(payload, "DTSTART"), ["20261005T070000Z", "20261019T070000Z"])

    def test_summer_and_winter(self):
        for month, expected in ((7, "20260705T070000Z"), (1, "20260105T080000Z")):
            payload = calendar.build_icalendar([calendar.CalendarAppointment(datetime(2026, month, 5, 9))], {})
            self.assertEqual(properties(payload, "DTSTART"), [expected])

    def test_timezone_is_configurable(self):
        payload = calendar.build_icalendar(starts(1), {"timezone": "UTC"})
        self.assertEqual(properties(payload, "DTSTART"), ["20261005T090000Z"])

    def test_default_duration_and_real_end(self):
        payload = calendar.build_icalendar(starts(1), {"default_duration_minutes": 30})
        self.assertEqual(properties(payload, "DTEND"), ["20261005T073000Z"])
        event = calendar.CalendarAppointment(datetime(2026, 10, 5, 9), datetime(2026, 10, 5, 9, 10))
        payload = calendar.build_icalendar([event], {"default_duration_minutes": 30})
        self.assertEqual(properties(payload, "DTEND"), ["20261005T071000Z"])

    def test_dst_change_duration_is_elapsed_time(self):
        event = calendar.CalendarAppointment(datetime(2026, 3, 29, 1, 55))
        payload = calendar.build_icalendar([event], {})
        self.assertEqual(properties(payload, "DTSTART"), ["20260329T005500Z"])
        self.assertEqual(properties(payload, "DTEND"), ["20260329T011000Z"])

    def test_dst_invalid_and_ambiguous_naive_times_not_guessed(self):
        for invalid in (datetime(2026, 3, 29, 2, 30), datetime(2026, 10, 25, 2, 30), "invalid date"):
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                payload = calendar.build_icalendar([calendar.CalendarAppointment(invalid), *starts(1)], {})
            self.assertEqual(payload.count(b"BEGIN:VEVENT"), 1)
            self.assertEqual(output.getvalue(), "invalid appointment datetime\n")

    def test_explicit_dst_fold_is_respected(self):
        for fold, expected in ((0, "20261025T003000Z"), (1, "20261025T013000Z")):
            value = datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo("Europe/Berlin"), fold=fold)
            payload = calendar.build_icalendar([calendar.CalendarAppointment(value)], {})
            self.assertEqual(properties(payload, "DTSTART"), [expected])

    def test_no_valid_appointments_fails(self):
        with self.assertRaises(ValueError):
            calendar.build_icalendar([], {})

    def test_invalid_end_is_discarded(self):
        invalid = calendar.CalendarAppointment(datetime(2026, 10, 5, 9), datetime(2026, 10, 5, 8))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(ValueError):
            calendar.build_icalendar([invalid], {})

    def test_location_opt_in_and_safe_escaping(self):
        config = {"summary": "Termin, Beratung; Praxis\\Haus\nOrt", "location": "Musterstraße 1, 12345 Teststadt"}
        self.assertEqual(properties(calendar.build_icalendar(starts(1), config), "LOCATION"), [])
        config["include_location"] = True
        payload = calendar.build_icalendar(starts(1), config)
        self.assertEqual(properties(payload, "LOCATION"), ["Musterstraße 1\\, 12345 Teststadt"])
        self.assertEqual(properties(payload, "SUMMARY"), ["Termin\\, Beratung\\; Praxis\\\\Haus\\nOrt"])

    def test_unicode_line_folding_is_at_most_75_octets(self):
        title = "Ärztlicher Termin " * 15
        payload = calendar.build_icalendar(starts(1), {"summary": title})
        for line in payload.split(b"\r\n"):
            self.assertLessEqual(len(line), 75)
            line.decode("utf-8")
        self.assertEqual(properties(payload, "SUMMARY"), [title])

    def test_fixed_utc_stamp(self):
        now = datetime(2026, 9, 17, 12, 30, tzinfo=timezone.utc)
        payload = calendar.build_icalendar(starts(2), {}, now=now)
        self.assertEqual(properties(payload, "DTSTAMP"), ["20260917T123000Z"] * 2)

    def test_independent_icalendar_parser(self):
        from icalendar import Calendar
        payload = calendar.build_icalendar(starts(5), {"include_location": True, "location": "Musterstraße 1, Teststadt"})
        parsed = Calendar.from_ical(payload)
        events = parsed.walk("VEVENT")
        self.assertEqual(len(events), 5)
        self.assertEqual(str(events[0]["SUMMARY"]), "Termin Arztpraxis")
        self.assertEqual(str(events[0]["LOCATION"]), "Musterstraße 1, Teststadt")
        self.assertEqual(events[0].decoded("DTSTART"), datetime(2026, 10, 5, 7, tzinfo=timezone.utc))


class QrTests(unittest.TestCase):
    def test_qr_decodes_byte_for_byte(self):
        import zxingcpp
        for count in (1, 2, 3, 5):
            payload = calendar.build_icalendar(starts(count), {})
            image = calendar.build_qr_image(payload, {"max_width_dots": 384})
            result = zxingcpp.read_barcode(image.convert("L"))
            self.assertIsNotNone(result)
            self.assertEqual(result.bytes, payload)
            self.assertEqual(image.mode, "1")
            self.assertLessEqual(image.width, 384)

    def test_five_events_exceed_old_360_dot_width(self):
        with self.assertRaises(calendar.PayloadTooLarge):
            calendar.build_qr_image(calendar.build_icalendar(starts(5), {}), {"max_width_dots": 360})

    def test_default_width_makes_small_single_event_qr(self):
        image = calendar.build_qr_image(calendar.build_icalendar(starts(1), {}), {})
        self.assertEqual(image.size, (219, 219))
        self.assertLessEqual(image.width, 256)

    def test_address_qr_decodes_byte_for_byte(self):
        import zxingcpp
        config = {"include_location": True, "location": "Musterstraße 1, 12345 Teststadt"}
        payload = calendar.build_icalendar(starts(1), config)
        image = calendar.build_qr_image(payload, config)
        self.assertEqual(zxingcpp.read_barcode(image.convert("L")).bytes, payload)

    def test_too_large_payload_rejected(self):
        with self.assertRaises(calendar.PayloadTooLarge):
            calendar.build_qr_image(calendar.build_icalendar(starts(30), {}), {})

    def test_quiet_zone_and_integer_module_size(self):
        import qrcode
        payload = calendar.build_icalendar(starts(1), {})
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
        qr.add_data(payload)
        qr.make(fit=True)
        modules = qr.get_matrix()
        image = calendar.build_qr_image(payload, {})
        dots = image.width // len(modules)
        self.assertGreaterEqual(dots, 3)
        self.assertEqual(image.width, len(modules) * dots)
        for y, row in enumerate(modules):
            for x, black in enumerate(row):
                block = image.crop((x * dots, y * dots, (x + 1) * dots, (y + 1) * dots))
                self.assertEqual(block.getextrema(), (0, 0) if black else (255, 255))

    def test_page_image_bits_bands_and_padding(self):
        from PIL import Image
        image = Image.new("1", (9, 25), 1)
        image.putpixel((0, 0), 0)
        image.putpixel((8, 24), 0)
        data = page_image(image, 17, 5)
        first = b"\x1b$\x11\x00\x1d$\x1c\x00\x1b*\x21\x09\x00"
        second = b"\x1b$\x11\x00\x1d$\x34\x00\x1b*\x21\x09\x00"
        self.assertTrue(data.startswith(first + b"\x80\x00\x00" + b"\x00" * 24))
        self.assertEqual(data[len(first) + 27:], second + b"\x00" * 24 + b"\x80\x00\x00")
        self.assertNotIn(b"\x1dv0\x00", data)

    def test_receipt_contains_one_page_before_footer_and_cut(self):
        config = {"calendar_qr": {"enabled": True}, "footer": {"text": "ENDE"}}
        raw = app.render(app.parse_t2med(TEXT), config)
        pages = decode_pages(raw)
        self.assertEqual(len(pages), 1)
        self.assertLess(raw.index(b"Do. 17.09.2026"), pages[0].start)
        self.assertLess(pages[0].end, raw.index(b"ENDE"))
        self.assertNotIn(b"Termin speichern", raw)
        self.assertNotIn(b"Benutzerdefinierte Beschriftung", raw)
        self.assertNotIn(b"\x1dv0\x00", raw)
        self.assertTrue(raw.endswith(b"\x1dV\x01"))

    def test_printed_pages_for_one_two_and_five_appointments_roundtrip(self):
        from icalendar import Calendar
        import zxingcpp

        expected_times = (
            datetime(2026, 9, 17, 7, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 17, 8, 30, tzinfo=timezone.utc),
            datetime(2026, 9, 17, 10, 15, tzinfo=timezone.utc),
            datetime(2026, 9, 17, 12, 45, tzinfo=timezone.utc),
            datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc),
        )
        for count in (1, 2, 5):
            with self.subTest(count=count):
                ticket = receipt_ticket(count)
                raw = app.render(ticket, {
                    "calendar_qr": {"enabled": True, "summary": "Praxis ABC"},
                    "footer": {"enabled": True, "text": "BONENDE"},
                })
                pages = decode_pages(raw)
                self.assertEqual(len(pages), count)
                decoded_times = []
                for index, (page, appointment) in enumerate(zip(pages, ticket.appointments)):
                    decoded = zxingcpp.read_barcode(page.qr_image().convert("L"))
                    self.assertIsNotNone(decoded)
                    parsed = Calendar.from_ical(decoded.bytes)
                    events = parsed.walk("VEVENT")
                    self.assertEqual(len(events), 1)
                    decoded_times.append(events[0].decoded("DTSTART"))
                    self.assertEqual(str(events[0]["SUMMARY"]), "Praxis ABC: " + appointment.kind)
                    self.assertNotIn("LOCATION", events[0])
                    self.assertNotIn(ticket.patient.encode(), decoded.bytes)

                    self.assertEqual(page.width, 420)
                    self.assertEqual(page.direction, 0)
                    self.assertEqual(page.bands[0].x + page.bands[0].width, 420)
                    self.assertEqual([text.size for text in page.texts], [0x11] * len(page.texts))
                    self.assertEqual([text.x for text in page.texts], [0] * len(page.texts))
                    self.assertEqual(page.texts[0].data.decode("cp858"), appointment.time)
                    self.assertEqual("".join(text.data.decode("cp858") for text in page.texts[1:]),
                                     appointment.kind)
                    qr_x = page.bands[0].x
                    for text in page.texts:
                        self.assertLessEqual(text.x + len(text.data) * 24, qr_x - 12)
                    self.assertTrue(all(band.mode == 33 for band in page.bands))
                    self.assertEqual([band.bottom for band in page.bands],
                                     list(range(23, len(page.bands) * 24, 24)))
                    self.assertEqual(len(page.bands), (page.bands[0].width + 23) // 24)
                    self.assertEqual(page.height, len(page.bands) * 24 + 8)
                    self.assertEqual(raw[page.end - 1:page.end + 7], b"\x0c\x1d!\x00\x1dP\x00\x00")
                    if index:
                        self.assertLess(pages[index - 1].end, page.start)
                self.assertLess(pages[-1].end, raw.index(b"BONENDE"))
                self.assertEqual(decoded_times, list(expected_times[:count]))

    def test_adapter_passes_kind_only_as_summary_not_appointment_or_patient(self):
        original = calendar.build_icalendar
        received = []

        def inspect(appointments, config):
            self.assertEqual(set(vars(appointments[0])), {"start", "end"})
            result = original(appointments, config)
            received.append(result)
            return result

        with patch.object(calendar, "build_icalendar", side_effect=inspect):
            app.render(app.parse_t2med(TEXT), {"calendar_qr": {"enabled": True}})
        self.assertEqual(len(received), 1)
        self.assertIn(b"SUMMARY:Termin Arztpraxis: Kontrolle", received[0])
        for forbidden in (b"Testperson", b"Alpha"):
            self.assertNotIn(forbidden, received[0])

    def test_prefix_variants_and_icalendar_escaping_from_printed_bytes(self):
        from icalendar import Calendar
        import zxingcpp

        ticket = app.ParsedTicket("Nicht im Kalender", [
            app.Appointment("Do.", "17.09.2026", "09:00", "Lufu, groß; \"A\""),
        ])
        for prefix, expected in (("Praxis, Süd: ", "Praxis, Süd: Lufu, groß; \"A\""),
                                 ("", "Lufu, groß; \"A\"")):
            with self.subTest(prefix=prefix):
                raw = app.render(ticket, {"calendar_qr": {"enabled": True, "summary": prefix}})
                decoded = zxingcpp.read_barcode(decode_pages(raw)[0].qr_image().convert("L"))
                event = Calendar.from_ical(decoded.bytes).walk("VEVENT")
                self.assertEqual(len(event), 1)
                self.assertEqual(str(event[0]["SUMMARY"]), expected)
                self.assertNotIn(ticket.patient.encode(), decoded.bytes)

    def test_umlaut_long_text_wrap_font_b_and_normal_size(self):
        kind = "Überprüfung Atemfunktion mit ausführlicher Nachkontrolle"
        ticket = app.ParsedTicket("Beispielperson", [
            app.Appointment("Do.", "17.09.2026", "09:00", kind),
        ])
        config = {"calendar_qr": {"enabled": True, "max_width_dots": 384},
                  "escpos": {"font": "B"},
                  "layout": {"columns": 35, "double_height": False, "double_width": False}}
        raw = app.render(ticket, config)
        page = decode_pages(raw)[0]
        self.assertEqual(page.width, 420)
        self.assertEqual(page.bands[0].x + page.bands[0].width, 420)
        self.assertLessEqual(page.bands[0].width, 358)
        self.assertGreater(len(page.texts), 2)
        self.assertEqual([text.size for text in page.texts], [0] * len(page.texts))
        self.assertEqual([text.baseline for text in page.texts],
                         list(range(23, 23 + len(page.texts) * 30, 30)))
        self.assertEqual(page.texts[0].data, b"09:00")
        joined = "".join(text.data.decode("cp858") for text in page.texts[1:])
        self.assertEqual(joined.replace(" ", ""), kind.replace(" ", ""))
        qr_x = page.bands[0].x
        self.assertTrue(all(text.x + len(text.data) * 10 <= qr_x - 12 for text in page.texts))

    def test_large_requested_qr_is_capped_to_leave_time_column(self):
        observed = []
        original = calendar.build_qr_image

        def inspect(payload, config):
            observed.append(config["max_width_dots"])
            return original(payload, config)

        with patch.object(calendar, "build_qr_image", side_effect=inspect):
            raw = app.render(app.parse_t2med(TEXT), {
                "calendar_qr": {"enabled": True, "max_width_dots": 384},
            })
        page = decode_pages(raw)[0]
        self.assertEqual(observed, [288])
        self.assertGreaterEqual(page.bands[0].x - 12, 5 * 24)

    def test_single_qr_failure_leaves_text_bon_identical_and_logs_no_payload(self):
        ticket = app.parse_t2med(TEXT)
        plain = app.render(ticket, {})
        for error, message in ((RuntimeError("Testperson Alpha"), "calendar QR generation failed"),
                               (calendar.PayloadTooLarge(), "calendar QR payload too large")):
            output = io.StringIO()
            with patch.object(calendar, "build_qr_image", side_effect=error), contextlib.redirect_stderr(output):
                raw = app.render(ticket, {"calendar_qr": {"enabled": True}})
            self.assertEqual(raw, plain)
            self.assertEqual(output.getvalue(), message + "\n")

    def test_middle_qr_failure_keeps_all_text_and_other_codes(self):
        from icalendar import Calendar
        import zxingcpp

        ticket = receipt_ticket(5)
        original = calendar.build_qr_image
        calls = 0

        def fail_middle(payload, config):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError("Beispielperson Art 3")
            return original(payload, config)

        output = io.StringIO()
        with patch.object(calendar, "build_qr_image", side_effect=fail_middle), contextlib.redirect_stderr(output):
            raw = app.render(ticket, {"calendar_qr": {"enabled": True}})

        for appointment in ticket.appointments:
            self.assertIn(appointment.time.encode(), raw)
            self.assertIn(appointment.kind.encode(), raw)
        self.assertNotIn("Beispielperson", output.getvalue())
        self.assertNotIn("Art 3", output.getvalue())
        self.assertEqual(output.getvalue(), "calendar QR generation failed\n")
        decoded_times = []
        for page in decode_pages(raw):
            decoded = zxingcpp.read_barcode(page.qr_image().convert("L"))
            self.assertIsNotNone(decoded)
            event = Calendar.from_ical(decoded.bytes).walk("VEVENT")
            self.assertEqual(len(event), 1)
            decoded_times.append(event[0].decoded("DTSTART"))
        self.assertEqual(decoded_times, [
            datetime(2026, 9, 17, 7, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 17, 8, 30, tzinfo=timezone.utc),
            datetime(2026, 9, 17, 12, 45, tzinfo=timezone.utc),
            datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc),
        ])

    def test_over_2400_dot_row_falls_back_atomically(self):
        from PIL import Image

        ticket = app.ParsedTicket("Beispielperson", [
            app.Appointment("Do.", "17.09.2026", "09:00", "A" * 350),
        ])
        plain = app.render(ticket, {})
        output = io.StringIO()
        with patch.object(calendar, "build_qr_image", return_value=Image.new("1", (219, 219), 1)), \
                contextlib.redirect_stderr(output):
            raw = app.render(ticket, {"calendar_qr": {"enabled": True}})
        self.assertEqual(raw, plain)
        self.assertEqual(decode_pages(raw), [])
        self.assertEqual(output.getvalue(), "calendar QR generation failed\n")

    def test_disabled_qr_does_not_generate_calendar(self):
        with patch.object(calendar, "build_icalendar") as generate, patch.object(calendar, "build_qr_image") as image:
            app.render(app.parse_t2med(TEXT), {"calendar_qr": {"enabled": False}})
        generate.assert_not_called()
        image.assert_not_called()

    def test_malformed_qr_configuration_does_not_break_text_bon(self):
        ticket = app.parse_t2med(TEXT)
        with contextlib.redirect_stderr(io.StringIO()):
            raw = app.render(ticket, {"calendar_qr": "not a table"})
        self.assertEqual(raw, app.render(ticket, {}))


if __name__ == "__main__":
    unittest.main()
