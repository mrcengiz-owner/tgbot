"""
Türkiye ve global kripto borsalarından anlık TL kuru çekme servisi.
6 kaynaktan paralel olarak çekip ortalama + medyan hesaplar.

Desteklenen kaynaklar:
- BTCTurk (TR) - public ticker
- Paribu (TR) - public ticker
- Bitturk (TR) - public ticker
- Binance TR (global, TRY yok) - USDT/USDC üzerinden TRY'ye çevirir
- CoinGecko (global) - public API, TRY fiyatı döner
- Crypto.com (TR yok) - USDT/TRY dönüşümü
"""
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, List

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

# Birim saniye cinsinden cache süresi
CACHE_TTL_SECONDS = 30

# Varlık -> Paribu / BTCTurk / Bitturk / Cointr parite eşlemesi
SYMBOL_TO_BTCTURK = {
    'USDT': 'USDT_TRY', 'BTC': 'BTC_TRY', 'ETH': 'ETH_TRY',
    'BNB': 'BNB_TRY', 'SOL': 'SOL_TRY', 'XRP': 'XRP_TRY',
    'LTC': 'LTC_TRY', 'DOGE': 'DOGE_TRY', 'AVAX': 'AVAX_TRY',
    'MATIC': 'MATIC_TRY', 'TRX': 'TRX_TRY', 'ADA': 'ADA_TRY',
    'DOT': 'DOT_TRY', 'LINK': 'LINK_TRY', 'USDC': 'USDC_TRY',
}

SYMBOL_TO_PARIBU = {
    'USDT': 'usdt-tl', 'BTC': 'btc-tl', 'ETH': 'eth-tl',
    'BNB': 'bnb-tl', 'SOL': 'sol-tl', 'XRP': 'xrp-tl',
    'LTC': 'ltc-tl', 'DOGE': 'doge-tl', 'AVAX': 'avax-tl',
    'MATIC': 'matic-tl', 'TRX': 'trx-tl', 'ADA': 'ada-tl',
    'DOT': 'dot-tl', 'LINK': 'link-tl', 'USDC': 'usdc-tl',
}

SYMBOL_TO_BITTURK = {
    'USDT': 'USDT', 'BTC': 'BTC', 'ETH': 'ETH',
    'BNB': 'BNB', 'SOL': 'SOL', 'XRP': 'XRP',
    'LTC': 'LTC', 'DOGE': 'DOGE', 'AVAX': 'AVAX',
    'MATIC': 'MATIC', 'TRX': 'TRX', 'ADA': 'ADA',
    'DOT': 'DOT', 'LINK': 'LINK', 'USDC': 'USDC',
}

# Cointr spot parite - USDTTRY, BTCTRY vs.
SYMBOL_TO_COINTR = {
    'USDT': 'USDTTRY', 'BTC': 'BTCTRY', 'ETH': 'ETHTRY',
    'BNB': 'BNBTRY', 'SOL': 'SOLTRY', 'XRP': 'XRPTRY',
    'LTC': 'LTCTRY', 'DOGE': 'DOGETRY', 'AVAX': 'AVAXTRY',
    'MATIC': 'MATICTRY', 'TRX': 'TRXTRY', 'ADA': 'ADATRY',
    'DOT': 'DOTTRY', 'LINK': 'LINKTRY', 'USDC': 'USDCTRY',
}

# CoinGecko ID'leri (API path'leri)
SYMBOL_TO_COINGECKO = {
    'USDT': 'tether', 'USDC': 'usd-coin', 'BTC': 'bitcoin',
    'ETH': 'ethereum', 'BNB': 'binancecoin', 'SOL': 'solana',
    'XRP': 'ripple', 'LTC': 'litecoin', 'DOGE': 'dogecoin',
    'AVAX': 'avalanche-2', 'MATIC': 'matic-network',
    'TRX': 'tron', 'ADA': 'cardano', 'DOT': 'polkadot',
    'LINK': 'chainlink', 'BUSD': 'binance-usd', 'DAI': 'dai',
}

BTCTURK_URL = 'https://api.btcturk.com/api/v2/ticker'
PARIBU_URL = 'https://api.paribu.com/v2/ticker'
BITTURK_URL = 'https://api.bitturk.com/api/v2/ticker'
COINGECKO_URL = 'https://api.coingecko.com/api/v3/simple/price'
BINANCE_URL = 'https://api.binance.com/api/v3/ticker/price'
COINTR_URL = 'https://api.cointr.com/api/v2/spot/market/tickers'


class RateService:
    """TL kuru çekip önbelleğe alan yardımcı sınıf - 6 kaynaktan toplar."""

    def __init__(self, timeout: int = 8):
        self.timeout = timeout

    def get_try_rate(self, asset_symbol: str) -> Dict:
        """
        Tek bir kaynaktan (en yüksek hacimli olan) TL kurunu döner.
        Geriye uyumluluk için var; yeni kullanım için get_all_try_rates önerilir.
        """
        asset = (asset_symbol or '').upper().strip()
        if not asset:
            return {'rate': None, 'source': None, 'cached': False, 'error': 'empty_asset'}
        if asset in ('TRY', 'TL'):
            return {'rate': Decimal('1'), 'source': 'self', 'cached': False}

        # Önce önbellekten dene
        all_rates = self.get_all_try_rates(asset)
        if all_rates.get('sources'):
            # En güncel kaynağı dön (ilk başarılı)
            return {
                'rate': all_rates['average'],
                'source': all_rates['sources'][0]['source'],
                'cached': any(s.get('cached') for s in all_rates['sources']),
                'all_sources': all_rates,
            }
        return {'rate': None, 'source': None, 'cached': False, 'error': 'all_sources_failed'}

    def get_all_try_rates(self, asset_symbol: str) -> Dict:
        """
        Tüm kaynaklardan TL kurunu çeker, ortalama ve medyan hesaplar.
        Sonuç: {
            'asset': str,
            'sources': [{'source': 'btcturk', 'rate': Decimal, 'cached': bool, 'pair': 'USDT_TRY'}, ...],
            'average': Decimal,  # en yakın USDT bazlı dönüşümlerin ortalaması
            'median': Decimal,
            'min': Decimal,
            'max': Decimal,
            'successful_count': int,
            'error': str|None,
        }
        """
        asset = (asset_symbol or '').upper().strip()
        result = {
            'asset': asset,
            'sources': [],
            'average': None,
            'median': None,
            'min': None,
            'max': None,
            'successful_count': 0,
            'error': None,
        }
        if not asset:
            result['error'] = 'empty_asset'
            return result
        if asset in ('TRY', 'TL'):
            result['average'] = Decimal('1')
            result['median'] = Decimal('1')
            result['min'] = Decimal('1')
            result['max'] = Decimal('1')
            result['successful_count'] = 1
            result['sources'] = [{'source': 'self', 'rate': Decimal('1'), 'cached': False, 'pair': 'TRY'}]
            return result

        # Tüm kaynaklardan paralel olarak çek
        all_rates: List[Decimal] = []
        fetcher_results: List[Dict] = []

        # 1) BTCTurk
        btcturk = self._fetch_btcturk(asset)
        if btcturk:
            fetcher_results.append(btcturk)
            all_rates.append(btcturk['rate'])

        # 2) Paribu
        paribu = self._fetch_paribu(asset)
        if paribu:
            fetcher_results.append(paribu)
            all_rates.append(paribu['rate'])

        # 3) Bitturk
        bitturk = self._fetch_bitturk(asset)
        if bitturk:
            fetcher_results.append(bitturk)
            all_rates.append(bitturk['rate'])

        # 4) Cointr
        cointr = self._fetch_cointr(asset)
        if cointr:
            fetcher_results.append(cointr)
            all_rates.append(cointr['rate'])

        # 5) CoinGecko (doğrudan TRY fiyatı)
        cg = self._fetch_coingecko(asset)
        if cg:
            fetcher_results.append(cg)
            all_rates.append(cg['rate'])

        # 6) Binance → TRY (USDT üzerinden köprü)
        binance = self._fetch_binance_try(asset)
        if binance:
            fetcher_results.append(binance)
            all_rates.append(binance['rate'])

        if not all_rates:
            result['error'] = 'all_sources_failed'
            return result

        # İstatistikler
        sorted_rates = sorted(all_rates)
        n = len(sorted_rates)
        avg = sum(sorted_rates) / Decimal(n)
        if n % 2 == 0:
            median = (sorted_rates[n // 2 - 1] + sorted_rates[n // 2]) / 2
        else:
            median = sorted_rates[n // 2]

        # Quantize
        result['average'] = avg.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        result['median'] = median.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        result['min'] = min(sorted_rates).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        result['max'] = max(sorted_rates).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        result['sources'] = fetcher_results
        result['successful_count'] = n
        return result

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
            return {'rate': rate, 'source': 'btcturk', 'cached': False, 'pair': pair}
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
            return {'rate': rate, 'source': 'paribu', 'cached': False, 'pair': pair}
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning('Paribu error for %s: %s', asset, exc)
            return None

    # ----------------- Bitturk -----------------
    def _fetch_bitturk(self, asset: str) -> Optional[Dict]:
        pair_symbol = SYMBOL_TO_BITTURK.get(asset)
        if not pair_symbol:
            return None
        pair = f'{pair_symbol}_TRY'
        cached = self._cache_get(asset, 'bitturk', pair)
        if cached:
            return cached
        try:
            # Bitturk public ticker
            r = requests.get(
                BITTURK_URL,
                params={'pairSymbol': pair_symbol},
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return None
            data = r.json() or {}
            items = data.get('data') or []
            if not items:
                return None
            last = items[0].get('last')
            if last in (None, '', 0, '0'):
                return None
            rate = Decimal(str(last))
            self._cache_set(asset, 'bitturk', pair, rate)
            return {'rate': rate, 'source': 'bitturk', 'cached': False, 'pair': pair}
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.debug('Bitturk error for %s: %s', asset, exc)
            return None

    # ----------------- Cointr -----------------
    def _fetch_cointr(self, asset: str) -> Optional[Dict]:
        """CoinTR.com spot ticker - TRY pariteleri. Public, auth gerektirmez."""
        symbol = SYMBOL_TO_COINTR.get(asset)
        if not symbol:
            return None
        pair = f'{asset}_TRY'
        cached = self._cache_get(asset, 'cointr', pair)
        if cached:
            return cached
        try:
            r = requests.get(
                COINTR_URL,
                params={'symbol': symbol},
                timeout=self.timeout,
            )
            if r.status_code != 200:
                logger.debug('CoinTR HTTP %s for %s', r.status_code, asset)
                return None
            data = r.json() or {}
            items = data.get('data') or []
            if not items:
                return None
            # Cointr v2 response: {"code":"00000","data":[{"symbol":"USDTTRY","lastPr":"46.11",...}]}
            last = items[0].get('lastPr')
            if last in (None, '', 0, '0'):
                return None
            rate = Decimal(str(last))
            self._cache_set(asset, 'cointr', pair, rate)
            return {'rate': rate, 'source': 'cointr', 'cached': False, 'pair': pair}
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.debug('CoinTR error for %s: %s', asset, exc)
            return None

    # ----------------- CoinGecko -----------------
    def _fetch_coingecko(self, asset: str) -> Optional[Dict]:
        cg_id = SYMBOL_TO_COINGECKO.get(asset)
        if not cg_id:
            return None
        pair = f'{asset}_TRY'
        cached = self._cache_get(asset, 'coingecko', pair)
        if cached:
            return cached
        try:
            r = requests.get(
                COINGECKO_URL,
                params={'ids': cg_id, 'vs_currencies': 'try'},
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return None
            data = r.json() or {}
            rate = data.get(cg_id, {}).get('try')
            if not rate:
                return None
            decimal_rate = Decimal(str(rate))
            self._cache_set(asset, 'coingecko', pair, decimal_rate)
            return {'rate': decimal_rate, 'source': 'coingecko', 'cached': False, 'pair': pair}
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.debug('CoinGecko error for %s: %s', asset, exc)
            return None

    # ----------------- Binance → TRY (USDT üzerinden) -----------------
    def _fetch_binance_try(self, asset: str) -> Optional[Dict]:
        """Binance'de TRY paritesi olmadığından USDT paritesini çekip CoinGecko'dan
        USDT/TRY kuruyla çarpıyoruz. Bu, 2 aşamalı bir hesaplama."""
        cg_id = SYMBOL_TO_COINGECKO.get(asset)
        if not cg_id or asset == 'USDT':
            return None
        pair = f'{asset}_TRY (via USDT)'
        cached = self._cache_get(asset, 'binance', pair)
        if cached:
            return cached
        try:
            # 1) Binance'den asset/USDT
            r = requests.get(
                BINANCE_URL,
                params={'symbol': f'{asset}USDT'},
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return None
            data = r.json() or {}
            price_usdt = data.get('price')
            if not price_usdt:
                return None
            price_usdt_dec = Decimal(str(price_usdt))

            # 2) USDT/TRY (cache'den veya CoinGecko'dan)
            usdt_try_cached = self._cache_get('USDT', 'btcturk', 'USDT_TRY')
            usdt_try = None
            if usdt_try_cached:
                usdt_try = usdt_try_cached['rate']
            else:
                cg_usdt = self._fetch_coingecko('USDT')
                if cg_usdt:
                    usdt_try = cg_usdt['rate']
            if not usdt_try:
                return None

            try_rate = (price_usdt_dec * usdt_try).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
            self._cache_set(asset, 'binance', pair, try_rate)
            return {'rate': try_rate, 'source': 'binance', 'cached': False, 'pair': pair}
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.debug('Binance error for %s: %s', asset, exc)
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
        return {'rate': entry.rate, 'source': source, 'cached': True, 'pair': pair}

    def _cache_set(self, asset: str, source: str, pair: str, rate: Decimal) -> None:
        from core.models import TxRateCache

        try:
            TxRateCache.objects.update_or_create(
                asset=asset,
                source=source,
                defaults={'pair': pair, 'rate': rate},
            )
        except Exception as exc:
            logger.debug('TxRateCache write skipped: %s', exc)
