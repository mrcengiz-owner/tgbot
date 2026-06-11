# Generated for Kripto TX Takip özelliği
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0002_remove_telegramgroup_bot_token_scheduledtask'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramgroup',
            name='tx_tracker_enabled',
            field=models.BooleanField(
                default=False,
                help_text='Bu grupta gönderilen transaction idler otomatik algilansin mi?',
                verbose_name='Kripto TX Takibi Aktif mi?',
            ),
        ),
        migrations.CreateModel(
            name='TxTracker',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tx_hash', models.CharField(max_length=128, unique=True, verbose_name='Tx Hash')),
                ('detected_chain', models.CharField(
                    choices=[
                        ('bitcoin', 'Bitcoin (BTC)'),
                        ('ethereum', 'Ethereum (ETH)'),
                        ('bsc', 'BNB Smart Chain (BSC)'),
                        ('polygon', 'Polygon (POL)'),
                        ('arbitrum', 'Arbitrum (ARB)'),
                        ('tron', 'Tron (TRX/TRC20)'),
                        ('litecoin', 'Litecoin (LTC)'),
                        ('dogecoin', 'Dogecoin (DOGE)'),
                        ('unknown', 'Bilinmiyor'),
                    ],
                    default='unknown',
                    max_length=20,
                    verbose_name='Algılanan Ağ',
                )),
                ('asset_symbol', models.CharField(blank=True, max_length=16, null=True, verbose_name='Varlık Sembolü (USDT, BTC, ETH)')),
                ('amount', models.DecimalField(blank=True, decimal_places=8, max_digits=24, null=True, verbose_name='Miktar')),
                ('from_address', models.CharField(blank=True, max_length=128, null=True, verbose_name='Gönderen Adres')),
                ('to_address', models.CharField(blank=True, max_length=128, null=True, verbose_name='Alan Adres')),
                ('try_rate', models.DecimalField(blank=True, decimal_places=8, max_digits=20, null=True, verbose_name='Anlık TL Kuru')),
                ('try_value', models.DecimalField(blank=True, decimal_places=2, max_digits=24, null=True, verbose_name='TL Karşılığı')),
                ('rate_source', models.CharField(blank=True, max_length=32, null=True, verbose_name='Kur Kaynağı (BTCTurk/Paribu)')),
                ('explorer_url', models.URLField(blank=True, max_length=500, null=True, verbose_name='Explorer Bağlantısı')),
                ('message_id', models.BigIntegerField(blank=True, null=True, verbose_name='Telegram Mesaj ID')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Beklemede'),
                        ('resolved', 'Çözümlendi'),
                        ('failed', 'Başarısız'),
                        ('ignored', 'Yoksayıldı (Devre Dışı)'),
                    ],
                    default='pending',
                    max_length=12,
                    verbose_name='Durum',
                )),
                ('raw_payload', models.JSONField(blank=True, null=True, verbose_name='Ham Veri')),
                ('error_message', models.TextField(blank=True, null=True, verbose_name='Hata Mesajı')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True, verbose_name='Çözüm Zamanı')),
                ('group', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='tx_records',
                    to='core.telegramgroup',
                    verbose_name='Kaynak Grup',
                )),
            ],
            options={
                'verbose_name': 'Kripto TX Kaydı',
                'verbose_name_plural': 'Kripto TX Kayıtları',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='TxRateCache',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('asset', models.CharField(max_length=16, verbose_name='Varlık (USDT, BTC...)')),
                ('source', models.CharField(max_length=32, verbose_name='Kaynak (btcturk/paribu)')),
                ('pair', models.CharField(max_length=16, verbose_name='Parite (örn: USDT_TRY)')),
                ('rate', models.DecimalField(decimal_places=8, max_digits=20, verbose_name='Kur')),
                ('fetched_at', models.DateTimeField(auto_now=True, verbose_name='Çekilme Zamanı')),
            ],
            options={
                'verbose_name': 'Kur Önbelleği',
                'verbose_name_plural': 'Kur Önbellekleri',
                'ordering': ['-fetched_at'],
                'unique_together': {('asset', 'source')},
            },
        ),
    ]
