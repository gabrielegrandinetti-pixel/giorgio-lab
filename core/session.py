"""Sessione locale validata, con salvataggio atomico e recupero prudente."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time

MAX_BYTES = 4 * 1024 * 1024
MODES = {'Chat', 'Agente', 'Studio'}
RESPONSE_STYLES = {'Breve', 'Normale', 'Dettagliata'}


class SessionError(ValueError):
    pass


def _text(value, limit, label):
    if not isinstance(value, str) or len(value) > limit:
        raise SessionError(f'{label}: testo non valido o troppo lungo.')
    return value


def _paths(value):
    if not isinstance(value, list) or len(value) > 20:
        raise SessionError('Allegati della sessione non validi.')
    return [_text(p, 4096, 'Percorso allegato') for p in value]


def _job(value):
    if not isinstance(value, dict):
        raise SessionError('Incarico salvato non valido.')
    project = value.get('project')
    if project is not None:
        project = _text(project, 4096, 'Progetto')
    mode = value.get('mode', 'Agente')
    if not isinstance(mode, str) or mode not in MODES:
        raise SessionError('Modalità incarico non valida.')
    response_style = value.get('response_style', 'Breve')
    if not isinstance(response_style, str) or response_style not in RESPONSE_STYLES:
        response_style = 'Breve'
    return {'request': _text(value.get('request'), 20000, 'Richiesta'),
            'project': project, 'model': _text(value.get('model'), 200, 'Modello'),
            'mode': mode, 'response_style': response_style,
            'attachments': _paths(value.get('attachments', [])),
            'history': []}


def validate(value):
    if not isinstance(value, dict) or value.get('version') != 1:
        raise SessionError('Formato sessione non riconosciuto.')
    mode = value.get('mode', 'Agente')
    if not isinstance(mode, str) or mode not in MODES:
        raise SessionError('Modalità sessione non valida.')
    project = value.get('project')
    if project is not None:
        project = _text(project, 4096, 'Progetto')
    history = value.get('history', [])
    if not isinstance(history, list) or len(history) > 40:
        raise SessionError('Storico sessione non valido.')
    clean_history = []
    for message in history:
        if not isinstance(message, dict) or message.get('role') not in {'user', 'assistant'}:
            raise SessionError('Messaggio nello storico non valido.')
        clean_history.append({'role': message['role'], 'content': _text(message.get('content'), 40000, 'Messaggio')})
    jobs = value.get('queue', [])
    if not isinstance(jobs, list) or len(jobs) > 101:
        raise SessionError('Coda sessione non valida (massimo 100 incarichi).')
    logs = value.get('logs', [])
    if not isinstance(logs, list) or len(logs) > 80:
        raise SessionError('Registro sessione non valido.')
    active = value.get('active_job')
    return {'version': 1, 'mode': mode, 'project': project,
            'draft': _text(value.get('draft', ''), 20000, 'Bozza'),
            'transcript': _text(value.get('transcript', ''), 250000, 'Conversazione'),
            'history': clean_history, 'queue': [_job(job) for job in jobs],
            'attachments': _paths(value.get('attachments', [])),
            'logs': [_text(line, 2000, 'Registro') for line in logs],
            'active_job': _job(active) if active is not None else None}


class SessionStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return None
        try:
            if self.path.stat().st_size > MAX_BYTES:
                raise SessionError('Sessione oltre il limite di 4 MB.')
            return validate(json.loads(self.path.read_text(encoding='utf-8')))
        except (ValueError, UnicodeError) as exc:
            # Conserva il file problematico; non si prova ad eseguirne il contenuto.
            recovered = self.path.with_name(self.path.name + f'.invalid-{time.time_ns()}')
            try:
                os.replace(self.path, recovered)
            except OSError as backup_error:
                raise SessionError(f'Sessione illeggibile; impossibile conservarla: {backup_error}') from exc
            raise SessionError(f'Sessione illeggibile conservata in {recovered.name}. Avvio di una sessione vuota.') from exc

    def save(self, snapshot):
        clean = validate(snapshot)
        encoded = json.dumps(clean, ensure_ascii=False, indent=2).encode('utf-8')
        if len(encoded) > MAX_BYTES:
            raise SessionError('Sessione oltre il limite di 4 MB; salvataggio precedente conservato.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.session-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
