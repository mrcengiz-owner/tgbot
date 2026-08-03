"""
Kasa uygunluk servisi.

- Saha: `/uygunluk 100 K` → sadece kendi kasasını günceller (onay mesajı).
- Yetkili grup: `/uygunluk` → tüm sahaların kasa listesi + toplam.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

from django.db.models import Sum
from django.utils import timezone

from core.models import TelegramGroup, UygunlukLog

logger = logging.getLogger(__name__)

# /uygunluk veya /uygunluk@BotName  [opsiyonel tutar]
_CMD_RE = re.compile(
    r'^/uygunluk(?:@\w+)?(?:\s+(.+))?$',
    re.IGNORECASE | re.DOTALL,
)

# 100 K | 100K | 1.5 M | 1,5M | 500 | 100.000 | 100,000
_AMOUNT_RE = re.compile(
    r"""
    ^\s*
    (?P<number>
        \d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?   # 100.000 veya 100,000.50
        |
        \d+(?:[.,]\d+)?                       # 100 | 1.5 | 1,5
    )
    \s*
    (?P<suffix>[KkMm])?                       # K / M (opsiyonel)
    \s*$
    """,
    re.VERBOSE,
)

_SUFFIX_MULT = {
    'k': Decimal('1000'),
    'm': Decimal('1000000'),
}


def is_uygunluk_command(text: str) -> bool:
    """Mesaj /uygunluk komutu mu?"""
    if not text:
        return False
    first_line = (text or '').strip().splitlines()[0].strip()
    return bool(_CMD_RE.match(first_line))


def parse_amount(raw: str) -> Optional[Decimal]:
    """
    '100 K' → 100000, '1.5 M' → 1500000, '500' → 500.
    Geçersizse None.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None

    match = _AMOUNT_RE.match(text)
    if not match:
        return None

    number_raw = match.group('number')
    suffix = (match.group('suffix') or '').lower()

    try:
        value = _parse_number(number_raw)
    except (InvalidOperation, ValueError):
        return None

    if suffix:
        value *= _SUFFIX_MULT[suffix]

    if value < 0:
        return None
    if value > Decimal('999999999999'):
        return None

    return value.quantize(Decimal('0.01'))


def _parse_number(raw: str) -> Decimal:
    """Türkçe/uluslararası sayı formatlarını Decimal'e çevir."""
    s = raw.strip()
    if not s:
        raise ValueError('boş sayı')

    if '.' in s and ',' in s:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
    elif '.' in s:
        parts = s.split('.')
        if len(parts) == 2 and len(parts[1]) <= 2 and len(parts[0]) <= 3:
            pass
        elif all(len(p) == 3 for p in parts[1:]):
            s = s.replace('.', '')

    return Decimal(s)


def format_tl(amount: Decimal) -> str:
    """125000 → '125.000' (Türkçe binlik ayırıcı, kuruş yoksa tam sayı)."""
    if amount is None:
        amount = Decimal('0')
    quantized = amount.quantize(Decimal('0.01'))
    if quantized == quantized.to_integral():
        whole = int(quantized)
        return f'{whole:,}'.replace(',', '.')
    sign = '-' if quantized < 0 else ''
    quantized = abs(quantized)
    whole = int(quantized)
    frac = int((quantized - whole) * 100)
    return f'{sign}{whole:,}'.replace(',', '.') + f',{frac:02d}'


class UygunlukService:
    """Kasa uygunluk güncelleme ve yetkili listeleme."""

    def handle(
        self,
        text: str,
        chat_id: str,
        chat_title: str = '',
        user_id: Optional[int] = None,
        username: str = '',
    ) -> Tuple[str, str]:
        """
        Returns:
            (reply_html, action_label)
            action_label: 'uygunluk_set' | 'uygunluk_list' | 'uygunluk_denied' | 'uygunluk_error'
        """
        first_line = (text or '').strip().splitlines()[0].strip()
        match = _CMD_RE.match(first_line)
        if not match:
            return self._error('Geçersiz /uygunluk komutu.'), 'uygunluk_error'

        amount_raw = (match.group(1) or '').strip()
        group = self._get_group(str(chat_id))

        # --- Liste isteği: yalnız yetkili grup ---
        if not amount_raw:
            if group is None:
                return (
                    self._error(
                        f'Bu grup panelde kayıtlı değil (chat_id: <code>{_escape(str(chat_id))}</code>).'
                    ),
                    'uygunluk_error',
                )
            if not group.uygunluk_yetkili:
                return (
                    self._error(
                        'Tüm sahaların listesini yalnızca <b>yetkili grup</b> görebilir.\n'
                        'Kasanızı güncellemek için: <code>/uygunluk 100 K</code>'
                    ),
                    'uygunluk_denied',
                )
            return self.format_list(), 'uygunluk_list'

        # --- Tutar yazma: saha kendi kasasını günceller (liste YOK) ---
        amount = parse_amount(amount_raw)
        if amount is None:
            return (
                self._error(
                    f'Geçersiz tutar: <code>{_escape(amount_raw)}</code>\n'
                    f'Örnek: <code>/uygunluk 100 K</code> veya <code>/uygunluk 1.5 M</code>'
                ),
                'uygunluk_error',
            )

        result = self._set_group_amount(
            group=group,
            chat_id=str(chat_id),
            chat_title=chat_title or '',
            amount=amount,
            raw_text=first_line[:255],
            user_id=user_id,
            username=username or '',
        )
        if isinstance(result, str):
            return self._error(result), 'uygunluk_error'

        updated_group = result
        return self._format_set_confirm(updated_group, amount), 'uygunluk_set'

    def _get_group(self, chat_id: str) -> Optional[TelegramGroup]:
        try:
            return TelegramGroup.objects.get(chat_id=str(chat_id))
        except TelegramGroup.DoesNotExist:
            return None

    def _set_group_amount(
        self,
        group: Optional[TelegramGroup],
        chat_id: str,
        chat_title: str,
        amount: Decimal,
        raw_text: str,
        user_id: Optional[int],
        username: str,
    ):
        """Grubun kasa tutarını güncelle. Hata str veya güncellenmiş TelegramGroup."""
        if group is None:
            return (
                f'Bu grup panelde kayıtlı değil (chat_id: <code>{_escape(str(chat_id))}</code>).\n'
                f'Önce web panelden grubu ekleyin.'
            )

        if not group.is_active:
            return 'Bu grup panelde pasif durumda. Önce aktifleştirin.'

        if chat_title and group.name != chat_title:
            group.name = chat_title[:255]

        previous = group.kasa_uygunluk or Decimal('0')
        group.kasa_uygunluk = amount
        group.kasa_updated_at = timezone.now()
        group.save(update_fields=['name', 'kasa_uygunluk', 'kasa_updated_at', 'updated_at'])

        UygunlukLog.objects.create(
            group=group,
            previous_amount=previous,
            new_amount=amount,
            raw_text=raw_text,
            user_id=user_id,
            username=username or '',
        )
        logger.info(
            'Uygunluk güncellendi: %s (%s) %s → %s',
            group.name, chat_id, previous, amount,
        )
        return group

    def _format_set_confirm(self, group: TelegramGroup, amount: Decimal) -> str:
        """Saha için kurumsal onay mesajı — tüm liste yok."""
        return (
            '🟢 <b>Uygunluk alındı.</b>\n'
            'Uygun çekim oluşması durumunda tarafınıza yönlendirilecektir. '
            'Paneli kontrolde tutalım.\n'
            '\n'
            '— <b>Mobilonay</b>\n'
            'İyi çalışmalar.'
        )

    def format_list(self) -> str:
        """Tüm aktif sahaların (yetkili hariç) kasa listesi + toplam (HTML)."""
        groups = list(
            TelegramGroup.objects.filter(
                is_active=True,
                uygunluk_yetkili=False,
            ).order_by('name')
        )
        if not groups:
            return (
                '<b>📊 Kasa Uygunluk</b>\n\n'
                '<i>Aktif saha bulunamadı.</i>'
            )

        name_width = max(len(g.name) for g in groups)
        name_width = min(max(name_width, 8), 28)

        lines = ['<b>📊 Kasa Uygunluk</b>', '', '<pre>']
        header_name = 'Grup'.ljust(name_width)
        lines.append(f'{header_name}  Kasa')
        lines.append(f'{"─" * name_width}  {"─" * 12}')

        total = Decimal('0')
        for g in groups:
            amount = g.kasa_uygunluk or Decimal('0')
            total += amount
            name = (g.name[: name_width - 1] + '…') if len(g.name) > name_width else g.name
            name_pad = name.ljust(name_width)
            amt = format_tl(amount).rjust(12)
            lines.append(f'{name_pad}  {amt}')

        lines.append(f'{"─" * name_width}  {"─" * 12}')
        total_label = 'TOPLAM'.ljust(name_width)
        lines.append(f'{total_label}  {format_tl(total).rjust(12)}')
        lines.append('</pre>')

        return '\n'.join(lines)

    def total_uygunluk(self) -> Decimal:
        result = TelegramGroup.objects.filter(
            is_active=True,
            uygunluk_yetkili=False,
        ).aggregate(total=Sum('kasa_uygunluk'))
        return result['total'] or Decimal('0')

    @staticmethod
    def _error(msg: str) -> str:
        return f'<b>⚠️ Uygunluk</b>\n\n{msg}'


def _escape(text: str) -> str:
    return (
        (text or '')
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )
