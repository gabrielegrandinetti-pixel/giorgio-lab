"""Pure, fail-closed parser for the Bridge's only accepted LLM intent."""

from __future__ import annotations

import hashlib
import json
import re

from core.bridge.base_provider import ActionIntent, BridgeError, BridgeErrorCode, BridgeResult


_TOP_LEVEL_KEYS = frozenset({'action_type', 'parameters', 'reasoning_summary'})
_PARAMETER_REQUIRED_KEYS = frozenset({'target_path', 'content'})
_PARAMETER_ALLOWED_KEYS = _PARAMETER_REQUIRED_KEYS | {'expected_sha256'}
_RESERVED_WINDOWS_NAMES = frozenset({
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{number}' for number in range(1, 10)),
    *(f'LPT{number}' for number in range(1, 10)),
})
_DRIVE_PREFIX = re.compile(r'^[A-Za-z]:')
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_WINDOWS_ILLEGAL = frozenset('<>:"|?*')


def _invalid(message: str) -> BridgeResult:
    return BridgeResult(error=BridgeError(BridgeErrorCode.INVALID_INTENT, message))


def _pairs_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def normalize_relative_path(path: str) -> str | None:
    if not path or len(path) > 1024:
        return None
    if path.startswith(('/', '\\')) or _DRIVE_PREFIX.match(path):
        return None
    if any(ord(character) < 32 or character in _WINDOWS_ILLEGAL for character in path):
        return None
    normalized = path.replace('\\', '/')
    components = normalized.split('/')
    if any(not component or component in {'.', '..'} for component in components):
        return None
    for component in components:
        if component.endswith(('.', ' ')):
            return None
        if component.split('.', 1)[0].upper() in _RESERVED_WINDOWS_NAMES:
            return None
    return normalized


def parse_intent(raw_response: str) -> BridgeResult:
    """Parse exactly one JSON object without filesystem or network I/O."""
    if type(raw_response) is not str:
        return _invalid('La risposta del provider deve essere una stringa JSON.')
    try:
        payload = json.loads(raw_response, object_pairs_hook=_pairs_without_duplicates)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _invalid('JSON non valido o ambiguo.')
    if type(payload) is not dict or set(payload) != _TOP_LEVEL_KEYS:
        return _invalid('Schema JSON non valido.')

    action_type = payload['action_type']
    parameters = payload['parameters']
    reasoning_summary = payload['reasoning_summary']
    if type(action_type) is not str or type(parameters) is not dict or type(reasoning_summary) is not str:
        return _invalid('Tipi JSON non validi.')
    if action_type != 'MODIFY_FILE':
        return BridgeResult(error=BridgeError(BridgeErrorCode.UNSUPPORTED_ACTION, 'Azione Bridge non supportata.'))
    if set(parameters) not in (_PARAMETER_REQUIRED_KEYS, _PARAMETER_ALLOWED_KEYS):
        return _invalid('Parametri JSON non validi.')

    target_path = parameters.get('target_path')
    content = parameters.get('content')
    supplied_digest = parameters.get('expected_sha256')
    if type(target_path) is not str or type(content) is not str:
        return _invalid('I parametri del file devono essere stringhe.')
    if supplied_digest is not None and type(supplied_digest) is not str:
        return _invalid('Digest non valido.')
    if not reasoning_summary.strip() or len(reasoning_summary) > 1000:
        return _invalid('Motivazione non valida.')

    safe_path = normalize_relative_path(target_path)
    if safe_path is None:
        return _invalid('Percorso destinazione non valido.')
    try:
        encoded_content = content.encode('utf-8')
    except UnicodeEncodeError:
        return _invalid('Contenuto non codificabile in UTF-8.')
    if len(encoded_content) > 2 * 1024 * 1024:
        return _invalid('Contenuto troppo grande.')
    digest = hashlib.sha256(encoded_content).hexdigest()
    if supplied_digest is not None and (not _SHA256.fullmatch(supplied_digest) or supplied_digest != digest):
        return _invalid('Digest fornito non valido.')

    return BridgeResult(intent=ActionIntent(
        action_type='MODIFY_FILE', target_path=safe_path, content=content,
        expected_sha256=digest, reasoning_summary=reasoning_summary,
    ))
