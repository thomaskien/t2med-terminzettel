import contextlib
import io
import unittest
from unittest.mock import patch
from test_installer import installer, cfg
from test_runtime import app, TEXT


class ReceiptSetupTests(unittest.TestCase):
    def configure(self, config, answers):
        with patch.object(installer.sys.stdin, 'isatty', return_value=True), patch('builtins.input', side_effect=answers), contextlib.redirect_stdout(io.StringIO()):
            return cfg.tomllib.loads(installer.configure_receipt(cfg.dump_config(config)))

    def test_initial_setup_multiline_header_default_footer_and_qr(self):
        result = self.configure({}, ['', 'Praxis "Beispiel"', 'Musterstraße 1 / Hof', '', '', '', '', ''])
        self.assertEqual(result['header']['text'], 'Praxis "Beispiel"\nMusterstraße 1 / Hof')
        self.assertTrue(result['header']['enabled'])
        self.assertTrue(result['calendar_qr']['enabled'])
        self.assertEqual(result['calendar_qr']['summary'], 'Termin Arztpraxis')
        self.assertEqual(result['calendar_qr']['caption'], 'Termin speichern')
        self.assertEqual(result['calendar_qr']['max_width_dots'], 256)
        self.assertTrue(result['footer']['enabled'])
        self.assertEqual(result['footer']['text'], 'Können Sie einen Termin nicht wahrnehmen, sagen Sie bitte unbedingt Bescheid.')

    def test_update_enter_keeps_texts_and_disabled_qr(self):
        original = {'header': {'enabled': True, 'text': 'Bestehende Praxis\nTelefon'},
                    'calendar_qr': {'enabled': False, 'max_width_dots': 360},
                    'footer': {'enabled': True, 'text': 'Bisheriger Hinweis'},
                    'layout': {'double_height': False}, 'output': {'queue': 'Custom'}}
        self.assertEqual(self.configure(original, ['', '', '', '', '']), original)

    def test_each_block_can_be_disabled_without_deleting_text(self):
        original = {'header': {'enabled': True, 'text': 'Praxis'},
                    'calendar_qr': {'enabled': True}, 'footer': {'enabled': True, 'text': 'Hinweis'}}
        result = self.configure(original, ['nein', 'n', 'no'])
        for section in ('header', 'calendar_qr', 'footer'):
            self.assertFalse(result[section]['enabled'])
        self.assertEqual(result['header']['text'], 'Praxis')
        self.assertEqual(result['footer']['text'], 'Hinweis')

    def test_configure_receipt_does_not_migrate_old_qr_width(self):
        result = self.configure({'calendar_qr': {'enabled': True, 'max_width_dots': 360}}, ['n', '', '', 'n'])
        self.assertEqual(result['calendar_qr']['max_width_dots'], 360)

    def test_individual_qr_width_is_preserved(self):
        result = self.configure({'calendar_qr': {'enabled': True, 'max_width_dots': 375}}, ['n', '', '', 'n'])
        self.assertEqual(result['calendar_qr']['max_width_dots'], 375)

    def test_custom_calendar_title_is_saved(self):
        result = self.configure({'calendar_qr': {'enabled': True}}, ['n', '', 'Nachkontrolle Praxis', 'n'])
        self.assertEqual(result['calendar_qr']['summary'], 'Nachkontrolle Praxis')

    def test_enter_keeps_existing_calendar_title(self):
        original = {'calendar_qr': {'enabled': True, 'summary': 'Bestehender Kalendername'}}
        result = self.configure(original, ['n', '', '', 'n'])
        self.assertEqual(result['calendar_qr']['summary'], 'Bestehender Kalendername')

    def test_disabled_qr_does_not_ask_for_calendar_title(self):
        original = {'calendar_qr': {'enabled': False, 'summary': 'Bleibt erhalten'}}
        with patch.object(installer, 'ask_calendar_title') as ask_title:
            result = self.configure(original, ['n', '', 'n'])
        ask_title.assert_not_called()
        self.assertEqual(result['calendar_qr']['summary'], 'Bleibt erhalten')

    def test_calendar_title_rejects_control_characters(self):
        output = io.StringIO()
        with patch('builtins.input', side_effect=['Unsicher\x7fTitel', 'Sicherer Titel']), contextlib.redirect_stdout(output):
            self.assertEqual(installer.ask_calendar_title('Termin Arztpraxis'), 'Sicherer Titel')
        self.assertIn('ohne Steuerzeichen', output.getvalue())

    def test_invalid_answer_and_control_characters_are_retried(self):
        result = self.configure({}, ['maybe', 'j', 'Bad\x1b@', 'Praxis', '', 'n', 'n'])
        self.assertEqual(result['header']['text'], 'Praxis')

    def test_text_can_be_cleared_explicitly(self):
        result = self.configure({'header': {'enabled': True, 'text': 'Alt'}}, ['', '-', 'n', 'n'])
        self.assertEqual(result['header']['text'], '')

    def test_cancel_does_not_start_system_changes(self):
        with patch.object(installer, 'plan', return_value={'/etc/terminzettel/config.toml': '[output]\nqueue="TMm10"\n'}), patch.object(installer.sys.stdin, 'isatty', return_value=True), patch('builtins.input', side_effect=EOFError), patch.object(installer, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'Einrichtung abgebrochen'):
                installer.install()
        run.assert_not_called()

    def test_without_terminal_there_are_no_questions_or_overrides(self):
        text = '[calendar_qr]\nenabled=false\n'
        with patch.object(installer.sys.stdin, 'isatty', return_value=False), patch('builtins.input') as ask:
            self.assertEqual(installer.configure_receipt(text), text)
        ask.assert_not_called()


def decode_lines(raw):
    """Read printer text and character-size commands, skipping the QR raster."""
    lines, text, size, pos = [], bytearray(), 0, 0
    while pos < len(raw):
        if raw[pos:pos+4] == b'\x1dv0\x00':
            width = int.from_bytes(raw[pos+4:pos+6], 'little')
            rows = int.from_bytes(raw[pos+6:pos+8], 'little')
            pos += 8 + width * rows
        elif raw[pos:pos+2] == b'\x1d!':
            size = raw[pos+2]
            pos += 3
        elif raw[pos:pos+2] == b'\x1b@':
            size = 0
            pos += 2
        elif raw[pos] in (0x1b, 0x1d):
            pos += 3
        elif raw[pos] == 10:
            if text:
                lines.append((text.decode('cp858'), size))
                text.clear()
            pos += 1
        else:
            text.append(raw[pos])
            pos += 1
    return lines, size


class ReceiptLayoutTests(unittest.TestCase):
    def config(self):
        return {'header': {'enabled': True, 'text': 'Praxis Beispiel'},
                'footer': {'enabled': True, 'text': 'Bitte unbedingt Bescheid sagen.'},
                'calendar_qr': {'enabled': True}}

    def test_all_text_is_double_height_and_width_and_keeps_case(self):
        raw = app.render(app.parse_t2med(TEXT), self.config())
        lines, ending_height = decode_lines(raw)
        self.assertTrue(all(size == 0x11 for text, size in lines))
        self.assertIn(('Praxis Beispiel', 0x11), lines)
        self.assertIn(('Testperson Alpha', 0x11), lines)
        self.assertIn(('09:00  Kontrolle', 0x11), lines)
        self.assertIn(('Bitte unbedingt', 0x11), lines)
        self.assertIn(('Bescheid sagen.', 0x11), lines)
        self.assertTrue(all(len(text) <= 17 for text, size in lines))
        self.assertFalse(ending_height)
        self.assertLess(raw.index(b'Praxis Beispiel'), raw.index(b'IHRE TERMINE'))
        self.assertLess(raw.index(b'Kontrolle'), raw.index(b'\x1dv0\x00'))
        self.assertLess(raw.index(b'\x1dv0\x00'), raw.index(b'Bitte unbedingt'))

    def test_normal_height_can_be_restored_in_toml(self):
        config = self.config()
        config['layout'] = {'double_height': False, 'double_width': False, 'heading_double_height': False}
        lines, ending_height = decode_lines(app.render(app.parse_t2med(TEXT), config))
        self.assertTrue(all(not height for text, height in lines))
        self.assertFalse(ending_height)

    def test_qr_only_receipt_resets_size_before_cut(self):
        lines, ending_height = decode_lines(app.render(app.parse_t2med(TEXT), {'calendar_qr': {'enabled': True}}))
        self.assertTrue(all(size == 0x11 for text, size in lines))
        self.assertFalse(ending_height)


if __name__ == '__main__':
    unittest.main()
