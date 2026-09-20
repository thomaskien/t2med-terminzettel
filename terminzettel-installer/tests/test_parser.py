import unittest
from test_runtime import app


def document(rows, name="Testperson Alpha"):
    return "TERMINE\n" + name + "\nTerminzeitpunkt              Termintyp\n" + rows + "\n"


ROW = "Do. 17.09.2026, 09:00 Kontrolle"


class ParserTests(unittest.TestCase):
    def test_normal(self):
        ticket = app.parse_t2med(document(ROW))
        self.assertEqual(ticket.patient, "Testperson Alpha")
        self.assertEqual(ticket.appointments[0].kind, "Kontrolle")

    def test_sort_and_exact_deduplication(self):
        ticket = app.parse_t2med(document("Fr. 18.09.2026, 10:00 Beratung\n" + ROW + "\n" + ROW))
        self.assertEqual([a.date for a in ticket.appointments], ["17.09.2026", "18.09.2026"])

    def test_date_and_time_normalization(self):
        ticket = app.parse_t2med(document("Mo. 7.9.2026, 9:00 Kontrolle\nMo. 07.09.2026, 09:00 Kontrolle"))
        self.assertEqual(len(ticket.appointments), 1)
        self.assertEqual(ticket.appointments[0].date, "07.09.2026")
        self.assertEqual(ticket.appointments[0].time, "09:00")

    def test_blank_gap(self):
        ticket = app.parse_t2med(document(ROW + "\n\n\nFr. 18.09.2026, 10:00 Beratung"))
        self.assertEqual(len(ticket.appointments), 2)

    def test_aligned_continuation(self):
        ticket = app.parse_t2med(document(ROW + "\n" + " " * ROW.index("Kontrolle") + "mit Beratung"))
        self.assertEqual(ticket.appointments[0].kind, "Kontrolle mit Beratung")

    def test_footer_not_in_type(self):
        ticket = app.parse_t2med(document(ROW + "\nBitte Karte mitbringen.\n    Telefonnummer 12345"))
        self.assertEqual(ticket.appointments[0].kind, "Kontrolle")

    def test_centered_footer_after_gap_not_in_type(self):
        ticket = app.parse_t2med(document(ROW + "\n\n" + " " * 32 + "Praxis Beispiel"))
        self.assertEqual(ticket.appointments[0].kind, "Kontrolle")

    def test_missing_type_rejected_even_after_valid_row(self):
        with self.assertRaises(ValueError):
            app.parse_t2med(document(ROW + "\nFr. 18.09.2026, 10:00"))

    def test_arbitrary_nonempty_type_is_valid(self):
        ticket = app.parse_t2med(document(ROW.replace("Kontrolle", "Nur Datum und Uhrzeit ohne Typ")))
        self.assertEqual(len(ticket.appointments), 1)

    def test_invalid_date_and_time_have_safe_errors(self):
        for row in ("Do. 31.02.2026, 09:00 Kontrolle", "Do. 17.09.2026, 25:00 Kontrolle"):
            with self.assertRaises(ValueError) as error:
                app.parse_t2med(document(row))
            self.assertNotIn("2026", str(error.exception))

    def test_second_page_rejected_even_for_same_patient(self):
        with self.assertRaises(ValueError):
            app.parse_t2med(document(ROW) + "\f" + document(ROW))

    def test_trailing_formfeed_and_empty_pages(self):
        ticket = app.parse_t2med(document(ROW) + "\f\n\f  ")
        self.assertEqual(len(ticket.appointments), 1)

    def test_repeated_header_rejected(self):
        with self.assertRaises(ValueError):
            app.parse_t2med(document(ROW) + "Terminzeitpunkt Termintyp\n" + ROW)

    def test_missing_patient_rejected(self):
        with self.assertRaises(ValueError):
            app.parse_t2med(document(ROW, ""))

    def test_missing_table_rejected(self):
        with self.assertRaises(ValueError):
            app.parse_t2med("unbekanntes Format")

    def test_nbsp_crlf(self):
        ticket = app.parse_t2med(document(ROW).replace(" ", "\u00a0").replace("\n", "\r\n"))
        self.assertEqual(len(ticket.appointments), 1)

    def test_control_bytes_rejected_before_interpretation(self):
        with self.assertRaises(ValueError):
            app.parse_t2med(document(ROW + "\x1b@"))


if __name__ == "__main__":
    unittest.main()
