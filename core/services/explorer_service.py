"""
Çeşitli blockchain ağları için tx hash doğrulama & zincire göre veri çekme.
- BTC/LTC/DOGE: public node / explorer public endpoint (sochain/mempool.space)
- ETH + EVM ağları: Etherscan v2 API (free tier 3 req/s)
- Tron (TRC20): TronGrid v1 (free 15 QPS, opsiyonel API key)
"""
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Dict, List

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ETHERSCAN_CHAIN_IDS = {
    'ethereum': 1,
    'bsc': 56,
    'polygon': 137,
    'arbitrum': 42161,
    'base': 8453,
}

EXPLORER_URLS = {
    'bitcoin': 'https://mempool.space/tx',
    'litecoin': 'https://blockchair.com/litecoin/transaction',
    'dogecoin': 'https://blockchair.com/dogecoin/transaction',
    'ethereum': 'https://etherscan.io/tx',
    'bsc': 'https://bscscan.com/tx',
    'polygon': 'https://polygonscan.com/tx',
    'arbitrum': 'https://arbiscan.io/tx',
    'tron': 'https://tronscan.org/#/transaction',
}


@dataclass
class TxDetails:
    chain: str
    asset_symbol: str
    amount: Optional[Decimal] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    confirmed: bool = False
    explorer_url: Optional[str] = None
    raw: Dict = field(default_factory=dict)


class ExplorerService:
    """Tx hash'ten zincir bilgisi ve detayları döner."""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.etherscan_key = getattr(settings, 'ETHERSCAN_API_KEY', '') or ''
        self.trongrid_key = getattr(settings, 'TRONGRID_API_KEY', '') or ''

    # ----------------- Public API -----------------
    def fetch(self, tx_hash: str, hint_chain: Optional[str] = None) -> Optional[TxDetails]:
        """Tx hash'i tanır ve ilgili zincirden detayları çeker.
        Akıllı strateji: ipucu varsa onu dene, yoksa sırayla TRON → EVM'ler → UTXO zincirleri."""
        # Hash'i normalleştir (0x prefix'i, küçük harf)
        h = self._normalize_hash(tx_hash)
        if not h:
            return None

        # 1) Önce ipucu/hint_chain varsa onu dene
        if hint_chain and hint_chain != 'unknown':
            result = self._try_chain(hint_chain, h)
            if result:
                return result

        # 2) Format tabanlı sıralı deneme
        # 64 hex → TRON veya EVM (sırayla dene)
        if re.fullmatch(r'[0-9a-fA-F]{64}', h):
            return self._fetch_evm_or_tron(h)

        # base58 (60-70 karakter) → UTXO zincirleri (BTC, LTC, DOGE)
        if re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{60,70}', h):
            for chain in ('bitcoin', 'litecoin', 'dogecoin'):
                result = self._fetch_utxo(chain, h)
                if result and result.amount is not None:
                    return result
            return None

        return None

    def _normalize_hash(self, tx_hash: str) -> Optional[str]:
        """Hash'i temizle: 0x öneki kaldır/ekle, küçük harfe çevir."""
        if not tx_hash:
            return None
        h = tx_hash.strip()
        # "0x" veya "0X" prefix'i kaldır (Etherscan API başında 0x olmadan da kabul eder
        # ama biz tutarlılık için temizleyelim)
        if h.lower().startswith('0x'):
            h = h[2:]
        return h

    def _try_chain(self, chain: str, h: str) -> Optional[TxDetails]:
        """Belirli bir zincirden çekmeyi dene."""
        if chain in ('bitcoin', 'litecoin', 'dogecoin'):
            return self._fetch_utxo(chain, h)
        if chain in ('ethereum', 'bsc', 'polygon', 'arbitrum'):
            return self._fetch_evm(chain, h)
        if chain == 'tron':
            return self._fetch_tron(h)
        return None

    def _fetch_evm_or_tron(self, h: str) -> Optional[TxDetails]:
        """64 hex hash için akıllı tahmin: TRON veya EVM zincirleri.
        Sıralama: Tron (TRC20 USDT en yaygın Türk kullanımı) → Ethereum → diğer EVM'ler."""
        # 1) Önce TRON dene (Türk kullanıcıları için en olası)
        tron_result = self._fetch_tron(h)
        if tron_result and (
            tron_result.amount is not None
            or tron_result.from_address
            or tron_result.to_address
        ):
            return tron_result

        # 2) EVM zincirlerini sırayla dene
        for chain in ('ethereum', 'bsc', 'polygon', 'arbitrum'):
            result = self._fetch_evm(chain, h)
            if result and (
                result.amount is not None
                or result.from_address
                or result.to_address
            ):
                return result

        return tron_result  # en azından TRON verisini döndür (boş da olsa)

    def detect_chain(self, tx_hash: str) -> str:
        """Hash uzunluğu & formatından zinciri tahmin et.
        Akıllı tahmin: Türk kullanıcıları için 64 hex hash genelde TRON/USDT-TRC20."""
        h = self._normalize_hash(tx_hash)
        if not h:
            return 'unknown'
        if re.fullmatch(r'[0-9a-fA-F]{64}', h):
            # 64 hex: öncelik TRON'da (Türk kullanımı)
            return 'tron'
        if re.fullmatch(r'[0-9a-fA-F]{40}', h):  # adres, tx değil
            return 'unknown'
        if re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{60,70}', h):
            return 'bitcoin'  # base58 - UTXO zincirleri
        return 'unknown'

    # ----------------- UTXO -----------------
    def _fetch_utxo(self, chain: str, tx_hash: str) -> Optional[TxDetails]:
        # Mempool.space Bitcoin için
        if chain == 'bitcoin':
            try:
                r = requests.get(f'https://mempool.space/api/tx/{tx_hash}', timeout=self.timeout)
                if r.status_code == 200:
                    data = r.json() or {}
                    vouts = data.get('vout') or []
                    total_out = sum((v.get('value') or 0) for v in vouts)
                    amount = (Decimal(total_out) / Decimal(100_000_000)) if total_out else None
                    addrs = data.get('vout', [{}])[0].get('scriptpubkey_address') if vouts else None
                    return TxDetails(
                        chain='bitcoin',
                        asset_symbol='BTC',
                        amount=amount,
                        to_address=addrs,
                        confirmed=data.get('status', {}).get('confirmed', False),
                        explorer_url=f"{EXPLORER_URLS['bitcoin']}/{tx_hash}",
                        raw=data,
                    )
            except requests.RequestException as exc:
                logger.warning('BTC mempool error: %s', exc)
            # Blockchair fallback
            try:
                r = requests.get(
                    f'https://api.blockchair.com/bitcoin/dashboards/transaction/{tx_hash}',
                    timeout=self.timeout,
                )
                if r.status_code == 200:
                    payload = r.json().get('data', {}).get(tx_hash, {})
                    outgoing = (payload.get('transaction', {}).get('output_total') or 0) / 1e8
                    explorer = f"{EXPLORER_URLS['bitcoin']}/{tx_hash}"
                    return TxDetails(
                        chain='bitcoin',
                        asset_symbol='BTC',
                        amount=Decimal(str(outgoing)) if outgoing else None,
                        confirmed=True,
                        explorer_url=explorer,
                        raw=payload,
                    )
            except requests.RequestException as exc:
                logger.warning('BTC blockchair error: %s', exc)
            return None

        if chain in ('litecoin', 'dogecoin'):
            try:
                r = requests.get(
                    f'https://api.blockchair.com/{chain}/dashboards/transaction/{tx_hash}',
                    timeout=self.timeout,
                )
                if r.status_code == 200:
                    payload = r.json().get('data', {}).get(tx_hash, {})
                    outgoing = (payload.get('transaction', {}).get('output_total') or 0) / 1e8
                    asset = 'LTC' if chain == 'litecoin' else 'DOGE'
                    return TxDetails(
                        chain=chain,
                        asset_symbol=asset,
                        amount=Decimal(str(outgoing)) if outgoing else None,
                        confirmed=True,
                        explorer_url=f"{EXPLORER_URLS[chain]}/{tx_hash}",
                        raw=payload,
                    )
            except requests.RequestException as exc:
                logger.warning('%s blockchair error: %s', chain, exc)
            return None
        return None

    # ----------------- EVM (Etherscan v2) -----------------
    def _fetch_evm(self, chain: str, tx_hash: str) -> Optional[TxDetails]:
        chain_id = ETHERSCAN_CHAIN_IDS.get(chain, 1)
        params = {
            'chainid': chain_id,
            'module': 'proxy',
            'action': 'eth_getTransactionByHash',
            'txhash': tx_hash,
        }
        if self.etherscan_key:
            params['apikey'] = self.etherscan_key
        try:
            r = requests.get('https://api.etherscan.io/v2/api', params=params, timeout=self.timeout)
            if r.status_code != 200:
                return None
            payload = r.json() or {}
            result = payload.get('result')
            if not isinstance(result, dict):
                return None
            value_wei = int(result.get('value', '0') or 0)
            amount_eth = Decimal(value_wei) / Decimal(10 ** 18)
            symbol = 'ETH' if chain == 'ethereum' else chain.upper()
            return TxDetails(
                chain=chain,
                asset_symbol=symbol,
                amount=amount_eth,
                from_address=result.get('from'),
                to_address=result.get('to'),
                confirmed=bool(result.get('blockNumber')),
                explorer_url=f"{EXPLORER_URLS[chain]}/{tx_hash}",
                raw=result,
            )
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning('Etherscan %s error: %s', chain, exc)
            return None

    # ----------------- Tron / TRC20 -----------------
    def _fetch_tron(self, tx_hash: str) -> Optional[TxDetails]:
        """Tron tx'ini çeker. Önce TRC20 events dene (USDT gibi token transferleri),
        bulamazsan native TRX transferi olarak yorumla."""
        headers = {'TRON-PRO-API-KEY': self.trongrid_key} if self.trongrid_key else {}

        # 1) Önce TRC20 token transferi olarak dene (USDT vb. için)
        trc20 = self._fetch_trc20(tx_hash, headers)
        if trc20 and trc20.amount is not None and trc20.amount > 0:
            return trc20

        # 2) TRC20 bulunamadıysa veya amount 0 döndüyse native TRX kontrolü yap
        try:
            r = requests.post(
                'https://api.trongrid.io/wallet/gettransactionbyid',
                json={'value': tx_hash},
                headers=headers,
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return trc20  # elimizdeki TRC20 sonucu (amount 0 olabilir) döndür
            tx = (r.json() or {}).get('tx') or {}
            raw_data = tx.get('raw_data', {})
            contract = (raw_data.get('contract') or [{}])[0]
            parameter = contract.get('parameter', {}).get('value', {}) or {}
            amount_sun = int(parameter.get('amount', 0) or 0)
            amount_trx = Decimal(amount_sun) / Decimal(10 ** 6)
            owner = parameter.get('owner_address')
            to = parameter.get('to_address')
            contract_type = contract.get('type')

            # Eğer contract_type TransferContract değilse (örn. TriggerSmartContract) ve
            # TRC20 events boş döndüyse, bu bir smart contract çağrısıdır.
            # Bu durumda elimizde TRC20 (amount 0) varsa onu döndürelim.
            if contract_type and contract_type != 'TransferContract':
                if trc20:
                    return trc20
                return TxDetails(
                    chain='tron',
                    asset_symbol='TRX',
                    amount=amount_trx,
                    from_address=self._tron_hex_to_base58(owner) if owner else None,
                    to_address=self._tron_hex_to_base58(to) if to else None,
                    confirmed=bool(tx.get('ret')),
                    explorer_url=f"{EXPLORER_URLS['tron']}/{tx_hash}",
                    raw=tx,
                )

            # Native TRX transferi
            return TxDetails(
                chain='tron',
                asset_symbol='TRX',
                amount=amount_trx,
                from_address=self._tron_hex_to_base58(owner) if owner else None,
                to_address=self._tron_hex_to_base58(to) if to else None,
                confirmed=bool(tx.get('ret')),
                explorer_url=f"{EXPLORER_URLS['tron']}/{tx_hash}",
                raw=tx,
            )
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning('TronGrid error: %s', exc)
            return trc20  # en azından TRC20 sonucunu (varsa) döndür

    def _fetch_trc20(self, tx_hash: str, headers: Dict) -> Optional[TxDetails]:
        """TronGrid events endpoint. Hem eski (token_info/value direkt)
        hem yeni (result.value, result.from, result.to) formatı destekler."""
        try:
            r = requests.get(
                f'https://api.trongrid.io/v1/transactions/{tx_hash}/events',
                headers=headers,
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return None
            events = (r.json() or {}).get('data') or []
            if not events:
                return None

            # Sadece gerçek Transfer eventlerini değerlendir; non-Transfer (örn. Approve)
            # event'lerini atla.
            transfer_events = [
                e for e in events
                if (e.get('event_name') or '').lower() == 'transfer'
            ]
            if not transfer_events:
                return None
            ev = transfer_events[0]

            # Yeni TronGrid formatı: tüm bilgiler result{} içinde; eski formatta direkt alanlardaydı
            result = ev.get('result') or {}
            contract_address = ev.get('contract_address') or ''

            # value: önce result.value (yeni), sonra direkt alan (eski)
            raw_value = result.get('value') if result else ev.get('value')
            from_addr = (result.get('from') if result else ev.get('from')) or ''
            to_addr = (result.get('to') if result else ev.get('to')) or ''

            if raw_value is None or raw_value == '':
                return None

            # token_info yeni API'de yok; decimals'ı sembol/contract'tan çıkar
            symbol, decimals = self._resolve_trc20_meta(ev, contract_address)

            raw_amount = int(raw_value)
            amount = Decimal(raw_amount) / Decimal(10 ** decimals)

            # Hex adresleri (0x...) base58'e çevir (T ile başlayan)
            from_b58 = self._hex_to_tron_base58(from_addr) if from_addr else ''
            to_b58 = self._hex_to_tron_base58(to_addr) if to_addr else ''

            return TxDetails(
                chain='tron',
                asset_symbol=symbol,
                amount=amount,
                from_address=from_b58 or from_addr,
                to_address=to_b58 or to_addr,
                confirmed=True,
                explorer_url=f"{EXPLORER_URLS['tron']}/{tx_hash}",
                raw=ev,
            )
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning('TronGrid TRC20 error: %s', exc)
            return None

    def _resolve_trc20_meta(self, ev: Dict, contract_address: str) -> tuple:
        """TRC20 sembol ve decimals'ı belirle. Bilinen yaygın tokenlar için
        hardcoded tablo kullan, geri kalanı için token_info (eski API) veya
        event adından fallback."""
        # Eski format desteği: token_info direkt event üzerinde
        token_info = ev.get('token_info') or {}
        if token_info:
            sym = (token_info.get('symbol') or '').upper()
            dec = int(token_info.get('decimals') or 6)
            if sym:
                return sym, dec

        # Bilinen yaygın TRC20 tokenlar (sembol -> decimals)
        known = {
            'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t': ('USDT', 6),  # Tether USD
            'TEkxiTehnzSmSe2XqrBj4p32aNm7JjyT8t': ('USDC', 6),
            'TSSMHYeV2uW9oKwHHr5xgo3K9VgrYU2w4w': ('BTT', 18),
            'TKfjV9ApKJUp4Y1dD2Z7Y8m2xQK5M2B8B3': ('WIN', 6),
            'TNUC9Qb1rRpS5CbWLmNMxKSkJ9Rw7Y3aDf': ('NFT', 6),
            'TLBaQaG5RseMrFZCf7B1qz1Hb1xY4qB6qk': ('JST', 18),
            'TCFLL5dx5ZJdKnW9Yzqe2rCnqwfu1t9Gpt': ('SUN', 18),
        }
        if contract_address in known:
            return known[contract_address]

        # Bilinmeyen token: event_name ve contract'tan default
        return 'TRC20', 6

    def _hex_to_tron_base58(self, hex_addr: str) -> str:
        """0x prefix'li (veya prefix'siz) 40-hex (20 byte) tron adresini
        base58'e çevir. Eğer zaten T ile başlıyorsa olduğu gibi döndür."""
        if not hex_addr:
            return ''
        if hex_addr.startswith('T') and len(hex_addr) == 34:
            return hex_addr
        try:
            import hashlib
            h = hex_addr[2:] if hex_addr.startswith('0x') else hex_addr
            # Tron events result'ı 0x + 40 hex (20 byte) döner
            if len(h) != 40:
                return ''
            # Tron address = 0x41 prefix + 20 byte address + 4 byte checksum
            raw = b'\x41' + bytes.fromhex(h)
            checksum = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
            payload = raw + checksum
            alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
            n = int.from_bytes(payload, 'big')
            res = ''
            while n > 0:
                n, rem = divmod(n, 58)
                res = alphabet[rem] + res
            pad = 0
            for byte in payload:
                if byte == 0:
                    pad += 1
                else:
                    break
            return 'T' + ('1' * pad) + res
        except Exception as exc:  # noqa: BLE001
            logger.debug('tron hex->base58 failed: %s', exc)
            return ''

    @staticmethod
    def _tron_hex_to_base58(hex_addr: str) -> Optional[str]:
        """Hex tron adresini base58'e çevirir; base58 ise olduğu gibi döner."""
        if not hex_addr:
            return None
        if hex_addr.startswith('T') and len(hex_addr) == 34:
            return hex_addr
        try:
            import base64
            import hashlib

            if hex_addr.startswith('0x'):
                hex_addr = hex_addr[2:]
            if len(hex_addr) != 42:
                return None
            address_bytes = bytes.fromhex(hex_addr)
            # mainnet prefix 0x41
            raw = b'\x41' + address_bytes
            checksum = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
            payload = raw + checksum
            alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
            n = int.from_bytes(payload, 'big')
            res = ''
            while n > 0:
                n, rem = divmod(n, 58)
                res = alphabet[rem] + res
            pad = 0
            for byte in payload:
                if byte == 0:
                    pad += 1
                else:
                    break
            return 'T' + ('1' * pad) + res
        except Exception as exc:  # noqa: BLE001
            logger.debug('Tron hex->base58 failed: %s', exc)
            return None
