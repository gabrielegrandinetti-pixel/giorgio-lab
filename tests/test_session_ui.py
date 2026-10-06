"""Test GUI: eseguire con un display Tkinter (anche Xvfb), senza Ollama."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'Richiede un display Tkinter')
class SessionUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from codex_app import GiorgioApp
        self.tk = tk
        self.App = GiorgioApp
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / 'progetto'
        self.project.mkdir()
        self.settings_patch = patch('codex_app.SETTINGS', self.base / 'settings.json')
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.apps = []
        self.addCleanup(self.dispose)

    def dispose(self):
        for app in self.apps:
            if app.root.winfo_exists():
                app.close()

    def make_app(self):
        root = self.tk.Tk()
        with patch.object(self.App, 'check_ollama'):
            app = self.App(root)
        self.apps.append(app)
        root.update()
        return app

    def select(self, app):
        app.projects = [str(self.project)]
        app.refresh_projects()
        app.project_list.selection_clear(0, 'end')
        app.project_list.selection_set(1)
        app.select_project()

    def test_draft_is_saved_automatically_while_window_stays_open(self):
        import time
        app = self.make_app()
        app.save_session()
        app.input.insert('1.0', 'Bozza salvata automaticamente')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            app.root.update()
            saved = app.session_store.load()
            if saved and saved['draft'] == 'Bozza salvata automaticamente':
                break
            time.sleep(0.01)
        else:
            self.fail('La bozza non è stata salvata automaticamente.')
        self.assertTrue(app.root.winfo_exists())

    def test_reopen_recovers_draft_history_mode_and_queue(self):
        app = self.make_app()
        self.select(app)
        app.mode.set('Studio')
        app.input.insert('1.0', 'Primo incarico')
        app.enqueue()
        app.input.insert('1.0', 'Bozza da finire')
        app.history = [{'role': 'user', 'content': 'domanda precedente'}]
        app.say('Tu', 'domanda precedente')
        app.close()
        self.apps.remove(app)
        reopened = self.make_app()
        self.assertEqual(reopened.current_project(), str(self.project))
        self.assertEqual(reopened.mode.get(), 'Studio')
        self.assertEqual(reopened.input.get('1.0', 'end-1c'), 'Bozza da finire')
        self.assertEqual(reopened.task_queue[0]['request'], 'Primo incarico')
        self.assertEqual(reopened.history[0]['content'], 'domanda precedente')
        self.assertIsNone(reopened.process)
        self.assertIsNone(reopened.pending)

    def test_interrupted_job_recovered_without_automatic_execution(self):
        app = self.make_app()
        app.active_job = {'request': 'Lavoro interrotto', 'project': str(self.project),
                          'attachments': [], 'history': [], 'model': 'modello', 'mode': 'Agente'}
        app.save_session()
        # Simula la scomparsa dell'app senza il salvataggio di una chiusura normale.
        if app.save_timer:
            app.root.after_cancel(app.save_timer)
        if app.poll_timer:
            app.root.after_cancel(app.poll_timer)
        app.root.destroy()
        self.apps.remove(app)
        reopened = self.make_app()
        self.assertEqual(reopened.task_queue[0]['request'], 'Lavoro interrotto')
        self.assertIsNone(reopened.process)
        self.assertEqual(reopened.history, [])

    def test_missing_project_keeps_job_waiting(self):
        app = self.make_app()
        job = {'request': 'Modifica', 'project': str(self.base / 'manca'),
               'attachments': [], 'history': [], 'model': 'modello', 'mode': 'Agente'}
        app.task_queue = [job]
        with patch.object(app, 'start_job') as launch:
            app.run_next()
        launch.assert_not_called()
        self.assertEqual(app.task_queue, [job])

    def test_queue_start_failure_restores_job_and_preserves_draft(self):
        app = self.make_app()
        self.select(app)
        app.history = [{'role': 'assistant', 'content': 'contesto precedente'}]
        app.mode.set('Chat')
        app.input.insert('1.0', 'Incarico')
        app.enqueue()
        app.input.insert('1.0', 'Bozza diversa')
        with patch('codex_app.mp.get_context', side_effect=OSError('Avvio worker fallito')):
            app.run_next()
        self.assertEqual(app.task_queue[0]['request'], 'Incarico')
        self.assertEqual(app.input.get('1.0', 'end-1c'), 'Bozza diversa')
        self.assertEqual(app.history, [{'role': 'assistant', 'content': 'contesto precedente'}])
        self.assertEqual(app.mode.get(), 'Chat')
        self.assertIsNone(app.active_job)
        app.save_session()
        self.assertEqual(app.session_store.load()['queue'][0]['request'], 'Incarico')

    def test_direct_start_failure_keeps_request_and_does_not_add_user_message(self):
        app = self.make_app()
        app.input.insert('1.0', 'Richiesta da riprovare')
        with patch('codex_app.mp.get_context', side_effect=OSError('Avvio worker fallito')):
            app.send_or_stop()
        self.assertEqual(app.input.get('1.0', 'end-1c'), 'Richiesta da riprovare')
        self.assertFalse(any(item.get('role') == 'user' for item in app.history))
        self.assertIsNone(app.active_job)

    def test_queue_completes_with_fake_worker_and_keeps_draft(self):
        import queue
        from types import SimpleNamespace
        class Events(queue.Queue):
            def close(self):
                pass
        class Process:
            def __init__(self, target, args, daemon):
                self.events, self.job = args
            def start(self):
                self.events.put(('text', 'Risposta verificata'))
                self.events.put(('done', None))
            def join(self, timeout=None):
                pass
            def is_alive(self):
                return False
            def close(self):
                pass
        app = self.make_app()
        self.select(app)
        app.mode.set('Studio')
        app.input.insert('1.0', 'Incarico in coda')
        app.enqueue()
        app.input.insert('1.0', 'Bozza diversa')
        app.history = [{'role': 'user', 'content': 'vecchio contesto'}]
        with patch('codex_app.mp.get_context', return_value=SimpleNamespace(Queue=Events, Process=Process)):
            app.run_next()
        self.assertEqual(app.process.job['history'], [])
        self.assertEqual(app.process.job['mode'], 'Studio')
        app.poll()
        self.assertIsNone(app.process)
        self.assertIsNone(app.active_job)
        self.assertEqual(app.task_queue, [])
        self.assertEqual(app.input.get('1.0', 'end-1c'), 'Bozza diversa')
        self.assertEqual(app.history[-1]['content'], 'Risposta verificata')
        app.save_session()
        self.assertIsNone(app.session_store.load()['active_job'])

    def test_pending_plan_blocks_next_job(self):
        app = self.make_app()
        app.input.insert('1.0', 'Incarico')
        app.enqueue()
        app.pending = {'operations': [{}]}
        with patch('codex_app.messagebox.showinfo'), patch.object(app, 'start_job') as launch:
            app.run_next()
        launch.assert_not_called()
        self.assertEqual(len(app.task_queue), 1)


if __name__ == '__main__':
    unittest.main()
