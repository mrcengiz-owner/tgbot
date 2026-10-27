"""Telegram Bot API çağrıları. Token panel kaydından, yoksa ortam değişkeninden okunur."""
from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r'<[^>]+>')


def get_bot_token() -> str:
    """Önce panelde kayıtlı token, yoksa TELEGRAM_BOT_TOKEN."""
    try:
        from core.models import Settings as AppSettings

        row = AppSettings.objects.filter(key='telegram_bot_token').only('value').first()
        if row and (row.value or '').strip():
            return row.value.strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug('Token DB okunamadı: %s', exc)
    return (getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or '').strip()


def api_url(method: str, token: Optional[str] = None) -> str:
    return f'https://api.telegram.org/bot{token or get_bot_token()}/{method}'


def send_message(
    chat_id,
    text: str,
    *,
    parse_mode: Optional[str] = 'HTML',
    token: Optional[str] = None,
    timeout: int = 10,
) -> Tuple[bool, str]:
    """Mesaj gönderir. HTML parse hatasında düz metinle bir kez daha dener."""
    token = (token or get_bot_token() or '').strip()
    if not token:
        return False, 'TELEGRAM_BOT_TOKEN boş'
    if not text:
        return False, 'boş mesaj'

    ok, err = _post_message(token, chat_id, text, parse_mode, timeout)
    if ok or not parse_mode:
        return ok, err

    lowered = (err or '').lower()
    if 'parse' in lowered or 'entity' in lowered or 'tag' in lowered or err.startswith('HTTP 400'):
        plain = _TAG_RE.sub('', text)
        ok2, err2 = _post_message(token, chat_id, plain, None, timeout)
        if ok2:
            return True, ''
        return False, err2 or err
    return False, err


def get_webhook_info(timeout: int = 10) -> dict:
    token = get_bot_token()
    if not token:
        return {'ok': False, 'error': 'TELEGRAM_BOT_TOKEN boş'}
    try:
        response = requests.get(api_url('getWebhookInfo', token), timeout=timeout)
        if response.headers.get('content-type', '').startswith('application/json'):
            return response.json()
        return {'ok': False, 'error': response.text[:300]}
    except requests.RequestException as exc:
        return {'ok': False, 'error': str(exc)}


def _post_message(token, chat_id, text, parse_mode, timeout) -> Tuple[bool, str]:
    payload = {
        'chat_id': chat_id,
        'text': text[:4096],
        'disable_web_page_preview': True,
    }
    if parse_mode:
        payload['parse_mode'] = parse_mode
    try:
        response = requests.post(api_url('sendMessage', token), json=payload, timeout=timeout)
    except requests.RequestException as exc:
        return False, f'ağ hatası: {exc}'

    if response.status_code == 200:
        return True, ''
    try:
        desc = response.json().get('description', response.text)
    except Exception:  # noqa: BLE001
        desc = response.text
    return False, f'HTTP {response.status_code}: {str(desc)[:200]}'
