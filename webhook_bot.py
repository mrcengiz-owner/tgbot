"""
Telegram Webhook Bot - Django ile entegre.

Sorumluluklar:
1) Her gelen webhook çağrısını WebhookLog tablosuna kaydeder (debug).
2) /kayit komutuna grup bilgisi ile cevap verir.
3) Tx hash tespiti: Kayıtlı ve tx_tracker_enabled=True olan gruplarda,
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
from core.models import TelegramGroup, WebhookLog  # noqa: E402

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'

# Modül seviyesinde tek bir service instance (yeniden kullanım için)
_tx_service = TxService(bot_token=TELEGRAM_BOT_TOKEN)


@csrf_exempt
def webhook(request):
    """Telegram webhook endpoint - her çağrıyı logla."""
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)

    try:
        body_text = request.body.decode('utf-8') if request.body else ''
        data = json.loads(body_text or '{}')
    except json.JSONDecodeError:
        logger.warning('Webhook: geçersiz JSON')
        return HttpResponse('Bad json', status=400)

    update = data.get('message') or data.get('edited_message') or data.get('channel_post') or {}
    chat = update.get('chat') or {}
    sender = update.get('from') or {}
    chat_id = chat.get('id')
    chat_type = chat.get('type')
    chat_title = chat.get('title') or chat.get('first_name') or ''
    text = update.get('text') or update.get('caption') or ''
    message_id = update.get('message_id')

    # Her çağrıyı kaydet (debug için)
    log = WebhookLog.objects.create(
        chat_id=str(chat_id) if chat_id else None,
        chat_type=chat_type or '',
        chat_title=chat_title or '',
        user_id=sender.get('id'),
        username=sender.get('username') or '',
        message_id=message_id,
        text=(text or '')[:4000],
        action='ignored',
    )

    if not chat_id:
        log.action = 'ignored'
        log.error_message = 'chat_id yok'
        log.save(update_fields=['action', 'error_message'])
        return HttpResponse('OK')

    # Mesaj yoksa log kaydet ve çık (ör: sticker, foto)
    if not text:
        log.action = 'ignored'
        log.error_message = 'metin mesajı değil'
        log.save(update_fields=['action', 'error_message'])
        return HttpResponse('OK')

    # 1) Eski davranış: /kayit komutu
    if chat_type in ('group', 'supergroup') and '/kayit' in text.lower():
        _handle_kayit(chat)
        log.action = 'kayit'
        log.save(update_fields=['action'])

    # 2) Yeni davranış: tx hash tespiti
    if chat_type in ('group', 'supergroup'):
        # Önce tx var mı kontrol et
        tx_hash = _tx_service.find_tx_in_text(text)
        log.tx_hash = tx_hash or ''
        log.has_tx_hash = bool(tx_hash)
        log.save(update_fields=['tx_hash', 'has_tx_hash'])

        if not tx_hash:
            log.action = 'no_tx'
            log.error_message = 'mesajda tx hash bulunamadı'
            log.save(update_fields=['action', 'error_message'])
            return HttpResponse('OK')

        # Grup kayıtlı mı?
        try:
            group = TelegramGroup.objects.get(chat_id=str(chat_id))
        except TelegramGroup.DoesNotExist:
            log.action = 'no_group'
            log.error_message = f'chat_id={chat_id} sistemde kayıtlı değil'
            log.save(update_fields=['action', 'error_message'])
            logger.info('Tx mesajı geldi ama grup kayıtlı değil: %s', chat_id)
            return HttpResponse('OK')

        if not group.is_active or not group.tx_tracker_enabled:
            log.action = 'ignored'
            log.error_message = (
                f"grup pasif veya tx takibi kapalı "
                f"(is_active={group.is_active}, tx_tracker_enabled={group.tx_tracker_enabled})"
            )
            log.save(update_fields=['action', 'error_message'])
            return HttpResponse('OK')

        # Asıl işlem
        try:
            reply = _tx_service.process(
                message_text=text,
                chat_id=str(chat_id),
                message_id=message_id,
            )
            if reply:
                log.action = 'processed'
                log.save(update_fields=['action'])
            else:
                log.action = 'no_reply'
                log.error_message = 'TxService.process None döndü (explorer verisi alınamamış olabilir)'
                log.save(update_fields=['action', 'error_message'])
        except Exception as exc:  # noqa: BLE001
            logger.exception('TxService.process hata: %s', exc)
            log.action = 'error'
            log.error_message = str(exc)[:1000]
            log.save(update_fields=['action', 'error_message'])

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
            json={
                'url': webhook_url,
                'allowed_updates': ['message', 'edited_message', 'channel_post'],
                'drop_pending_updates': True,
            },
            timeout=10,
        )
        tg_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text

        # doğrulama: webhookInfo
        info_resp = requests.get(f'{TELEGRAM_API_URL}/getWebhookInfo', timeout=10)
        info = info_resp.json() if info_resp.headers.get('content-type', '').startswith('application/json') else info_resp.text

        return JsonResponse({
            'webhook_url': webhook_url,
            'telegram_response': tg_data,
            'webhook_info': info,
        })
    except requests.RequestException as exc:
        return JsonResponse({'error': str(exc)}, status=500)


@csrf_exempt
def delete_webhook(request):
    """Telegram'daki webhook kaydını sil."""
    try:
        response = requests.post(f'{TELEGRAM_API_URL}/deleteWebhook', timeout=10)
        return JsonResponse({
            'telegram_response': response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
        })
    except requests.RequestException as exc:
        return JsonResponse({'error': str(exc)}, status=500)


@csrf_exempt
def webhook_info(request):
    """Telegram webhook durumunu kontrol et."""
    try:
        response = requests.get(f'{TELEGRAM_API_URL}/getWebhookInfo', timeout=10)
        return JsonResponse(
            response.json() if response.headers.get('content-type', '').startswith('application/json') else {'raw': response.text}
        )
    except requests.RequestException as exc:
        return JsonResponse({'error': str(exc)}, status=500)
