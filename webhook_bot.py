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
            
            # Sadece gruplarda çalışsın
            if chat_type in ['group', 'supergroup']:
                response_text = f"👋 Mesajınız alındı!\nGrup: {chat.get('title', 'Bilinmeyen')}\nMesaj: {text[:100] if text else 'Boş'}"
                
                # Mesaj gönder
                send_message_url = f"{TELEGRAM_API_URL}/sendMessage"
                payload = {
                    'chat_id': chat_id,
                    'text': response_text
                }
                
                import requests
                requests.post(send_message_url, json=payload, timeout=10)
                
            return HttpResponse('OK')
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return HttpResponse('Error', status=500)
    
    return HttpResponse('Method not allowed', status=405)

def set_webhook(request):
    """Webhook ayarla"""
    import requests
    
    # Webhook URL'i ayarla
    # NOT: Bu URL'yi Coolify'da belirlediğiniz domain ile değiştirin
    webhook_url = "https://your-domain.com/webhook/"
    
    url = f"{TELEGRAM_API_URL}/setWebhook"
    payload = {'url': webhook_url}
    
    response = requests.post(url, json=payload)
    return HttpResponse(f"Webhook set: {response.text}")

def delete_webhook(request):
    """Webhook sil"""
    import requests
    
    url = f"{TELEGRAM_API_URL}/deleteWebhook"
    response = requests.post(url)
    return HttpResponse(f"Webhook deleted: {response.text}")