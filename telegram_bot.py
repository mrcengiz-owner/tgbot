"""
Telegram Bot - Mesajları dinler ve gruplara gönderir
"""
import logging
import os
import django

# Django ayarlarını yükle
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'telegram_panel.settings')
django.setup()

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from django.conf import settings
import requests

# Logging ayarla
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Token
BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start komutu"""
    await update.message.reply_text(
        "🤖 *Telegram Panel Bot*\n\n"
        "Merhaba! Bu bot gruplarınıza mesaj göndermek için kullanılıyor.\n\n"
        "*Komutlar:*\n"
        "/help - Yardım\n"
        "/status - Durum\n"
        "/groups - Grupları listele\n",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help komutu"""
    await update.message.reply_text(
        "📖 *Yardım*\n\n"
        "Bu bot şu özellikleri destekler:\n"
        "• /start - Botu başlat\n"
        "• /help - Bu yardım mesajı\n"
        "• /status - Sistem durumu\n"
        "• /groups - Kayıtlı grupları göster\n",
        parse_mode='Markdown'
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Status komutu"""
    from core.models import TelegramGroup, MessageLog
    
    active_groups = TelegramGroup.objects.filter(is_active=True).count()
    total_messages = MessageLog.objects.count()
    success_count = MessageLog.objects.filter(status='success').count()
    
    await update.message.reply_text(
        f"📊 *Sistem Durumu*\n\n"
        f"✅ Aktif Gruplar: {active_groups}\n"
        f"📨 Toplam Mesaj: {total_messages}\n"
        f"✅ Başarılı: {success_count}\n"
        f"❌ Başarısız: {total_messages - success_count}",
        parse_mode='Markdown'
    )

async def groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Grupları listele komutu"""
    from core.models import TelegramGroup
    
    groups = TelegramGroup.objects.filter(is_active=True)
    
    if not groups:
        await update.message.reply_text("❌ Aktif grup bulunamadı.")
        return
    
    text = "📋 *Kayıtlı Gruplar*\n\n"
    for i, group in enumerate(groups, 1):
        text += f"{i}. {group.name}\n"
        text += f"   ID: `{group.chat_id}`\n\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def echo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tüm mesajlara yanıt ver"""
    # Sadece gruplarda çalışsın
    if update.message.chat.type in ['group', 'supergroup']:
        await update.message.reply_text(
            f"👋 Mesajınız alındı!\n"
            f"Grup: {update.message.chat.title}\n"
            f"Mesaj: {update.message.text[:100] if update.message.text else 'Boş mesaj'}",
            parse_mode='Markdown'
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hata yakalayıcı"""
    logger.error(f"Hata: {context.error}")

def main():
    """Botu başlat"""
    logger.info("Telegram Bot başlatılıyor...")
    
    # Application oluştur
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Komut işleyicileri
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("groups", groups_command))
    
    # Mesaj işleyici
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_message))
    
    # Hata yakalayıcı
    application.add_error_handler(error_handler)
    
    # Botu başlat (polling)
    logger.info("Bot polling başladı. Durdurmak için Ctrl+C basın.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()