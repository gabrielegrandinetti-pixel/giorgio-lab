import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from core.transaction_supervisor import (
    JournalRecoveryRequired, SupervisorState, TransactionStatus, TransactionSupervisor,
)
from core.executor import isolated_executor_entry


def ok_executor(task_id, capability, args):
    return {'status': 'VERIFIED', 'evidence': {'task_id': task_id}}


def fail_executor(task_id, capability, args):
    return {'status': 'FAILED', 'error': 'expected failure'}


def rollback_executor(task_id, capability, args):
    return {'status': 'ROLLED_BACK', 'evidence': {'restored': True}}


def crash_executor(task_id, capability, args):
    raise RuntimeError('boom from child')


def malformed_executor(task_id, capability, args):
    return 'VERIFIED'


def selective_hang_executor(task_id, capability, args):
    if task_id == 'TASK_A_HANG':
        time.sleep(5)
    return {'status': 'VERIFIED'}


def late_mutation_executor(task_id, capability, args):
    marker = Path(args['marker'])
    delay = float(args.get('delay', 0.25))
    time.sleep(delay)
    marker.write_text('late mutation', encoding='utf-8')
    return {'status': 'VERIFIED'}


def quick_mutation_executor(task_id, capability, args):
    Path(args['marker']).write_text('done', encoding='utf-8')
    return {'status': 'VERIFIED'}

def mutate_then_hang_executor(task_id, capability, args):
    Path(args['marker']).write_text('done', encoding='utf-8')
    time.sleep(2)
    return {'status': 'VERIFIED'}


def race_executor(task_id, capability, args):
    time.sleep(float(args['delay']))
    Path(args['marker']).write_text('done', encoding='utf-8')
    return {'status': 'VERIFIED'}


def readonly_verifier(record):
    marker = record.arguments.get('marker')
    if marker:
        p = Path(marker)
        if p.exists() and p.is_file():
            import hashlib
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            expected = record.expected_evidence.get('sha256')
            if expected and digest == expected:
                return {'status': 'VERIFIED', 'evidence': {'sha256': digest}}
        if not p.exists() and record.pre_evidence.get('absent') is True:
            return {'status': 'NOT_APPLIED', 'evidence': {'absent': True}}
    return {'status': 'RECOVERY_REQUIRED'}


def always_not_applied(record):
    return {'status': 'NOT_APPLIED', 'evidence': {'read_only': True}}


def always_verified(record):
    return {'status': 'VERIFIED', 'evidence': {'read_only': True}}


def unknown_verifier(record):
    return {'status': 'RECOVERY_REQUIRED'}


def noop_recovery(record):
    return {'attempted': True}


class IsolationKernelHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.journal = self.root / 'giorgio_journal.json'

    def tearDown(self):
        self.tmp.cleanup()

    def sup(self, executor=ok_executor, verifier=always_not_applied, recovery=None, **kw):
        return TransactionSupervisor(self.journal, executor, verifier, recovery, **kw)

    def test_01_normal_completion(self):
        s = self.sup()
        self.assertEqual(s.submit_transaction('T1', 'TEST', {}, 1), TransactionStatus.VERIFIED)
        self.assertEqual(s.registry['T1'].status, 'VERIFIED')

    def test_02_core_exception(self):
        s = self.sup(crash_executor)
        self.assertEqual(s.submit_transaction('T2', 'TEST', {}, 1), TransactionStatus.FAILED)
        self.assertIn('boom from child', json.dumps(s.registry['T2'].terminal_result))

    def test_03_normal_rollback(self):
        s = self.sup(rollback_executor)
        self.assertEqual(s.submit_transaction('T3', 'TEST', {}, 1), TransactionStatus.ROLLED_BACK)

    def test_04_hard_hang_has_no_late_mutation(self):
        marker = self.root / 'zombie.txt'
        s = self.sup(late_mutation_executor, readonly_verifier, start_timeout=2)
        status = s.submit_transaction('T4', 'WRITE', {'marker': str(marker), 'delay': 1.0},
                                      timeout=.1, pre_evidence={'absent': True})
        self.assertEqual(status, TransactionStatus.NOT_APPLIED)
        time.sleep(1.1)
        self.assertFalse(marker.exists(), 'terminated executor mutated after deadline')

    def test_05_late_completion_reconciles_to_verified_late(self):
        marker = self.root / 'late.txt'
        expected_bytes = b'done'
        import hashlib
        expected = hashlib.sha256(expected_bytes).hexdigest()
        s = self.sup(mutate_then_hang_executor, readonly_verifier)
        # The child mutates first but withholds CORE_RESULT until after the deadline.
        # Reconciliation must therefore discover the completed state.
        status = s.submit_transaction('T5', 'WRITE', {'marker': str(marker)}, timeout=.15,
                                      pre_evidence={'absent': True}, expected_evidence={'sha256': expected})
        self.assertEqual(status, TransactionStatus.VERIFIED_LATE)
        self.assertTrue(marker.exists())

    def test_06_unknown_state_requires_recovery(self):
        s = self.sup(late_mutation_executor, unknown_verifier, noop_recovery)
        status = s.submit_transaction('T6', 'TEST', {'marker': str(self.root/'u'), 'delay': 2}, .05)
        self.assertEqual(status, TransactionStatus.RECOVERY_REQUIRED)

    def test_07_task_b_after_hung_a_is_immediate(self):
        s = self.sup(selective_hang_executor, always_not_applied)
        self.assertEqual(s.submit_transaction('TASK_A_HANG', 'TEST', {}, .05), TransactionStatus.NOT_APPLIED)
        started = time.monotonic()
        self.assertEqual(s.submit_transaction('TASK_B_FAST', 'TEST', {}, 1), TransactionStatus.VERIFIED)
        self.assertLess(time.monotonic() - started, 1.5)

    def test_08_shutdown_rejects_new_and_reconciles_running(self):
        s = self.sup(selective_hang_executor, always_not_applied)
        box = {}
        def run_a():
            box['status'] = s.submit_transaction('TASK_A_HANG', 'TEST', {}, 5)
        t = threading.Thread(target=run_a)
        t.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            rec = s.registry.get('TASK_A_HANG')
            if rec is not None and rec.status == 'RUNNING':
                break
            time.sleep(.01)
        self.assertIsNotNone(s.registry.get('TASK_A_HANG'))
        self.assertEqual(s.registry['TASK_A_HANG'].status, 'RUNNING')
        s.shutdown()
        t.join(2)
        self.assertFalse(t.is_alive())
        self.assertEqual(s.state, SupervisorState.STOPPED)
        self.assertEqual(s.submit_transaction('AFTER', 'TEST', {}, 1), TransactionStatus.FAILED)
        self.assertNotEqual(s.registry['TASK_A_HANG'].status, 'RUNNING')

    def test_09_duplicate_task_id(self):
        s = self.sup()
        self.assertEqual(s.submit_transaction('DUP', 'TEST', {}, 1), TransactionStatus.VERIFIED)
        self.assertEqual(s.submit_transaction('DUP', 'TEST', {}, 1), TransactionStatus.FAILED)

    def test_10_malformed_core_result(self):
        s = self.sup(malformed_executor)
        self.assertEqual(s.submit_transaction('BAD', 'TEST', {}, 1), TransactionStatus.FAILED)

    def test_11_restart_reconciliation(self):
        seed = {
            'CRASHED': {
                'task_id': 'CRASHED', 'capability': 'WRITE', 'arguments': {}, 'status': 'RUNNING',
                'created_at': time.time(), 'deadline_seconds': 5.0, 'pid': 999999,
                'pre_evidence': {}, 'expected_evidence': {}, 'terminal_result': None,
            }
        }
        self.journal.write_text(json.dumps(seed), encoding='utf-8')
        s = self.sup(ok_executor, always_verified)
        result = s.reconcile_after_restart()
        self.assertEqual(result['CRASHED'], TransactionStatus.VERIFIED_AFTER_RESTART)
        self.assertEqual(s.registry['CRASHED'].status, 'VERIFIED_AFTER_RESTART')

    def test_12_cancellation_race_has_one_terminal_state(self):
        marker = self.root / 'race.txt'
        import hashlib
        expected = hashlib.sha256(b'done').hexdigest()
        s = self.sup(race_executor, readonly_verifier)
        status = s.submit_transaction('RACE', 'WRITE', {'marker': str(marker), 'delay': .04}, .04,
                                      pre_evidence={'absent': True}, expected_evidence={'sha256': expected})
        self.assertIn(status, {TransactionStatus.VERIFIED, TransactionStatus.VERIFIED_LATE,
                               TransactionStatus.NOT_APPLIED, TransactionStatus.RECOVERY_REQUIRED})
        persisted = json.loads(self.journal.read_text(encoding='utf-8'))['RACE']['status']
        self.assertEqual(persisted, s.registry['RACE'].status)
        self.assertIn(persisted, {x.value for x in TransactionStatus} - {'PENDING', 'RUNNING', 'NEEDS_RECONCILIATION'})


    def test_authorization_barrier_blocks_mutation_before_execute_allowed(self):
        marker = self.root / 'before_auth.txt'
        ctx = __import__('multiprocessing').get_context('spawn')
        parent, child = ctx.Pipe(duplex=True)
        proc = ctx.Process(target=isolated_executor_entry,
                           args=(child, 'AUTH', 'WRITE', {'marker': str(marker)}, quick_mutation_executor))
        proc.start()
        child.close()
        self.assertTrue(parent.poll(2.0))
        started = parent.recv()
        self.assertEqual(started.get('event'), 'STARTED')
        self.assertEqual(started.get('pid'), proc.pid)
        self.assertFalse(marker.exists())
        proc.terminate()
        proc.join(1.0)
        self.assertFalse(marker.exists())
        parent.close()
        proc.close()

    def test_journal_corruption_is_fail_closed(self):
        self.journal.write_text('{ definitely broken', encoding='utf-8')
        with self.assertRaises(JournalRecoveryRequired):
            self.sup()


if __name__ == '__main__':
    unittest.main()
