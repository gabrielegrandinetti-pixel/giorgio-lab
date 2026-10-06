"""Ollama adapter with an injected transport and no execution privileges."""

from __future__ import annotations

from collections.abc import Callable

from core.bridge.base_provider import BridgeError, BridgeErrorCode, BridgeResult, LLMBridgeProvider
from core.bridge.intent_parser import parse_intent


class OllamaBridgeProvider(LLMBridgeProvider):
    """Translate one injected Ollama response into a validated Bridge result."""

    def __init__(self, transport: Callable[[str], str]):
        self._transport = transport

    @property
    def provider_name(self) -> str:
        return 'ollama'

    def request_intent(self, prompt: str) -> BridgeResult:
        if type(prompt) is not str or not prompt.strip():
            return self._failure(TypeError('prompt must be a non-empty string'))
        try:
            raw_response = self._transport(prompt)
            if not isinstance(raw_response, str):
                raise TypeError('transport must return a string')
        except Exception as exc:
            return self._failure(exc)
        return parse_intent(raw_response)

    def _failure(self, exc: Exception) -> BridgeResult:
        return BridgeResult(error=BridgeError(
            code=BridgeErrorCode.PROVIDER_FAILURE,
            message='Il provider Ollama non ha prodotto una risposta valida.',
            provider=self.provider_name,
            exception_type=type(exc).__name__,
        ))
