"""Operazioni deterministiche sulla coda degli incarichi di Giorgio."""
from __future__ import annotations


class QueueEditError(ValueError):
    pass


def _index(items, index):
    if not isinstance(index, int) or index < 0 or index >= len(items):
        raise QueueEditError('Selezione della coda non valida.')
    return index


def move(items, index, offset):
    index = _index(items, index)
    destination = index + offset
    if destination < 0 or destination >= len(items):
        return index
    items[index], items[destination] = items[destination], items[index]
    return destination


def remove(items, index):
    return items.pop(_index(items, index))


def update(items, index, request, mode, model, response_style='Breve'):
    index = _index(items, index)
    request, model = request.strip(), model.strip()
    if not request or len(request) > 20_000:
        raise QueueEditError('La richiesta deve contenere da 1 a 20.000 caratteri.')
    if mode not in {'Chat', 'Agente', 'Studio'}:
        raise QueueEditError('Modalità non valida.')
    if not model or len(model) > 200:
        raise QueueEditError('Il modello deve contenere da 1 a 200 caratteri.')
    if response_style not in {'Breve', 'Normale', 'Dettagliata'}:
        raise QueueEditError('Lunghezza risposta non valida.')
    changed = dict(items[index])
    changed.update(request=request, mode=mode, model=model,
                   response_style=response_style, history=[])
    items[index] = changed
    return changed


def label(job, width=72):
    request = ' '.join(str(job.get('request', '')).split())
    if len(request) > width:
        request = request[:max(1, width - 1)] + '…'
    project = job.get('project')
    project_name = str(project).replace('\\', '/').rstrip('/').split('/')[-1] if project else 'nessun progetto'
    style = job.get('response_style', 'Breve')
    return f"{job.get('mode', 'Agente')} · {style} · {project_name} · {request}"
