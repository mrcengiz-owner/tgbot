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
        """Tx hash'i tanır ve ilgili zincirden detayları çeker."""
        chain = hint_chain or self.detect_chain(tx_hash)
        if chain == 'unknown' or not chain:
            return None

        if chain in ('bitcoin', 'litecoin', 'dogecoin'):
            return self._fetch_utxo(chain, tx_hash)
        if chain in ('ethereum', 'bsc', 'polygon', 'arbitrum'):
            return self._fetch_evm(chain, tx_hash)
        if chain == 'tron':
            return self._fetch_tron(tx_hash)
        return None

    def detect_chain(self, tx_hash: str) -> str:
        """Hash uzunluğu & formatından zinciri tahmin et."""
        h = (tx_hash or '').strip()
        if not h:
            return 'unknown'
        if re.fullmatch(r'[0-9a-fA-F]{64}', h):
            # 64 hex: ETH/EVM/TRX hepsi için ortak; TRC20 token transferini tercih et
            # (Türk kullanıcıları için USDT gönderimleri TRC20 çoğunlukta)
            return 'tron' if self._looks_like_tron_tx(h) else 'ethereum'
        if re.fullmatch(r'[0-9a-fA-F]{40}', h):  # adres, tx değil
            return 'unknown'
        if re.fullmatch(r'[0-9a-fA-F]{64}', h):
            return 'bitcoin'
        # BTC/LTC/DOGE genelde base58
        if re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{60,70}', h):
            # Ayırt etmek zor; önce mempool'a BTC olarak sor, başarısız olursa LTC/DOGE dene
            return 'bitcoin'
        return 'unknown'

    def _looks_like_tron_tx(self, h: str) -> bool:
        """Tron tx hash genelde 64 hex; ama ETH ile aynı formatta.
        Belirgin bir ayrım yok; default olarak Ethereum varsayalım (Etherscan tüm EVM'i kapsar)."""
        return False

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
        headers = {'TRON-PRO-API-KEY': self.trongrid_key} if self.trongrid_key else {}
        try:
            r = requests.post(
                'https://api.trongrid.io/wallet/gettransactionbyid',
                json={'value': tx_hash},
                headers=headers,
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return None
            tx = (r.json() or {}).get('tx') or {}
            raw_data = tx.get('raw_data', {})
            contract = (raw_data.get('contract') or [{}])[0]
            parameter = contract.get('parameter', {}).get('value', {}) or {}
            amount_sun = int(parameter.get('amount', 0) or 0)
            amount_trx = Decimal(amount_sun) / Decimal(10 ** 6)
            owner = parameter.get('owner_address')
            to = parameter.get('to_address')
            # TRX native mi yoksa TRC20 mi? TRC20 ise token transfer ayrı endpoint gerekir
            contract_type = contract.get('type')
            if contract_type and contract_type != 'TransferContract':
                return self._fetch_trc20(tx_hash, headers)
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
            return None

    def _fetch_trc20(self, tx_hash: str, headers: Dict) -> Optional[TxDetails]:
        try:
            r = requests.get(
                f'https://api.trongrid.io/v1/transactions/{tx_hash}/events',
                headers=headers,
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return None
            data = (r.json() or {}).get('data') or []
            if not data:
                return None
            ev = data[0]
            token_info = ev.get('token_info', {}) or {}
            symbol = (token_info.get('symbol') or 'USDT').upper()
            decimals = int(token_info.get('decimals') or 6)
            raw_amount = int(ev.get('value') or 0)
            amount = Decimal(raw_amount) / Decimal(10 ** decimals)
            return TxDetails(
                chain='tron',
                asset_symbol=symbol,
                amount=amount,
                from_address=ev.get('from'),
                to_address=ev.get('to'),
                confirmed=bool(ev.get('confirmed')),
                explorer_url=f"{EXPLORER_URLS['tron']}/{tx_hash}",
                raw=ev,
            )
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning('TronGrid TRC20 error: %s', exc)
            return None

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
