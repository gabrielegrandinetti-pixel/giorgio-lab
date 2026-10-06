"""Integrazione del controllo Ollama nella GUI, senza rete o server reale."""
import os
import queue
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'Richiede un display Tkinter')
class OllamaStatusUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from codex_app import GiorgioApp
        self.tk, self.App = tk, GiorgioApp
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Path(self.temp.name) / 'settings.json'
        self.patch = patch('codex_app.SETTINGS', self.settings)
        self.patch.start()
        self.addCleanup(self.patch.stop)
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

    def test_success_updates_models_and_ready_state(self):
        app = self.app()
        app.ollama_check_id = 3
        app.ollama_check_running = True
        app.ollama_events.put((3, {'connected': True, 'models': [app.model, 'llama:3b'],
                                   'selected': app.model, 'message': 'Ollama pronto · ' + app.model}))
        app.poll_ollama()
        self.assertEqual(app.available_models, [app.model, 'llama:3b'])
        self.assertIn('pronto', app.state.get())
        self.assertFalse(app.ollama_check_running)
        self.assertEqual(str(app.ollama_button['state']), 'normal')

    def test_stale_result_is_ignored(self):
        app = self.app()
        app.ollama_check_id = 9
        app.ollama_check_running = True
        app.ollama_events.put((8, {'connected': True, 'models': ['vecchio'],
                                   'selected': 'vecchio', 'message': 'vecchio'}))
        app.poll_ollama()
        self.assertEqual(app.available_models, [])
        self.assertTrue(app.ollama_check_running)

    def test_result_does_not_overwrite_active_job_status(self):
        app = self.app()
        app.process = object()
        app.state.set('Sto lavorando…')
        app.ollama_check_id = 1
        app.ollama_events.put((1, {'connected': False, 'models': [],
                                   'selected': app.model, 'message': 'Ollama non raggiungibile'}))
        app.poll_ollama()
        self.assertEqual(app.state.get(), 'Sto lavorando…')
        app.process = None

    def test_check_runs_outside_gui_thread(self):
        app = self.app()
        called = queue.Queue()
        def inspect(model, factory):
            called.put(threading.current_thread().name)
            return {'connected': True, 'models': [model], 'selected': model,
                    'message': 'Ollama pronto · ' + model}
        with patch('codex_app.inspect_ollama', side_effect=inspect):
            app.check_ollama(force=True)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and app.ollama_events.empty():
                app.root.update()
                time.sleep(0.01)
        self.assertNotEqual(called.get_nowait(), threading.current_thread().name)
        app.poll_ollama()
        self.assertIn('pronto', app.state.get())


if __name__ == '__main__':
    unittest.main()
