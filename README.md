# Telegram Mesaj Panel

Modern Django tabanlı Telegram mesaj gönderim paneli.

## Özellikler

- 📊 **Dashboard** - İstatistikler ve son gönderimler
- 👥 **Gruplar** - Telegram grupları yönetimi
- 📝 **Hazır Mesajlar** - Mesaj şablonları
- 🚀 **Gönderimler** - Toplu mesaj gönderimi
- ⚙️ **Ayarlar** - Bot token ve sistem ayarları

## Teknolojiler

- Django 6.0
- Python 3.12
- python-telegram-bot 20.7
- Bootstrap 5

## Kurulum

### Yerel Geliştirme

```bash
# Virtual environment oluştur
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Bağımlılıkları yükle
pip install -r requirements.txt

# Migration
python manage.py migrate

# Superuser oluştur
python manage.py createsuperuser

# Sunucu başlat
python manage.py runserver
```

### Coolify Deployment

**1. Dockerfile Eklendi:** Proje artık nixpacks yerine manuel Dockerfile kullanıyor.

**2. Environment Variables:**
```
DJANGO_SECRET_KEY=<rastgele-bir-key>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=<domain-adresiniz>
TELEGRAM_BOT_TOKEN=8058870569:AAFfuGffgNC15hED-sdasdasdsadas
```

**3. Build Command:**
```bash
docker build -t telegram-panel .
```

**4. Start Command:**
```bash
gunicorn telegram_panel.wsgi:application --bind 0.0.0.0:8000
```

**5. Webhook Ayarla (Deploy sonrası):**
Tarayıcıda şu URL'yi açın:
```
https://<domain>/webhook/set/
```

## Telegram Bot Kullanımı

### Botu Gruba Ekleme

1. @BotFather'dan yeni bot oluşturun
2. Botu gruba admin olarak ekleyin
3. Grubun Chat ID'sini alın (@userinfobot kullanın)
4. Gruplar sayfasına ekleyin

### Webhook Aktifleştirme

Coolify'da deploy edildikten sonra:
1. `https://domain.com/webhook/set/` adresini ziyaret edin
2. "success": true yanıtı alırsınız

## Dosya Yapısı

```
TelegramBot/
├── core/                  # Ana uygulama
│   ├── models.py         # Veritabanı modelleri
│   ├── views.py          # View fonksiyonları
│   ├── admin.py          # Admin panel
│   └── urls.py           # URL routing
├── templates/core/        # HTML şablonları
├── telegram_panel/        # Django proje ayarları
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── telegram_bot.py       # Telegram polling bot
├── webhook_bot.py        # Webhook bot
├── requirements.txt
└── manage.py
```

## Proje Durumu

✅ Tamamlandı - Coolify deploy için hazır

## Lisans

MIT
