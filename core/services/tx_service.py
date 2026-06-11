"""
Webhook'tan gelen tx hash'leri işleyen ana orkestratör.
Mesaj regex'i, zincir tespiti, kur çevirimi, Telegram gönderimi ve DB kaydı burada.
"""
import logging
import re
import time
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Optional, Tuple

import requests
from django.conf import settings
from django.utils import timezone

from .explorer_service import ExplorerService
from .rate_service import RateService

logger = logging.getLogger(__name__)

# Tx hash regex'leri
# 64 hex (ETH/EVM/TRX) veya 60+ base58 (BTC/LTC/DOGE) - kelime sınırlarıyla
# İsteğe bağlı "0x"/"tx:" öneklerini de yutuyoruz
TX_REGEX = re.compile(
    r'(?<![A-Za-z0-9])'                              # sol sınır
    r'(?:0x|tx:|TX:|Tx)?'                            # opsiyonel önek
    r'('
    r'[0-9a-fA-F]{64}'                              # EVM/TRX hex
    r'|'
    r'[1-9A-HJ-NP-Za-km-z]{60,70}'                  # BTC/LTC/DOGE base58
    r')'
    r'(?![A-Za-z0-9])'                               # sağ sınır
)

# Token sembol regex'i (opsiyonel, mesajda "USDT 100" gibi belirtmişse)
ASSET_HINT_REGEX = re.compile(
    r'\b('
    r'USDT|USDC|USD₮|BUSD|DAI|TUSD|TETHER|TETHER\(TRC20\)|'
    r'BTC|BITCOIN|ETH|ETHEREUM|BNB|SOL|SOLANA|XRP|RIPPLE|'
    r'LTC|LITECOIN|DOGE|DOGECOIN|AVAX|AVALANCHE|MATIC|POL|POLYGON|'
    r'TRX|TRON|ADA|CARDANO|DOT|POLKADOT|LINK|CHAINLINK'
    r')\b',
    re.IGNORECASE,
)

ASSET_NAME_TO_SYMBOL = {
    'TETHER': 'USDT',
    'TETHER(TRC20)': 'USDT',
    'BITCOIN': 'BTC',
    'ETHEREUM': 'ETH',
    'SOLANA': 'SOL',
    'RIPPLE': 'XRP',
    'LITECOIN': 'LTC',
    'DOGECOIN': 'DOGE',
    'AVALANCHE': 'AVAX',
    'POL': 'MATIC',
    'POLYGON': 'MATIC',
    'TRON': 'TRX',
    'CARDANO': 'ADA',
    'POLKADOT': 'DOT',
    'CHAINLINK': 'LINK',
    'USD₮': 'USDT',
}

# Ağ standardı ipucu (TRC20, ERC20, BEP20, vs) - mesajda "TRC20 USDT" gibi geçiyorsa
NETWORK_HINT_REGEX = re.compile(
    r'(?i)\b('
    r'TRC[\-\s]?20|TRC[\-\s]?10|TRON|'
    r'ERC[\-\s]?20|ETH(?:\s*MAINNET)?|ETHEREUM|'
    r'BEP[\-\s]?20|BSC|BNB(?:\s*CHAIN)?|'
    r'POLYGON|MATIC|POL(?:\s*CHAIN)?|'
    r'ARBITRUM|ARB(?:\s*ONE)?|'
    r'BITCOIN|BTC(?:\s*MAINNET)?'
    r')\b',
)

NETWORK_NAME_TO_CHAIN = {
    'TRC20': 'tron',
    'TRC-20': 'tron',
    'TRC10': 'tron',
    'TRC-10': 'tron',
    'TRON': 'tron',
    'ERC20': 'ethereum',
    'ERC-20': 'ethereum',
    'ETH': 'ethereum',
    'ETHEREUM': 'ethereum',
    'BEP20': 'bsc',
    'BEP-20': 'bsc',
    'BSC': 'bsc',
    'BNB': 'bsc',
    'POLYGON': 'polygon',
    'MATIC': 'polygon',
    'POL': 'polygon',
    'ARBITRUM': 'arbitrum',
    'ARB': 'arbitrum',
    'BITCOIN': 'bitcoin',
    'BTC': 'bitcoin',
    'BTC MAINNET': 'bitcoin',
}


class TxService:
    """Webhook mesajından tx çıkar, çözümle, Telegram'a yanıt gönder."""

    def __init__(self, bot_token: Optional[str] = None, timeout: int = 10):
        self.bot_token = bot_token or getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        self.timeout = timeout
        self.explorer = ExplorerService(timeout=timeout)
        self.rate = RateService(timeout=timeout)

    # ----------------- Public API -----------------
    def find_tx_in_text(self, text: str) -> Optional[str]:
        if not text:
            return None
        m = TX_REGEX.search(text)
        if m:
            return m.group(1)
        return None

    def detect_asset_hint(self, text: str) -> Optional[str]:
        if not text:
            return None
        m = ASSET_HINT_REGEX.search(text)
        if not m:
            return None
        raw = m.group(1).upper()
        return ASSET_NAME_TO_SYMBOL.get(raw, raw)

    def detect_network_hint(self, text: str) -> Optional[str]:
        """Mesajdan ağ ipucu çıkar: 'TRC20 USDT' → 'tron', 'ERC20' → 'ethereum'."""
        if not text:
            return None
        m = NETWORK_HINT_REGEX.search(text)
        if not m:
            return None
        raw = m.group(1).upper()
        return NETWORK_NAME_TO_CHAIN.get(raw)

    def process(
        self,
        *,
        message_text: str,
        chat_id: str,
        message_id: Optional[int] = None,
        send_to_telegram: bool = True,
    ) -> Optional[str]:
        """Mesajı işle, Telegram'a gönderilecek formatlı metni döner.
        Dönüş None ise işlem yapılmadı (tx yok / grup pasif / hata)."""
        tx_hash = self.find_tx_in_text(message_text)
        if not tx_hash:
            return None

        # Grup bu özellik için aktif mi?
        from core.models import TelegramGroup, TxTracker  # lazy

        try:
            group = TelegramGroup.objects.get(chat_id=str(chat_id))
        except TelegramGroup.DoesNotExist:
            logger.info('Tx mesajı geldi ama grup kayıtlı değil: %s', chat_id)
            return None
        if not group.is_active or not group.tx_tracker_enabled:
            # Sessizce yoksay ama DB'ye kısa bir kayıt bırak (analytics için)
            TxTracker.objects.create(
                tx_hash=tx_hash,
                group=group,
                message_id=message_id,
                status='ignored',
                detected_chain='unknown',
            )
            return None

        # DB kaydı oluştur (idempotent: aynı hash gelirse güncelle)
        record, created = TxTracker.objects.get_or_create(
            tx_hash=tx_hash,
            defaults={
                'group': group,
                'message_id': message_id,
                'status': 'pending',
                'detected_chain': 'unknown',
            },
        )
        if not created:
            # 5 dakika içinde aynı hash geldiyse tekrar işleme
            if record.created_at and (timezone.now() - record.created_at).total_seconds() < 300:
                return None
            record.status = 'pending'
            record.error_message = None
            record.save(update_fields=['status', 'error_message'])

        # Varlık ipucu (opsiyonel) - kullanıcı "USDT 100" gibi yazdıysa
        asset_hint = self.detect_asset_hint(message_text)
        # Ağ ipucu (opsiyonel) - kullanıcı "TRC20" veya "ERC20" yazdıysa
        network_hint = self.detect_network_hint(message_text)

        start = time.time()
        details = self.explorer.fetch(tx_hash, hint_chain=network_hint)
        if details is None:
            record.status = 'failed'
            record.error_message = 'Explorer verisi alınamadı (zincir/format desteklenmiyor olabilir)'
            record.save(update_fields=['status', 'error_message'])
            return self._format_error(record)

        # Sembol ipucu ile zincirdeki sembolü karşılaştır
        asset_symbol = (asset_hint or details.asset_symbol or 'USDT').upper()
        try:
            amount = Decimal(str(details.amount)) if details.amount is not None else Decimal('0')
        except (InvalidOperation, TypeError):
            amount = Decimal('0')

        rate_result = self.rate.get_try_rate(asset_symbol)
        try_rate = rate_result.get('rate') if rate_result else None
        rate_source = rate_result.get('source') if rate_result else None

        try_value = None
        if try_rate and amount:
            try_value = (amount * try_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        record.detected_chain = details.chain
        record.asset_symbol = asset_symbol
        record.amount = amount
        record.from_address = details.from_address
        record.to_address = details.to_address
        record.try_rate = try_rate
        record.try_value = try_value
        record.rate_source = rate_source
        record.explorer_url = details.explorer_url
        record.status = 'resolved'
        record.resolved_at = timezone.now()
        record.raw_payload = details.raw
        record.error_message = None
        record.save()

        # Telegram'a gönder
        reply_text = self._format_resolved(record, elapsed=time.time() - start)
        if send_to_telegram:
            self._send_to_telegram(chat_id, reply_text, reply_to_message_id=message_id)
        return reply_text

    # ----------------- Format -----------------
    @staticmethod
    def _standard_label(chain: str, asset: str) -> str:
        """Zincir + varlık kombinasyonundan 'TRC20 USDT' gibi insan-okunabilir standart üretir."""
        if not chain:
            return asset or '?'
        chain_lower = (chain or '').lower()
        asset_up = (asset or '').upper()
        if chain_lower == 'tron' and asset_up in ('USDT', 'USDC', 'TUSD', 'BUSD'):
            return f'TRC20 {asset_up}'
        if chain_lower == 'ethereum' and asset_up in ('USDT', 'USDC', 'DAI', 'BUSD'):
            return f'ERC20 {asset_up}'
        if chain_lower == 'bsc' and asset_up in ('USDT', 'USDC', 'BUSD', 'CAKE'):
            return f'BEP20 {asset_up}'
        if chain_lower == 'polygon' and asset_up in ('USDT', 'USDC'):
            return f'Polygon {asset_up}'
        if chain_lower == 'arbitrum' and asset_up in ('USDT', 'USDC'):
            return f'Arbitrum {asset_up}'
        return asset_up

    def _format_resolved(self, record, elapsed: float = 0.0) -> str:
        chain_label = dict(record._meta.get_field('detected_chain').choices).get(
            record.detected_chain, record.detected_chain.upper()
        )
        asset = record.asset_symbol or '?'
        standard = self._standard_label(record.detected_chain, asset)
        amount = record.amount if record.amount is not None else Decimal('0')
        amount_str = self._format_amount(amount)
        rate = record.try_rate
        rate_source = (record.rate_source or 'bilinmiyor').upper()
        value = record.try_value if record.try_value is not None else Decimal('0')
        value_str = self._format_money(value)

        rate_str = '—'
        if rate is not None:
            try:
                rate_str = f"{rate.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):,}".replace(',', ' ')
            except (InvalidOperation, AttributeError):
                rate_str = str(rate)

        # Varlık satırı: standart etiket ekle (örn. "USDT (TRC20)")
        asset_display = asset
        if standard and standard != asset and standard != '?':
            asset_display = f'{standard}'

        lines = [
            '🪙 <b>Kripto İşlem Detayı</b>',
            '',
            f'💎 <b>Varlık:</b> <code>{asset_display}</code>',
            f'🔢 <b>Miktar:</b> <code>{amount_str}</code> {asset}',
            f'💱 <b>Anlık Kur ({rate_source}):</b> <code>{rate_str}</code> ₺',
            f'🇹🇷 <b>TL Karşılığı:</b> <code>{value_str}</code> ₺',
            '',
            f'🌐 <b>Ağ:</b> {chain_label}',
        ]
        if record.from_address:
            lines.append(f'📤 <b>Gönderen:</b> <code>{self._short_addr(record.from_address)}</code>')
        if record.to_address:
            lines.append(f'📥 <b>Alan:</b> <code>{self._short_addr(record.to_address)}</code>')
        lines.append('')
        lines.append(f'🆔 <b>Tx:</b>')
        lines.append(f'<code>{record.tx_hash}</code>')
        if record.explorer_url:
            lines.append(f'<a href="{record.explorer_url}">🔎 Explorer\'da Gör</a>')
        lines.append('')
        elapsed_str = f' · ⏱ {elapsed:.1f}s' if elapsed else ''
        lines.append(f'<i>🤖 Otomatik algılandı{elapsed_str}</i>')
        return '\n'.join(lines)

    def _format_error(self, record) -> str:
        return (
            '⚠️ <b>Tx okunamadı</b>\n\n'
            f'Hash: <code>{record.tx_hash}</code>\n'
            f'Hata: {record.error_message or "Bilinmeyen zincir/format"}\n\n'
            '<i>Desteklenen ağlar: BTC, ETH, BSC, Polygon, Arbitrum, TRX/TRC20, LTC, DOGE</i>'
        )

    @staticmethod
    def _format_amount(amount: Decimal) -> str:
        try:
            if amount == 0:
                return '0'
            if amount >= 1:
                return f"{amount.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP):,}".replace(',', ' ')
            # küçük sayılar için anlamlı basamak
            text = f"{amount:.8f}".rstrip('0').rstrip('.')
            return text
        except (InvalidOperation, AttributeError):
            return str(amount)

    @staticmethod
    def _format_money(value: Decimal) -> str:
        try:
            return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,}".replace(',', ' ')
        except (InvalidOperation, AttributeError):
            return str(value)

    @staticmethod
    def _short_addr(addr: str, head: int = 6, tail: int = 6) -> str:
        if not addr:
            return ''
        if len(addr) <= head + tail + 3:
            return addr
        return f"{addr[:head]}…{addr[-tail:]}"

    # ----------------- Telegram send -----------------
    def _send_to_telegram(self, chat_id: str, text: str, reply_to_message_id: Optional[int] = None) -> bool:
        """
        Telegram'a mesaj gönderir.
        Hata durumunda False döner, detay loglanır.
        Returns (success, error_message) — caller WebhookLog'a yazabilir.
        """
        if not self.bot_token:
            logger.warning('TELEGRAM_BOT_TOKEN boş - mesaj gönderilmedi')
            return False
        url = f'https://api.telegram.org/bot{self.bot_token}/sendMessage'
        # Önce reply_to olmadan dene (silinen mesaja reply hatası alabiliriz)
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }
        try:
            r = requests.post(url, json=payload, timeout=self.timeout)
            if r.status_code == 200:
                return True
            err_text = (r.text or '')[:300]
            logger.warning('Telegram sendMessage %s: %s', r.status_code, err_text)
            # Bilinen ve yaygın hataları kullanıcı dostu metne çevir
            hint = ''
            try:
                err_json = r.json()
                desc = (err_json.get('description') or '').lower()
                if 'chat not found' in desc:
                    hint = ' — bot gruba eklenmemiş veya chat_id yanlış'
                elif 'bot was blocked' in desc or 'bot was kicked' in desc:
                    hint = ' — bot gruptan atılmış, yeniden ekleyin'
                elif 'not enough rights' in desc or 'have no rights' in desc or 'forbidden' in desc:
                    hint = ' — bot gruba ADMIN olarak eklenmeli (yöneticilerden)'
                elif 'message is too long' in desc:
                    hint = ' — mesaj çok uzun'
                elif 'replied message not found' in desc:
                    hint = ' — orijinal mesaj silinmiş'
            except Exception:  # noqa: BLE001
                pass
            logger.warning('Telegram gönderim hatası: %s%s', err_text, hint)
            return False
        except requests.RequestException as exc:
            logger.warning('Telegram sendMessage error: %s', exc)
            return False
