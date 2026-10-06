import socket
import unittest

from core.ollama_status import inspect_ollama


class ObjectModel:
    def __init__(self, name):
        self.model = name


class ObjectResponse:
    def __init__(self, models):
        self.models = models


class Client:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error

    def list(self):
        if self.error:
            raise self.error
        return self.response


class OllamaStatusTests(unittest.TestCase):
    def test_lists_dict_and_object_models_sorted_without_duplicates(self):
        response = ObjectResponse([ObjectModel('qwen:7b'), {'name': 'llama:3b'}, {'model': 'qwen:7b'}])
        result = inspect_ollama('qwen:7b', lambda: Client(response))
        self.assertTrue(result['connected'])
        self.assertEqual(result['models'], ['llama:3b', 'qwen:7b'])
        self.assertIn('pronto', result['message'])

    def test_reports_empty_installation(self):
        result = inspect_ollama('qwen:7b', lambda: Client({'models': []}))
        self.assertTrue(result['connected'])
        self.assertEqual(result['models'], [])
        self.assertIn('nessun modello', result['message'])

    def test_reports_missing_selected_model(self):
        result = inspect_ollama('qwen:7b', lambda: Client({'models': [{'name': 'llama:3b'}]}))
        self.assertTrue(result['connected'])
        self.assertIn('non installato', result['message'])

    def test_connection_refused_is_user_friendly(self):
        result = inspect_ollama('qwen:7b', lambda: Client(error=ConnectionError('connection refused secret detail')))
        self.assertFalse(result['connected'])
        self.assertIn('non raggiungibile', result['message'])
        self.assertIn('secret detail', result['detail'])

    def test_timeout_is_distinct(self):
        result = inspect_ollama('qwen:7b', lambda: Client(error=socket.timeout('slow')))
        self.assertFalse(result['connected'])
        self.assertIn('tempo previsto', result['message'])

    def test_unknown_error_is_bounded(self):
        result = inspect_ollama('qwen:7b', lambda: Client(error=RuntimeError('x' * 1000)))
        self.assertEqual(len(result['detail']), 500)
        self.assertEqual(result['message'], 'Controllo Ollama non riuscito')


if __name__ == '__main__':
    unittest.main()
