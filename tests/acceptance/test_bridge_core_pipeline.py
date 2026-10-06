import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.transaction_supervisor import TransactionStatus, TransactionSupervisor
from core.bridge.base_provider import ActionIntent
from core.bridge.core_adapter import ModifyPermission, adapt_modify_intent


class BridgeCorePipelineTests(unittest.TestCase):
    def make_request(self, target, content):
        original = target.read_bytes()
        intent = ActionIntent(
            action_type='MODIFY_FILE',
            target_path=target.name,
            content=content,
            expected_sha256=hashlib.sha256(content.encode('utf-8')).hexdigest(),
            reasoning_summary='Aggiornamento controllato.',
        )
        permission = ModifyPermission(
            target_path=target.name,
            pre_sha256=hashlib.sha256(original).hexdigest(),
            granted=True,
        )
        return adapt_modify_intent(intent, permission)

    def test_permission_bound_request_reaches_verified_core(self):
        from core.bridge.modify_runtime import (
            execute_modify_request,
            submit_modify_request,
            verify_modify_request,
        )

        with TemporaryDirectory(prefix='giorgio-bridge-core-') as directory:
            root = Path(directory)
            target = root / 'app.py'
            target.write_text('print("prima")\n', encoding='utf-8', newline='')
            content = 'print("dopo")\n'
            request = self.make_request(target, content)
            journal = root / 'giorgio_journal.json'
            supervisor = TransactionSupervisor(journal, execute_modify_request, verify_modify_request)
            try:
                status = submit_modify_request(supervisor, 'BRIDGE_CORE_OK', root, request, timeout=5.0)
            finally:
                supervisor.shutdown()

            self.assertEqual(status, TransactionStatus.VERIFIED)
            self.assertEqual(target.read_text(encoding='utf-8'), content)
            record = json.loads(journal.read_text(encoding='utf-8'))['BRIDGE_CORE_OK']
            self.assertEqual(record['capability'], 'MODIFY_FILE')
            self.assertEqual(record['status'], 'VERIFIED')
            self.assertEqual(record['expected_evidence']['sha256'], request.expected_sha256)

    def test_stale_permission_fails_without_overwriting_external_change(self):
        from core.bridge.modify_runtime import (
            execute_modify_request,
            submit_modify_request,
            verify_modify_request,
        )

        with TemporaryDirectory(prefix='giorgio-bridge-stale-') as directory:
            root = Path(directory)
            target = root / 'app.py'
            target.write_text('prima\n', encoding='utf-8', newline='')
            request = self.make_request(target, 'dopo\n')
            target.write_text('modifica esterna\n', encoding='utf-8', newline='')
            supervisor = TransactionSupervisor(
                root / 'giorgio_journal.json', execute_modify_request, verify_modify_request
            )
            try:
                status = submit_modify_request(supervisor, 'BRIDGE_CORE_STALE', root, request, timeout=5.0)
            finally:
                supervisor.shutdown()

            self.assertEqual(status, TransactionStatus.FAILED)
            self.assertEqual(target.read_text(encoding='utf-8'), 'modifica esterna\n')


if __name__ == '__main__':
    unittest.main()
