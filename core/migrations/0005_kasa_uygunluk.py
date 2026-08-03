# Generated manually for kasa uygunluk module

from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_webhooklog'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramgroup',
            name='kasa_uygunluk',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0'),
                help_text='Grubun güncel kasa uygunluk tutarı (TL). /uygunluk komutu ile güncellenir.',
                max_digits=18,
                verbose_name='Kasa Uygunluk',
            ),
        ),
        migrations.AddField(
            model_name='telegramgroup',
            name='kasa_updated_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Kasa Son Güncelleme',
            ),
        ),
        migrations.CreateModel(
            name='UygunlukLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('previous_amount', models.DecimalField(decimal_places=2, default=0, max_digits=18, verbose_name='Önceki Tutar')),
                ('new_amount', models.DecimalField(decimal_places=2, max_digits=18, verbose_name='Yeni Tutar')),
                ('raw_text', models.CharField(blank=True, max_length=255, verbose_name='Ham Komut')),
                ('user_id', models.BigIntegerField(blank=True, null=True, verbose_name='Kullanıcı ID')),
                ('username', models.CharField(blank=True, max_length=128, null=True, verbose_name='Kullanıcı Adı')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('group', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='uygunluk_logs',
                    to='core.telegramgroup',
                    verbose_name='Grup',
                )),
            ],
            options={
                'verbose_name': 'Uygunluk Logu',
                'verbose_name_plural': 'Uygunluk Logları',
                'ordering': ['-created_at'],
            },
        ),
    ]
