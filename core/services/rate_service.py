"""
Türkiye kripto borsalarından (BTCTurk, Paribu) anlık TL kur çekme servisi.
Sonuçlar TxRateCache tablosunda 30 saniyeye kadar önbelleğe alınır.
"""
import logging
import time
from decimal import Decimal
from typing import Optional, Dict

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

# Birim saniye cinsinden cache süresi
CACHE_TTL_SECONDS = 30

# Varlık -> Paribu / BTCTurk parite eşlemesi
SYMBOL_TO_BTCTURK = {
    'USDT': 'USDT_TRY',
    'BTC': 'BTC_TRY',
    'ETH': 'ETH_TRY',
    'BNB': 'BNB_TRY',
    'SOL': 'SOL_TRY',
    'XRP': 'XRP_TRY',
    'LTC': 'LTC_TRY',
    'DOGE': 'DOGE_TRY',
    'AVAX': 'AVAX_TRY',
    'MATIC': 'MATIC_TRY',
    'TRX': 'TRX_TRY',
    'ADA': 'ADA_TRY',
    'DOT': 'DOT_TRY',
    'LINK': 'LINK_TRY',
}

SYMBOL_TO_PARIBU = {
    'USDT': 'usdt-tl',
    'BTC': 'btc-tl',
    'ETH': 'eth-tl',
    'BNB': 'bnb-tl',
    'SOL': 'sol-tl',
    'XRP': 'xrp-tl',
    'LTC': 'ltc-tl',
    'DOGE': 'doge-tl',
    'AVAX': 'avax-tl',
    'MATIC': 'matic-tl',
    'TRX': 'trx-tl',
    'ADA': 'ada-tl',
    'DOT': 'dot-tl',
    'LINK': 'link-tl',
}

BTCTURK_URL = 'https://api.btcturk.com/api/v2/ticker'
PARIBU_URL = 'https://api.paribu.com/v2/ticker'  # Paribu public ticker


class RateService:
    """TL kuru çekip önbelleğe alan yardımcı sınıf."""

    def __init__(self, timeout: int = 8):
        self.timeout = timeout

    def get_try_rate(self, asset_symbol: str) -> Dict:
        """
        Belirtilen varlık için TL kurunu döner.
        Birden çok kaynaktan dener, ilk başarılı olanı kullanır.
        Sonuç: {'rate': Decimal, 'source': 'btcturk'|'paribu', 'cached': bool}
        """
        asset = (asset_symbol or '').upper().strip()
        if not asset:
            return {'rate': None, 'source': None, 'cached': False, 'error': 'empty_asset'}

        # Stable coin'ler için TRY ile birebir kuru kabul et
        if asset in ('TRY', 'TL'):
            return {'rate': Decimal('1'), 'source': 'self', 'cached': False}

        # 1) BTCTurk dene
        btcturk = self._fetch_btcturk(asset)
        if btcturk:
            return btcturk

        # 2) Paribu dene
        paribu = self._fetch_paribu(asset)
        if paribu:
            return paribu

        return {'rate': None, 'source': None, 'cached': False, 'error': 'all_sources_failed'}

    # ----------------- BTCTurk -----------------
    def _fetch_btcturk(self, asset: str) -> Optional[Dict]:
        pair = SYMBOL_TO_BTCTURK.get(asset)
        if not pair:
            return None
        cached = self._cache_get(asset, 'btcturk', pair)
        if cached:
            return cached
        try:
            r = requests.get(BTCTURK_URL, params={'pairSymbol': pair}, timeout=self.timeout)
            if r.status_code != 200:
                logger.warning('BTCTurk HTTP %s for %s', r.status_code, asset)
                return None
            data = r.json() or {}
            items = data.get('data') or []
            if not items:
                return None
            last = items[0].get('last')
            if last in (None, '', 0, '0'):
                return None
            rate = Decimal(str(last))
            self._cache_set(asset, 'btcturk', pair, rate)
            return {'rate': rate, 'source': 'btcturk', 'cached': False}
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning('BTCTurk error for %s: %s', asset, exc)
            return None

    # ----------------- Paribu -----------------
    def _fetch_paribu(self, asset: str) -> Optional[Dict]:
        pair = SYMBOL_TO_PARIBU.get(asset)
        if not pair:
            return None
        cached = self._cache_get(asset, 'paribu', pair)
        if cached:
            return cached
        try:
            r = requests.get(PARIBU_URL, timeout=self.timeout)
            if r.status_code != 200:
                logger.warning('Paribu HTTP %s for %s', r.status_code, asset)
                return None
            payload = r.json() or {}
            # Paribu hem list hem dict dönebilir; farklı formatlara karşı sağlam ol
            ticker = None
            if isinstance(payload, dict):
                ticker = payload.get(pair) or payload.get(pair.upper()) or payload.get(pair.lower())
                if ticker is None and 'data' in payload and isinstance(payload['data'], dict):
                    ticker = payload['data'].get(pair) or payload['data'].get(pair.upper())
            elif isinstance(payload, list):
                for entry in payload:
                    if isinstance(entry, dict) and entry.get('pair') in (pair, pair.upper()):
                        ticker = entry
                        break
            if not isinstance(ticker, dict):
                return None
            last = ticker.get('last') or ticker.get('price') or ticker.get('current')
            if last in (None, '', 0, '0'):
                return None
            rate = Decimal(str(last))
            self._cache_set(asset, 'paribu', pair, rate)
            return {'rate': rate, 'source': 'paribu', 'cached': False}
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning('Paribu error for %s: %s', asset, exc)
            return None

    # ----------------- Cache -----------------
    def _cache_get(self, asset: str, source: str, pair: str) -> Optional[Dict]:
        from core.models import TxRateCache  # lazy import

        try:
            entry = TxRateCache.objects.get(asset=asset, source=source)
        except TxRateCache.DoesNotExist:
            return None
        age = (timezone.now() - entry.fetched_at).total_seconds()
        if age > CACHE_TTL_SECONDS:
            return None
        return {'rate': entry.rate, 'source': source, 'cached': True}

    def _cache_set(self, asset: str, source: str, pair: str, rate: Decimal) -> None:
        from core.models import TxRateCache

        try:
            TxRateCache.objects.update_or_create(
                asset=asset,
                source=source,
                defaults={'pair': pair, 'rate': rate},
            )
        except Exception as exc:  # tablo henüz migrate edilmediyse sessiz geç
            logger.debug('TxRateCache write skipped: %s', exc)
