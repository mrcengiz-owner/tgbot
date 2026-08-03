# Generated manually for yetkili uygunluk listesi

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_kasa_uygunluk'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramgroup',
            name='uygunluk_yetkili',
            field=models.BooleanField(
                default=False,
                help_text='True ise /uygunluk komutu tüm sahaların kasa listesini gösterir. Sahalar sadece kendi tutarını yazar.',
                verbose_name='Uygunluk Yetkili Grup mu?',
            ),
        ),
    ]
