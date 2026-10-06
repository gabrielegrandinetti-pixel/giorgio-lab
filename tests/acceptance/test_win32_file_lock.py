import ctypes
from ctypes import wintypes
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest


sys.modules.setdefault('ollama', types.SimpleNamespace())

from core.transaction_supervisor import SupervisorState, TransactionStatus, TransactionSupervisor
from core.executor import apply_approved


ORIGINAL_BYTES = b'\x00GIORGIO-ORIGINAL\r\n\xff'
EXPECTED_BYTES = b'GIORGIO-UPDATED\n'
EXPECTED_TEXT = EXPECTED_BYTES.decode('ascii')


def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def real_modify_executor(task_id, capability, arguments):
    if capability != 'MODIFY_FILE':
        raise ValueError(f'capability non supportata: {capability}')
    relative = arguments['relative_path']
    apply_approved(
        arguments['root'],
        [{'type': 'modify', 'path': relative, 'content': arguments['content']}],
        {relative: arguments['pre_sha256']},
    )
    target = Path(arguments['root']) / relative
    payload = target.read_bytes()
    return {
        'status': 'VERIFIED',
        'evidence': {
            'sha256': sha256_bytes(payload),
            'size': len(payload),
            'task_id': task_id,
        },
    }


def readonly_modify_verifier(record):
    target = Path(record.arguments['root']) / record.arguments['relative_path']
    lock_handle = record.arguments.get('lock_handle')
    if lock_handle is not None:
        payload = read_handle_bytes(lock_handle, record.pre_evidence['size'])
    elif not target.is_file():
        return {'status': 'RECOVERY_REQUIRED', 'evidence': {'exists': False}}
    else:
        payload = target.read_bytes()
    actual = sha256_bytes(payload)
    evidence = {'exists': True, 'sha256': actual, 'size': len(payload)}
    if actual == record.expected_evidence.get('sha256'):
        return {'status': 'VERIFIED', 'evidence': evidence}
    if actual == record.pre_evidence.get('sha256'):
        return {'status': 'NOT_APPLIED', 'evidence': evidence}
    return {'status': 'RECOVERY_REQUIRED', 'evidence': evidence}


def temporary_artifacts(root):
    root = Path(root)
    found = []
    for path in root.rglob('*'):
        if not path.is_file() or '.giorgio_backups' in path.parts:
            continue
        if path.name.startswith('.giorgio-') or path.name.startswith('.giorgio-journal-'):
            found.append(path.relative_to(root).as_posix())
    return sorted(found)


def active_child_pids():
    return {process.pid for process in multiprocessing.active_children() if process.pid is not None}


def acquire_exclusive_handle(path):
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    generic_read = 0x80000000
    generic_write = 0x40000000
    open_existing = 3
    file_attribute_normal = 0x80
    handle = create_file(
        str(Path(path)),
        generic_read | generic_write,
        0,
        None,
        open_existing,
        file_attribute_normal,
        None,
    )
    invalid_handle_value = ctypes.c_void_p(-1).value
    if handle == invalid_handle_value:
        raise ctypes.WinError(ctypes.get_last_error())
    return kernel32, handle


def close_exclusive_handle(kernel32, handle):
    if not kernel32.CloseHandle(handle):
        raise ctypes.WinError(ctypes.get_last_error())


def read_handle_bytes(handle, size):
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    set_pointer = kernel32.SetFilePointerEx
    set_pointer.argtypes = (wintypes.HANDLE, ctypes.c_longlong, ctypes.c_void_p, wintypes.DWORD)
    set_pointer.restype = wintypes.BOOL
    read_file = kernel32.ReadFile
    read_file.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    read_file.restype = wintypes.BOOL
    if not set_pointer(handle, 0, None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(size)
    bytes_read = wintypes.DWORD()
    if not read_file(handle, buffer, size, ctypes.byref(bytes_read), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.raw[:bytes_read.value]


@unittest.skipUnless(os.name == 'nt', 'richiede Win32 CreateFileW')
class Win32FileLockAcceptance(unittest.TestCase):
    def test_locked_not_applied_then_unlocked_verified_without_restart(self):
        with tempfile.TemporaryDirectory(prefix='giorgio-win32-lock-') as directory:
            root = Path(directory)
            target = root / 'test_lock.txt'
            journal = root / 'giorgio_journal.json'
            target.write_bytes(ORIGINAL_BYTES)

            original_sha256 = sha256_bytes(ORIGINAL_BYTES)
            expected_sha256 = sha256_bytes(EXPECTED_BYTES)
            original_size = len(ORIGINAL_BYTES)
            temps_before = temporary_artifacts(root)
            children_before = active_child_pids()
            supervisor = TransactionSupervisor(
                journal,
                real_modify_executor,
                readonly_modify_verifier,
                start_timeout=2.0,
                kill_grace=1.0,
            )
            arguments = {
                'root': str(root),
                'relative_path': 'test_lock.txt',
                'content': EXPECTED_TEXT,
                'pre_sha256': original_sha256,
            }

            kernel32, handle = acquire_exclusive_handle(target)
            try:
                locked_arguments = dict(arguments, lock_handle=int(handle))
                locked_status = supervisor.submit_transaction(
                    'WIN32_LOCKED',
                    'MODIFY_FILE',
                    locked_arguments,
                    timeout=5.0,
                    pre_evidence={'sha256': original_sha256, 'size': original_size},
                    expected_evidence={'sha256': expected_sha256, 'size': len(EXPECTED_BYTES)},
                )
            finally:
                close_exclusive_handle(kernel32, handle)

            locked_bytes = target.read_bytes()
            locked_record = supervisor.registry['WIN32_LOCKED']
            locked_terminal = locked_record.terminal_result or {}
            locked_core_error = locked_terminal.get('core_error', locked_terminal)
            locked_evidence = {
                'status': locked_status.value,
                'winerror': locked_core_error.get('winerror'),
                'errno': locked_core_error.get('errno'),
                'error_type': locked_core_error.get('type'),
                'pre_sha256': original_sha256,
                'post_sha256': sha256_bytes(locked_bytes),
                'pre_size': original_size,
                'post_size': len(locked_bytes),
                'temporary_artifacts': temporary_artifacts(root),
                'residual_executor_pids': sorted(active_child_pids() - children_before),
                'supervisor_state': supervisor.state.value,
                'journal_status': json.loads(journal.read_text(encoding='utf-8'))['WIN32_LOCKED']['status'],
            }

            unlocked_status = supervisor.submit_transaction(
                'WIN32_UNLOCKED',
                'MODIFY_FILE',
                arguments,
                timeout=5.0,
                pre_evidence={'sha256': original_sha256, 'size': original_size},
                expected_evidence={'sha256': expected_sha256, 'size': len(EXPECTED_BYTES)},
            )
            unlocked_bytes = target.read_bytes()
            journal_data = json.loads(journal.read_text(encoding='utf-8'))
            unlocked_evidence = {
                'status': unlocked_status.value,
                'original_sha256': original_sha256,
                'expected_sha256': expected_sha256,
                'actual_sha256': sha256_bytes(unlocked_bytes),
                'temporary_artifacts': temporary_artifacts(root),
                'residual_executor_pids': sorted(active_child_pids() - children_before),
                'supervisor_state': supervisor.state.value,
                'journal_status': journal_data['WIN32_UNLOCKED']['status'],
            }
            print('WIN32_LOCK_EVIDENCE=' + json.dumps(
                {'locked': locked_evidence, 'unlocked': unlocked_evidence},
                sort_keys=True,
            ))

            self.assertEqual(locked_status, TransactionStatus.NOT_APPLIED)
            self.assertEqual(locked_evidence['error_type'], 'PermissionError')
            if locked_evidence['winerror'] is None:
                self.assertIsInstance(locked_evidence['errno'], int)
            else:
                self.assertIsInstance(locked_evidence['winerror'], int)
            self.assertEqual(locked_bytes, ORIGINAL_BYTES)
            self.assertEqual(locked_evidence['post_size'], original_size)
            self.assertEqual(locked_evidence['post_sha256'], original_sha256)
            self.assertEqual(locked_evidence['temporary_artifacts'], temps_before)
            self.assertEqual(locked_evidence['residual_executor_pids'], [])
            self.assertEqual(supervisor.state, SupervisorState.RUNNING)
            self.assertEqual(locked_evidence['journal_status'], TransactionStatus.NOT_APPLIED.value)

            self.assertEqual(unlocked_status, TransactionStatus.VERIFIED)
            self.assertEqual(unlocked_bytes, EXPECTED_BYTES)
            self.assertEqual(unlocked_evidence['actual_sha256'], expected_sha256)
            self.assertNotEqual(unlocked_evidence['actual_sha256'], original_sha256)
            self.assertEqual(unlocked_evidence['temporary_artifacts'], temps_before)
            self.assertEqual(unlocked_evidence['residual_executor_pids'], [])
            self.assertEqual(unlocked_evidence['journal_status'], TransactionStatus.VERIFIED.value)
            self.assertEqual(set(journal_data), {'WIN32_LOCKED', 'WIN32_UNLOCKED'})
            self.assertTrue(all(
                record['status'] not in {'PENDING', 'RUNNING', 'NEEDS_RECONCILIATION'}
                for record in journal_data.values()
            ))

            supervisor.shutdown()


if __name__ == '__main__':
    unittest.main()
