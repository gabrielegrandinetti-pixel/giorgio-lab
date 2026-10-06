"""Deterministic parsing for simple, high-confidence filesystem actions.

This layer intentionally handles only commands it can understand without guessing.
Anything ambiguous falls back to the normal agent planner.
"""
from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath

_FOLDER = r"(?:cartella|directory)"
_FILE = r"(?:file|documento)"
_CREATE_FILE = re.compile(
    rf"\b(?:crea\w*|aggiung\w*)\s+(?:(?:un|il)\s+)?(?:file\s+)?(?:vuoto\s+)?(?P<body>.*)$",
    re.IGNORECASE,
)
_FILE_NAME = re.compile(r"(?:con\s+il\s+nome|chiamat[oa])\s+[\"\']?(?P<name>[^\"\',]+?)[\"\']?(?=\s+(?:nella|dentro)\b|$)", re.IGNORECASE)
_FILE_SIMPLE = re.compile(r"^\s*[\"\']?(?P<name>[\w ._-]+\.[A-Za-z0-9]{1,12})[\"\']?(?=\s+(?:nella|dentro)\b|$)", re.IGNORECASE)
_CREATE_FOLDER = re.compile(
    rf"\b(?:crea\w*|aggiung\w*)\s+(?:una\s+)?{_FOLDER}\b(?P<body>.*)$",
    re.IGNORECASE,
)
_NAME = re.compile(r"\b(?:con\s+il\s+nome|chiamat[ao]|nome)\s+[\"']?(?P<name>[^\"',]+?)[\"']?(?=\s+(?:nella|dentro|in\s+questo\s+percorso|nel\s+percorso)\b|$)", re.IGNORECASE)
_SIMPLE_NAME = re.compile(r"^\s+[\"']?(?P<name>[\w ._-]+?)[\"']?(?=\s+(?:nella|dentro|in\s+questo\s+percorso|nel\s+percorso)\b|$)", re.IGNORECASE)
_PARENT = re.compile(rf"\b(?:nella|dentro)\s+(?:(?:la\s+)?{_FOLDER}\s+)?[\"']?(?P<parent>[^\"',]+?)[\"']?(?=\s+(?:in\s+questo\s+percorso|nel\s+percorso)\b|$)", re.IGNORECASE)
_BASE = re.compile(r"\b(?:in\s+questo\s+percorso|nel\s+percorso)\s+[\"']?(?P<base>[A-Za-z]:[\\/][^\"']+?)[\"']?\s*$", re.IGNORECASE)
_INVALID = re.compile(r"[<>:\"/\\|?*]")
_WRITE_FILE = re.compile(r'\b(?:scrivi|inserisci|metti)\s+(?P<content>.+?)\s+(?:nel|dentro\s+il)\s+file\s+["\']?(?P<name>[\w ._-]+\.[A-Za-z0-9]{1,12})["\']?\s*$', re.IGNORECASE)
_RENAME_FILE = re.compile(r'\b(?:rinomina|rinominami)\s+(?:il\s+)?(?:file\s+)?["\']?(?P<src>[\w ._-]+\.[A-Za-z0-9]{1,12})["\']?\s+(?:in|come)\s+["\']?(?P<dst>[\w ._-]+\.[A-Za-z0-9]{1,12})["\']?\s*$', re.IGNORECASE)
_MOVE_FILE = re.compile(r'\b(?:sposta|spostami|muovi|muovimi)\s+(?:il\s+)?(?:file\s+)?["\']?(?P<src>[\w ._-]+\.[A-Za-z0-9]{1,12})["\']?\s+(?:nella|dentro(?:\s+la)?|in)\s+(?:(?:cartella|directory)\s+)?["\']?(?P<folder>[\w ._-]+?)["\']?\s*$', re.IGNORECASE)
_MODIFY_EXACT = re.compile(r'\b(?:nel\s+file\s+)?[\"\']?(?P<name>[\w ._-]+\.[A-Za-z0-9]{1,12})[\"\']?\s+(?:cambia|sostituisci)\s+[\"\']?(?P<old>.+?)[\"\']?\s+(?:in|con)\s+[\"\']?(?P<new>.+?)[\"\']?\s*$', re.IGNORECASE)
_MODIFY_EXACT_ALT = re.compile(r'\b(?:cambia|sostituisci)\s+[\"\']?(?P<old>.+?)[\"\']?\s+(?:in|con)\s+[\"\']?(?P<new>.+?)[\"\']?\s+(?:nel|dentro\s+il)\s+file\s+[\"\']?(?P<name>[\w ._-]+\.[A-Za-z0-9]{1,12})[\"\']?\s*$', re.IGNORECASE)
_DELETE_FILE = re.compile(r'\b(?:elimina|cancella|rimuovi)\s+(?:il\s+)?(?:file\s+)?[\"\']?(?P<name>[\w ._-]+\.[A-Za-z0-9]{1,12})[\"\']?\s*$', re.IGNORECASE)
_COPY_FILE = re.compile(r'\b(?:copia|copiami|duplica|duplicami)\s+(?:il\s+)?(?:file\s+)?["\']?(?P<src>[\w ._-]+\.[A-Za-z0-9]{1,12})["\']?\s+(?:nella|dentro(?:\s+la)?|in)\s+(?:(?:cartella|directory)\s+)?["\']?(?P<folder>[\w ._-]+?)["\']?\s*$', re.IGNORECASE)


def _clean_component(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().strip("'\"").rstrip(" .")
    if not value or value in {".", ".."} or _INVALID.search(value):
        return None
    return value


def _same_windows_path(a: str, b: str | Path) -> bool:
    def norm(value: str) -> str:
        return str(PureWindowsPath(value.replace('/', '\\'))).rstrip('\\').casefold()
    return norm(a) == norm(str(b))


def parse_simple_action(request: str, project_root: str | Path) -> dict | None:
    """Return one safe structured operation when confidence is high, else None."""
    text = (request or "").strip()

    # P0: modifica testuale esatta e non ambigua di un singolo file.
    # Il parser costruisce l'intero contenuto atteso; l'executor applica poi
    # temp+fsync+atomic replace e verifica rileggendo il file.
    modify_match = _MODIFY_EXACT.search(text) or _MODIFY_EXACT_ALT.search(text)
    if modify_match:
        file_name = _clean_component(modify_match.group("name"))
        old = modify_match.group("old").strip().strip("\'\"")
        new = modify_match.group("new").strip().strip("\'\"")
        if not file_name or not old or not new or old == new:
            return None
        target = Path(project_root) / file_name
        if not target.is_file():
            return None
        try:
            original = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        # Zero o piu di una corrispondenza = nessuna modifica automatica.
        if original.count(old) != 1:
            return None
        expected = original.replace(old, new, 1)
        if expected == original:
            return None
        return {
            "type": "modify", "path": file_name, "destination": None,
            "content": expected, "reason": "Sostituzione testuale esplicita e univoca",
        }

    # P0: DELETE_FILE e deliberatamente una quarantena reversibile.
    # Un nome senza percorso viene risolto solo se identifica UN SOLO file
    # nel workspace. Zero o piu match => nessuna azione automatica.
    delete_match = _DELETE_FILE.search(text)
    if delete_match:
        file_name = _clean_component(delete_match.group("name"))
        if not file_name:
            return None
        root = Path(project_root)
        protected = {".git", ".giorgio_backups", ".giorgio_trash", "__pycache__", ".venv", "venv", "node_modules"}
        matches = []
        try:
            for candidate in root.rglob(file_name):
                try:
                    rel = candidate.relative_to(root)
                except ValueError:
                    continue
                if candidate.is_file() and not any(part.casefold() in protected for part in rel.parts):
                    matches.append(candidate)
        except OSError:
            return None
        if len(matches) != 1:
            return None
        rel = matches[0].relative_to(root).as_posix()
        return {
            "type": "delete", "path": rel, "destination": None,
            "content": None, "reason": "Quarantena reversibile richiesta esplicitamente dall'utente",
        }

    # P0: rinomina esplicita di un singolo file nel project root.
    # La rappresentiamo come MOVE, ma solo quando origine e destinazione sono
    # nomi file semplici: niente path impliciti o destinazioni inventate.
    rename_match = _RENAME_FILE.search(text)
    if rename_match:
        source = _clean_component(rename_match.group("src"))
        destination = _clean_component(rename_match.group("dst"))
        if not source or not destination or source.casefold() == destination.casefold():
            return None
        return {
            "type": "move", "path": source, "destination": destination,
            "content": None, "reason": "Richiesta esplicita dell'utente",
        }

    # P0: copia esplicita di un file in una cartella del project root.
    # La copia conserva i byte originali; non passa attraverso testo/encoding.
    copy_match = _COPY_FILE.search(text)
    if copy_match:
        source = _clean_component(copy_match.group("src"))
        folder = _clean_component(copy_match.group("folder"))
        if not source or not folder:
            return None
        destination = f"{folder}/{source}"
        return {
            "type": "copy", "path": source, "destination": destination,
            "content": None, "reason": "Richiesta esplicita dell'utente",
        }

    # P0: spostamento esplicito di un file in una cartella del project root.
    # Manteniamo il basename: la destinazione e cartella/nomefile.
    move_match = _MOVE_FILE.search(text)
    if move_match:
        source = _clean_component(move_match.group("src"))
        folder = _clean_component(move_match.group("folder"))
        if not source or not folder:
            return None
        destination = f"{folder}/{source}"
        return {
            "type": "move", "path": source, "destination": destination,
            "content": None, "reason": "Richiesta esplicita dell'utente",
        }

    # P0: scrittura esplicita di testo in un file. Il contenuto deve essere
    # presente nella richiesta e il nome file deve essere semplice/sicuro.
    # Se il file esiste lo modifichiamo; altrimenti lo creiamo.
    write_match = _WRITE_FILE.search(text)
    if write_match:
        file_name = _clean_component(write_match.group("name"))
        content = write_match.group("content").strip().strip("\'\"")
        if not file_name or not content or "." not in file_name or file_name.startswith("."):
            return None
        target = Path(project_root) / file_name
        return {
            "type": "modify" if target.is_file() else "create",
            "path": file_name, "destination": None, "content": content,
            "reason": "Richiesta esplicita dell'utente",
        }

    match = _CREATE_FOLDER.search(text)
    if not match:
        # P0: creazione deterministica di un file vuoto. Accettiamo solo un nome
        # file esplicito (con estensione) e, opzionalmente, una cartella padre.
        # Il contenuto non viene mai inventato.
        file_match = _CREATE_FILE.search(text)
        if not file_match:
            return None
        body = file_match.group("body") or ""
        file_name_match = _FILE_NAME.search(body) or _FILE_SIMPLE.search(body)
        file_name = _clean_component(file_name_match.group("name") if file_name_match else None)
        if not file_name or "." not in file_name or file_name.startswith("."):
            return None
        parent_match = _PARENT.search(body)
        parent = _clean_component(parent_match.group("parent") if parent_match else None)
        # Se l'utente ha specificato esplicitamente una cartella padre ma il
        # componente non e sicuro (es. ..), non dobbiamo perderlo e degradare
        # silenziosamente l'azione nel project root. Meglio fallback/rifiuto.
        if parent_match and parent is None:
            return None
        base_match = _BASE.search(body)
        if base_match and not _same_windows_path(base_match.group("base").strip(), project_root):
            return None
        relative = f"{parent}/{file_name}" if parent else file_name
        return {
            "type": "create", "path": relative, "destination": None,
            "content": "", "reason": "Richiesta esplicita dell'utente",
        }
    body = match.group("body") or ""
    name_match = _NAME.search(body) or _SIMPLE_NAME.search(body)
    name = _clean_component(name_match.group("name") if name_match else None)
    if not name:
        return None
    parent_match = _PARENT.search(body)
    parent = _clean_component(parent_match.group("parent") if parent_match else None)
    # Stessa regola per MKDIR: un parent esplicito invalido non puo essere
    # ignorato trasformando la richiesta in una creazione nel project root.
    if parent_match and parent is None:
        return None
    base_match = _BASE.search(body)
    if base_match and not _same_windows_path(base_match.group("base").strip(), project_root):
        return None
    relative = f"{parent}/{name}" if parent else name
    return {
        "type": "mkdir", "path": relative, "destination": None,
        "content": None, "reason": "Richiesta esplicita dell'utente",
    }
