"""Explicit real-Ollama E2E runner; excluded from normal unittest discovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

import ollama

from core.action_intent import parse_simple_action
from core.transaction_supervisor import TransactionStatus, TransactionSupervisor
from core.bridge.core_adapter import ModifyPermission, adapt_modify_intent
from core.bridge.modify_runtime import (
    execute_modify_request,
    submit_modify_request,
    verify_modify_request,
)
from core.bridge.ollama_provider import OllamaBridgeProvider


MODEL = 'qwen3:4b-instruct'


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class RealOllamaBridgeE2E(unittest.TestCase):
    def test_real_ollama_to_verified_core(self):
        request_text = (
            'Aggiorna config.py in modo che l’applicazione sia attiva, '
            'mantenendo invariata ogni altra impostazione.'
        )
        with TemporaryDirectory(prefix='giorgio-ollama-e2e-') as directory:
            root = Path(directory)
            target = root / 'config.py'
            before = b'ENABLED = False\nRETRIES = 3\n'
            target.write_bytes(before)
            self.assertIsNone(parse_simple_action(request_text, root))

            schema = {
                'type': 'object',
                'additionalProperties': False,
                'required': ['action_type', 'parameters', 'reasoning_summary'],
                'properties': {
                    'action_type': {'type': 'string', 'enum': ['MODIFY_FILE']},
                    'parameters': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': ['target_path', 'content'],
                        'properties': {
                            'target_path': {'type': 'string', 'enum': ['config.py']},
                            'content': {'type': 'string'},
                        },
                    },
                    'reasoning_summary': {'type': 'string', 'minLength': 1},
                },
            }
            client = ollama.Client(timeout=120.0)

            def transport(prompt: str) -> str:
                response = client.chat(
                    model=MODEL,
                    messages=[
                        {
                            'role': 'system',
                            'content': (
                                'Restituisci esclusivamente JSON conforme allo schema. '
                                'Puoi proporre solo MODIFY_FILE. Il campo content deve '
                                'contenere il file completo risultante, senza Markdown.'
                            ),
                        },
                        {
                            'role': 'user',
                            'content': (
                                f'Richiesta: {prompt}\nPercorso: config.py\n'
                                f'Contenuto attuale:\n{before.decode("utf-8")}'
                            ),
                        },
                    ],
                    format=schema,
                    options={'temperature': 0, 'num_ctx': 4096, 'num_predict': 512},
                )
                message = getattr(response, 'message', None)
                content = getattr(message, 'content', None)
                if content is None and isinstance(response, dict):
                    content = response.get('message', {}).get('content')
                return content

            started = time.monotonic()
            result = OllamaBridgeProvider(transport).request_intent(request_text)
            self.assertIsNone(result.error, result.error)
            self.assertIsNotNone(result.intent)
            self.assertEqual(result.intent.target_path, 'config.py')
            self.assertIn('ENABLED = True', result.intent.content)
            self.assertIn('RETRIES = 3', result.intent.content)

            pre_sha256 = sha256(before)
            permission = ModifyPermission('config.py', pre_sha256, True)
            core_request = adapt_modify_intent(result.intent, permission)
            journal = root / 'giorgio_journal.json'
            supervisor = TransactionSupervisor(
                journal, execute_modify_request, verify_modify_request,
                start_timeout=5.0, kill_grace=1.0,
            )
            try:
                status = submit_modify_request(
                    supervisor, 'OLLAMA_REAL_E2E', root, core_request, timeout=10.0
                )
                record = supervisor.registry['OLLAMA_REAL_E2E']
            finally:
                supervisor.shutdown()

            after = target.read_bytes()
            duration_ms = round((time.monotonic() - started) * 1000)
            evidence = {
                'model': MODEL,
                'duration_ms': duration_ms,
                'deterministic_fallback': True,
                'bridge_error': None,
                'capability': record.capability,
                'core_status': status.value,
                'verifier_status': verify_modify_request(record)['status'],
                'pre_sha256': pre_sha256,
                'expected_sha256': core_request.expected_sha256,
                'post_sha256': sha256(after),
                'journal_status': record.status,
            }
            print('OLLAMA_REAL_E2E_EVIDENCE=' + json.dumps(evidence, sort_keys=True))
            self.assertEqual(status, TransactionStatus.VERIFIED)
            self.assertEqual(evidence['verifier_status'], 'VERIFIED')
            self.assertEqual(evidence['post_sha256'], core_request.expected_sha256)


if __name__ == '__main__':
    unittest.main(verbosity=2)
