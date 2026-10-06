"""Authorized MODIFY_FILE execution and independent verification for the Core."""

from __future__ import annotations

import hashlib
from pathlib import Path

from core.bridge.core_adapter import CoreModifyRequest
from core.executor import apply_approved
from core.security import safe_project_path


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def execute_modify_request(task_id: str, capability: str, arguments: dict) -> dict:
    """Supervisor child entry point; mutation remains inside verified Core code."""
    if capability != 'MODIFY_FILE':
        raise ValueError(f'Capability non supportata: {capability}')
    root = arguments['root']
    relative_path = arguments['relative_path']
    content = arguments['content']
    pre_sha256 = arguments['pre_sha256']
    apply_approved(
        root,
        [{'type': 'modify', 'path': relative_path, 'destination': None,
          'content': content, 'reason': arguments.get('reasoning_summary', '')}],
        {relative_path: pre_sha256},
    )
    target = safe_project_path(Path(root).resolve(), relative_path)
    payload = target.read_bytes()
    return {
        'status': 'VERIFIED',
        'evidence': {
            'task_id': task_id,
            'sha256': _sha256(payload),
            'size': len(payload),
        },
    }


def verify_modify_request(record) -> dict:
    """Read-only verifier used by reconciliation and restart recovery."""
    try:
        root = Path(record.arguments['root']).resolve()
        target = safe_project_path(root, record.arguments['relative_path'])
        if not target.is_file():
            return {'status': 'RECOVERY_REQUIRED', 'evidence': {'exists': False}}
        payload = target.read_bytes()
        actual = _sha256(payload)
        evidence = {'exists': True, 'sha256': actual, 'size': len(payload)}
        if actual == record.expected_evidence.get('sha256'):
            return {'status': 'VERIFIED', 'evidence': evidence}
        if actual == record.pre_evidence.get('sha256'):
            return {'status': 'NOT_APPLIED', 'evidence': evidence}
        return {'status': 'RECOVERY_REQUIRED', 'evidence': evidence}
    except Exception as exc:
        return {
            'status': 'RECOVERY_REQUIRED',
            'evidence': {'error_type': type(exc).__name__, 'error': str(exc)},
        }


def submit_modify_request(supervisor, task_id: str, project_root, request: CoreModifyRequest,
                          timeout: float = 5.0):
    """Submit an already permission-bound request to the existing Supervisor."""
    if not isinstance(request, CoreModifyRequest):
        raise TypeError('È richiesta una CoreModifyRequest autorizzata.')
    arguments = {
        'root': str(Path(project_root).resolve()),
        'relative_path': request.relative_path,
        'content': request.content,
        'pre_sha256': request.pre_sha256,
        'reasoning_summary': request.reasoning_summary,
    }
    return supervisor.submit_transaction(
        task_id,
        request.capability,
        arguments,
        timeout=timeout,
        pre_evidence={'sha256': request.pre_sha256},
        expected_evidence={
            'sha256': request.expected_sha256,
            'size': request.expected_size,
        },
    )
