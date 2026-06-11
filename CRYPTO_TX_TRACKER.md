# Kripto TX Takip Modülü

Telegram gruplarında paylaşılan transaction id'leri otomatik algılayıp, blockchain
doğrulaması yapıp, Türkiye borsalarından (BTCTurk, Paribu, Bitturk, Cointr) ve
uluslararası borsalardan (CoinGecko, Binance) anlık TL kuru çekip detaylı
biçimlendirilmiş mesaj olarak gruba yansıtır.

## Davranış

- Bir kayıtlı Telegram grubunda kullanıcı bir mesaj yazdığında bot, mesajdaki
  64 haneli hex (EVM / TRX) veya 60+ base58 (BTC/LTC/DOGE) tx hash'ini tespit eder.
- Tx geçerliyse ilgili explorer'dan miktar, gönderici ve alıcı adres çekilir.
- Varlık sembolü (USDT, BTC vb.) için sırasıyla BTCTurk → Paribu → Bitturk →
  Cointr → CoinGecko → Binance (USDT üzerinden) anlık TL kuru alınır. Ortalama
  ve medyan hesaplanır. 30 saniyelik cache uygulanır.
- Sonuç aşağıdaki formatta gruba yanıt olarak gönderilir:

```
🪙 Kripto İşlem Detayı

💎 Varlık: USDT
🔢 Miktar: 6 423
💱 Anlık Kur (BTCTURK): 46.11 ₺
🇹🇷 TL Karşılığı: 296 164.53 ₺

🌐 Ağ: TRON
📤 Gönderen: TAbc…Xyz
📥 Alan: TDef…Uvw

🆔 Tx:
fa76f4164b018e7f377f9612687d09ae21f7a7e34f9bb951bfae3d0255b2a503
🔎 Explorer'da Gör

🤖 Otomatik algılandı · ⏱ 1.4s
```

## Hangi Gruplar Aktif?

- Her grup için `tx_tracker_enabled` alanı vardır (varsayılan: kapalı).
- Web panelde **Gruplar** sayfasındaki kartlarda "TX Takibi Aç/Kapat" butonu
  veya **Kripto Takip** menüsü altındaki tablodan tek tek açılabilir.
- Yeni grup eklenirken modal içinde "Kripto TX takibini aktifleştir" checkbox'ı
  işaretlenirse grup otomatik aktif gelir.

## Kapsam

| Ağ       | Explorer Kaynağı               | Token Desteği                |
|----------|--------------------------------|------------------------------|
| BTC      | mempool.space / blockchair     | native BTC                   |
| LTC      | blockchair                     | native LTC                   |
| DOGE     | blockchair                     | native DOGE                  |
| ETH      | Etherscan v2                   | native ETH                   |
| BSC      | Etherscan v2 (chainid=56)      | native BNB                   |
| Polygon  | Etherscan v2 (chainid=137)     | native MATIC                 |
| Arbitrum | Etherscan v2 (chainid=42161)   | native ETH                   |
| TRX/TRC20| TronGrid v1                    | TRX, USDT, TRC20 tokenlar    |

> Ücretsiz Etherscan v2 tier 3 istek/saniye, TronGrid ücretsiz 15 QPS ile sınırlıdır.
> Daha yüksek hacim gerekirse `ETHERSCAN_API_KEY` ve `TRONGRID_API_KEY` env değişkenlerini
> doldurun.

## Ortam Değişkenleri

```
ETHERSCAN_API_KEY=...     # opsiyonel - Etherscan v2 ücretsiz anahtar
TRONGRID_API_KEY=...      # opsiyonel - TronGrid ücretsiz anahtar
```

## Kurulum (Coolify / lokal)

```bash
# 1) Yeni modeli uygula
python manage.py migrate

# 2) Webhook'u kur (Coolify HTTPS'i otomatik sağlar)
# Tarayıcıdan: https://<domain>/webhook/set/

# 3) (Opsiyonel) Bir gruba botu admin olarak ekle
# 4) Admin panelden veya Gruplar sayfasından tx_tracker_enabled=True yap
```

## Test

```bash
python manage.py test core.tests
```

## Dosya Haritası

- `core/models.py` — `TxTracker`, `TxRateCache` + `TelegramGroup.tx_tracker_enabled`
- `core/services/rate_service.py` — 5 farklı borsa (BTCTurk, Paribu, Bitturk,
  Cointr, Binance) + CoinGecko public ticker + 30s cache
- `core/services/explorer_service.py` — Çoklu zincir explorer entegrasyonu
- `core/services/tx_service.py` — Orkestrasyon, regex, formatlama
- `webhook_bot.py` — Telegram webhook handler'ı tx'leri yakalar
- `core/views.py` — `/kripto/` dashboard + manuel sorgu
- `templates/core/tx_tracker.html` — Web paneldeki kripto takip sayfası
- `core/admin.py` — Django admin entegrasyonu
- `core/migrations/0003_txcrypto_tracker.py` — Veritabanı şeması
