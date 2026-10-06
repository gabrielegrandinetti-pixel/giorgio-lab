"""Verifica visualizzazione e copia del codice senza modello reale."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'Richiede un display Tkinter')
class ChatFormatUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from codex_app import GiorgioApp
        self.tk, self.App = tk, GiorgioApp
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_patch = patch('codex_app.SETTINGS', Path(self.temp.name) / 'settings.json')
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.apps = []
        self.addCleanup(self.dispose)

    def dispose(self):
        for app in self.apps:
            if app.root.winfo_exists():
                app.close()

    def app(self):
        root = self.tk.Tk()
        with patch.object(self.App, 'check_ollama'):
            app = self.App(root)
        self.apps.append(app)
        root.update()
        return app

    def test_complete_stream_becomes_tagged_code_with_copy_button(self):
        app = self.app()
        answer = 'Ecco:\n```python\nprint("ciao")\n```\nFine.'
        app.append_text(answer[:12])
        app.append_text(answer[12:])
        app.finalize_reply_view()
        self.assertEqual(app.chat.get('code.first', 'code.last').strip(), 'print("ciao")')
        self.assertEqual(len(app.code_buttons), 1)
        app.code_buttons[0].invoke()
        self.assertEqual(app.root.clipboard_get(), 'print("ciao")')
        self.assertIn('```python', app.transcript_text)

    def test_session_reopen_restores_format_and_button(self):
        app = self.app()
        app.say('Giorgio', '```sql\nSELECT 1;\n```')
        app.save_session()
        app.close()
        self.apps.remove(app)
        reopened = self.app()
        self.assertEqual(reopened.chat.get('code.first', 'code.last').strip(), 'SELECT 1;')
        self.assertEqual(len(reopened.code_buttons), 1)
        reopened.code_buttons[0].invoke()
        self.assertEqual(reopened.root.clipboard_get(), 'SELECT 1;')

    def test_export_keeps_markdown_fences(self):
        app = self.app()
        app.say('Giorgio', '```python\nx = 1\n```')
        destination = Path(self.temp.name) / 'chat.txt'
        with patch('codex_app.filedialog.asksaveasfilename', return_value=str(destination)):
            app.export_chat()
        self.assertIn('```python\nx = 1\n```', destination.read_text(encoding='utf-8'))

    def test_unclosed_stream_stays_plain_when_completed(self):
        app = self.app()
        app.append_text('```python\nx = 1')
        app.finalize_reply_view()
        self.assertFalse(app.chat.tag_ranges('code'))
        self.assertIn('```python', app.chat.get('1.0', 'end'))


if __name__ == '__main__':
    unittest.main()
