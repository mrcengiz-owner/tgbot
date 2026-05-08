"""
Planlı görevleri çalıştıran Django management komutu
Bu komut sürekli çalışmalı (celery/beat kullanılabilir ama basitlik için loop)
"""
import time
import requests
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from core.models import ScheduledTask


class Command(BaseCommand):
    help = 'Planlı görevleri otomatik olarak çalıştırır'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Planlı görev servisi başlatıldı...'))
        
        while True:
            try:
                self.run_pending_tasks()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Hata: {e}'))
            
            time.sleep(60)  # Her 60 saniyede kontrol et

    def run_pending_tasks(self):
        """Bekleyen görevleri çalıştır"""
        now = timezone.now()
        active_tasks = ScheduledTask.objects.filter(is_active=True)
        
        for task in active_tasks:
            # Son çalışmadan bu yana yeterli zaman geçti mi kontrol et
            if task.last_run:
                next_run = task.last_run + timezone.timedelta(minutes=task.interval_minutes)
                if now < next_run:
                    continue
            
            # Görevi çalıştır
            self.run_task(task)

    def run_task(self, task):
        """Bir görevi çalıştır ve mesajları gönder"""
        self.stdout.write(f"Çalıştırılıyor: {task.name}")
        
        groups = task.groups.filter(is_active=True)
        message_content = task.template.content
        
        # Token ayarla
        bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
        if not bot_token:
            self.stdout.write(self.style.ERROR('Bot token ayarlanmamış!'))
            return
        
        sent = 0
        failed = 0
        
        for group in groups:
            try:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                data = {
                    'chat_id': group.chat_id,
                    'text': message_content
                }
                response = requests.post(url, data=data, timeout=10)
                
                if response.status_code == 200:
                    sent += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                self.stdout.write(f"  {group.name}: Hata - {e}")
        
        # Son çalışma zamanını güncelle
        task.last_run = timezone.now()
        task.save()
        
        self.stdout.write(self.style.SUCCESS(f"  {task.name}: {sent} gönderildi, {failed} başarısız"))