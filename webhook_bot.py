"""
Telegram Webhook Bot - Django ile entegre
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'telegram_panel.settings')
django.setup()

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import json
import logging

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

@csrf_exempt
def webhook(request):
    """Telegram webhook endpoint"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            logger.info(f"Received update: {data}")
            
            update = data.get('message', {})
            chat = update.get('chat', {})
            text = update.get('text', '')
            chat_id = chat.get('id')
            chat_type = chat.get('type')
            
            # Sadece /kayit komutunda yanıt ver
            if chat_type in ['group', 'supergroup'] and chat_id and chat_id < 0:
                if text and '/kayit' in text.lower():
                    response_text = f"📋 Kayıt Bilgileri\n\n"
                    response_text += f"🔹 Grup Adı: {chat.get('title', 'Bilinmeyen')}\n"
                    response_text += f"🔹 Grup ID: {chat_id}\n"
                    response_text += f"🔹 Grup Türü: {'Süper Grup' if chat_type == 'supergroup' else 'Grup'}\n"
                    if chat.get('username'):
                        response_text += f"🔹 Kullanıcı Adı: @{chat.get('username')}\n"
                    
                    # Mesaj gönder
                    send_message_url = f"{TELEGRAM_API_URL}/sendMessage"
                    payload = {
                        'chat_id': chat_id,
                        'text': response_text
                    }
                    
                    import requests
                    resp = requests.post(send_message_url, json=payload, timeout=10)
                    logger.info(f"Send message response: {resp.status_code}")
                
            return HttpResponse('OK')
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return HttpResponse('Error', status=500)
    
    return HttpResponse('Method not allowed', status=405)

def set_webhook(request):
    """Webhook ayarla"""
    import requests
    
    # Her zaman HTTPS kullan - Coolify otomatik HTTPS sağlar
    host = request.get_host()
    webhook_url = f"https://{host}/webhook/"
    
    url = f"{TELEGRAM_API_URL}/setWebhook"
    payload = {'url': webhook_url}
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return HttpResponse(f"Webhook URL: {webhook_url}<br>Response: {response.text}")
    except Exception as e:
        return HttpResponse(f"Error: {str(e)}", status=500)

def delete_webhook(request):
    """Webhook sil"""
    import requests
    
    url = f"{TELEGRAM_API_URL}/deleteWebhook"
    response = requests.post(url)
    return HttpResponse(f"Webhook deleted: {response.text}")