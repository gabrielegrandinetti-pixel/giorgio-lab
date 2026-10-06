from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Literal


class BridgeErrorCode(str, Enum):
    INVALID_INTENT = 'INVALID_INTENT'
    UNSUPPORTED_ACTION = 'UNSUPPORTED_ACTION'
    PROVIDER_FAILURE = 'PROVIDER_FAILURE'


@dataclass(frozen=True)
class ActionIntent:
    action_type: Literal['MODIFY_FILE']
    target_path: str
    content: str
    expected_sha256: str
    reasoning_summary: str


@dataclass(frozen=True)
class BridgeError:
    code: BridgeErrorCode
    message: str
    provider: str | None = None
    exception_type: str | None = None


@dataclass(frozen=True)
class BridgeResult:
    intent: ActionIntent | None = None
    error: BridgeError | None = None

    def __post_init__(self) -> None:
        if (self.intent is None) == (self.error is None):
            raise ValueError('BridgeResult richiede esattamente uno tra intent ed error.')


class LLMBridgeProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def request_intent(self, prompt: str) -> BridgeResult:
        raise NotImplementedError
