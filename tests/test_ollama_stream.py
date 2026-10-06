import sys
import types
import unittest
from unittest.mock import Mock
try:
    import ollama
except ImportError:
    sys.modules['ollama'] = types.ModuleType('ollama')
from core.ollama_client import OllamaClient, OllamaError


class StreamTests(unittest.TestCase):
    def client(self, chunks):
        client = OllamaClient.__new__(OllamaClient)
        client.model = 'test'
        client.num_ctx = 4096
        client.temperature = 0
        client.request_timeout = 90
        client._client = Mock()
        client._client.chat.return_value = iter(chunks)
        return client

    def test_assembles_json_and_reports_progress(self):
        client = self.client([
            {'message': {'content': '{"a":'}, 'done': False},
            {'message': {'content': '8}'}, 'done': False},
            {'message': {'content': ''}, 'done': True, 'done_reason': 'stop'},
        ])
        events = []
        self.assertEqual(client.chat_json([{'role': 'user', 'content': 'test'}],
                                         progress_callback=events.append, max_tokens=256), {'a': 8})
        self.assertTrue(events)
        self.assertTrue(client._client.chat.call_args.kwargs['stream'])
        self.assertEqual(client._client.chat.call_args.kwargs['options']['num_predict'], 256)

    def test_rejects_token_limit_even_if_json_looks_valid(self):
        client = self.client([{'message': {'content': '{}'}, 'done': True, 'done_reason': 'length'}])
        with self.assertRaisesRegex(OllamaError, 'Proposta incompleta'):
            client.chat_json([{'role': 'user', 'content': 'test'}])

    def test_rejects_missing_done(self):
        client = self.client([{'message': {'content': '{}'}, 'done': False}])
        with self.assertRaisesRegex(OllamaError, 'prima del completamento'):
            client.chat_json([{'role': 'user', 'content': 'test'}])

    def test_stream_closes_on_interrupt(self):
        closed = []
        def chunks():
            try:
                yield {'message': {'content': '{'}, 'done': False}
                raise KeyboardInterrupt
            finally:
                closed.append(True)
        client = self.client([])
        client._client.chat.return_value = chunks()
        with self.assertRaises(KeyboardInterrupt):
            client.chat_json([{'role': 'user', 'content': 'test'}])
        self.assertEqual(closed, [True])

    def test_empty_timeout_has_useful_message(self):
        client = self.client([])
        client._client.chat.side_effect = TimeoutError()
        with self.assertRaisesRegex(OllamaError, 'timeout'):
            client.chat_json([{'role': 'user', 'content': 'test'}])
