from django.db import models
from django.contrib.auth.models import User


class TelegramGroup(models.Model):
    """Telegram gruplarını saklayan model"""
    name = models.CharField(max_length=255, verbose_name="Grup Adı")
    chat_id = models.CharField(max_length=100, unique=True, verbose_name="Chat ID")
    description = models.TextField(blank=True, null=True, verbose_name="Açıklama")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    tx_tracker_enabled = models.BooleanField(
        default=False,
        verbose_name="Kripto TX Takibi Aktif mi?",
        help_text="Bu grupta gönderilen transaction id'ler otomatik algılansın mı?",
    )
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


class TxTracker(models.Model):
    """Webhook üzerinden gelen ve çözümlenen kripto transaction kayıtları"""

    CHAIN_CHOICES = [
        ('bitcoin', 'Bitcoin (BTC)'),
        ('ethereum', 'Ethereum (ETH)'),
        ('bsc', 'BNB Smart Chain (BSC)'),
        ('polygon', 'Polygon (POL)'),
        ('arbitrum', 'Arbitrum (ARB)'),
        ('tron', 'Tron (TRX/TRC20)'),
        ('litecoin', 'Litecoin (LTC)'),
        ('dogecoin', 'Dogecoin (DOGE)'),
        ('unknown', 'Bilinmiyor'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Beklemede'),
        ('resolved', 'Çözümlendi'),
        ('failed', 'Başarısız'),
        ('ignored', 'Yoksayıldı (Devre Dışı)'),
    ]

    tx_hash = models.CharField(max_length=128, unique=True, verbose_name="Tx Hash")
    detected_chain = models.CharField(
        max_length=20, choices=CHAIN_CHOICES, default='unknown', verbose_name="Algılanan Ağ"
    )
    asset_symbol = models.CharField(
        max_length=16, blank=True, null=True, verbose_name="Varlık Sembolü (USDT, BTC, ETH)"
    )
    amount = models.DecimalField(
        max_digits=24, decimal_places=8, null=True, blank=True, verbose_name="Miktar"
    )
    from_address = models.CharField(
        max_length=128, blank=True, null=True, verbose_name="Gönderen Adres"
    )
    to_address = models.CharField(
        max_length=128, blank=True, null=True, verbose_name="Alan Adres"
    )
    try_rate = models.DecimalField(
        max_digits=20, decimal_places=8, null=True, blank=True, verbose_name="Anlık TL Kuru"
    )
    try_value = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True, verbose_name="TL Karşılığı"
    )
    rate_source = models.CharField(
        max_length=32, blank=True, null=True, verbose_name="Kur Kaynağı (BTCTurk/Paribu)"
    )
    explorer_url = models.URLField(
        max_length=500, blank=True, null=True, verbose_name="Explorer Bağlantısı"
    )
    group = models.ForeignKey(
        'TelegramGroup',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tx_records',
        verbose_name="Kaynak Grup",
    )
    message_id = models.BigIntegerField(
        null=True, blank=True, verbose_name="Telegram Mesaj ID"
    )
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default='pending', verbose_name="Durum"
    )
    raw_payload = models.JSONField(blank=True, null=True, verbose_name="Ham Veri")
    error_message = models.TextField(blank=True, null=True, verbose_name="Hata Mesajı")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="Çözüm Zamanı")

    class Meta:
        verbose_name = "Kripto TX Kaydı"
        verbose_name_plural = "Kripto TX Kayıtları"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.tx_hash[:14]}... - {self.get_status_display()}"


class TxRateCache(models.Model):
    """Anlık kur önbelleği - saniye başına API'yi boğmamak için"""

    asset = models.CharField(max_length=16, verbose_name="Varlık (USDT, BTC...)")
    source = models.CharField(max_length=32, verbose_name="Kaynak (btcturk/paribu)")
    pair = models.CharField(max_length=16, verbose_name="Parite (örn: USDT_TRY)")
    rate = models.DecimalField(max_digits=20, decimal_places=8, verbose_name="Kur")
    fetched_at = models.DateTimeField(auto_now=True, verbose_name="Çekilme Zamanı")

    class Meta:
        verbose_name = "Kur Önbelleği"
        verbose_name_plural = "Kur Önbellekleri"
        unique_together = [('asset', 'source')]
        ordering = ['-fetched_at']

    def __str__(self):
        return f"{self.asset} @ {self.source} = {self.rate} (cache)"
