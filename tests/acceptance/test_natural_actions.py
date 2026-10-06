import tempfile
import unittest
from pathlib import Path
import sys
import types

# Headless acceptance tests do not exercise Ollama. Keep app_worker importable
# without requiring the optional Ollama SDK in the test container.
sys.modules.setdefault('ollama', types.SimpleNamespace())

from core.action_intent import parse_simple_action
from core.executor import apply_approved


class NaturalActionTests(unittest.TestCase):
    def test_exact_real_world_request_parses_and_executes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'Stefano').mkdir()
            request = f'Crea una cartella con il nome Gabriele nella cartella Stefano in questo percorso {root}'
            op = parse_simple_action(request, root)
            self.assertIsNotNone(op)
            self.assertEqual(op['type'], 'mkdir')
            self.assertEqual(op['path'], 'Stefano/Gabriele')
            apply_approved(str(root), [op], {'Stefano/Gabriele': None})
            target = root / 'Stefano' / 'Gabriele'
            self.assertTrue(target.exists() and target.is_dir())

    def test_varied_names(self):
        root = Path(r'C:\Users\gabri\Desktop\Progetto')
        cases = {
            'Crea una cartella Test': 'Test',
            'Creami una directory Prove dentro la cartella Archivio': 'Archivio/Prove',
            'Crea una cartella chiamata Foto nella cartella Backup': 'Backup/Foto',
            'Crea una cartella con il nome Alpha dentro la directory Beta': 'Beta/Alpha',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_simple_action(text, root)['path'], expected)

    def test_explicit_matching_windows_base(self):
        root = Path(r'C:\Users\gabri\Desktop\Progetto')
        text = r'Crea una cartella con il nome Gabriele nella cartella Stefano in questo percorso C:/Users/gabri/Desktop/Progetto'
        self.assertEqual(parse_simple_action(text, root)['path'], 'Stefano/Gabriele')

    def test_different_explicit_base_falls_back(self):
        root = Path(r'C:\Users\gabri\Desktop\Progetto')
        text = r'Crea una cartella Test nel percorso C:/Users/gabri/Desktop/Altro'
        self.assertIsNone(parse_simple_action(text, root))

    def test_questions_and_unsafe_names_do_not_parse(self):
        root = Path(r'C:\Users\gabri\Desktop\Progetto')
        for text in ['Come creo una cartella Test?', 'Crea una cartella ../Fuori', 'Crea una cartella A/B']:
            with self.subTest(text=text):
                self.assertIsNone(parse_simple_action(text, root))

    def test_create_empty_file_from_natural_language_is_verified(self):
        cases = {
            'Crea il file note.txt': 'note.txt',
            'Creami un file vuoto appunti.md': 'appunti.md',
            'Aggiungi un file report.csv dentro la cartella Dati': 'Dati/report.csv',
            'Crea un file chiamato prova.json': 'prova.json',
        }
        for text, expected in cases.items():
            with self.subTest(text=text), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                if '/' in expected:
                    (root / expected.split('/')[0]).mkdir()
                op = parse_simple_action(text, root)
                self.assertIsNotNone(op)
                self.assertEqual(op['type'], 'create')
                self.assertEqual(op['path'], expected)
                self.assertEqual(op['content'], '')
                apply_approved(str(root), [op], {expected: None})
                target = root / expected
                self.assertTrue(target.is_file())
                self.assertEqual(target.read_bytes(), b'')

    def test_create_file_ambiguous_or_unsafe_falls_back(self):
        root = Path(r'C:\Users\gabri\Desktop\Progetto')
        for text in [
            'Crea un file',
            'Crea un file senza nome',
            'Crea il file ../fuori.txt',
            'Come creo il file note.txt?',
        ]:
            with self.subTest(text=text):
                self.assertIsNone(parse_simple_action(text, root))

    def test_rename_file_from_natural_language_is_verified(self):
        cases = {
            'Rinomina prova.txt in finale.txt': ('prova.txt', 'finale.txt'),
            'Rinominami appunti.md come lezione.md': ('appunti.md', 'lezione.md'),
            'Rinomina il file dati.csv in archivio.csv': ('dati.csv', 'archivio.csv'),
        }
        for text, (source, destination) in cases.items():
            with self.subTest(text=text), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                src = root / source
                src.write_text('immutato', encoding='utf-8')
                from core.executor import fingerprint
                source_fp = fingerprint(src)
                op = parse_simple_action(text, root)
                self.assertEqual(op['type'], 'move')
                self.assertEqual(op['path'], source)
                self.assertEqual(op['destination'], destination)
                apply_approved(str(root), [op], {source: source_fp, destination: None})
                self.assertFalse(src.exists())
                self.assertEqual((root / destination).read_text(encoding='utf-8'), 'immutato')

    def test_rename_refuses_existing_destination_without_damage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src, dst = root / 'a.txt', root / 'b.txt'
            src.write_text('A', encoding='utf-8')
            dst.write_text('B', encoding='utf-8')
            from core.executor import fingerprint
            op = parse_simple_action('Rinomina a.txt in b.txt', root)
            with self.assertRaises(Exception):
                apply_approved(str(root), [op], {'a.txt': fingerprint(src), 'b.txt': None})
            self.assertEqual(src.read_text(encoding='utf-8'), 'A')
            self.assertEqual(dst.read_text(encoding='utf-8'), 'B')

    def test_rename_unsafe_or_ambiguous_falls_back(self):
        root = Path(r'C:\Users\gabri\Desktop\Progetto')
        for text in ['Rinomina a.txt in ../b.txt', 'Rinomina file.txt', 'Come rinomino a.txt in b.txt?', 'Rinomina a.txt in a.txt']:
            with self.subTest(text=text):
                self.assertIsNone(parse_simple_action(text, root))


    def test_copy_binary_file_from_natural_language_is_verified(self):
        cases = {
            'Copia dati.csv nella cartella Backup': ('dati.csv', 'Backup/dati.csv'),
            'Copiami foto.jpg in Immagini': ('foto.jpg', 'Immagini/foto.jpg'),
            'Duplica blob.bin dentro la directory Archivio': ('blob.bin', 'Archivio/blob.bin'),
        }
        for text, (source, destination) in cases.items():
            with self.subTest(text=text), tempfile.TemporaryDirectory() as td:
                root = Path(td); src = root / source
                payload = b'\x00\xffbinary\r\n'; src.write_bytes(payload)
                from core.executor import fingerprint
                op = parse_simple_action(text, root)
                self.assertEqual(op['type'], 'copy')
                self.assertEqual(op['destination'], destination)
                apply_approved(str(root), [op], {source: fingerprint(src), destination: None})
                self.assertEqual(src.read_bytes(), payload)
                self.assertEqual((root / destination).read_bytes(), payload)

    def test_copy_refuses_existing_destination_without_damage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); src = root / 'a.txt'; dst = root / 'Backup' / 'a.txt'
            dst.parent.mkdir(); src.write_text('A'); dst.write_text('B')
            from core.executor import fingerprint
            op = parse_simple_action('Copia a.txt nella cartella Backup', root)
            with self.assertRaises(Exception):
                apply_approved(str(root), [op], {'a.txt': fingerprint(src), 'Backup/a.txt': None})
            self.assertEqual(src.read_text(), 'A'); self.assertEqual(dst.read_text(), 'B')


    def test_exact_modify_from_natural_language_is_verified(self):
        cases = [
            ('Nel file config.py cambia DEBUG = False in DEBUG = True', 'config.py', 'DEBUG = False', 'DEBUG = True'),
            ('Sostituisci timeout=10 con timeout=30 nel file settings.ini', 'settings.ini', 'timeout=10', 'timeout=30'),
            ('Nel file app.txt sostituisci versione 5 in versione 6', 'app.txt', 'versione 5', 'versione 6'),
        ]
        for request, name, old, new in cases:
            with self.subTest(request=request), tempfile.TemporaryDirectory() as td:
                root = Path(td); target = root / name
                target.write_text(f'prima\n{old}\ndopo\n', encoding='utf-8')
                from core.executor import fingerprint
                before = fingerprint(target)
                op = parse_simple_action(request, root)
                self.assertIsNotNone(op)
                self.assertEqual(op['type'], 'modify')
                self.assertEqual(op['path'], name)
                apply_approved(str(root), [op], {name: before})
                self.assertEqual(target.read_text(encoding='utf-8'), f'prima\n{new}\ndopo\n')

    def test_exact_modify_refuses_zero_or_multiple_matches(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); target = root / 'config.py'
            target.write_text('DEBUG = False\nDEBUG = False\n', encoding='utf-8')
            self.assertIsNone(parse_simple_action('Nel file config.py cambia DEBUG = False in DEBUG = True', root))
            self.assertEqual(target.read_text(encoding='utf-8'), 'DEBUG = False\nDEBUG = False\n')
            target.write_text('DEBUG = True\n', encoding='utf-8')
            self.assertIsNone(parse_simple_action('Nel file config.py cambia DEBUG = False in DEBUG = True', root))
            self.assertEqual(target.read_text(encoding='utf-8'), 'DEBUG = True\n')


    def test_delete_quarantines_binary_file_and_verifies(self):
        import os
        from core.executor import fingerprint
        cases = ['Elimina foto.jpg', 'Cancella pacchetto.zip', 'Rimuovi old.log']
        for i, request in enumerate(cases):
            with self.subTest(request=request), tempfile.TemporaryDirectory() as td:
                root = Path(td); name = request.split()[-1]
                target = root / name; payload = os.urandom(257 + i); target.write_bytes(payload)
                before = fingerprint(target)
                op = parse_simple_action(request, root)
                self.assertIsNotNone(op); self.assertEqual(op['type'], 'delete')
                apply_approved(str(root), [op], {op['path']: before})
                self.assertFalse(target.exists())
                quarantined = list((root / '.giorgio_trash').rglob(name))
                self.assertEqual(len(quarantined), 1)
                self.assertEqual(quarantined[0].read_bytes(), payload)

    def test_delete_ambiguous_name_does_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root/'A').mkdir(); (root/'B').mkdir()
            (root/'A'/'dati.log').write_bytes(b'A'); (root/'B'/'dati.log').write_bytes(b'B')
            self.assertIsNone(parse_simple_action('Elimina dati.log', root))
            self.assertEqual((root/'A'/'dati.log').read_bytes(), b'A')
            self.assertEqual((root/'B'/'dati.log').read_bytes(), b'B')

    def test_delete_question_is_not_action(self):
        from core.app_worker import is_action_request
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'config.py').write_text('x=1')
            self.assertFalse(is_action_request('Cosa succede se elimino config.py?'))
            self.assertIsNone(parse_simple_action('Cosa succede se elimino config.py?', root))
            self.assertTrue((root/'config.py').exists())

    def test_delete_toctou_fingerprint_change_aborts(self):
        from core.executor import fingerprint
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); target=root/'volatile.bin'; target.write_bytes(b'old')
            op=parse_simple_action('Elimina volatile.bin', root); before=fingerprint(target)
            target.write_bytes(b'changed')
            with self.assertRaises(Exception):
                apply_approved(str(root), [op], {'volatile.bin': before})
            self.assertEqual(target.read_bytes(), b'changed')


if __name__ == '__main__':
    unittest.main()
