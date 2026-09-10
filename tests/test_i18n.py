import csv
import tempfile
import unittest
from pathlib import Path
from string import Formatter
from unittest.mock import patch
from photoclean import i18n
from photoclean.core import ScanResult, export_csv, scan


class LanguageTests(unittest.TestCase):
    def tearDown(self):
        i18n.language = 'pl'

    def test_catalog_placeholders_match(self):
        def fields(text):
            return {field for _, field, _, _ in Formatter().parse(text) if field is not None}
        for original, translated in i18n.EN.items():
            self.assertEqual(fields(original), fields(translated), original)

    def test_corrupt_missing_and_unknown_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            self.assertEqual(i18n.load_language(path), 'pl')
            for value in ('bad json', '[]', 'null', '{"language":"xx"}'):
                path.write_text(value, encoding='utf-8')
                self.assertEqual(i18n.load_language(path), 'pl')
            i18n.save_language(path, 'en')
            with patch('photoclean.i18n.os.replace', side_effect=OSError('blocked')):
                with self.assertRaises(OSError):
                    i18n.save_language(path, 'pl')
            self.assertEqual(i18n.load_language(path), 'en')
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_english_scan_warning_and_csv(self):
        i18n.language = 'en'
        with tempfile.TemporaryDirectory() as folder:
            result = scan([Path(folder) / 'missing'])
            self.assertIn('folder unavailable', result.warnings[0])
            target = Path(folder) / 'report.csv'
            export_csv(ScanResult(), target)
            with target.open(encoding='utf-8-sig') as stream:
                self.assertEqual(next(csv.reader(stream, delimiter=';'))[:3], ['Group', 'Type', 'Path'])
