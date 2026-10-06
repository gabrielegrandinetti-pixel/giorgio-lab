import importlib.util
import multiprocessing as mp
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
import zipfile
from core.attachments import read_document, select_context
from core.executor import apply_approved, fingerprint
from core.backup import BackupManager


def slow_worker(event):
    event.set()
    time.sleep(30)


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_text_contents_are_really_read_and_retrieved(self):
        path = self.root / 'lezione.txt'
        path.write_text('Introduzione.\n' + 'abc ' * 400 + '\nLa varianza misura la dispersione.', encoding='utf-8')
        document = read_document(str(path))
        result = select_context([document], 'Spiegami la varianza', budget=1600)
        self.assertIn('La varianza misura la dispersione', result)
        self.assertIn('lezione.txt', result)

    @unittest.skipUnless(importlib.util.find_spec('reportlab'), 'Fixture PDF richiede reportlab opzionale')
    def test_pdf_text_and_page_citations(self):
        from reportlab.pdfgen import canvas
        path = self.root / 'lezione.pdf'
        writer = canvas.Canvas(str(path))
        writer.drawString(50, 700, 'La probabilita di un evento certo vale uno.')
        writer.save()
        document = read_document(str(path))
        result = select_context([document], 'probabilita')
        self.assertIn('evento certo vale uno', result)
        self.assertIn('pagina 1', result)

    def test_scanned_pdf_reports_no_extractable_text(self):
        from pypdf import PdfWriter
        path = self.root / 'scan.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=400, height=400)
        with path.open('wb') as output:
            writer.write(output)
        with self.assertRaisesRegex(ValueError, 'nessun testo estraibile'):
            read_document(str(path))

    def test_docx_real_text(self):
        path = self.root / 'note.docx'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Contenuto vero</w:t></w:r></w:p></w:body></w:document>')
        self.assertIn('Contenuto vero', read_document(str(path)).sections[0][1])

    def test_unsupported_image_is_not_passed_as_text(self):
        path = self.root / 'immagine.png'
        path.write_bytes(b'fake')
        with self.assertRaisesRegex(ValueError, 'formato non supportato'):
            read_document(str(path))

    def test_binary_is_rejected(self):
        path = self.root / 'binary.txt'
        path.write_bytes(b'abc\x00')
        with self.assertRaisesRegex(ValueError, 'binario'):
            read_document(str(path))

    def test_context_is_bounded(self):
        path = self.root / 'long.txt'
        path.write_text('testo ' * 1000)
        self.assertLessEqual(len(select_context([read_document(str(path))], 'testo', 1800)), 1850)

    def operation(self, path, content, kind='modify'):
        return {'type': kind, 'path': path, 'content': content, 'reason': 'test', 'destination': None}

    def test_apply_backup_and_restore(self):
        path = self.root / 'calcoli.py'
        original = b'def somma(a,b): return a-b\n'
        path.write_bytes(original)
        result = apply_approved(str(self.root), [self.operation('calcoli.py', 'def somma(a,b): return a+b\n')], {'calcoli.py': fingerprint(path)})
        self.assertIn('Sintassi Python verificata', result)
        self.assertIn('a+b', path.read_text())
        backup = BackupManager(self.root)
        backup.restore(backup.latest_backup())
        self.assertEqual(path.read_bytes(), original)

    def test_two_backups_are_unique_when_clock_value_is_identical(self):
        target = self.root / 'same-clock.txt'
        target.write_text('contenuto', encoding='utf-8')
        manager = BackupManager(self.root)
        fixed = datetime(2026, 10, 6, 10, 24, 30, 118552)
        with patch('core.backup.datetime') as clock:
            clock.now.return_value = fixed
            first = manager.create_backup(['same-clock.txt'], 'correzione')
            second = manager.create_backup(['same-clock.txt'], 'correzione')
        self.assertNotEqual(first, second)
        self.assertTrue((first / 'manifest.json').is_file())
        self.assertTrue((second / 'manifest.json').is_file())

    def test_readback_failure_rolls_back(self):
        path = self.root / 'a.txt'
        path.write_text('originale')
        original_replace = __import__('os').replace
        calls = []
        def corrupt(source, destination):
            original_replace(source, destination)
            if Path(destination) == path and not calls:
                calls.append(destination)
                Path(destination).write_text('contenuto corrotto')
        with patch('core.executor.os.replace', side_effect=corrupt):
            with self.assertRaisesRegex(RuntimeError, 'rilettura diversa'):
                apply_approved(str(self.root), [self.operation('a.txt', 'nuovo')], {'a.txt': fingerprint(path)})
        self.assertEqual(path.read_text(), 'originale')

    def test_stale_plan_is_blocked(self):
        path = self.root / 'a.py'
        path.write_text('x=1')
        old = fingerprint(path)
        path.write_text('x=2')
        with self.assertRaisesRegex(ValueError, 'è cambiato'):
            apply_approved(str(self.root), [self.operation('a.py', 'x=3')], {'a.py': old})
        self.assertEqual(path.read_text(), 'x=2')

    def test_bad_syntax_is_rejected_before_any_write(self):
        path = self.root / 'a.py'
        path.write_text('x=1')
        with self.assertRaises(SyntaxError):
            apply_approved(str(self.root), [self.operation('a.py', 'def broken(')], {'a.py': fingerprint(path)})
        self.assertEqual(path.read_text(), 'x=1')
        self.assertFalse((self.root / '.giorgio_backups').exists())

    def test_second_write_failure_restores_first_file(self):
        first, second = self.root / 'a.py', self.root / 'b.py'
        first.write_text('x=1')
        second.write_text('y=1')
        import os
        replace = os.replace
        calls = []
        def fail_second(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError('simulated disk failure')
            return replace(source, destination)
        with patch('core.executor.os.replace', side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'file ripristinati'):
                apply_approved(str(self.root), [self.operation('a.py', 'x=2'), self.operation('b.py', 'y=2')], {'a.py': fingerprint(first), 'b.py': fingerprint(second)})
        self.assertEqual(first.read_text(), 'x=1')
        self.assertEqual(second.read_text(), 'y=1')
        self.assertFalse(list(self.root.glob('.giorgio-*')))

    def test_create_new_parents_then_restore(self):
        apply_approved(str(self.root), [self.operation('new/child/a.py', 'x=1', 'create')], {'new/child/a.py': None})
        backup = BackupManager(self.root)
        backup.restore(backup.latest_backup())
        self.assertFalse((self.root / 'new').exists())

    def test_mkdir_is_applied_and_verified_then_can_be_rolled_back(self):
        operation = self.operation('Stefano/Gabriele', None, 'mkdir')
        result = apply_approved(str(self.root), [operation], {'Stefano/Gabriele': None})
        target = self.root / 'Stefano' / 'Gabriele'
        self.assertTrue(target.exists())
        self.assertTrue(target.is_dir())
        self.assertIn('Applicate e verificate 1 operazioni', result)
        backup = BackupManager(self.root)
        backup.restore(backup.latest_backup())
        self.assertFalse((self.root / 'Stefano').exists())

    def test_mkdir_stale_plan_is_blocked(self):
        target = self.root / 'Stefano' / 'Gabriele'
        target.mkdir(parents=True)
        operation = self.operation('Stefano/Gabriele', None, 'mkdir')
        with self.assertRaisesRegex(Exception, 'esiste già'):
            apply_approved(str(self.root), [operation], {'Stefano/Gabriele': None})

    def test_worker_can_be_terminated_without_waiting_for_task(self):
        context = mp.get_context('spawn')
        event = context.Event()
        process = context.Process(target=slow_worker, args=(event,))
        process.start()
        try:
            self.assertTrue(event.wait(5))
            started = time.monotonic()
            process.terminate()
            process.join(timeout=2)
            self.assertFalse(process.is_alive())
            self.assertLess(time.monotonic() - started, 2)
        finally:
            if process.is_alive():
                process.kill()
                process.join()
            process.close()

class WorkerMkdirIntegrationTests(unittest.TestCase):
    """Copre il ponte chat Agente -> piano -> snapshot -> executor per MKDIR."""

    class Queue:
        def __init__(self):
            self.items = []
        def put(self, item):
            self.items.append(item)
        def close(self):
            pass
        def join_thread(self):
            pass

    def test_agent_mkdir_plan_can_be_applied_and_verified(self):
        from dataclasses import dataclass
        import sys, types
        sys.modules.setdefault("ollama", types.ModuleType("ollama"))
        from core.app_worker import work_request

        with TemporaryDirectory() as temp:
            project = Path(temp) / 'Progetto'
            project.mkdir()

            @dataclass
            class Project:
                path: Path

            class Plan:
                summary = 'Creo la cartella richiesta.'
                analysis = ''
                operations = [
                    __import__('core.operations', fromlist=['FileOperation']).FileOperation(
                        type='mkdir', path='Stefano/Gabriele', reason='Richiesta utente'
                    )
                ]

            plan = Plan()
            plan.project = Project(project)

            class FakeAgent:
                def __init__(self, *args, **kwargs):
                    self.context_builder = type('Context', (), {'max_chars': 0})()
                def set_current_project(self, value):
                    self.project = value
                def plan(self, request, attachment_context=''):
                    return plan

            queue = self.Queue()
            job = {'attachments': [], 'model': 'fake', 'project': str(project),
                   'mode': 'Agente', 'request': 'Crea una cartella Gabriele dentro Stefano',
                   'history': [], 'response_style': 'Breve'}
            with patch('core.app_worker.OllamaClient'), patch('core.app_worker.GiorgioAgent', FakeAgent):
                work_request(queue, job)

            errors = [value for kind, value in queue.items if kind == 'error']
            self.assertEqual(errors, [])
            plans = [value for kind, value in queue.items if kind == 'plan']
            self.assertEqual(len(plans), 1)
            payload = plans[0]
            self.assertEqual(payload['expected'], {'Stefano/Gabriele': None})

            result = apply_approved(payload['project'], payload['operations'], payload['expected'])
            target = project / 'Stefano' / 'Gabriele'
            self.assertTrue(target.is_dir())
            self.assertIn('Applicate e verificate 1 operazioni', result)

class ActionIntentRoutingTests(unittest.TestCase):
    """Il router non deve degradare comandi pratici a semplice chat."""

    def test_common_workspace_commands_are_actions(self):
        import sys, types
        sys.modules.setdefault('ollama', types.ModuleType('ollama'))
        from core.app_worker import is_action_request
        requests = [
            'Crea una cartella Gabriele dentro Stefano',
            'Rinomina prova.txt in finale.txt',
            'Sposta il file nella cartella archivio',
            'Muovi report.pdf dentro Documenti',
            'Cancella temp.txt',
            'Elimina la cartella vecchia',
            'Rimuovi questo file',
            'Copia config.json in backup',
            'Scrivi ciao dentro note.txt',
            'Salva queste modifiche nel file',
            'Sostituisci il valore 3 con 4',
            'Installa la dipendenza pytest',
        ]
        for request in requests:
            with self.subTest(request=request):
                self.assertTrue(is_action_request(request))

    def test_questions_remain_read_only(self):
        import sys, types
        sys.modules.setdefault('ollama', types.ModuleType('ollama'))
        from core.app_worker import is_action_request
        for request in [
            'Come funziona questo progetto?',
            'Dove viene usata la classe OperationManager?',
            'Perché questo test fallisce?',
            'Che cosa contiene il file settings.json?',
        ]:
            with self.subTest(request=request):
                self.assertFalse(is_action_request(request))
