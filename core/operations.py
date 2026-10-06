from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.security import (
    SecurityError,
    safe_project_path,
    validate_operation_count,
)


OperationType = Literal[
    "create",
    "modify",
    "delete",
    "move",
    "copy",
    "mkdir",
]


@dataclass
class FileOperation:
    """
    Una singola operazione proposta da Giorgio.

    IMPORTANTE:
    questa classe descrive l'operazione,
    ma non la esegue automaticamente.
    """

    type: OperationType
    path: str
    content: str | None = None
    destination: str | None = None
    reason: str = ""


class OperationError(Exception):
    """Errore durante la validazione di un'operazione."""


class OperationManager:
    """
    Valida e prepara le operazioni sui file.

    L'esecuzione effettiva avverrà soltanto dopo
    l'autorizzazione esplicita dell'utente.
    """

    VALID_TYPES = {
        "create",
        "modify",
        "delete",
        "move",
        "copy",
        "mkdir",
    }

    def __init__(
        self,
        project_root: str | Path,
        max_operations: int = 15,
    ):
        self.project_root = Path(project_root).resolve()
        self.max_operations = max_operations

    # ---------------------------------------------------------
    # CONVERSIONE JSON -> OPERAZIONI
    # ---------------------------------------------------------

    def parse_operations(
        self,
        raw_operations: list[dict],
    ) -> list[FileOperation]:

        if not isinstance(raw_operations, list):
            raise OperationError(
                "La lista delle operazioni non è valida."
            )

        validate_operation_count(
            raw_operations,
            self.max_operations,
        )

        operations: list[FileOperation] = []

        for index, raw in enumerate(
            raw_operations,
            start=1,
        ):
            if not isinstance(raw, dict):
                raise OperationError(
                    f"Operazione {index} non valida."
                )

            operation_type = str(
                raw.get("type", "")
            ).strip().lower()

            path = str(
                raw.get("path", "")
            ).strip()

            destination = raw.get("destination")
            content = raw.get("content")
            reason = str(
                raw.get("reason", "")
            ).strip()

            if destination is not None:
                destination = str(destination).strip()

            if content is not None:
                content = str(content)

            operation = FileOperation(
                type=operation_type,
                path=path,
                content=content,
                destination=destination,
                reason=reason,
            )

            self.validate(operation)
            operations.append(operation)

        return operations

    # ---------------------------------------------------------
    # VALIDAZIONE
    # ---------------------------------------------------------

    def validate(
        self,
        operation: FileOperation,
    ) -> None:

        if operation.type not in self.VALID_TYPES:
            raise OperationError(
                f"Tipo di operazione non consentito: "
                f"{operation.type}"
            )

        if not operation.path:
            raise OperationError(
                "Percorso dell'operazione mancante."
            )

        try:
            target = safe_project_path(
                self.project_root,
                operation.path,
            )
        except SecurityError as exc:
            raise OperationError(str(exc)) from exc

        # CREATE
        if operation.type == "create":

            if operation.content is None:
                raise OperationError(
                    f"Contenuto mancante per la creazione "
                    f"di {operation.path}."
                )

            if target.exists():
                raise OperationError(
                    f"CREATE rifiutato: {operation.path} "
                    f"esiste già."
                )

        # MODIFY
        elif operation.type == "modify":

            if operation.content is None:
                raise OperationError(
                    f"Contenuto mancante per la modifica "
                    f"di {operation.path}."
                )

            if not target.exists():
                raise OperationError(
                    f"MODIFY rifiutato: {operation.path} "
                    f"non esiste."
                )

            if not target.is_file():
                raise OperationError(
                    f"{operation.path} non è un file."
                )

        # DELETE
        elif operation.type == "delete":

            if not target.exists():
                raise OperationError(
                    f"DELETE rifiutato: {operation.path} "
                    f"non esiste."
                )

        # MOVE
        elif operation.type == "move":

            if not target.exists():
                raise OperationError(
                    f"MOVE rifiutato: {operation.path} "
                    f"non esiste."
                )

            if not operation.destination:
                raise OperationError(
                    "Destinazione mancante per MOVE."
                )

            try:
                destination = safe_project_path(
                    self.project_root,
                    operation.destination,
                )
            except SecurityError as exc:
                raise OperationError(str(exc)) from exc

            if destination.exists():
                raise OperationError(
                    f"MOVE rifiutato: "
                    f"{operation.destination} esiste già."
                )

            if target == destination:
                raise OperationError(
                    "Origine e destinazione coincidono."
                )

        # COPY
        elif operation.type == "copy":
            if not target.exists() or not target.is_file():
                raise OperationError(f"COPY rifiutato: {operation.path} non è un file.")
            if not operation.destination:
                raise OperationError("Destinazione mancante per COPY.")
            try:
                destination = safe_project_path(self.project_root, operation.destination)
            except SecurityError as exc:
                raise OperationError(str(exc)) from exc
            if destination.exists():
                raise OperationError(f"COPY rifiutato: {operation.destination} esiste già.")
            if target == destination:
                raise OperationError("Origine e destinazione coincidono.")

        # MKDIR
        elif operation.type == "mkdir":

            if target.exists():
                raise OperationError(
                    f"MKDIR rifiutato: {operation.path} "
                    f"esiste già."
                )

    # ---------------------------------------------------------
    # DESCRIZIONE PER ANTEPRIMA
    # ---------------------------------------------------------

    def describe(
        self,
        operation: FileOperation,
    ) -> str:

        reason = (
            f"\nMotivo: {operation.reason}"
            if operation.reason
            else ""
        )

        if operation.type == "create":
            return (
                f"CREA FILE: {operation.path}"
                f"{reason}"
            )

        if operation.type == "modify":
            return (
                f"MODIFICA FILE: {operation.path}"
                f"{reason}"
            )

        if operation.type == "delete":
            return (
                f"ELIMINA: {operation.path}"
                f"{reason}"
            )

        if operation.type == "move":
            return (
                f"SPOSTA/RINOMINA:\n"
                f"{operation.path}\n"
                f"→ {operation.destination}"
                f"{reason}"
            )

        if operation.type == "copy":
            return (f"COPIA:\n{operation.path}\n→ {operation.destination}" f"{reason}")

        if operation.type == "mkdir":
            return (
                f"CREA CARTELLA: {operation.path}"
                f"{reason}"
            )

        return operation.type

    # ---------------------------------------------------------
    # PERCORSI COINVOLTI
    # ---------------------------------------------------------

    def affected_paths(
        self,
        operations: list[FileOperation],
    ) -> list[Path]:

        paths: list[Path] = []

        for operation in operations:

            target = safe_project_path(
                self.project_root,
                operation.path,
            )

            paths.append(target)

            if (
                operation.type in {"move", "copy"}
                and operation.destination
            ):
                destination = safe_project_path(
                    self.project_root,
                    operation.destination,
                )

                paths.append(destination)

        # Rimuove duplicati mantenendo l'ordine.
        unique: list[Path] = []
        seen: set[Path] = set()

        for path in paths:
            if path not in seen:
                seen.add(path)
                unique.append(path)

        return unique