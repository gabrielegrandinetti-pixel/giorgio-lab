from __future__ import annotations

from pathlib import Path


class SecurityError(Exception):
    """Operazione rifiutata dal sistema di sicurezza di Giorgio."""


PROTECTED_NAMES = {
    ".git",
    ".giorgio_backups",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
}


def safe_project_path(project_root: Path, relative_path: str) -> Path:
    """
    Controlla che un percorso sia realmente dentro il progetto.
    """

    project_root = Path(project_root).resolve()
    relative_path = relative_path.strip().replace("\\", "/")

    if not relative_path:
        raise SecurityError("Percorso vuoto.")

    relative = Path(relative_path)

    # Giorgio non può usare percorsi assoluti tipo C:\...
    if relative.is_absolute():
        raise SecurityError(
            f"Percorso assoluto non consentito: {relative_path}"
        )

    # Impedisce di uscire dal progetto con ../
    if ".." in relative.parts:
        raise SecurityError(
            f"Uso di '..' non consentito: {relative_path}"
        )

    protected = {name.lower() for name in PROTECTED_NAMES}

    # Protegge cartelle importanti
    for part in relative.parts:
        if part.lower() in protected:
            raise SecurityError(
                f"Percorso protetto: {relative_path}"
            )

    final_path = (project_root / relative).resolve()

    # Controllo finale: deve essere dentro il progetto
    try:
        final_path.relative_to(project_root)
    except ValueError as exc:
        raise SecurityError(
            f"Il percorso esce dal progetto: {relative_path}"
        ) from exc

    return final_path


def validate_operation_count(
    operations: list,
    max_operations: int = 15,
) -> None:
    """
    Blocca richieste anomale con troppe modifiche contemporaneamente.
    """

    if len(operations) > max_operations:
        raise SecurityError(
            f"Giorgio vuole eseguire {len(operations)} operazioni. "
            f"Il limite di sicurezza è {max_operations}."
        )


def is_protected_path(relative_path: str) -> bool:
    """Controlla velocemente se un percorso contiene cartelle protette."""

    parts = Path(relative_path.replace("\\", "/")).parts
    protected = {name.lower() for name in PROTECTED_NAMES}

    return any(part.lower() in protected for part in parts)