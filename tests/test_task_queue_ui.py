"""Test GUI del pannello di gestione della coda, senza Ollama reale."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'Richiede un display Tkinter')
class TaskQueueUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from codex_app import GiorgioApp
        self.tk = tk
        self.App = GiorgioApp
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
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

    @staticmethod
    def job(request, mode='Agente', model='modello', project=None):
        return {'request': request, 'project': project, 'attachments': ['nota.txt'],
                'history': [{'role': 'user', 'content': 'vecchio'}],
                'model': model, 'mode': mode}

    def select(self, app, index):
        app.queue_list.selection_clear(0, 'end')
        app.queue_list.selection_set(index)
        app.load_queue_selection()

    def test_panel_edits_job_and_persists_queue(self):
        app = self.make_app()
        app.task_queue = [self.job('Prima richiesta')]
        app.refresh_queue_controls()
        app.open_queue()
        self.assertIn('Prima richiesta', app.queue_list.get(0))
        app.queue_editor.delete('1.0', 'end')
        app.queue_editor.insert('1.0', 'Richiesta aggiornata')
        app.queue_mode.set('Studio')
        app.queue_model.set('qwen:nuovo')
        app.queue_response_style.set('Dettagliata')
        app.save_queue_selection()
        job = app.task_queue[0]
        self.assertEqual(job['request'], 'Richiesta aggiornata')
        self.assertEqual(job['mode'], 'Studio')
        self.assertEqual(job['model'], 'qwen:nuovo')
        self.assertEqual(job['response_style'], 'Dettagliata')
        self.assertEqual(job['attachments'], ['nota.txt'])
        self.assertEqual(job['history'], [])
        app.save_session()
        self.assertEqual(app.session_store.load()['queue'][0]['request'], 'Richiesta aggiornata')

    def test_reorder_remove_and_count(self):
        app = self.make_app()
        app.task_queue = [self.job('Uno'), self.job('Due'), self.job('Tre')]
        app.refresh_queue_controls()
        app.open_queue()
        self.select(app, 1)
        app.move_queue_selection(1)
        self.assertEqual([j['request'] for j in app.task_queue], ['Uno', 'Tre', 'Due'])
        self.assertEqual(app.selected_queue_index(), 2)
        app.move_queue_selection(-1)
        self.assertEqual([j['request'] for j in app.task_queue], ['Uno', 'Due', 'Tre'])
        app.remove_queue_selection()
        self.assertEqual([j['request'] for j in app.task_queue], ['Uno', 'Tre'])
        self.assertEqual(app.queue_manage_button.cget('text'), 'Gestisci coda (2)')

    def test_start_selected_promotes_stably_then_runs(self):
        app = self.make_app()
        app.task_queue = [self.job('Uno'), self.job('Due'), self.job('Tre')]
        app.refresh_queue_controls()
        app.open_queue()
        self.select(app, 2)
        with patch.object(app, 'run_next') as run_next:
            app.start_queue_selection()
        self.assertEqual([j['request'] for j in app.task_queue], ['Tre', 'Uno', 'Due'])
        run_next.assert_called_once_with()
        self.assertIsNone(app.queue_window)

    def test_running_job_blocks_queue_changes(self):
        app = self.make_app()
        app.task_queue = [self.job('Uno'), self.job('Due')]
        app.refresh_queue_controls()
        app.open_queue()
        app.process = object()
        with patch('codex_app.messagebox.showinfo') as info:
            app.remove_queue_selection()
        self.assertEqual([j['request'] for j in app.task_queue], ['Uno', 'Due'])
        info.assert_called_once()
        app.process = None

    def test_pending_plan_does_not_reorder_or_close_queue(self):
        app = self.make_app()
        app.task_queue = [self.job('Uno'), self.job('Due'), self.job('Tre')]
        app.refresh_queue_controls()
        app.open_queue()
        self.select(app, 2)
        app.pending = {'operations': [{}]}
        with patch('codex_app.messagebox.showinfo') as info, patch.object(app, 'run_next') as run_next:
            app.start_queue_selection()
        self.assertEqual([j['request'] for j in app.task_queue], ['Uno', 'Due', 'Tre'])
        self.assertIsNotNone(app.queue_window)
        info.assert_called_once()
        run_next.assert_not_called()


if __name__ == '__main__':
    unittest.main()
