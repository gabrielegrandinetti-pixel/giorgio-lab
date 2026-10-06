"""Applicazione locale dopo il clic esplicito su Correggi."""
import hashlib
import os
import shutil
from pathlib import Path
import tempfile
from core.backup import BackupManager
from core.operations import FileOperation, OperationManager
from core.security import safe_project_path


def fingerprint(path: Path):
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f'{path.name}: non è un file.')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_approved(root: str, raw_operations: list[dict], expected: dict) -> str:
    project = Path(root).resolve()
    manager = OperationManager(project)
    operations = manager.parse_operations(raw_operations)
    if not operations:
        return 'Nessuna modifica da applicare.'
    paths = []
    missing_parents = set()
    for operation in operations:
        if operation.type not in {'create', 'modify', 'mkdir', 'move', 'copy', 'delete'}:
            raise ValueError('Operazione non supportata da questa interfaccia verificata.')
        path = safe_project_path(project, operation.path)
        destination = safe_project_path(project, operation.destination) if operation.type in {'move', 'copy'} else None
        if operation.path not in expected:
            raise ValueError(f'{operation.path} non è stato verificato. Richiedi una nuova proposta.')
        if operation.type == 'delete':
            if not path.is_file() or fingerprint(path) != expected[operation.path]:
                raise ValueError(f'{operation.path} è cambiato o non è stato verificato.')
        elif operation.type in {'move', 'copy'}:
            if not path.is_file() or fingerprint(path) != expected[operation.path]:
                raise ValueError(f'{operation.path} è cambiato o non è stato verificato.')
            if operation.destination not in expected or expected[operation.destination] is not None or destination.exists():
                raise ValueError(f'{operation.destination} è cambiato o esiste già. Richiedi una nuova proposta.')
        elif operation.type == 'mkdir':
            # Per una mkdir approvata, None significa: la destinazione era assente
            # quando il piano è stato verificato. Non usiamo fingerprint(), che è
            # intenzionalmente riservato ai file.
            if expected[operation.path] is not None or path.exists():
                raise ValueError(f'{operation.path} è cambiato o esiste già. Richiedi una nuova proposta.')
        else:
            if fingerprint(path) != expected[operation.path]:
                raise ValueError(f'{operation.path} è cambiato o non è stato verificato. Richiedi una nuova proposta.')
            if len((operation.content or '').encode('utf-8')) > 2 * 1024 * 1024:
                raise ValueError(f'{operation.path}: contenuto oltre il limite di 2 MB.')
            if path.suffix.lower() in {'.py', '.pyw'}:
                compile(operation.content or '', operation.path, 'exec')
        paths.append(operation.path)
        if operation.type in {'move', 'copy'}:
            paths.append(operation.destination)
        parent = destination.parent if operation.type in {'move', 'copy'} else path.parent
        while parent != project and not parent.exists():
            missing_parents.add(parent.relative_to(project).as_posix())
            parent = parent.parent
    if len(set(paths)) != len(paths):
        raise ValueError('Proposta con operazioni duplicate sullo stesso file.')
    # Includiamo i genitori nuovi perché anche le cartelle siano rimosse nel rollback.
    backup = BackupManager(project)
    saved = backup.create_backup(sorted(missing_parents, key=lambda p: p.count('/')) + paths, 'correzione')
    try:
        for operation in operations:
            path = safe_project_path(project, operation.path)
            if operation.type == 'delete':
                # DELETE P0 = quarantena reversibile, mai os.remove().
                if fingerprint(path) != expected[operation.path]:
                    raise ValueError(f'{operation.path}: stato cambiato durante la quarantena.')
                trash_root = path.parent / '.giorgio_trash'
                trash_root.mkdir(exist_ok=True)
                import uuid
                quarantine_dir = trash_root / uuid.uuid4().hex
                quarantine_dir.mkdir(exist_ok=False)
                quarantine = quarantine_dir / path.name
                # Ricontrollo TOCTOU immediatamente prima del move.
                if fingerprint(path) != expected[operation.path]:
                    quarantine_dir.rmdir()
                    raise ValueError(f'{operation.path}: fingerprint cambiato prima del move.')
                os.replace(path, quarantine)
                # Evidenza runtime usata dalla fase VERIFY.
                operation.destination = quarantine.relative_to(project).as_posix()
                continue
            if operation.type == 'delete':
                quarantine = project / operation.destination
                if path.exists() or not quarantine.is_file() or fingerprint(quarantine) != expected[operation.path]:
                    raise ValueError(f'{operation.path}: verifica quarantena fallita.')
            elif operation.type in {'move', 'copy'}:
                destination = safe_project_path(project, operation.destination)
                if fingerprint(path) != expected[operation.path] or destination.exists():
                    raise ValueError(f'{operation.path}: stato cambiato durante l’operazione.')
                destination.parent.mkdir(parents=True, exist_ok=True)
                if operation.type == 'move':
                    os.replace(path, destination)
                else:
                    shutil.copy2(path, destination)
                continue
            if operation.type == 'mkdir':
                if path.exists():
                    raise ValueError(f'{operation.path} è cambiato durante il salvataggio.')
                path.mkdir(parents=True, exist_ok=False)
                continue
            if fingerprint(path) != expected[operation.path]:
                raise ValueError(f'{operation.path} è cambiato durante il salvataggio.')
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix='.giorgio-', dir=path.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8', newline='') as output:
                    output.write(operation.content or '')
                    output.flush()
                    os.fsync(output.fileno())
                if path.exists():
                    os.chmod(temp, path.stat().st_mode)
                os.replace(temp, path)
            finally:
                Path(temp).unlink(missing_ok=True)
        for operation in operations:
            path = safe_project_path(project, operation.path)
            if operation.type == 'delete':
                quarantine = project / operation.destination
                if path.exists() or not quarantine.is_file() or fingerprint(quarantine) != expected[operation.path]:
                    raise ValueError(f'{operation.path}: verifica quarantena fallita.')
            elif operation.type in {'move', 'copy'}:
                destination = safe_project_path(project, operation.destination)
                source_ok = (not path.exists()) if operation.type == 'move' else (path.is_file() and fingerprint(path) == expected[operation.path])
                if not source_ok or not destination.is_file() or fingerprint(destination) != expected[operation.path]:
                    raise ValueError(f'{operation.path}: verifica {operation.type} fallita.')
            elif operation.type == 'mkdir':
                if not path.exists() or not path.is_dir():
                    raise ValueError(f'{operation.path}: verifica directory fallita.')
            elif path.read_bytes() != (operation.content or '').encode('utf-8'):
                raise ValueError(f'{operation.path}: rilettura diversa dal contenuto previsto.')
        checked = [op.path for op in operations if Path(op.path).suffix.lower() in {'.py', '.pyw'}]
        return (f'Applicate e verificate {len(operations)} operazioni. Backup: {saved.name}. '
                + (f'Sintassi Python verificata per {len(checked)} file. ' if checked else '')
                + 'Il funzionamento del programma richiede una prova; non sono stati eseguiti test funzionali.')
    except Exception as exc:
        try:
            backup.restore(saved)
        except Exception as restore_error:
            raise RuntimeError(f'Salvataggio fallito: {exc}. Anche il ripristino è fallito: {restore_error}. Backup: {saved}') from exc
        raise RuntimeError(f'Salvataggio fallito; file ripristinati: {exc}') from exc

# --- P0 Isolation Kernel -------------------------------------------------
# This entry point is deliberately separate from apply_approved(): the
# existing verified executor remains unchanged while the Supervisor gains a
# process boundary and a two-phase STARTED -> EXECUTE_ALLOWED handshake.
def _exception_evidence(exc):
    """Serialize an exception without losing structured OS error fields."""
    import traceback as _traceback

    evidence = {
        'type': type(exc).__name__,
        'message': str(exc),
        'traceback': _traceback.format_exc(),
    }
    error_number = getattr(exc, 'errno', None)
    if isinstance(error_number, int):
        evidence['errno'] = error_number
    filename = getattr(exc, 'filename', None)
    if filename is not None:
        evidence['filename'] = str(filename)
    current = exc
    visited = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        winerror = getattr(current, 'winerror', None)
        if isinstance(winerror, int):
            evidence['winerror'] = winerror
            break
        current = current.__cause__ or current.__context__
    return evidence


def isolated_executor_entry(pipe, task_id, capability, arguments, executor_func):
    """Child-process entry point. No mutation is allowed before authorization."""
    import os as _os
    try:
        pipe.send({'event': 'STARTED', 'task_id': task_id, 'pid': _os.getpid()})
        command = pipe.recv()
        if not isinstance(command, dict) or command.get('event') != 'EXECUTE_ALLOWED':
            pipe.send({'event': 'ABORTED', 'task_id': task_id, 'reason': 'authorization_missing'})
            return
        try:
            result = executor_func(task_id, capability, arguments)
            pipe.send({'event': 'CORE_RESULT', 'task_id': task_id, 'result': result})
        except BaseException as exc:
            pipe.send({'event': 'CORE_EXCEPTION', 'task_id': task_id,
                       'error': _exception_evidence(exc)})
    except (EOFError, BrokenPipeError, OSError):
        # Parent vanished before authorization/result delivery.  In the first
        # case no mutation has happened; in the latter restart reconciliation
        # uses the persisted pre/expected evidence.
        return
    finally:
        try:
            pipe.close()
        except Exception:
            pass
