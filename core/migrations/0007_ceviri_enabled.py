from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_uygunluk_yetkili'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramgroup',
            name='ceviri_enabled',
            field=models.BooleanField(
                default=False,
                help_text='Açıksa yabancı mesajlar Türkçeye çevrilir. Alıntıya yazılan cevap, alıntının diline çevrilip iletilir.',
                verbose_name='Çeviri Aktif mi?',
            ),
        ),
    ]
