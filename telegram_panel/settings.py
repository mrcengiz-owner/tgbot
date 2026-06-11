"""
Django settings for telegram_panel project.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-change-this-in-production-key-12345')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True'

ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',')

# Coolify / reverse proxy başlığına güven - Django https 'görsün'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'telegram_panel.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'telegram_panel.wsgi.application'

# PostgreSQL Database Configuration
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'tgbot'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', '5.255.112.31'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'tr-TR'
TIME_ZONE = 'Europe/Istanbul'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8058870569:AAFfuGffgNC15hED-nlUIfqQYSewf8RND4M')

# Kripto TX Takip için opsiyonel API anahtarları
# Etherscan v2: https://etherscan.io/apis (ücretsiz 5 req/s, 100k çağrı/gün)
ETHERSCAN_API_KEY = os.environ.get('ETHERSCAN_API_KEY', '')
# TronGrid: https://www.trongrid.io/ (ücretsiz 100k istek/gün, 15 QPS)
TRONGRID_API_KEY = os.environ.get('TRONGRID_API_KEY', '')

# Security settings for production (Coolify reverse proxy kullanıyor, SSL sağlıyor)
if not DEBUG:
    # Coolify HTTPS sağlıyor; SSL redirect'e gerek yok
    SECURE_SSL_REDIRECT = False
    # HTTPS üzerinden geldiğimiz için cookie'ler Secure olabilir
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 0
    SECURE_REFERRER_POLICY = 'same-origin'
    # CSRF trusted origins - her olası domain varyasyonunu kapsa
    _origins_env = os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '')
    if _origins_env:
        CSRF_TRUSTED_ORIGINS = [o.strip() for o in _origins_env.split(',') if o.strip()]
    else:
        CSRF_TRUSTED_ORIGINS = [
            'https://tgbot.nexkasa.com',
            'http://tgbot.nexkasa.com',
            'https://www.tgbot.nexkasa.com',
            'http://www.tgbot.nexkasa.com',
            'https://localhost',
            'http://localhost',
            'https://127.0.0.1',
            'http://127.0.0.1',
        ]
    # Cookie'nin SameSite davranışı (Telegram in-app browser uyumu)
    CSRF_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SAMESITE = 'Lax'

# Login settings
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# CSRF hata sayfası - gerçek sebebi görmek için telegram_panel/csrf_failure.py içinde
CSRF_FAILURE_VIEW = 'telegram_panel.csrf_failure.csrf_failure'