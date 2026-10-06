"""P0 Action Harness: baseline riproducibile delle capacita operative di Giorgio.

Non usa Ollama/Groq: misura solo gli strati deterministici gia presenti.
Una richiesta LLM non viene quindi dichiarata end-to-end verificata da questo harness.
"""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# app_worker importa il client Ollama, ma is_action_request non richiede un server.
try:
    import ollama  # noqa: F401
except ImportError:
    import types
    sys.modules['ollama'] = types.ModuleType('ollama')

from core.app_worker import is_action_request
from core.executor import apply_approved, fingerprint
from core.action_intent import parse_simple_action


@dataclass
class Result:
    case: str
    stage: str
    passed: bool
    detail: str = ""


ACTION_CASES = [
    "Crea una cartella Gabriele dentro Stefano",
    "Crea il file note.txt",
    "Aggiungi un file README.md",
    "Modifica config.json",
    "Correggi il bug in main.py",
    "Sistema la funzione login",
    "Implementa il controllo errori",
    "Fixa il problema nel parser",
    "Rinomina prova.txt in finale.txt",
    "Sposta report.pdf nella cartella Archivio",
    "Muovi foto.jpg in Immagini",
    "Cancella temp.txt",
    "Elimina la cartella cache",
    "Rimuovi old.log",
    "Copia dati.csv in backup",
    "Scrivi ciao nel file messaggio.txt",
    "Salva questa configurazione",
    "Sostituisci il contenuto di a.txt",
    "Installa requests nel progetto",
    "creami una directory Test",
    "aggiungimi un file vuoto",
    "modificami il README",
    "rinominami questa cartella",
    "spostami il file nella directory output",
    "copiami il file in backup",
]

READ_ONLY_CASES = [
    "Cos'è un file JSON?",
    "Mi spieghi questa funzione?",
    "Quale file contiene la configurazione?",
    "Perché il programma va in errore?",
    "Come funziona Git?",
    "Dove si trova main.py?",
    "Puoi spiegarmi il README senza modificarlo?",
    "Qual è la differenza tra copia e spostamento?",
    "Che cosa fa questa classe?",
    "Secondo te questa architettura è buona?",
    "Mostrami come funziona il parser",
    "Analizza questo errore",
    "Dimmi quali dipendenze usa il progetto",
    "Quanto è grande questo file?",
    "Cosa succede se elimino questa cartella?",
]


def routing_results() -> list[Result]:
    out = []
    for i, text in enumerate(ACTION_CASES, 1):
        got = is_action_request(text)
        out.append(Result(f"action-{i:02d}", "INTENT", got, text))
    for i, text in enumerate(READ_ONLY_CASES, 1):
        got = not is_action_request(text)
        out.append(Result(f"readonly-{i:02d}", "INTENT", got, text))
    return out


def executor_results() -> list[Result]:
    """10 prove fisiche su filesystem temporaneo: 5 mkdir + 5 create/modify."""
    out: list[Result] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i in range(5):
            rel = f"Parent{i}/Child{i}"
            raw = [{"type": "mkdir", "path": rel, "destination": None,
                    "content": None, "reason": "acceptance"}]
            try:
                apply_approved(str(root), raw, {rel: None})
                target = root / rel
                ok = target.exists() and target.is_dir()
                out.append(Result(f"mkdir-{i+1:02d}", "VERIFIED", ok, rel))
            except Exception as exc:
                out.append(Result(f"mkdir-{i+1:02d}", "EXECUTION", False, str(exc)))

        for i in range(5):
            rel = f"file{i}.txt"
            content = f"contenuto-{i}\n"
            create = [{"type": "create", "path": rel, "destination": None,
                       "content": content, "reason": "acceptance"}]
            try:
                apply_approved(str(root), create, {rel: None})
                path = root / rel
                created = path.exists() and path.read_text() == content
                new_content = content + "modificato\n"
                modify = [{"type": "modify", "path": rel, "destination": None,
                           "content": new_content, "reason": "acceptance"}]
                apply_approved(str(root), modify, {rel: fingerprint(path)})
                ok = created and path.read_text() == new_content
                out.append(Result(f"file-{i+1:02d}", "VERIFIED", ok, rel))
            except Exception as exc:
                out.append(Result(f"file-{i+1:02d}", "EXECUTION", False, str(exc)))
    return out


def natural_create_results() -> list[Result]:
    """4 E2E deterministici, con metriche separate per i cinque stadi P0."""
    cases = [
        ("Crea il file note.txt", "note.txt"),
        ("Creami un file vuoto appunti.md", "appunti.md"),
        ("Aggiungi un file report.csv dentro la cartella Dati", "Dati/report.csv"),
        ("Crea un file chiamato prova.json", "prova.json"),
    ]
    out: list[Result] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "Dati").mkdir()
        for i, (request, expected_path) in enumerate(cases, 1):
            key = f"natural-create-{i:02d}"
            intent_ok = is_action_request(request)
            out.append(Result(key, "INTENT", intent_ok, request))
            op = parse_simple_action(request, root) if intent_ok else None
            tool_ok = bool(op and op.get("type") == "create")
            out.append(Result(key, "TOOL", tool_ok, str(op)))
            args_ok = bool(tool_ok and op.get("path") == expected_path and op.get("content") == "")
            out.append(Result(key, "ARGUMENTS", args_ok, str(op)))
            executed = False
            if args_ok:
                try:
                    apply_approved(str(root), [op], {expected_path: None})
                    executed = True
                except Exception as exc:
                    out.append(Result(key, "EXECUTION", False, str(exc)))
            if not any(r.case == key and r.stage == "EXECUTION" for r in out):
                out.append(Result(key, "EXECUTION", executed, expected_path))
            target = root / expected_path
            verified = executed and target.is_file() and target.read_bytes() == b""
            out.append(Result(key, "VERIFY", verified, expected_path))
    return out



def natural_write_results() -> list[Result]:
    """E2E deterministici per scrittura esplicita, inclusa precondizione verificata."""
    cases = [
        ("Scrivi ciao nel file messaggio.txt", "messaggio.txt", "ciao", False),
        ("Inserisci versione 2 nel file stato.txt", "stato.txt", "versione 2", True),
        ("Metti pronto dentro il file esito.md", "esito.md", "pronto", False),
        ("Scrivi ordine 847 completato nel file log.txt", "log.txt", "ordine 847 completato", True),
    ]
    out: list[Result] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i, (request, expected_path, expected_content, preexisting) in enumerate(cases, 1):
            key = f"natural-write-{i:02d}"
            target = root / expected_path
            if preexisting:
                target.write_text("vecchio", encoding="utf-8")
            intent_ok = is_action_request(request)
            out.append(Result(key, "INTENT", intent_ok, request))
            op = parse_simple_action(request, root) if intent_ok else None
            expected_type = "modify" if preexisting else "create"
            tool_ok = bool(op and op.get("type") == expected_type)
            out.append(Result(key, "TOOL", tool_ok, str(op)))
            args_ok = bool(tool_ok and op.get("path") == expected_path and op.get("content") == expected_content)
            out.append(Result(key, "ARGUMENTS", args_ok, str(op)))
            expected_state = fingerprint(target) if preexisting else None
            permission_ok = args_ok and ((preexisting and expected_state is not None) or (not preexisting and not target.exists()))
            out.append(Result(key, "PERMISSION", permission_ok, str(expected_state)))
            executed = False
            if permission_ok:
                try:
                    apply_approved(str(root), [op], {expected_path: expected_state})
                    executed = True
                except Exception as exc:
                    out.append(Result(key, "EXECUTION", False, str(exc)))
            if not any(r.case == key and r.stage == "EXECUTION" for r in out):
                out.append(Result(key, "EXECUTION", executed, expected_path))
            verified = executed and target.is_file() and target.read_text(encoding="utf-8") == expected_content
            out.append(Result(key, "VERIFY", verified, expected_path))
    return out


def natural_rename_results() -> list[Result]:
    """E2E deterministici per rinomina file: intent -> move -> args -> precondizioni -> verify."""
    cases = [
        ("Rinomina prova.txt in finale.txt", "prova.txt", "finale.txt"),
        ("Rinominami appunti.md come lezione.md", "appunti.md", "lezione.md"),
        ("Rinomina il file dati.csv in archivio.csv", "dati.csv", "archivio.csv"),
        ("Rinomina foto_01.jpg come copertina.jpg", "foto_01.jpg", "copertina.jpg"),
    ]
    out: list[Result] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i, (request, source, destination) in enumerate(cases, 1):
            key = f"natural-rename-{i:02d}"
            src = root / source
            dst = root / destination
            payload = f"payload-{i}".encode()
            src.write_bytes(payload)
            intent_ok = is_action_request(request)
            out.append(Result(key, "INTENT", intent_ok, request))
            op = parse_simple_action(request, root) if intent_ok else None
            tool_ok = bool(op and op.get("type") == "move")
            out.append(Result(key, "TOOL", tool_ok, str(op)))
            args_ok = bool(tool_ok and op.get("path") == source and op.get("destination") == destination)
            out.append(Result(key, "ARGUMENTS", args_ok, str(op)))
            source_fp = fingerprint(src) if src.is_file() else None
            permission_ok = bool(args_ok and source_fp and not dst.exists())
            out.append(Result(key, "PERMISSION", permission_ok, str(source_fp)))
            executed = False
            if permission_ok:
                try:
                    apply_approved(str(root), [op], {source: source_fp, destination: None})
                    executed = True
                except Exception as exc:
                    out.append(Result(key, "EXECUTION", False, str(exc)))
            if not any(r.case == key and r.stage == "EXECUTION" for r in out):
                out.append(Result(key, "EXECUTION", executed, f"{source} -> {destination}"))
            verified = executed and not src.exists() and dst.is_file() and dst.read_bytes() == payload
            out.append(Result(key, "VERIFY", verified, f"{source} -> {destination}"))
    return out


def natural_move_results() -> list[Result]:
    """E2E deterministici per spostamento file in cartella: tutti gli stadi P0."""
    cases = [
        ("Sposta report.pdf nella cartella Archivio", "report.pdf", "Archivio/report.pdf"),
        ("Muovi foto.jpg in Immagini", "foto.jpg", "Immagini/foto.jpg"),
        ("Spostami note.txt dentro la directory Backup", "note.txt", "Backup/note.txt"),
        ("Muovimi dati.csv dentro Export 2026", "dati.csv", "Export 2026/dati.csv"),
    ]
    out: list[Result] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i, (request, source, destination) in enumerate(cases, 1):
            key = f"natural-move-{i:02d}"
            src = root / source
            dst = root / destination
            payload = f"move-payload-{i}".encode()
            src.write_bytes(payload)
            intent_ok = is_action_request(request)
            out.append(Result(key, "INTENT", intent_ok, request))
            op = parse_simple_action(request, root) if intent_ok else None
            tool_ok = bool(op and op.get("type") == "move")
            out.append(Result(key, "TOOL", tool_ok, str(op)))
            args_ok = bool(tool_ok and op.get("path") == source and op.get("destination") == destination)
            out.append(Result(key, "ARGUMENTS", args_ok, str(op)))
            source_fp = fingerprint(src) if src.is_file() else None
            permission_ok = bool(args_ok and source_fp and not dst.exists())
            out.append(Result(key, "PERMISSION", permission_ok, str(source_fp)))
            executed = False
            if permission_ok:
                try:
                    apply_approved(str(root), [op], {source: source_fp, destination: None})
                    executed = True
                except Exception as exc:
                    out.append(Result(key, "EXECUTION", False, str(exc)))
            if not any(r.case == key and r.stage == "EXECUTION" for r in out):
                out.append(Result(key, "EXECUTION", executed, f"{source} -> {destination}"))
            verified = executed and not src.exists() and dst.is_file() and dst.read_bytes() == payload
            out.append(Result(key, "VERIFY", verified, f"{source} -> {destination}"))
    return out


def move_guard_results() -> list[Result]:
    """Collisione destinazione: l'executor deve rifiutare senza alterare i file."""
    out: list[Result] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "collisione.txt"
        dst = root / "Backup" / "collisione.txt"
        dst.parent.mkdir()
        src.write_text("origine", encoding="utf-8")
        dst.write_text("destinazione", encoding="utf-8")
        request = "Sposta collisione.txt nella cartella Backup"
        op = parse_simple_action(request, root)
        intent_ok = is_action_request(request)
        out.append(Result("move-collision", "INTENT", intent_ok, request))
        out.append(Result("move-collision", "TOOL", bool(op and op.get("type") == "move"), str(op)))
        args_ok = bool(op and op.get("path") == "collisione.txt" and op.get("destination") == "Backup/collisione.txt")
        out.append(Result("move-collision", "ARGUMENTS", args_ok, str(op)))
        permission_ok = args_ok and not dst.exists()
        # Qui PASS significa che il controllo ha correttamente negato il permesso.
        out.append(Result("move-collision", "PERMISSION", not permission_ok, "destination already exists"))
        rejected = False
        try:
            apply_approved(str(root), [op], {"collisione.txt": fingerprint(src), "Backup/collisione.txt": None})
        except Exception:
            rejected = True
        intact = src.read_text(encoding="utf-8") == "origine" and dst.read_text(encoding="utf-8") == "destinazione"
        out.append(Result("move-collision", "EXECUTION", rejected, "collision rejected"))
        out.append(Result("move-collision", "VERIFY", rejected and intact, "both files intact"))
    return out

def natural_copy_results() -> list[Result]:
    """E2E deterministici per copia binaria: tutti gli stadi P0, origine preservata."""
    cases = [
        ("Copia dati.csv nella cartella Backup", "dati.csv", "Backup/dati.csv"),
        ("Copiami foto.jpg in Immagini 2", "foto.jpg", "Immagini 2/foto.jpg"),
        ("Duplica note.txt dentro la directory Archivio", "note.txt", "Archivio/note.txt"),
        ("Duplicami pacchetto.bin in Export", "pacchetto.bin", "Export/pacchetto.bin"),
    ]
    out: list[Result] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i, (request, source, destination) in enumerate(cases, 1):
            key = f"natural-copy-{i:02d}"
            src, dst = root / source, root / destination
            payload = bytes([0, 255, i, 10, 13]) + f"copy-{i}".encode()
            src.write_bytes(payload)
            intent_ok = is_action_request(request)
            out.append(Result(key, "INTENT", intent_ok, request))
            op = parse_simple_action(request, root) if intent_ok else None
            tool_ok = bool(op and op.get("type") == "copy")
            out.append(Result(key, "TOOL", tool_ok, str(op)))
            args_ok = bool(tool_ok and op.get("path") == source and op.get("destination") == destination)
            out.append(Result(key, "ARGUMENTS", args_ok, str(op)))
            source_fp = fingerprint(src) if src.is_file() else None
            permission_ok = bool(args_ok and source_fp and not dst.exists())
            out.append(Result(key, "PERMISSION", permission_ok, str(source_fp)))
            executed = False
            if permission_ok:
                try:
                    apply_approved(str(root), [op], {source: source_fp, destination: None})
                    executed = True
                except Exception as exc:
                    out.append(Result(key, "EXECUTION", False, str(exc)))
            if not any(r.case == key and r.stage == "EXECUTION" for r in out):
                out.append(Result(key, "EXECUTION", executed, f"{source} -> {destination}"))
            verified = executed and src.is_file() and dst.is_file() and src.read_bytes() == payload and dst.read_bytes() == payload
            out.append(Result(key, "VERIFY", verified, f"{source} -> {destination}"))
    return out

def copy_guard_results() -> list[Result]:
    """Collisione copia: rifiuto e nessun danno ai due file."""
    out: list[Result] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); src = root / "a.bin"; dst = root / "Backup" / "a.bin"
        dst.parent.mkdir(); src.write_bytes(b"source\x00"); dst.write_bytes(b"dest\xff")
        request = "Copia a.bin nella cartella Backup"
        op = parse_simple_action(request, root); intent_ok = is_action_request(request)
        out.append(Result("copy-collision", "INTENT", intent_ok, request))
        out.append(Result("copy-collision", "TOOL", bool(op and op.get("type") == "copy"), str(op)))
        args_ok = bool(op and op.get("path") == "a.bin" and op.get("destination") == "Backup/a.bin")
        out.append(Result("copy-collision", "ARGUMENTS", args_ok, str(op)))
        out.append(Result("copy-collision", "PERMISSION", args_ok and dst.exists(), "destination collision detected"))
        rejected = False
        try:
            apply_approved(str(root), [op], {"a.bin": fingerprint(src), "Backup/a.bin": None})
        except Exception:
            rejected = True
        intact = src.read_bytes() == b"source\x00" and dst.read_bytes() == b"dest\xff"
        out.append(Result("copy-collision", "EXECUTION", rejected, "collision rejected"))
        out.append(Result("copy-collision", "VERIFY", rejected and intact, "both files intact"))
    return out

def natural_modify_exact_results() -> list[Result]:
    """P0 modifica testuale mirata: target univoco, write atomico e verifica finale."""
    cases = [
        ("Nel file config.py cambia DEBUG = False in DEBUG = True", "config.py", "DEBUG = False", "DEBUG = True"),
        ("Sostituisci timeout=10 con timeout=30 nel file settings.ini", "settings.ini", "timeout=10", "timeout=30"),
        ("Nel file stato.txt sostituisci versione 5 in versione 6", "stato.txt", "versione 5", "versione 6"),
        ("Cambia MODE=dev con MODE=prod nel file env.txt", "env.txt", "MODE=dev", "MODE=prod"),
    ]
    out: list[Result] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i, (request, name, old, new) in enumerate(cases, 1):
            key = f"natural-modify-{i:02d}"
            target = root / name
            original = f"header-{i}\n{old}\nfooter-{i}\n"
            target.write_text(original, encoding="utf-8")
            before_fp = fingerprint(target)
            intent_ok = is_action_request(request)
            out.append(Result(key, "INTENT", intent_ok, request))
            op = parse_simple_action(request, root) if intent_ok else None
            tool_ok = bool(op and op.get("type") == "modify")
            out.append(Result(key, "TOOL", tool_ok, str(op)))
            expected_text = original.replace(old, new, 1)
            args_ok = bool(tool_ok and op.get("path") == name and op.get("content") == expected_text)
            out.append(Result(key, "ARGUMENTS", args_ok, str(op)))
            permission_ok = bool(args_ok and before_fp and target.is_file())
            out.append(Result(key, "PERMISSION", permission_ok, str(before_fp)))
            executed = False
            if permission_ok:
                try:
                    apply_approved(str(root), [op], {name: before_fp})
                    executed = True
                except Exception as exc:
                    out.append(Result(key, "EXECUTION", False, str(exc)))
            if not any(r.case == key and r.stage == "EXECUTION" for r in out):
                out.append(Result(key, "EXECUTION", executed, name))
            verified = executed and target.read_text(encoding="utf-8") == expected_text
            out.append(Result(key, "VERIFY", verified, name))

        # Ambiguita: due match non devono produrre alcuna mutazione.
        target = root / "ambiguo.txt"
        original = "FLAG=off\nFLAG=off\n"
        target.write_text(original, encoding="utf-8")
        request = "Nel file ambiguo.txt cambia FLAG=off in FLAG=on"
        key = "natural-modify-ambiguous"
        intent_ok = is_action_request(request)
        out.append(Result(key, "INTENT", intent_ok, request))
        op = parse_simple_action(request, root) if intent_ok else None
        out.append(Result(key, "TOOL", op is None, str(op)))
        out.append(Result(key, "ARGUMENTS", op is None, "multiple matches rejected"))
        out.append(Result(key, "PERMISSION", op is None, "no mutation authorized"))
        out.append(Result(key, "EXECUTION", target.read_text(encoding="utf-8") == original, "unchanged"))
        out.append(Result(key, "VERIFY", target.read_text(encoding="utf-8") == original, "unchanged"))
    return out


def natural_delete_quarantine_results() -> list[Result]:
    """P0 DELETE = quarantena atomica reversibile, inclusi casi cattivi."""
    import os
    out: list[Result] = []
    cases = [
        ("Elimina foto.jpg", "foto.jpg"),
        ("Cancella pacchetto.zip", "pacchetto.zip"),
        ("Rimuovi old.log", "old.log"),
        ("Elimina documento.pdf", "documento.pdf"),
    ]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i, (request, name) in enumerate(cases, 1):
            key=f"natural-delete-{i:02d}"; target=root/name; payload=os.urandom(333+i); target.write_bytes(payload)
            fp=fingerprint(target); intent_ok=is_action_request(request); out.append(Result(key,"INTENT",intent_ok,request))
            op=parse_simple_action(request,root) if intent_ok else None
            tool_ok=bool(op and op.get('type')=='delete'); out.append(Result(key,"TOOL",tool_ok,str(op)))
            args_ok=bool(tool_ok and op.get('path')==name); out.append(Result(key,"ARGUMENTS",args_ok,str(op)))
            perm_ok=bool(args_ok and fp); out.append(Result(key,"PERMISSION",perm_ok,str(fp)))
            executed=False
            try:
                if perm_ok: apply_approved(str(root),[op],{name:fp}); executed=True
            except Exception as exc: out.append(Result(key,"EXECUTION",False,str(exc)))
            if not any(r.case==key and r.stage=='EXECUTION' for r in out): out.append(Result(key,"EXECUTION",executed,name))
            q=list((root/'.giorgio_trash').rglob(name))
            verified=executed and not target.exists() and len(q)==1 and q[0].read_bytes()==payload
            out.append(Result(key,"VERIFY",verified,str(q)))

        # Due omonimi: nessuna scelta arbitraria.
        (root/'A').mkdir(); (root/'B').mkdir(); (root/'A'/'dati.log').write_bytes(b'A'); (root/'B'/'dati.log').write_bytes(b'B')
        request='Elimina dati.log'; key='delete-ambiguous'; intent_ok=is_action_request(request); out.append(Result(key,'INTENT',intent_ok,request))
        op=parse_simple_action(request,root); out.append(Result(key,'TOOL',op is None,str(op))); out.append(Result(key,'ARGUMENTS',op is None,'duplicate basename'))
        out.append(Result(key,'PERMISSION',op is None,'no target authorized')); intact=(root/'A'/'dati.log').read_bytes()==b'A' and (root/'B'/'dati.log').read_bytes()==b'B'
        out.append(Result(key,'EXECUTION',intact,'unchanged')); out.append(Result(key,'VERIFY',intact,'unchanged'))

        # Domanda informativa: CONVERSATION, nessuna capability.
        (root/'config.py').write_text('x=1',encoding='utf-8'); request='Cosa succede se elimino config.py?'; key='delete-question'
        intent_ok=is_action_request(request); out.append(Result(key,'INTENT',not intent_ok,request)); op=parse_simple_action(request,root) if intent_ok else None
        out.append(Result(key,'TOOL',op is None,str(op))); out.append(Result(key,'ARGUMENTS',op is None,'conversation'))
        out.append(Result(key,'PERMISSION',op is None,'not authorized')); out.append(Result(key,'EXECUTION',(root/'config.py').exists(),'untouched')); out.append(Result(key,'VERIFY',(root/'config.py').read_text()=='x=1','untouched'))

        # TOCTOU: fingerprint cambia dopo il piano -> executor deve abortire.
        target=root/'volatile.bin'; target.write_bytes(b'old'); request='Elimina volatile.bin'; key='delete-toctou'; oldfp=fingerprint(target)
        intent_ok=is_action_request(request); out.append(Result(key,'INTENT',intent_ok,request)); op=parse_simple_action(request,root)
        out.append(Result(key,'TOOL',bool(op and op.get('type')=='delete'),str(op))); out.append(Result(key,'ARGUMENTS',bool(op and op.get('path')=='volatile.bin'),str(op)))
        target.write_bytes(b'changed'); out.append(Result(key,'PERMISSION',oldfp!=fingerprint(target),'change detected'))
        rejected=False
        try: apply_approved(str(root),[op],{'volatile.bin':oldfp})
        except Exception: rejected=True
        out.append(Result(key,'EXECUTION',rejected,'stale plan rejected')); out.append(Result(key,'VERIFY',rejected and target.read_bytes()==b'changed','new state preserved'))
    return out

def unsafe_parent_guard_results() -> list[Result]:
    """P0 ARGUMENTS/PERMISSION: un parent esplicito non sicuro non va mai ignorato."""
    cases = [
        "Crea il file note.txt dentro la cartella ..",
        "Crea un file report.csv nella cartella .",
        "Crea una cartella Gabriele dentro ..",
        "Creami una directory Output dentro .",
    ]
    out: list[Result] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        for i, request in enumerate(cases, 1):
            key = f"unsafe-parent-{i:02d}"
            intent_ok = is_action_request(request)
            out.append(Result(key, "INTENT", intent_ok, request))
            op = parse_simple_action(request, root) if intent_ok else None
            # Il parser deterministico deve rifiutare/fare fallback, non inventare
            # una destinazione diversa da quella esplicitamente richiesta.
            out.append(Result(key, "ARGUMENTS", op is None, str(op)))
            out.append(Result(key, "PERMISSION", op is None, "unsafe explicit parent rejected"))
            after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
            out.append(Result(key, "EXECUTION", before == after, "no filesystem mutation"))
            out.append(Result(key, "VERIFY", before == after, "workspace unchanged"))
    return out

def main() -> int:
    results = routing_results() + executor_results() + natural_create_results() + natural_write_results() + natural_rename_results() + natural_move_results() + move_guard_results() + natural_copy_results() + copy_guard_results() + natural_modify_exact_results() + natural_delete_quarantine_results() + unsafe_parent_guard_results()
    passed = sum(r.passed for r in results)
    total = len(results)
    by_stage = {}
    for r in results:
        s = by_stage.setdefault(r.stage, {"passed": 0, "total": 0})
        s["total"] += 1
        s["passed"] += int(r.passed)
    report = {
        "harness": "P0 deterministic baseline",
        "scope": "routing + deterministic executor; excludes LLM argument extraction and real UI",
        "passed": passed,
        "total": total,
        "rate": round(passed / total, 4) if total else 0,
        "by_stage": by_stage,
        "failures": [asdict(r) for r in results if not r.passed],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
