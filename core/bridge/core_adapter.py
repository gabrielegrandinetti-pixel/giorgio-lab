"""Pure, fail-closed translation from a Bridge intent to a Core request."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from core.bridge.base_provider import ActionIntent
from core.bridge.intent_parser import normalize_relative_path


_SHA256 = re.compile(r'^[0-9a-f]{64}$')


@dataclass(frozen=True)
class ModifyPermission:
    """Explicit permission bound to one target and its verified pre-state."""

    target_path: str
    pre_sha256: str
    granted: bool


@dataclass(frozen=True)
class CoreModifyRequest:
    """Immutable data needed by the existing MODIFY_FILE Core boundary."""

    capability: Literal['MODIFY_FILE']
    relative_path: str
    content: str
    pre_sha256: str
    expected_sha256: str
    expected_size: int
    reasoning_summary: str


def adapt_modify_intent(intent: ActionIntent, permission: ModifyPermission) -> CoreModifyRequest:
    """Validate and translate without filesystem, network, or Supervisor I/O."""
    if not isinstance(intent, ActionIntent):
        raise TypeError('È richiesto un ActionIntent validato.')
    if not isinstance(permission, ModifyPermission):
        raise TypeError('È richiesta una permission MODIFY_FILE esplicita.')
    if intent.action_type != 'MODIFY_FILE':
        raise ValueError('Azione Bridge non supportata dal Core adapter.')
    if type(intent.target_path) is not str or type(intent.content) is not str:
        raise ValueError('Campi intento mancanti o non testuali.')
    if type(intent.expected_sha256) is not str or type(intent.reasoning_summary) is not str:
        raise ValueError('Digest o motivazione intento non validi.')

    safe_path = normalize_relative_path(intent.target_path)
    if safe_path is None or safe_path != intent.target_path:
        raise ValueError('Percorso intento non canonico o non sicuro.')
    if not intent.reasoning_summary.strip():
        raise ValueError('Motivazione intento mancante.')
    try:
        encoded = intent.content.encode('utf-8')
    except (AttributeError, UnicodeEncodeError) as exc:
        raise ValueError('Contenuto intento non valido.') from exc
    expected_sha256 = hashlib.sha256(encoded).hexdigest()
    if intent.expected_sha256 != expected_sha256:
        raise ValueError('Digest post-modifica incoerente con il contenuto.')

    if type(permission.granted) is not bool or not permission.granted:
        raise PermissionError('Permission MODIFY_FILE non concessa.')
    if type(permission.target_path) is not str or permission.target_path != safe_path:
        raise PermissionError('La permission non appartiene al file richiesto.')
    if type(permission.pre_sha256) is not str or not _SHA256.fullmatch(permission.pre_sha256):
        raise ValueError('Fingerprint pre-modifica non canonico.')

    return CoreModifyRequest(
        capability='MODIFY_FILE', relative_path=safe_path, content=intent.content,
        pre_sha256=permission.pre_sha256, expected_sha256=expected_sha256,
        expected_size=len(encoded), reasoning_summary=intent.reasoning_summary,
    )
