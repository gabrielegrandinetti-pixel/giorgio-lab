from __future__ import annotations

import json
import socket
import time
from typing import Any, Callable

import ollama


class OllamaError(Exception):
    """Errore nella comunicazione tra Giorgio e Ollama."""


class OllamaClient:
    """
    Gestisce la comunicazione con Ollama.

    Giorgio usa questo modulo invece di chiamare Ollama
    direttamente dal resto dell'applicazione.
    """

    def __init__(
        self,
        model: str = "qwen2.5-coder:7b",
        num_ctx: int = 16384,
        temperature: float = 0.2,
        request_timeout: float = 90.0,
        connection_timeout: float = 10.0,
    ):
        if request_timeout <= 0 or connection_timeout <= 0:
            raise ValueError("I timeout di Ollama devono essere maggiori di zero.")

        self.model = model
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.request_timeout = request_timeout
        self.connection_timeout = connection_timeout
        self._client = ollama.Client(timeout=request_timeout)
        self._connection_client = ollama.Client(timeout=connection_timeout)

    # ---------------------------------------------------------
    # CONTROLLO OLLAMA
    # ---------------------------------------------------------

    def check_connection(self) -> tuple[bool, str]:
        """
        Controlla che Ollama sia raggiungibile.
        """

        try:
            self._connection_client.list()
            return True, "Ollama connesso."

        except Exception as exc:
            return False, (
                "Ollama non sembra essere attivo.\n"
                f"Dettaglio: {exc}"
            )

    # ---------------------------------------------------------
    # CONTROLLO MODELLO
    # ---------------------------------------------------------

    def model_available(self) -> bool:
        """
        Controlla se il modello configurato è installato.
        """

        try:
            response = self._connection_client.list()

            models = getattr(response, "models", None)

            if models is None and isinstance(response, dict):
                models = response.get("models", [])

            for model in models or []:

                name = getattr(model, "model", None)

                if name is None and isinstance(model, dict):
                    name = (
                        model.get("model")
                        or model.get("name")
                    )

                if name == self.model:
                    return True

            return False

        except Exception:
            return False

    # ---------------------------------------------------------
    # CHAT NORMALE
    # ---------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> str:
        """
        Conversazione normale con Giorgio.
        Non richiede JSON strutturato.
        """

        final_messages = self._prepare_messages(
            messages,
            system_prompt,
        )

        try:
            response = self._client.chat(
                model=self.model,
                messages=final_messages,
                options={
                    "temperature": self.temperature,
                    "num_ctx": self.num_ctx,
                },
            )

            return self._extract_content(response)

        except Exception as exc:
            raise OllamaError(
                self._friendly_error(exc)
            ) from exc

    def chat_stream(self, messages, system_prompt=None, max_tokens=1024):
        """Trasmette testo alla chat; il worker può essere terminato dalla UI."""
        stream = None
        try:
            stream = self._client.chat(
                model=self.model,
                messages=self._prepare_messages(messages, system_prompt),
                stream=True,
                options={"temperature": self.temperature, "num_ctx": self.num_ctx,
                         "num_predict": max_tokens},
            )
            for chunk in stream:
                content = self._extract_content(chunk)
                if content:
                    yield content
                done = chunk.get("done", False) if isinstance(chunk, dict) else getattr(chunk, "done", False)
                reason = chunk.get("done_reason") if isinstance(chunk, dict) else getattr(chunk, "done_reason", None)
                if done:
                    if reason == "length":
                        yield "\n\n[Risposta fermata al limite di lunghezza. Puoi chiedermi di continuare.]"
                    return
            raise OllamaError("La risposta si è interrotta prima del completamento.")
        except OllamaError:
            raise
        except Exception as exc:
            raise OllamaError(self._friendly_error(exc)) from exc
        finally:
            if stream is not None:
                close = getattr(stream, "close", None)
                if close is not None:
                    close()

    # ---------------------------------------------------------
    # RISPOSTA JSON PER L'AGENTE
    # ---------------------------------------------------------

    def chat_json(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        schema: dict[str, Any] | None = None,
        progress_callback: Callable[[str], None] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """
        Richiede a Qwen una risposta JSON.

        Verrà usato dall'agente per generare piani e
        operazioni sui file in maniera controllabile.
        """

        if max_tokens <= 0:
            raise ValueError("max_tokens deve essere maggiore di zero.")
        final_messages = self._prepare_messages(
            messages,
            system_prompt,
        )

        if sum(len(m['content']) for m in final_messages) > self.num_ctx * 2:
            raise OllamaError(
                "Troppo materiale per il contesto configurato. "
                "Riduci gli allegati o scegli un progetto più piccolo; nessun file è stato modificato."
            )

        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": final_messages,
                "options": {
                    "temperature": self.temperature,
                    "num_ctx": self.num_ctx,
                    "num_predict": max_tokens,
                },
                "stream": True,
            }

            if schema:
                kwargs["format"] = schema
            else:
                kwargs["format"] = "json"

            stream = self._client.chat(**kwargs)
            parts: list[str] = []
            total_chars = 0
            started = time.monotonic()
            last_report = started
            completed = False
            try:
                for chunk in stream:
                    text = self._extract_content(chunk)
                    if text:
                        parts.append(text)
                        total_chars += len(text)
                    done = chunk.get("done", False) if isinstance(chunk, dict) else getattr(chunk, "done", False)
                    reason = chunk.get("done_reason") if isinstance(chunk, dict) else getattr(chunk, "done_reason", None)
                    now = time.monotonic()
                    if progress_callback and text and (len(parts) == 1 or now - last_report >= 5):
                        progress_callback(
                            f"Qwen sta generando: {total_chars} caratteri ricevuti "
                            f"in {now - started:.0f} secondi."
                        )
                        last_report = now
                    if done:
                        if reason == "length":
                            raise OllamaError(
                                f"Qwen ha raggiunto il limite di {max_tokens} token. "
                                "Proposta incompleta scartata: nessuna modifica applicata."
                            )
                        completed = True
                        break
            finally:
                close = getattr(stream, "close", None)
                if close is not None:
                    close()
            if not completed:
                raise OllamaError("La risposta di Qwen si è interrotta prima del completamento.")
            return self._parse_json("".join(parts))

        except OllamaError:
            raise

        except Exception as exc:
            raise OllamaError(
                self._friendly_error(exc)
            ) from exc

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------

    def _prepare_messages(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None,
    ) -> list[dict[str, str]]:

        prepared: list[dict[str, str]] = []

        # Il system prompt viene sempre mantenuto.
        if system_prompt:
            prepared.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        for message in messages:

            role = message.get("role", "").strip()
            content = message.get("content", "")

            if role not in {
                "user",
                "assistant",
                "system",
            }:
                continue

            if not content:
                continue

            prepared.append(
                {
                    "role": role,
                    "content": content,
                }
            )

        return prepared

    @staticmethod
    def _extract_content(response: Any) -> str:
        """
        Supporta sia le nuove risposte object-style
        sia quelle dict-style di Ollama.
        """

        try:
            message = getattr(response, "message", None)

            if message is not None:
                content = getattr(message, "content", None)

                if content is not None:
                    return str(content)

            if isinstance(response, dict):
                message = response.get("message", {})

                if isinstance(message, dict):
                    return str(
                        message.get("content", "")
                    )

        except Exception:
            pass

        raise OllamaError(
            "Ollama ha restituito una risposta "
            "che Giorgio non riesce a interpretare."
        )

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:

        content = content.strip()

        if not content:
            raise OllamaError(
                "Il modello ha restituito una risposta vuota."
            )

        try:
            result = json.loads(content)

        except json.JSONDecodeError as exc:
            raise OllamaError(
                "Qwen non ha restituito un JSON valido."
            ) from exc

        if not isinstance(result, dict):
            raise OllamaError(
                "La risposta JSON di Qwen non è un oggetto."
            )

        return result

    def _friendly_error(self, exc: Exception) -> str:
        """
        Trasforma gli errori tecnici più comuni
        in messaggi comprensibili.
        """

        text = str(exc)
        lower = text.lower()

        if (
            "connection refused" in lower
            or "failed to connect" in lower
            or "connection error" in lower
        ):
            return (
                "Non riesco a collegarmi a Ollama. "
                "Controlla che Ollama sia avviato."
            )

        if "not found" in lower and self.model.lower() in lower:
            return (
                f"Il modello '{self.model}' non è installato. "
                f"Installa il modello in Ollama prima di continuare."
            )

        if "context length" in lower:
            return (
                "Il contesto inviato a Qwen è troppo grande. "
                "Giorgio dovrà ridurre i file forniti al modello."
            )

        if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in lower:
            return (
                "Ollama non ha inviato dati entro il timeout "
                f"({self.request_timeout:.0f} secondi). "
                "Il modello potrebbe essere lento, sovraccarico o ancora in caricamento."
            )

        if "readtimeout" in lower or "connecttimeout" in lower:
            return (
                "Ollama non ha risposto entro il tempo previsto. "
                "Controlla che il modello non sia sovraccarico e riprova."
            )

        return f"Errore Ollama: {text}"
