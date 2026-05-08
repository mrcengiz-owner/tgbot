from django.db import models
from django.contrib.auth.models import User


class TelegramGroup(models.Model):
    """Telegram gruplarını saklayan model"""
    name = models.CharField(max_length=255, verbose_name="Grup Adı")
    chat_id = models.CharField(max_length=100, unique=True, verbose_name="Chat ID")
    description = models.TextField(blank=True, null=True, verbose_name="Açıklama")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Telegram Grubu"
        verbose_name_plural = "Telegram Grupları"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.chat_id})"


class MessageTemplate(models.Model):
    """Hazır mesaj şablonları"""
    name = models.CharField(max_length=255, verbose_name="Şablon Adı")
    content = models.TextField(verbose_name="Mesaj İçeriği")
    description = models.TextField(blank=True, null=True, verbose_name="Açıklama")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Mesaj Şablonu"
        verbose_name_plural = "Mesaj Şablonları"
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name


class MessageLog(models.Model):
    """Gönderilen mesajların logları"""
    STATUS_CHOICES = [
        ('pending', 'Beklemede'),
        ('success', 'Başarılı'),
        ('failed', 'Başarısız'),
    ]
    
    template = models.ForeignKey(
        MessageTemplate, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name="Şablon"
    )
    message_content = models.TextField(verbose_name="Mesaj İçeriği")
    groups = models.ManyToManyField(TelegramGroup, verbose_name="Gruplar")
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='pending',
        verbose_name="Durum"
    )
    sent_count = models.IntegerField(default=0, verbose_name="Gönderilen Sayı")
    failed_count = models.IntegerField(default=0, verbose_name="Başarısız Sayı")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name="Gönderim Zamanı")
    
    class Meta:
        verbose_name = "Mesaj Logu"
        verbose_name_plural = "Mesaj Logları"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Mesaj {self.id} - {self.status}"


class Settings(models.Model):
    """Sistem ayarları"""
    key = models.CharField(max_length=100, unique=True, verbose_name="Anahtar")
    value = models.TextField(verbose_name="Değer")
    description = models.TextField(blank=True, null=True, verbose_name="Açıklama")
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Ayar"
        verbose_name_plural = "Ayarlar"
    
    def __str__(self):
        return self.key


class ScheduledTask(models.Model):
    """Planlanmış görevler"""
    name = models.CharField(max_length=255, verbose_name="Görev Adı")
    template = models.ForeignKey(
        MessageTemplate, 
        on_delete=models.CASCADE, 
        verbose_name="Şablon"
    )
    groups = models.ManyToManyField(TelegramGroup, verbose_name="Gruplar")
    interval_minutes = models.IntegerField(default=60, verbose_name="Aralık (dk)")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    last_run = models.DateTimeField(null=True, blank=True, verbose_name="Son Çalışma")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Planlanmış Görev"
        verbose_name_plural = "Planlanmış Görevler"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.interval_minutes} dk"
