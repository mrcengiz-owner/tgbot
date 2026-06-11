"""
Telegram Webhook Bot - Django ile entegre.

Sorumluluklar:
1) /kayit komutu: Grubun bilgilerini admin'e gönderir (mevcut davranış).
2) Tx hash tespiti: Kayıtlı ve tx_tracker_enabled=True olan gruplarda,
   mesaj içindeki transaction hash'ini otomatik algılar, blockchain
   explorer'ından miktarı çeker, BTCTurk/Paribu'dan anlık TL kurunu alır
   ve gruba detaylı biçimlendirilmiş mesaj gönderir.
"""
import json
import logging
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'telegram_panel.settings')
django.setup()

from django.conf import settings  # noqa: E402
from django.http import HttpResponse, JsonResponse  # noqa: E402
from django.views.decorators.csrf import csrf_exempt  # noqa: E402
import requests  # noqa: E402

from core.services import TxService  # noqa: E402

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'

# Modül seviyesinde tek bir service instance (yeniden kullanım için)
_tx_service = TxService(bot_token=TELEGRAM_BOT_TOKEN)


@csrf_exempt
def webhook(request):
    """Telegram webhook endpoint."""
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return HttpResponse('Bad json', status=400)

    update = data.get('message') or data.get('edited_message') or {}
    chat = update.get('chat') or {}
    chat_id = chat.get('id')
    chat_type = chat.get('type')
    text = update.get('text') or ''
    message_id = update.get('message_id')

    if not chat_id:
        return HttpResponse('OK')

    # 1) Eski davranış: /kayit komutu (mevcut kullanıcılar için geriye uyumlu)
    if chat_type in ('group', 'supergroup') and chat_id and str(chat_id).startswith('-'):
        if text and '/kayit' in text.lower():
            _handle_kayit(chat)

    # 2) Yeni davranış: tx hash tespiti (gruba özel açma/kapama)
    if chat_type in ('group', 'supergroup') and text:
        try:
            _tx_service.process(
                message_text=text,
                chat_id=str(chat_id),
                message_id=message_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception('TxService.process hata: %s', exc)

    return HttpResponse('OK')


def _handle_kayit(chat: dict) -> None:
    """Mevcut /kayit komutunun gösterdiği grup bilgisini gönderir."""
    chat_id = chat.get('id')
    response_text = (
        f"📋 Kayıt Bilgileri\n\n"
        f"🔹 Grup Adı: {chat.get('title', 'Bilinmeyen')}\n"
        f"🔹 Grup ID: {chat_id}\n"
        f"🔹 Grup Türü: {'Süper Grup' if chat.get('type') == 'supergroup' else 'Grup'}\n"
    )
    if chat.get('username'):
        response_text += f"🔹 Kullanıcı Adı: @{chat.get('username')}\n"
    try:
        requests.post(
            f'{TELEGRAM_API_URL}/sendMessage',
            json={'chat_id': chat_id, 'text': response_text},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning('/kayit gönderilemedi: %s', exc)


@csrf_exempt
def set_webhook(request):
    """Webhook URL'sini Telegram'a kaydet."""
    host = request.get_host()
    webhook_url = f'https://{host}/webhook/'
    try:
        response = requests.post(
            f'{TELEGRAM_API_URL}/setWebhook',
            json={'url': webhook_url},
            timeout=10,
        )
        return JsonResponse(
            {
                'webhook_url': webhook_url,
                'telegram_response': response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
            }
        )
    except requests.RequestException as exc:
        return JsonResponse({'error': str(exc)}, status=500)


@csrf_exempt
def delete_webhook(request):
    """Telegram'daki webhook kaydını sil."""
    try:
        response = requests.post(f'{TELEGRAM_API_URL}/deleteWebhook', timeout=10)
        return JsonResponse(
            {
                'telegram_response': response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
            }
        )
    except requests.RequestException as exc:
        return JsonResponse({'error': str(exc)}, status=500)
