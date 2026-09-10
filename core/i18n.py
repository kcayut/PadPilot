"""Shared presentation translations; device data and protocol values stay untouched."""
import json
import re
from string import Formatter
from pathlib import Path

LANGUAGES = {'en': 'English', 'zh-Hant': '繁體中文', 'ja': '日本語'}
LANGUAGE_CODES = {name: code for code, name in LANGUAGES.items()}
TRANSLATIONS = json.loads(Path(__file__).with_name('translations.json').read_text(encoding='utf-8'))
_language = 'zh-Hant'


def set_language(language):
    global _language
    _language = language if isinstance(language, str) and language in LANGUAGES else 'zh-Hant'


def tr(message, *args):
    translated = TRANSLATIONS.get(message, {}).get(_language, message)
    return translated.format(*args) if args else translated


def tr_message(message):
    """Translate known service messages, retaining unknown errors and captured data."""
    if message in TRANSLATIONS:
        return tr(message)
    for pattern, template in _MESSAGE_PATTERNS:
        match = pattern.fullmatch(message)
        if match:
            translated = TRANSLATIONS[template].get(_language, template)
            return ''.join(literal + (match.group(int(field) + 1) if field is not None else '')
                           for literal, field, _, _ in Formatter().parse(translated))
    return message


# Only message templates with meaningful fixed text; never translate device labels.
_MESSAGE_PATTERNS = []
for _template in TRANSLATIONS:
    _parts = list(Formatter().parse(_template))
    if any(field is not None for _, field, _, _ in _parts) and sum(len(s) for s, _, _, _ in _parts) >= 3:
        _MESSAGE_PATTERNS.append((re.compile(''.join(re.escape(s) + ('(.+?)' if f is not None else '')
                                                    for s, f, _, _ in _parts), re.DOTALL), _template))
