import hashlib
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.bridge.base_provider import ActionIntent


class BridgeCoreAdapterTests(unittest.TestCase):
    def setUp(self):
        from core.bridge.core_adapter import ModifyPermission, adapt_modify_intent

        self.ModifyPermission = ModifyPermission
        self.adapt = adapt_modify_intent
        self.content = 'print("aggiornato")\n'
        self.post_sha256 = hashlib.sha256(self.content.encode('utf-8')).hexdigest()
        self.pre_sha256 = hashlib.sha256(b'print("prima")\n').hexdigest()
        self.intent = ActionIntent(
            action_type='MODIFY_FILE',
            target_path='src/main.py',
            content=self.content,
            expected_sha256=self.post_sha256,
            reasoning_summary='Aggiorna il messaggio.',
        )

    def permission(self, **changes):
        values = {
            'target_path': self.intent.target_path,
            'pre_sha256': self.pre_sha256,
            'granted': True,
        }
        values.update(changes)
        return self.ModifyPermission(**values)

    def test_valid_intent_maps_to_immutable_core_request(self):
        request = self.adapt(self.intent, self.permission())

        self.assertEqual(request.capability, 'MODIFY_FILE')
        self.assertEqual(request.relative_path, 'src/main.py')
        self.assertEqual(request.content, self.content)
        self.assertEqual(request.pre_sha256, self.pre_sha256)
        self.assertEqual(request.expected_sha256, self.post_sha256)
        self.assertEqual(request.expected_size, len(self.content.encode('utf-8')))
        with self.assertRaises(FrozenInstanceError):
            request.content = 'alterato'

    def test_no_permission_means_no_core_request(self):
        with self.assertRaises(PermissionError):
            self.adapt(self.intent, self.permission(granted=False))

    def test_permission_must_match_the_exact_target(self):
        with self.assertRaises(PermissionError):
            self.adapt(self.intent, self.permission(target_path='src/altro.py'))

    def test_unsupported_or_incoherent_intents_fail_closed(self):
        invalid = [
            replace(self.intent, action_type='DELETE'),
            replace(self.intent, target_path=None),
            replace(self.intent, target_path='../fuori.py'),
            replace(self.intent, target_path='C:/Windows/system.ini'),
            replace(self.intent, content=None),
            replace(self.intent, expected_sha256='0' * 64),
            replace(self.intent, reasoning_summary=None),
            replace(self.intent, reasoning_summary=''),
        ]
        for intent in invalid:
            with self.subTest(intent=intent):
                with self.assertRaises(ValueError):
                    self.adapt(intent, self.permission(target_path=intent.target_path))

    def test_permission_fingerprint_must_be_canonical(self):
        for digest in (None, '', 'xyz', 'A' * 64, '0' * 63):
            with self.subTest(digest=digest):
                with self.assertRaises(ValueError):
                    self.adapt(self.intent, self.permission(pre_sha256=digest))

    def test_adapter_performs_no_filesystem_mutation(self):
        with TemporaryDirectory(prefix='giorgio-adapter-pure-') as directory:
            root = Path(directory)
            before = sorted(path.relative_to(root) for path in root.rglob('*'))
            self.adapt(self.intent, self.permission())
            after = sorted(path.relative_to(root) for path in root.rglob('*'))
            self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
