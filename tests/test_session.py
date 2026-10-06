import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core.session import SessionStore, SessionError


def snapshot():
    return {'version': 1, 'mode': 'Studio', 'project': None,
            'draft': 'Spiegami la probabilità', 'transcript': 'Tu\nCiao\n',
            'history': [{'role': 'user', 'content': 'Ciao'}],
            'queue': [{'request': 'Leggi a.py', 'project': '/progetto',
                       'model': 'modello', 'mode': 'Agente', 'response_style': 'Dettagliata',
                       'attachments': ['a.py']}],
            'attachments': [], 'logs': ['Pronto'], 'active_job': None}


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'session.json'
        self.store = SessionStore(self.path)

    def test_roundtrip_preserves_draft_history_and_jobs(self):
        value = snapshot()
        self.store.save(value)
        restored = self.store.load()
        self.assertEqual(restored['draft'], value['draft'])
        self.assertEqual(restored['history'], value['history'])
        self.assertEqual(restored['queue'][0]['project'], '/progetto')
        self.assertEqual(restored['queue'][0]['history'], [])
        self.assertEqual(restored['queue'][0]['response_style'], 'Dettagliata')
        self.assertEqual(restored['mode'], 'Studio')

    def test_interrupted_job_is_retained_separately(self):
        value = snapshot()
        value['active_job'] = value['queue'].pop()
        self.store.save(value)
        self.assertEqual(self.store.load()['active_job']['request'], 'Leggi a.py')

    def test_failed_replace_preserves_previous_session(self):
        self.store.save(snapshot())
        original = self.path.read_bytes()
        value = snapshot()
        value['draft'] = 'modificata'
        with patch('core.session.os.replace', side_effect=OSError('disco non disponibile')):
            with self.assertRaises(OSError):
                self.store.save(value)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob('.session-*')), [])

    def test_corrupt_json_is_preserved_and_reported(self):
        original = b'{invalid json'
        self.path.write_bytes(original)
        with self.assertRaisesRegex(SessionError, 'conservata'):
            self.store.load()
        backups = list(self.path.parent.glob('session.json.invalid-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertIsNone(self.store.load())

    def test_invalid_mode_and_system_history_are_rejected(self):
        for field, value in [('mode', []), ('history', [{'role': 'system', 'content': 'istruzioni'}])]:
            data = snapshot()
            data[field] = value
            self.path.write_text(json.dumps(data))
            with self.assertRaises(SessionError):
                self.store.load()

    def test_bad_snapshot_cannot_replace_valid_one(self):
        self.store.save(snapshot())
        original = self.path.read_bytes()
        value = snapshot()
        value['draft'] = 'x' * 20001
        with self.assertRaises(SessionError):
            self.store.save(value)
        self.assertEqual(self.path.read_bytes(), original)

    def test_oversized_file_is_not_read_as_json(self):
        self.path.write_bytes(b'x' * (4 * 1024 * 1024 + 1))
        with patch('core.session.json.loads') as decoder:
            with self.assertRaises(SessionError):
                self.store.load()
        decoder.assert_not_called()

    def test_missing_session_starts_empty(self):
        self.assertIsNone(self.store.load())


if __name__ == '__main__':
    unittest.main()
