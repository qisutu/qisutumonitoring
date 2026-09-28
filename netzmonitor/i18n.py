"""Local language catalogs shared by the installer and web interface."""
from functools import lru_cache
import json
from pathlib import Path

LANGUAGES = {'cs': 'Čeština', 'de': 'Deutsch', 'en': 'English', 'es': 'Español',
             'fr': 'Français', 'it': 'Italiano', 'nl': 'Nederlands', 'pl': 'Polski',
             'pt-BR': 'Português (Brasil)', 'pt-PT': 'Português (Portugal)', 'tr': 'Türkçe'}
DIRECTORY = Path(__file__).parent / 'languages'


def normalize_language(value):
    if not isinstance(value, str) or value not in LANGUAGES:
        raise ValueError('Bitte eine verfügbare Sprache auswählen.')
    return value


@lru_cache(maxsize=11)
def catalog(language):
    return json.loads((DIRECTORY / (normalize_language(language) + '.json')).read_text(encoding='utf-8'))


def translate(text, language='de'):
    return catalog(language)['messages'].get(text, text)
