import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# I test dell'agente non richiedono Ollama installato o un server attivo.
try:
    import ollama
except ImportError:
    sys.modules['ollama'] = types.ModuleType('ollama')

from core.agent import GiorgioAgent, AgentError, FINAL_SCHEMA
from core.tools import AgentTools


class FakeModel:
    def __init__(self, decisions, operation=None):
        self.decisions = iter(decisions)
        self.prompts = []
        self.operation = operation

    def chat_json(self, messages, system_prompt=None, schema=None, **kwargs):
        self.prompts.append(messages[0]['content'])
        if schema is FINAL_SCHEMA:
            return {'summary': 'La somma usa la sottrazione.', 'analysis': '',
                    'operations': [self.operation] if self.operation else []}
        return next(self.decisions)


def read(path='calcoli.py'):
    return {'action': 'tool', 'tool': 'read_file', 'arguments': {'path': path}}


def modify(path='calcoli.py'):
    return {'type': 'modify', 'path': path, 'content': 'def somma(a,b): return a+b\n',
            'destination': None, 'reason': 'Correggere la somma'}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.root = self.workspace / 'ProgettoProva'
        self.root.mkdir()
        (self.root / 'calcoli.py').write_text('def somma(a,b): return a-b\n')
        (self.root / 'main.py').write_text('from calcoli import somma\n')

    def test_repeated_tool_is_executed_once_and_plan_is_read_only(self):
        model = FakeModel([read(), read(), read()], modify())
        events = []
        agent = GiorgioAgent(self.workspace, model, status_callback=events.append)
        original = (self.root / 'calcoli.py').read_bytes()
        with patch.object(AgentTools, 'execute', autospec=True,
                          side_effect=AgentTools.execute) as execute:
            plan = agent.plan('Nel ProgettoProva correggi somma')
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(len(model.prompts), 4)
        self.assertEqual(model.prompts[-1].count('STRUTTURA DEL PROGETTO:'), 1)
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual((self.root / 'calcoli.py').read_bytes(), original)
        self.assertTrue(any('senza progressi' in event for event in events))

    def test_failed_duplicate_does_not_hide_failure(self):
        model = FakeModel([read('missing.py')] * 3)
        plan = GiorgioAgent(self.workspace, model).plan('Nel ProgettoProva controlla somma')
        self.assertFalse(plan.steps[0].success)
        self.assertIn('File non trovato', model.prompts[-1])

    def test_unread_modification_is_blocked(self):
        (self.root / 'unrelated.txt').write_text('contenuto importante')
        model = FakeModel([{'action': 'finish'}], modify('unrelated.txt'))
        with self.assertRaisesRegex(AgentError, 'non è stato letto integralmente'):
            GiorgioAgent(self.workspace, model).plan('Nel ProgettoProva correggi somma')

    def test_path_escape_is_blocked(self):
        model = FakeModel([{'action': 'finish'}], modify('../outside.py'))
        with self.assertRaises(AgentError):
            GiorgioAgent(self.workspace, model).plan('Nel ProgettoProva correggi somma')

    def test_large_entrypoint_stays_inside_context_budget(self):
        (self.root / 'codex_app.py').write_text('print("hello")\n' * 3000)
        model = FakeModel([read('codex_app.py'), {'action': 'finish'}])
        model.num_ctx = 8192
        agent = GiorgioAgent(self.workspace, model)
        plan = agent.plan('Nel ProgettoProva controlla questo progetto')
        self.assertFalse(plan.operations)
        self.assertTrue(any(file.truncated for file in plan.context.files))
        self.assertTrue(all(len(prompt) + 2200 < model.num_ctx * 2 for prompt in model.prompts))

    def test_large_partial_file_cannot_be_replaced(self):
        (self.root / 'codex_app.py').write_text('print("hello")\n' * 3000)
        model = FakeModel([read('codex_app.py'), {'action': 'finish'}], modify('codex_app.py'))
        model.num_ctx = 8192
        with self.assertRaisesRegex(AgentError, 'non è stato letto integralmente'):
            GiorgioAgent(self.workspace, model).plan('Nel ProgettoProva correggi codex_app.py')

    def test_fresh_request_executes_tools_again(self):
        model = FakeModel([read(), {'action': 'finish'}, read(), {'action': 'finish'}])
        agent = GiorgioAgent(self.workspace, model)
        with patch.object(AgentTools, 'execute', autospec=True,
                          side_effect=AgentTools.execute) as execute:
            agent.plan('Nel ProgettoProva controlla somma')
            agent.plan('Nel ProgettoProva controlla somma')
        self.assertEqual(execute.call_count, 2)


if __name__ == '__main__':
    unittest.main()
