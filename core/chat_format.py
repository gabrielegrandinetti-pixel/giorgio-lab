"""Parser prudente dei blocchi Markdown utili alla chat Tkinter."""
from __future__ import annotations

import re

OPEN = re.compile(r'^```([^`\r\n]{0,40})[ \t]*$', re.MULTILINE)
CLOSE = re.compile(r'^```[ \t]*$', re.MULTILINE)


def split_fenced(text, max_blocks=40, max_code_chars=200_000):
    """Divide in segmenti text/code; i fence incompleti restano testo normale."""
    if not isinstance(text, str):
        raise TypeError('Il testo della chat deve essere una stringa.')
    parts = []
    position = 0
    blocks = 0
    while blocks < max_blocks:
        opening = OPEN.search(text, position)
        if not opening:
            break
        code_start = opening.end()
        if code_start < len(text) and text[code_start] == '\n':
            code_start += 1
        closing = CLOSE.search(text, code_start)
        if not closing:
            break
        code = text[code_start:closing.start()]
        if code.endswith('\n'):
            code = code[:-1]
        if len(code) > max_code_chars:
            break
        if opening.start() > position:
            parts.append(('text', '', text[position:opening.start()]))
        language = opening.group(1).strip() or 'codice'
        parts.append(('code', language, code))
        position = closing.end()
        if position < len(text) and text[position] == '\n':
            position += 1
        blocks += 1
    if position < len(text):
        parts.append(('text', '', text[position:]))
    if not parts:
        return [('text', '', text)]
    return parts
