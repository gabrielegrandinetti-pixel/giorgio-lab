import inspect
import json
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch


from core.bridge import (
    ActionIntent,
    BridgeError,
    BridgeErrorCode,
    BridgeResult,
    LLMBridgeProvider,
)
from core.bridge.intent_parser import parse_intent
from core.bridge.ollama_provider import OllamaBridgeProvider


class BridgeContractTests(unittest.TestCase):
    def setUp(self):
        self.intent = ActionIntent(
            action_type='MODIFY_FILE',
            target_path='src/main.py',
            content="print('Giorgio')\n",
            expected_sha256='0' * 64,
            reasoning_summary='Aggiorna il file principale.',
        )
        self.error = BridgeError(
            code=BridgeErrorCode.INVALID_INTENT,
            message='Payload non valido.',
            provider='test',
            exception_type='ValueError',
        )

    def test_bridge_result_requires_exactly_one_variant(self):
        with self.assertRaises(ValueError):
            BridgeResult()
        with self.assertRaises(ValueError):
            BridgeResult(intent=self.intent, error=self.error)

        success = BridgeResult(intent=self.intent)
        failure = BridgeResult(error=self.error)
        self.assertIs(success.intent, self.intent)
        self.assertIsNone(success.error)
        self.assertIs(failure.error, self.error)
        self.assertIsNone(failure.intent)

    def test_action_intent_and_result_are_frozen(self):
        result = BridgeResult(intent=self.intent)
        with self.assertRaises(FrozenInstanceError):
            self.intent.content = 'mutazione'
        with self.assertRaises(FrozenInstanceError):
            result.error = self.error
        with self.assertRaises(FrozenInstanceError):
            self.error.message = 'mutazione'

    def test_provider_interface_is_abstract(self):
        self.assertTrue(inspect.isabstract(LLMBridgeProvider))
        with self.assertRaises(TypeError):
            LLMBridgeProvider()

        class MissingRequestIntent(LLMBridgeProvider):
            @property
            def provider_name(self):
                return 'missing'

        with self.assertRaises(TypeError):
            MissingRequestIntent()


def valid_payload(**overrides):
    payload = {
        'action_type': 'MODIFY_FILE',
        'parameters': {
            'target_path': 'src/main.py',
            'content': "print('Giorgio')\n",
        },
        'reasoning_summary': 'Aggiorna il file principale.',
    }
    for key, value in overrides.items():
        if key in payload['parameters'] or key == 'expected_sha256':
            payload['parameters'][key] = value
        else:
            payload[key] = value
    return json.dumps(payload)


class StrictParserTests(unittest.TestCase):
    def assert_invalid(self, raw):
        result = parse_intent(raw)
        self.assertIsNone(result.intent)
        self.assertEqual(result.error.code, BridgeErrorCode.INVALID_INTENT)

    def test_valid_payload_produces_action_intent_without_io(self):
        with patch('builtins.open', side_effect=AssertionError('I/O')), \
             patch('pathlib.Path.resolve', side_effect=AssertionError('I/O')), \
             patch('pathlib.Path.exists', side_effect=AssertionError('I/O')), \
             patch('pathlib.Path.stat', side_effect=AssertionError('I/O')), \
             patch('os.stat', side_effect=AssertionError('I/O')):
            result = parse_intent(valid_payload())
        self.assertIsInstance(result.intent, ActionIntent)
        self.assertEqual(result.intent.action_type, 'MODIFY_FILE')
        self.assertEqual(result.intent.target_path, 'src/main.py')


class HashAndBoundsTests(unittest.TestCase):
    def assert_invalid(self, raw):
        result = parse_intent(raw)
        self.assertEqual(result.error.code, BridgeErrorCode.INVALID_INTENT)

    def test_canonical_digest_is_inserted_and_matching_digest_is_accepted(self):
        expected = 'b133a0c0e9bee3be20163d2ad31d6248db292aa6dcb1ee087a2aa50e0fc75ae2'
        result = parse_intent(valid_payload(content='ciao'))
        self.assertEqual(result.intent.expected_sha256, expected)
        matching = parse_intent(valid_payload(content='ciao', expected_sha256=expected))
        self.assertEqual(matching.intent.expected_sha256, expected)

    def test_bad_digests_are_rejected(self):
        for digest in ('A5CD64B45D86684E0797A140E92DD4C17AF4B61B6E815553C4AACB5FC1B412D3', '0' * 63, 'g' * 64, '0' * 64):
            with self.subTest(digest=digest):
                self.assert_invalid(valid_payload(content='ciao', expected_sha256=digest))

    def test_content_and_textual_boundaries(self):
        self.assertIsNotNone(parse_intent(valid_payload(content='')).intent)
        self.assertIsNotNone(parse_intent(valid_payload(content='a' * (2 * 1024 * 1024))).intent)
        self.assert_invalid(valid_payload(content='a' * (2 * 1024 * 1024 + 1)))
        self.assertIsNotNone(parse_intent(valid_payload(content='€' * ((2 * 1024 * 1024) // 3))).intent)
        self.assert_invalid(valid_payload(content='€' * ((2 * 1024 * 1024) // 3 + 1)))
        self.assertIsNotNone(parse_intent(valid_payload(reasoning_summary='r' * 1000)).intent)
        self.assert_invalid(valid_payload(reasoning_summary='r' * 1001))
        self.assertIsNotNone(parse_intent(valid_payload(target_path='a' * 1024)).intent)
        self.assert_invalid(valid_payload(target_path='a' * 1025))

    def test_strict_json_and_closed_schema_reject_invalid_payloads(self):
        invalid = (
            '```json\n' + valid_payload() + '\n```',
            'prose ' + valid_payload(),
            valid_payload() + ' trailing',
            valid_payload() + ' {}',
            '[]',
            '{"action_type":"MODIFY_FILE","action_type":"DELETE","parameters":{"target_path":"a","content":""},"reasoning_summary":"x"}',
            '{"action_type":"MODIFY_FILE","parameters":{"target_path":"a","target_path":"b","content":""},"reasoning_summary":"x"}',
            json.dumps({'action_type': 'MODIFY_FILE', 'parameters': {'target_path': 'a', 'content': ''}, 'reasoning_summary': 'x', 'extra': True}),
            json.dumps({'action_type': 'MODIFY_FILE', 'parameters': {'target_path': 'a', 'content': '', 'extra': True}, 'reasoning_summary': 'x'}),
            json.dumps({'action_type': 'MODIFY_FILE', 'parameters': {'target_path': 'a'}, 'reasoning_summary': 'x'}),
            json.dumps({'action_type': 'MODIFY_FILE', 'parameters': {'target_path': 'a', 'content': 1}, 'reasoning_summary': 'x'}),
            json.dumps({'action_type': True, 'parameters': {'target_path': 'a', 'content': ''}, 'reasoning_summary': 'x'}),
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assert_invalid(raw)

    def test_unsupported_action_is_distinct(self):
        for action in ('CREATE', 'DELETE', 'EXECUTE', 'modify_file'):
            with self.subTest(action=action):
                result = parse_intent(valid_payload(action_type=action))
                self.assertIsNone(result.intent)
                self.assertEqual(result.error.code, BridgeErrorCode.UNSUPPORTED_ACTION)

    def test_lexically_unsafe_paths_are_rejected(self):
        unsafe = (
            '', '.', '..', 'src//main.py', 'src/./main.py', 'src/../main.py',
            '/etc/passwd', '\\etc\\passwd', 'C:/temp/main.py', 'C:temp/main.py',
            '\\\\server\\share\\file.py', '\\\\?\\C:\\temp\\file.py',
            'src/file.py:secret', 'src/<file>.py', 'src/file. ', 'src/file.',
            'CON', 'aux.txt', 'COM1.py', 'lpt9.txt', 'src/\x00file.py', 'src/\x1ffile.py',
        )
        for target_path in unsafe:
            with self.subTest(target_path=repr(target_path)):
                self.assert_invalid(valid_payload(target_path=target_path))

    def test_backslashes_are_normalized_only_for_safe_relative_path(self):
        result = parse_intent(valid_payload(target_path='src\\main.py'))
        self.assertIsNotNone(result.intent)
        self.assertEqual(result.intent.target_path, 'src/main.py')


class ProviderAdapterTests(unittest.TestCase):
    def test_mock_transport_returns_valid_intent(self):
        calls = []
        provider = OllamaBridgeProvider(lambda prompt: calls.append(prompt) or valid_payload())
        result = provider.request_intent('aggiorna il file')
        self.assertIsNotNone(result.intent)
        self.assertEqual(calls, ['aggiorna il file'])

    def test_invalid_prompt_or_transport_fault_is_provider_failure(self):
        for prompt, transport in (
            ('', lambda _: valid_payload()),
            (None, lambda _: valid_payload()),
            ('ok', lambda _: 3),
            ('ok', lambda _: (_ for _ in ()).throw(TimeoutError('timeout'))),
        ):
            with self.subTest(prompt=prompt):
                result = OllamaBridgeProvider(transport).request_intent(prompt)
                self.assertIsNone(result.intent)
                self.assertEqual(result.error.code, BridgeErrorCode.PROVIDER_FAILURE)
                self.assertEqual(result.error.provider, 'ollama')

    def test_parser_fault_is_returned_unchanged_and_no_supervisor_is_called(self):
        class SupervisorSpy:
            calls = 0

            def submit_transaction(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError('Bridge must not invoke Supervisor')

        supervisor = SupervisorSpy()
        result = OllamaBridgeProvider(lambda _: 'not json').request_intent('ok')
        self.assertEqual(result.error.code, BridgeErrorCode.INVALID_INTENT)
        self.assertEqual(supervisor.calls, 0)


if __name__ == '__main__':
    unittest.main()
