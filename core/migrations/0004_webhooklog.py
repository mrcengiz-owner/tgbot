# Generated for WebhookLog - debug/log
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0003_txcrypto_tracker'),
    ]

    operations = [
        migrations.CreateModel(
            name='WebhookLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chat_id', models.CharField(blank=True, db_index=True, max_length=100, null=True, verbose_name='Chat ID')),
                ('chat_type', models.CharField(blank=True, max_length=32, null=True, verbose_name='Sohbet Türü')),
                ('chat_title', models.CharField(blank=True, max_length=255, null=True, verbose_name='Grup/Chat Adı')),
                ('user_id', models.BigIntegerField(blank=True, null=True, verbose_name='Kullanıcı ID')),
                ('username', models.CharField(blank=True, max_length=128, null=True, verbose_name='Kullanıcı Adı')),
                ('message_id', models.BigIntegerField(blank=True, null=True, verbose_name='Mesaj ID')),
                ('text', models.TextField(blank=True, null=True, verbose_name='Mesaj İçeriği')),
                ('has_tx_hash', models.BooleanField(default=False, verbose_name='Tx Hash Var mı?')),
                ('tx_hash', models.CharField(blank=True, max_length=128, null=True, verbose_name='Bulunan Tx Hash')),
                ('action', models.CharField(default='ignored', help_text='processed | ignored | error | no_tx | no_group', max_length=32, verbose_name='İşlem')),
                ('error_message', models.TextField(blank=True, null=True, verbose_name='Hata')),
                ('received_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'verbose_name': 'Webhook Log',
                'verbose_name_plural': 'Webhook Logları',
                'ordering': ['-received_at'],
            },
        ),
    ]
