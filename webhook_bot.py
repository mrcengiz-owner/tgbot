"""
Telegram Webhook Bot - Django ile entegre.

Sorumluluklar:
1) Her gelen webhook çağrısını WebhookLog tablosuna kaydeder.
2) /start, /help, /kayit, /id, /durum komutlarına cevap verir (özel sohbet dahil).
3) /uygunluk: grubun kasa tutarını günceller veya yetkili grupta listeyi basar.
4) Kayıtlı ve tx takibi açık gruplarda transaction hash'ini çözümler.
"""
import json
import logging
import re

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import requests

from core.models import TelegramGroup, MessageLog, WebhookLog
from core.services import TxService, UygunlukService, is_uygunluk_command
from core.services.bot_client import api_url, get_bot_token, get_webhook_info, send_message

logger = logging.getLogger(__name__)

_tx_service = TxService()
_uygunluk_service = UygunlukService()

_CMD_RE = re.compile(r'^/([a-z0-9_]+)(?:@\w+)?', re.IGNORECASE)

HELP_TEXT = (
    '<b>MobilOnay Bot</b>\n\n'
    '<b>Komutlar</b>\n'
    '/kayit — bu sohbetin ID bilgisini gösterir\n'
    '/uygunluk 100 K — kasa tutarını yazar\n'
    '/uygunluk — yalnızca yetkili grupta tüm kasaları listeler\n'
    '/durum — kısa sistem özeti\n'
    '/help — bu mesaj\n\n'
    'TX takibi açık gruplarda işlem hash\'i yazıldığında tutar ve TL karşılığı cevaplanır.\n\n'
    '<i>Grup mesajlarını görmüyorsa botu yönetici yapın veya BotFather\'da '
    '/setprivacy komutunu Disable konumuna alın.</i>'
)

BOT_COMMANDS = [
    {'command': 'start', 'description': 'Botu başlat'},
    {'command': 'help', 'description': 'Komut listesi'},
    {'command': 'kayit', 'description': 'Sohbet / grup ID'},
    {'command': 'uygunluk', 'description': 'Kasa uygunluğu'},
    {'command': 'durum', 'description': 'Kısa sistem özeti'},
]


def _command_name(text: str) -> str:
    if not text:
        return ''
    first = text.strip().splitlines()[0].strip().split()[0]
    match = _CMD_RE.match(first)
    return f'/{match.group(1).lower()}' if match else ''


def _reply(chat_id, text: str) -> tuple:
    _tx_service.bot_token = get_bot_token()
    return send_message(chat_id, text, token=_tx_service.bot_token)


def _chat_info(chat: dict) -> str:
    chat_id = chat.get('id')
    chat_type = chat.get('type')
    if chat_type in ('group', 'supergroup', 'channel'):
        kind = {
            'supergroup': 'Süper Grup',
            'channel': 'Kanal',
        }.get(chat_type, 'Grup')
        lines = [
            '<b>Kayıt bilgileri</b>',
            '',
            f'Grup adı: {chat.get("title") or "Bilinmeyen"}',
            f'Grup ID: <code>{chat_id}</code>',
            f'Grup türü: {kind}',
        ]
        if chat.get('username'):
            lines.append(f'Kullanıcı adı: @{chat.get("username")}')
        lines.append('')
        lines.append('Bu ID\'yi paneldeki Gruplar sayfasına ekleyin.')
        lines.append(
            '<i>Hash mesajlarının okunması için bot yönetici olmalı '
            'veya BotFather /setprivacy Disable olmalı.</i>'
        )
        return '\n'.join(lines)
    return (
        '<b>Özel sohbet</b>\n\n'
        f'Sohbet ID: <code>{chat_id}</code>\n'
        'Grup ID\'sini almak için /kayit komutunu grubun içinde yazın.'
    )


def _status_text() -> str:
    active_groups = TelegramGroup.objects.filter(is_active=True).count()
    tracker_groups = TelegramGroup.objects.filter(is_active=True, tx_tracker_enabled=True).count()
    total_messages = MessageLog.objects.count()
    success_count = MessageLog.objects.filter(status='success').count()
    return (
        '<b>Sistem durumu</b>\n\n'
        f'Aktif grup: {active_groups}\n'
        f'TX takibi açık: {tracker_groups}\n'
        f'Panel gönderimi: {total_messages} (başarılı {success_count})'
    )


def _log_send(log: WebhookLog, action: str, ok: bool, err: str) -> None:
    if ok:
        log.action = action
        log.error_message = ''
        log.save(update_fields=['action', 'error_message'])
        return
    log.action = 'send_failed'
    log.error_message = (err or 'gönderilemedi')[:1000]
    log.save(update_fields=['action', 'error_message'])


@csrf_exempt
def webhook(request):
    """Telegram webhook endpoint."""
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)

    try:
        body_text = request.body.decode('utf-8') if request.body else ''
        data = json.loads(body_text or '{}')
    except json.JSONDecodeError:
        logger.warning('Webhook: geçersiz JSON')
        return HttpResponse('Bad json', status=400)

    _tx_service.bot_token = get_bot_token()

    if data.get('my_chat_member'):
        _handle_my_chat_member(data['my_chat_member'])
        return HttpResponse('OK')

    update = data.get('message') or data.get('edited_message') or data.get('channel_post') or {}
    chat = update.get('chat') or {}
    sender = update.get('from') or {}
    chat_id = chat.get('id')
    chat_type = chat.get('type') or ''
    chat_title = chat.get('title') or chat.get('first_name') or ''
    text = update.get('text') or update.get('caption') or ''
    message_id = update.get('message_id')

    log = WebhookLog.objects.create(
        chat_id=str(chat_id) if chat_id else None,
        chat_type=chat_type,
        chat_title=chat_title or '',
        user_id=sender.get('id'),
        username=sender.get('username') or '',
        message_id=message_id,
        text=(text or '')[:4000],
        action='ignored',
    )

    if not chat_id:
        log.error_message = 'chat_id yok'
        log.save(update_fields=['error_message'])
        return HttpResponse('OK')

    if not text:
        log.error_message = 'metin mesajı değil'
        log.save(update_fields=['error_message'])
        return HttpResponse('OK')

    command = _command_name(text)
    in_group = chat_type in ('group', 'supergroup', 'channel')

    if command in ('/start', '/help'):
        ok, err = _reply(chat_id, HELP_TEXT)
        _log_send(log, 'help', ok, err)
        return HttpResponse('OK')

    if command in ('/kayit', '/id', '/chatid'):
        ok, err = _reply(chat_id, _chat_info(chat))
        _log_send(log, 'kayit', ok, err)
        return HttpResponse('OK')

    if command in ('/durum', '/status', '/groups'):
        try:
            ok, err = _reply(chat_id, _status_text())
            _log_send(log, 'status', ok, err)
        except Exception as exc:  # noqa: BLE001
            logger.exception('/durum hata: %s', exc)
            log.action = 'error'
            log.error_message = str(exc)[:1000]
            log.save(update_fields=['action', 'error_message'])
        return HttpResponse('OK')

    if is_uygunluk_command(text):
        if not in_group:
            ok, err = _reply(chat_id, '⚠️ /uygunluk yalnızca grup içinde kullanılır.')
            _log_send(log, 'uygunluk_denied', ok, err)
            return HttpResponse('OK')
        try:
            reply, action = _uygunluk_service.handle(
                text=text,
                chat_id=str(chat_id),
                chat_title=chat_title or '',
                user_id=sender.get('id'),
                username=sender.get('username') or '',
            )
            ok, err = _reply(chat_id, reply)
            _log_send(log, action, ok, err)
        except Exception as exc:  # noqa: BLE001
            logger.exception('/uygunluk hata: %s', exc)
            log.action = 'error'
            log.error_message = str(exc)[:1000]
            log.save(update_fields=['action', 'error_message'])
        return HttpResponse('OK')

    if command:
        first_token = text.strip().split()[0]
        mentioned = '@' in first_token
        # Grupta başka botun komutuna cevap verme; sadece bize yazıldıysa veya özel sohbette yanıtla.
        if chat_type == 'private' or mentioned:
            ok, err = _reply(chat_id, 'Bu komutu tanımıyorum. Liste için /help yazın.')
            _log_send(log, 'unknown_command', ok, err)
        return HttpResponse('OK')

    if chat_type == 'private':
        ok, err = _reply(chat_id, 'Merhaba. Komutlar için /help yazın.')
        _log_send(log, 'help', ok, err)
        return HttpResponse('OK')

    if not in_group:
        return HttpResponse('OK')

    tx_hash = _tx_service.find_tx_in_text(text)
    log.tx_hash = tx_hash or ''
    log.has_tx_hash = bool(tx_hash)
    log.save(update_fields=['tx_hash', 'has_tx_hash'])

    if not tx_hash:
        log.action = 'no_tx'
        log.error_message = 'mesajda tx hash bulunamadı'
        log.save(update_fields=['action', 'error_message'])
        return HttpResponse('OK')

    try:
        group = TelegramGroup.objects.get(chat_id=str(chat_id))
    except TelegramGroup.DoesNotExist:
        log.action = 'no_group'
        log.error_message = f'chat_id={chat_id} sistemde kayıtlı değil'
        log.save(update_fields=['action', 'error_message'])
        return HttpResponse('OK')

    if not group.is_active or not group.tx_tracker_enabled:
        log.action = 'ignored'
        log.error_message = (
            f'grup pasif veya tx takibi kapalı '
            f'(is_active={group.is_active}, tx_tracker_enabled={group.tx_tracker_enabled})'
        )
        log.save(update_fields=['action', 'error_message'])
        return HttpResponse('OK')

    try:
        reply = _tx_service.process(
            message_text=text,
            chat_id=str(chat_id),
            message_id=message_id,
        )
        if reply and _tx_service.last_send_ok:
            log.action = 'sent'
            log.error_message = ''
            log.save(update_fields=['action', 'error_message'])
        elif reply:
            log.action = 'send_failed'
            log.error_message = f'cevap gönderilemedi: {_tx_service.last_send_error}'[:1000]
            log.save(update_fields=['action', 'error_message'])
        else:
            log.action = 'no_reply'
            log.error_message = 'TxService.process yanıt üretmedi'
            log.save(update_fields=['action', 'error_message'])
    except Exception as exc:  # noqa: BLE001
        logger.exception('TxService.process hata: %s', exc)
        log.action = 'error'
        log.error_message = str(exc)[:1000]
        log.save(update_fields=['action', 'error_message'])

    return HttpResponse('OK')


def _handle_my_chat_member(member: dict) -> None:
    """Bot gruba eklenince chat id'yi yazar."""
    chat = member.get('chat') or {}
    chat_id = chat.get('id')
    new_status = (member.get('new_chat_member') or {}).get('status')
    old_status = (member.get('old_chat_member') or {}).get('status')
    if not chat_id:
        return
    if new_status in ('member', 'administrator') and old_status in ('left', 'kicked', None):
        send_message(
            chat_id,
            _chat_info(chat),
            token=get_bot_token(),
        )


@login_required
@csrf_exempt
def set_webhook(request):
    """Webhook URL'sini Telegram'a kaydet ve komut menüsünü güncelle."""
    public = (getattr(settings, 'WEBHOOK_PUBLIC_URL', '') or '').rstrip('/')
    base = public or f'https://{request.get_host()}'
    webhook_url = f'{base}/webhook/'
    token = get_bot_token()
    if not token:
        return JsonResponse({'error': 'Bot token tanımlı değil'}, status=500)
    try:
        response = requests.post(
            api_url('setWebhook', token),
            json={
                'url': webhook_url,
                'allowed_updates': ['message', 'edited_message', 'channel_post', 'my_chat_member'],
                'drop_pending_updates': False,
            },
            timeout=10,
        )
        tg_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
        commands_resp = requests.post(
            api_url('setMyCommands', token),
            json={'commands': BOT_COMMANDS},
            timeout=10,
        )
        commands_data = (
            commands_resp.json()
            if commands_resp.headers.get('content-type', '').startswith('application/json')
            else commands_resp.text
        )
        return JsonResponse({
            'webhook_url': webhook_url,
            'telegram_response': tg_data,
            'commands': commands_data,
            'webhook_info': get_webhook_info(),
        })
    except requests.RequestException as exc:
        return JsonResponse({'error': str(exc)}, status=500)


@login_required
@csrf_exempt
def delete_webhook(request):
    """Telegram'daki webhook kaydını sil."""
    token = get_bot_token()
    try:
        response = requests.post(api_url('deleteWebhook', token), timeout=10)
        return JsonResponse({
            'telegram_response': response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
        })
    except requests.RequestException as exc:
        return JsonResponse({'error': str(exc)}, status=500)


@login_required
@csrf_exempt
def webhook_info(request):
    """Telegram webhook durumunu kontrol et."""
    info = get_webhook_info()
    status = 200 if info.get('ok', True) and 'error' not in info else 502
    if info.get('ok') is False:
        status = 502
    return JsonResponse(info, status=status)
