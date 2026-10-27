"""
Grup çevirisi.

- Düz mesaj, Türkçe değilse Türkçeye çevrilir.
- Bir mesaj alıntılanmışsa cevap, alıntının diline çevrilip iletilir.
  Alıntı zaten aynı dildeyse ve Türkçe değilse yine Türkçe çeviri basılır.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

LANG_NAMES = {
    'tr': 'Türkçe',
    'en': 'İngilizce',
    'ru': 'Rusça',
    'de': 'Almanca',
    'ar': 'Arapça',
    'fr': 'Fransızca',
    'es': 'İspanyolca',
    'it': 'İtalyanca',
    'fa': 'Farsça',
    'az': 'Azerbaycanca',
    'ku': 'Kürtçe',
    'zh': 'Çince',
    'ja': 'Japonca',
    'ko': 'Korece',
    'uk': 'Ukraynaca',
    'bg': 'Bulgarca',
    'ro': 'Rumence',
    'nl': 'Felemenkçe',
    'pt': 'Portekizce',
    'pl': 'Lehçe',
    'hi': 'Hintçe',
    'ur': 'Urduca',
    'he': 'İbranice',
    'el': 'Yunanca',
    'sv': 'İsveççe',
    'cs': 'Çekçe',
    'hu': 'Macarca',
    'sq': 'Arnavutça',
    'ka': 'Gürcüce',
    'hy': 'Ermenice',
    'id': 'Endonezce',
    'ms': 'Malayca',
    'th': 'Tayca',
    'vi': 'Vietnamca',
}

_NAME_TO_CODE = {name.casefold(): code for code, name in LANG_NAMES.items()}
_HEADER_RE = re.compile(r'^(🇹🇷|💬)\s+(.+?)\s*$')
_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)
_HEX_RE = re.compile(r'\b(?:0x)?[0-9a-fA-F]{64}\b')
_BASE58_RE = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{60,70}\b')
_LETTER_RE = re.compile(r'[^\W\d_]', re.UNICODE)
_SPACE_RE = re.compile(r'\s+')

TranslateFn = Callable[[str, str], Optional[Tuple[str, str]]]


@dataclass
class PlannedTranslation:
    html: str
    action: str


def plan_translation(
    text: str,
    quoted: Optional[str] = None,
    translate: Optional[TranslateFn] = None,
) -> Optional[PlannedTranslation]:
    """Çevrilecek metin yoksa None. translate(metin, hedef_dil) → (çeviri, kaynak_dil)."""
    text = (text or '').strip()
    if not _worth_translating(text):
        return None

    translate = translate or google_translate
    quoted = (quoted or '').strip()
    quoted_lang = _language_of_quote(quoted, translate) if quoted else None

    if quoted_lang:
        converted = translate(text, quoted_lang)
        if not converted:
            return None
        translated, source = converted
        source = _canon(source)
        target = _canon(quoted_lang)
        if source != target and not _same(translated, text):
            return PlannedTranslation(
                html=_format('💬', target, translated),
                action='ceviri_yanit',
            )
        if source != 'tr':
            to_tr = translate(text, 'tr')
            if to_tr and not _same(to_tr[0], text):
                return PlannedTranslation(
                    html=_format('🇹🇷', _canon(to_tr[1]), to_tr[0]),
                    action='ceviri_tr',
                )
        return None

    to_tr = translate(text, 'tr')
    if not to_tr:
        return None
    translated, source = to_tr
    source = _canon(source)
    if source == 'tr' or _same(translated, text):
        return None
    return PlannedTranslation(
        html=_format('🇹🇷', source, translated),
        action='ceviri_tr',
    )


def google_translate(text: str, target: str) -> Optional[Tuple[str, str]]:
    """Google çeviri. (çevrilmiş metin, algılanan kaynak dil) veya None."""
    import requests

    target = _canon(target) or 'tr'
    try:
        response = requests.post(
            'https://translate.googleapis.com/translate_a/single',
            data={
                'client': 'gtx',
                'sl': 'auto',
                'tl': target,
                'dt': 't',
                'dj': '1',
                'q': text[:4000],
            },
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning('Çeviri isteği başarısız: %s', exc)
        return None

    sentences = payload.get('sentences') if isinstance(payload, dict) else None
    if not sentences:
        return None
    translated = ' '.join((part.get('trans') or '').strip() for part in sentences if part.get('trans')).strip()
    source = _canon(str(payload.get('src') or ''))
    if not translated or not source:
        return None
    return translated, source


def _language_of_quote(quoted: str, translate: TranslateFn) -> Optional[str]:
    embedded = _embedded_language(quoted)
    if embedded:
        return embedded
    body = quoted
    first = quoted.splitlines()[0].strip() if quoted else ''
    if _HEADER_RE.match(first):
        body = '\n'.join(quoted.splitlines()[1:]).strip()
    if not _worth_translating(body):
        return None
    detected = translate(body, 'tr')
    if not detected:
        return None
    return _canon(detected[1])


def _embedded_language(text: str) -> Optional[str]:
    """Botun kendi çeviri mesajından hedef/kaynak dili okur."""
    if not text:
        return None
    first = text.splitlines()[0].strip()
    match = _HEADER_RE.match(first)
    if not match:
        return None
    mark, label = match.group(1), match.group(2).split('→')[0].strip()
    code = _NAME_TO_CODE.get(label.casefold())
    if code:
        return code
    token = label.casefold().replace('_', '-')
    if re.fullmatch(r'[a-z]{2,5}(?:-[a-z]{2})?', token):
        return _canon(token)
    return None


def _worth_translating(text: str) -> bool:
    if not text or _HEADER_RE.match(text.splitlines()[0].strip()):
        return False
    cleaned = _BASE58_RE.sub(' ', _HEX_RE.sub(' ', _URL_RE.sub(' ', text)))
    return len(_LETTER_RE.findall(cleaned)) >= 2


def _format(mark: str, lang: str, translated: str) -> str:
    name = LANG_NAMES.get(lang, lang.upper())
    return f'{mark} <b>{_escape(name)}</b>\n{_escape(translated)}'


def _canon(code: str) -> str:
    code = (code or '').lower().replace('_', '-')
    if code in LANG_NAMES:
        return code
    base = code.split('-')[0]
    return base or code


def _same(left: str, right: str) -> bool:
    return _SPACE_RE.sub(' ', left).strip().casefold() == _SPACE_RE.sub(' ', right).strip().casefold()


def _escape(text: str) -> str:
    return (
        (text or '')
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )
