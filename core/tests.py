"""
Kripto TX Takip modülü için unit testler.
Gerçek ağ çağrısı yapmadan regex/format mantığını doğrular.
"""
from decimal import Decimal
from django.test import TestCase, override_settings

from core.services.tx_service import TxService


VALID_BTC_HASH = '0' * 60 + '1111'   # 64 hex değil
VALID_EVM_HASH = 'a' * 64             # ETH/TRX ortak
VALID_BTC_BASE58 = '1' * 62           # base58 uzunluğu


class TxHashDetectionTests(TestCase):
    def setUp(self):
        self.svc = TxService(bot_token='dummy')

    def test_detect_evm_hash(self):
        text = f'Gönderim tamam, tx: {VALID_EVM_HASH} lütfen kontrol et'
        self.assertEqual(self.svc.find_tx_in_text(text), VALID_EVM_HASH)

    def test_detect_base58_hash(self):
        text = f'Yatırıldı - tx {VALID_BTC_BASE58} selamlar'
        self.assertEqual(self.svc.find_tx_in_text(text), VALID_BTC_BASE58)

    def test_no_hash_returns_none(self):
        self.assertIsNone(self.svc.find_tx_in_text('selamlar herkese'))
        self.assertIsNone(self.svc.find_tx_in_text(None))
        self.assertIsNone(self.svc.find_tx_in_text(''))

    def test_short_hex_ignored(self):
        # Çok kısa hex - tx değil
        self.assertIsNone(self.svc.find_tx_in_text('hash 0x1234'))

    def test_hash_at_word_boundary(self):
        # Kelimenin ortasında olmamalı (örn: başka bir uzun kelimenin parçası olmamalı)
        self.assertIsNotNone(self.svc.find_tx_in_text(f'\n{VALID_EVM_HASH}\n'))

    def test_asset_hint(self):
        self.assertEqual(self.svc.detect_asset_hint('USDT gönderdim'), 'USDT')
        self.assertEqual(self.svc.detect_asset_hint('bnb aldım'), 'BNB')
        self.assertEqual(self.svc.detect_asset_hint('Merhaba dünya'), None)


class FormatTests(TestCase):
    def setUp(self):
        self.svc = TxService(bot_token='dummy')

    def test_format_amount_integer(self):
        self.assertEqual(self.svc._format_amount(Decimal('1234.56789012')), '1 234.56789012')

    def test_format_amount_small(self):
        # 0 < x < 1 - anlamlı basamak
        out = self.svc._format_amount(Decimal('0.00001234'))
        self.assertIn('0.00001234', out)

    def test_format_money(self):
        out = self.svc._format_money(Decimal('1234567.89'))
        self.assertIn('1 234 567.89', out)

    def test_short_addr(self):
        self.assertEqual(self.svc._short_addr(''), '')
        self.assertEqual(self.svc._short_addr('TQr'), 'TQr')
        long = 'T' + 'X' * 40
        out = self.svc._short_addr(long)
        self.assertIn('…', out)


class RateServiceCacheTests(TestCase):
    @override_settings(DEBUG=True)
    def test_get_try_rate_for_try(self):
        from core.services.rate_service import RateService
        r = RateService()
        out = r.get_try_rate('TRY')
        self.assertEqual(out['rate'], Decimal('1'))
        self.assertEqual(out['source'], 'self')

    def test_get_try_rate_unknown_asset(self):
        from core.services.rate_service import RateService
        out = RateService().get_try_rate('')
        self.assertIsNone(out['rate'])
