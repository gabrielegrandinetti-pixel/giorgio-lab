"""Controllo leggero di Ollama, separato dalla GUI e facile da verificare."""
from __future__ import annotations

import socket


def _model_name(model):
    if isinstance(model, dict):
        return model.get('model') or model.get('name')
    return getattr(model, 'model', None) or getattr(model, 'name', None)


def inspect_ollama(model, client_factory):
    """Restituisce uno stato serializzabile; non lascia uscire errori tecnici."""
    try:
        client = client_factory()
        response = client.list()
        models = getattr(response, 'models', None)
        if models is None and isinstance(response, dict):
            models = response.get('models', [])
        names = sorted({str(name) for item in (models or []) if (name := _model_name(item))})
        if not names:
            return {'connected': True, 'models': [], 'selected': model,
                    'message': 'Ollama attivo · nessun modello installato'}
        if model not in names:
            return {'connected': True, 'models': names, 'selected': model,
                    'message': f'Ollama attivo · modello {model} non installato'}
        return {'connected': True, 'models': names, 'selected': model,
                'message': f'Ollama pronto · {model}'}
    except Exception as exc:
        text = str(exc).lower()
        if isinstance(exc, (TimeoutError, socket.timeout)) or 'timed out' in text or 'timeout' in text:
            message = 'Ollama non risponde entro il tempo previsto'
        elif any(part in text for part in ('connection refused', 'failed to connect', 'connection error')):
            message = 'Ollama non raggiungibile · avvialo e riprova'
        else:
            message = 'Controllo Ollama non riuscito'
        return {'connected': False, 'models': [], 'selected': model,
                'message': message, 'detail': str(exc)[:500]}
