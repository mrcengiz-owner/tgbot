"""
Webhook'tan gelen tx hash'leri işleyen ana orkestratör.
Mesaj regex'i, zincir tespiti, kur çevirimi, Telegram gönderimi ve DB kaydı burada.
"""
import logging
import re
import time
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Optional, Tuple

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
        self.last_send_ok = False
        self.last_send_error = ''

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
        self.last_send_ok = False
        self.last_send_error = ''
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
            TxTracker.objects.get_or_create(
                tx_hash=tx_hash,
                defaults={
                    'group': group,
                    'message_id': message_id,
                    'status': 'ignored',
                    'detected_chain': 'unknown',
                },
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
            # Aynı hash kısa sürede tekrar gelirse sessiz kalma; gruba bilgi ver.
            if record.created_at and (timezone.now() - record.created_at).total_seconds() < 300:
                note = 'ℹ️ Bu işlem kısa süre önce işlendi.'
                if send_to_telegram:
                    self._send_to_telegram(chat_id, note)
                return note
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
            reply = self._format_error(record)
            if send_to_telegram:
                self._send_to_telegram(chat_id, reply)
            return reply

        # Sembol ipucu ile zincirdeki sembolü karşılaştır
        asset_symbol = (asset_hint or details.asset_symbol or 'USDT').upper()
        try:
            amount = Decimal(str(details.amount)) if details.amount is not None else Decimal('0')
        except (InvalidOperation, TypeError):
            amount = Decimal('0')

        # Tüm kaynaklardan kur çek
        all_rates = self.rate.get_all_try_rates(asset_symbol)
        try_rate = all_rates.get('average')
        rate_source = f"{all_rates.get('successful_count', 0)} kaynak ort."
        if all_rates.get('error') and not try_rate:
            rate_source = 'bilinmiyor'

        try_value = None
        if try_rate and amount:
            try_value = (amount * try_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Tüm kaynakları ayrıntılı log için sakla (raw_payload'a ek)
        rates_payload = {
            'sources': [
                {'source': s['source'], 'rate': str(s['rate']), 'pair': s.get('pair', ''), 'cached': s.get('cached', False)}
                for s in all_rates.get('sources', [])
            ],
            'average': str(all_rates.get('average')) if all_rates.get('average') is not None else None,
            'median': str(all_rates.get('median')) if all_rates.get('median') is not None else None,
            'min': str(all_rates.get('min')) if all_rates.get('min') is not None else None,
            'max': str(all_rates.get('max')) if all_rates.get('max') is not None else None,
            'count': all_rates.get('successful_count', 0),
        }

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
        # Hem raw hem rate'leri sakla
        combined_payload = dict(details.raw or {})
        combined_payload['_rates'] = rates_payload
        record.raw_payload = combined_payload
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
        """Modern, mobile-friendly HTML formatı.
        Yapı: başlık → ana bilgi kartı → kur kartı → adres kartı → tx kartı → footer."""
        chain_label = dict(record._meta.get_field('detected_chain').choices).get(
            record.detected_chain, record.detected_chain.upper()
        )
        asset = record.asset_symbol or '?'
        standard = self._standard_label(record.detected_chain, asset)
        amount = record.amount if record.amount is not None else Decimal('0')
        amount_str = self._format_amount(amount)
        rate = record.try_rate
        value = record.try_value if record.try_value is not None else Decimal('0')
        value_str = self._format_money(value)

        rates_payload = {}
        if isinstance(record.raw_payload, dict):
            rates_payload = record.raw_payload.get('_rates', {}) or {}

        rate_str = '—'
        if rate is not None:
            try:
                rate_str = f"{rate.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):,}".replace(',', ' ')
            except (InvalidOperation, AttributeError):
                rate_str = str(rate)

        asset_display = standard if (standard and standard != '?') else asset

        # Kaynak ikonları
        source_icons = {
            'btcturk': '🇹🇷', 'paribu': '🇹🇷', 'bitturk': '🇹🇷', 'cointr': '🇹🇷',
            'binance': '🌐', 'coingecko': '🌐',
        }
        source_names = {
            'btcturk': 'BTCTurk', 'paribu': 'Paribu', 'bitturk': 'Bitturk',
            'cointr': 'Cointr', 'binance': 'Binance', 'coingecko': 'CoinGecko',
        }

        parts = []
        # Başlık
        parts.append('┏━━━━━━━━━━━━━━━━━━━━━━━━━┓')
        parts.append(f'┃  🪙 <b>{self._escape(standard)} Detayı</b>')
        parts.append('┗━━━━━━━━━━━━━━━━━━━━━━━━━┛')
        parts.append('')

        # Ana bilgi: varlık + miktar + TL
        parts.append(f'💎 <b>Varlık</b>      <code>{self._escape(asset)}</code>')
        parts.append(f'🔢 <b>Miktar</b>      <code>{self._escape(amount_str)}</code> <i>{self._escape(asset)}</i>')
        parts.append(f'🇹🇷 <b>TL Karşılığı</b>  <code>{self._escape(value_str)} ₺</code>')
        parts.append('')

        # Kur kartı
        sources = rates_payload.get('sources', []) if rates_payload else []
        if sources:
            parts.append('┌── 💱 <b>Anlık Kur</b> ──┐')
            for s in sources:
                icon = source_icons.get(s.get('source', ''), '•')
                name = source_names.get(s.get('source', ''), s.get('source', '?').upper())
                rate_val = s.get('rate', '?')
                cached = ' <i>📦</i>' if s.get('cached') else ''
                parts.append(f'│ {icon} <code>{self._escape(str(rate_val))} ₺</code>  <b>{name}</b>{cached}')
            avg = rates_payload.get('average')
            med = rates_payload.get('median')
            mn = rates_payload.get('min')
            mx = rates_payload.get('max')
            if avg and med:
                avg_s = self._escape(str(avg))
                med_s = self._escape(str(med))
                mn_s = self._escape(str(mn))
                mx_s = self._escape(str(mx))
                parts.append(f'│ ────────────────────')
                parts.append(f'│ <b>Ort</b> <code>{avg_s}</code>  <b>Med</b> <code>{med_s}</code>')
                parts.append(f'│ <b>Min</b> <code>{mn_s}</code>  <b>Max</b> <code>{mx_s}</code> ₺')
            parts.append(f'│ <i>⮕ Hesaplanan:</i> <code>{self._escape(rate_str)} ₺</code>')
            parts.append('└─────────────────────┘')
        else:
            rate_source = (record.rate_source or 'bilinmiyor').upper()
            parts.append(f'┌── 💱 <b>Anlık Kur</b> ──┐')
            parts.append(f'│ <b>{self._escape(rate_source)}</b>  <code>{self._escape(rate_str)} ₺</code>')
            parts.append('└─────────────────────┘')
        parts.append('')

        # Ağ & adresler
        parts.append(f'🌐 <b>Ağ</b>         <code>{self._escape(chain_label)}</code>')
        if record.from_address:
            short_from = self._short_addr(record.from_address)
            parts.append(f'📤 <b>Gönderen</b>    <code>{self._escape(short_from)}</code>')
        if record.to_address:
            short_to = self._short_addr(record.to_address)
            parts.append(f'📥 <b>Alan</b>       <code>{self._escape(short_to)}</code>')
        parts.append('')

        # Tx kartı
        short_hash = self._short_hash(record.tx_hash)
        if record.explorer_url:
            explorer_names = {
                'tron': 'Tronscan',
                'ethereum': 'Etherscan',
                'bsc': 'BscScan',
                'polygon': 'Polygonscan',
                'arbitrum': 'Arbiscan',
                'bitcoin': 'Mempool',
                'litecoin': 'Blockchair',
                'dogecoin': 'Blockchair',
            }
            label = explorer_names.get(record.detected_chain, 'Explorer')
            href = self._escape(record.explorer_url).replace('"', '%22')
            parts.append(
                f'🔗 <a href="{href}"><b>{label}\'da Gör</b></a>  '
                f'<code>{self._escape(short_hash)}</code>'
            )
        else:
            parts.append(f'🆔 <b>Tx</b>  <code>{self._escape(short_hash)}</code>')
        parts.append('')

        # Footer
        elapsed_str = f'  ⏱ {elapsed:.1f}s' if elapsed else ''
        parts.append(f'<i>🤖 Otomatik algılandı{self._escape(elapsed_str)}</i>')
        return '\n'.join(parts)

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

    @staticmethod
    def _short_hash(h: str, head: int = 8, tail: int = 6) -> str:
        """Tx hash'i kısa göster: 'b9862d70...1e8d7'."""
        if not h:
            return ''
        if len(h) <= head + tail + 3:
            return h
        return f"{h[:head]}…{h[-tail:]}"

    @staticmethod
    def _escape(text: str) -> str:
        """Telegram HTML parse_mode için güvenli kaçış.
        <, >, & karakterleri Telegram tarafından mesaj kırıcı olarak yorumlanır."""
        if not text:
            return ''
        return (
            str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
        )

    # ----------------- Telegram send -----------------
    def _send_to_telegram(self, chat_id: str, text: str, reply_to_message_id: Optional[int] = None) -> bool:
        """Telegram'a tek mesaj gönderir. HTML bozulursa düz metne düşer."""
        del reply_to_message_id  # silinmiş mesaja reply Telegram'ı düşürüyor
        from core.services.bot_client import send_message

        if not self.bot_token:
            self.last_send_ok = False
            self.last_send_error = 'TELEGRAM_BOT_TOKEN boş'
            logger.warning(self.last_send_error)
            return False

        ok, err = send_message(chat_id, text, token=self.bot_token, timeout=self.timeout)
        self.last_send_ok = ok
        self.last_send_error = err
        if not ok:
            logger.warning('Telegram gönderim hatası: %s', err)
        return ok
