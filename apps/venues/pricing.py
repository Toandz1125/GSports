"""Helpers for the owner field pricing panel.

The project intentionally has no "default price" model. Instead of adding a
migration, the shared default price table lives here as a constant. When a
``Field`` has no custom :class:`~apps.venues.models.FieldPriceRule` covering a
one-hour block, the panel renders the matching default price from this helper.
The owner only persists a ``FieldPriceRule`` when they save a custom price.

Blocks are one hour wide to match the booking slot interval
(see ``apps.bookings.services.BOOKING_SLOT_INTERVAL_MINUTES``) so the pricing
panel and the booking UI stay in sync.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

# One-hour granularity to match the booking slot interval
# (apps.bookings.services.BOOKING_SLOT_INTERVAL_MINUTES = 60).
PRICING_BLOCK_MINUTES = 60
TIME_LABEL_FORMAT = '%H:%M'

PRICING_MODE_DEFAULT = 'default'
PRICING_MODE_MANUAL = 'manual'
PRICING_MODE_CHOICES = (
    (PRICING_MODE_DEFAULT, 'Bảng giá mặc định'),
    (PRICING_MODE_MANUAL, 'Nhập bảng giá thủ công'),
)

# Fallback pricing window when the venue has no operating hours configured.
DEFAULT_PRICING_START = time(6, 0)
DEFAULT_PRICING_END = time(22, 0)

# Shared default price table (per hour) applied when a field has no custom rule
# covering a block. Each entry is ``(start, end, price_per_hour)`` and is treated
# as a half-open range ``[start, end)``.
DEFAULT_FIELD_PRICE_RULES = (
    (time(6, 0), time(17, 0), Decimal('100000')),
    (time(17, 0), time(22, 0), Decimal('150000')),
)
DEFAULT_FIELD_PRICE_PER_HOUR = Decimal('100000')

SOURCE_DEFAULT = 'DEFAULT'
SOURCE_CUSTOM = 'CUSTOM'


def _as_dt(value):
    return datetime.combine(date.min, value)


def _add_minutes(value, minutes):
    return (_as_dt(value) + timedelta(minutes=minutes)).time()


def iter_pricing_blocks(start, end, minutes=PRICING_BLOCK_MINUTES):
    """Yield ``(block_start, block_end)`` tuples across ``[start, end)``."""
    current = _as_dt(start)
    end_dt = _as_dt(end)
    step = timedelta(minutes=minutes)
    while current < end_dt:
        nxt = current + step
        if nxt > end_dt:
            break
        yield current.time(), nxt.time()
        current = nxt


def get_pricing_window(field):
    """Return the ``(start, end)`` window for the pricing table.

    Uses the venue operating hours when available (widest open/close across the
    week), otherwise falls back to ``06:00``-``22:00``.
    """
    venue = getattr(field, 'venue', None)
    opens = []
    closes = []
    if venue is not None:
        for hour in venue.operating_hours.all():
            opens.append(hour.open_time)
            closes.append(hour.close_time)
    start = min(opens) if opens else DEFAULT_PRICING_START
    end = max(closes) if closes else DEFAULT_PRICING_END
    if _as_dt(end) <= _as_dt(start):
        return DEFAULT_PRICING_START, DEFAULT_PRICING_END
    return start, end


def _ceil_to_hour(value):
    """Round a time UP to the next whole hour.

    ``06:00 -> 06:00``, ``05:30 -> 06:00``, ``06:15 -> 07:00``. Returns ``None``
    when no whole-hour start fits before midnight (e.g. ``23:30``).
    """
    if value.minute == 0 and value.second == 0 and value.microsecond == 0:
        return time(value.hour, 0)
    if value.hour >= 23:
        return None
    return time(value.hour + 1, 0)


def get_hourly_pricing_window(field):
    """Pricing window aligned to whole hours, matching the booking slot grid.

    The booking screen books on round one-hour slots (06:00-07:00, ...). To keep
    the pricing panel identical, the window start is rounded UP to the next whole
    hour so a half-hour lead block such as ``05:30-06:30`` is never shown; the
    end is left as-is because ``iter_pricing_blocks`` stops before exceeding it
    (close 22:30 still ends the last block at 22:00).
    """
    raw_start, raw_end = get_pricing_window(field)
    start = _ceil_to_hour(raw_start)
    if start is None or _as_dt(raw_end) <= _as_dt(start):
        # Rounding left no room for a whole-hour block -> safe default window.
        return DEFAULT_PRICING_START, DEFAULT_PRICING_END
    return start, raw_end


def get_default_price_per_hour(block_start):
    """Default per-hour price for a block based on its start time."""
    for start, end, price in DEFAULT_FIELD_PRICE_RULES:
        if start <= block_start < end:
            return price
    return DEFAULT_FIELD_PRICE_PER_HOUR


def get_default_price_rule_payloads():
    """Return default ``FieldPriceRule`` payloads without requiring the model."""
    return [
        {
            'day_of_week': None,
            'start_time': start,
            'end_time': end,
            'price_per_hour': price,
            'start_date': None,
            'end_date': None,
            'priority': index,
            'is_holiday': False,
            'special_event': '',
        }
        for index, (start, end, price) in enumerate(DEFAULT_FIELD_PRICE_RULES)
    ]


def resolve_pricing_payload_rules(pricing_payload):
    """Resolve a stored pricing payload to a list of rule payloads.

    The public payload shape is ``{'mode': 'default'|'manual', 'rules': [...]}``.
    Missing pricing defaults to the shared default price table for backward
    compatibility with older venue requests.
    """
    if pricing_payload in (None, ''):
        return get_default_price_rule_payloads()
    if isinstance(pricing_payload, list):
        return pricing_payload
    if not isinstance(pricing_payload, dict):
        raise ValidationError('Bảng giá không hợp lệ.')

    mode = pricing_payload.get('mode') or PRICING_MODE_DEFAULT
    if mode in {PRICING_MODE_DEFAULT, PRICING_MODE_DEFAULT.upper()}:
        return get_default_price_rule_payloads()
    if mode in {PRICING_MODE_MANUAL, PRICING_MODE_MANUAL.upper()}:
        return pricing_payload.get('rules') or []
    raise ValidationError('Cách nhập bảng giá không hợp lệ.')


def _parse_payload_time(value, field_label):
    if isinstance(value, time):
        return value
    if value in (None, ''):
        raise ValidationError(f'{field_label} không được để trống.')
    for fmt in (TIME_LABEL_FORMAT, '%H:%M:%S'):
        try:
            return datetime.strptime(str(value).strip(), fmt).time()
        except ValueError:
            continue
    raise ValidationError(f'{field_label} không hợp lệ.')


def _parse_optional_payload_date(value, field_label):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if value in (None, ''):
        return None
    try:
        return datetime.strptime(str(value).strip(), '%Y-%m-%d').date()
    except ValueError as exc:
        raise ValidationError(f'{field_label} không hợp lệ.') from exc


def _parse_optional_int(value, field_label, default=None):
    if value in (None, ''):
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f'{field_label} không hợp lệ.') from exc


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if value in (None, ''):
        return False
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def validate_price_rule_payloads(price_rule_payloads):
    """Validate and normalize payloads used to create ``FieldPriceRule`` rows."""
    if not isinstance(price_rule_payloads, list):
        raise ValidationError('Bảng giá phải là danh sách các dòng giá.')
    if not price_rule_payloads:
        raise ValidationError('Vui lòng nhập ít nhất 1 dòng giá hợp lệ.')

    normalized_rules = []
    for index, payload in enumerate(price_rule_payloads, start=1):
        if not isinstance(payload, dict):
            raise ValidationError(f'Dòng giá #{index} không hợp lệ.')

        day_of_week = _parse_optional_int(payload.get('day_of_week'), 'Ngày trong tuần')
        if day_of_week is not None and not 0 <= day_of_week <= 6:
            raise ValidationError(f'Dòng giá #{index}: ngày trong tuần phải từ 0 đến 6.')

        start_time = _parse_payload_time(payload.get('start_time'), 'Giờ bắt đầu')
        end_time = _parse_payload_time(payload.get('end_time'), 'Giờ kết thúc')
        if _as_dt(end_time) <= _as_dt(start_time):
            raise ValidationError(f'Dòng giá #{index}: giờ kết thúc phải sau giờ bắt đầu.')

        try:
            price_per_hour = parse_price(payload.get('price_per_hour'))
        except ValueError as exc:
            raise ValidationError(f'Dòng giá #{index}: {exc}') from exc

        start_date = _parse_optional_payload_date(payload.get('start_date'), 'Ngày bắt đầu')
        end_date = _parse_optional_payload_date(payload.get('end_date'), 'Ngày kết thúc')
        if start_date and end_date and end_date < start_date:
            raise ValidationError(f'Dòng giá #{index}: ngày kết thúc phải sau ngày bắt đầu.')

        priority = _parse_optional_int(payload.get('priority'), 'Độ ưu tiên', default=0)
        special_event = payload.get('special_event')
        if special_event is not None:
            special_event = str(special_event).strip()

        normalized_rules.append({
            'day_of_week': day_of_week,
            'start_time': start_time,
            'end_time': end_time,
            'price_per_hour': price_per_hour,
            'start_date': start_date,
            'end_date': end_date,
            'priority': priority,
            'is_holiday': _parse_bool(payload.get('is_holiday')),
            'special_event': special_event or '',
        })

    return normalized_rules


def _exact_custom_rules(field):
    """Map ``(start_time, end_time) -> rule`` for whole-field (day_of_week NULL).

    Only exact one-hour matches are used so a misaligned legacy rule (e.g.
    ``05:30-06:30`` or a wide ``06:00-17:00`` range) never colours an hourly
    block; the block falls back to the default price instead. If two rules share
    a block, the newest (highest pk) wins.
    """
    exact = {}
    for rule in field.price_rules.all():
        if rule.day_of_week is not None:
            continue
        key = (rule.start_time, rule.end_time)
        current = exact.get(key)
        if current is None or rule.pk > current.pk:
            exact[key] = rule
    return exact


def get_field_pricing_blocks(field, start=None, end=None):
    """Build the pricing-table rows for ``field``.

    Blocks are one hour wide and aligned to whole hours so they match the
    booking slot grid exactly (06:00-07:00, 07:00-08:00, ...). Each row:
    ``start``/``end`` (time), labels, ``value`` (``HH:MM-HH:MM``),
    ``price_per_hour`` (Decimal), ``source`` (``DEFAULT``/``CUSTOM``),
    ``is_custom`` and ``rule_id``.
    """
    if start is None or end is None:
        window_start, window_end = get_hourly_pricing_window(field)
        start = start or window_start
        end = end or window_end

    exact_rules = _exact_custom_rules(field)
    blocks = []
    for block_start, block_end in iter_pricing_blocks(start, end):
        rule = exact_rules.get((block_start, block_end))
        if rule is not None:
            price = rule.price_per_hour
            source = SOURCE_CUSTOM
        else:
            price = get_default_price_per_hour(block_start)
            source = SOURCE_DEFAULT
        start_label = block_start.strftime(TIME_LABEL_FORMAT)
        end_label = block_end.strftime(TIME_LABEL_FORMAT)
        blocks.append({
            'start': block_start,
            'end': block_end,
            'start_label': start_label,
            'end_label': end_label,
            'value': f'{start_label}-{end_label}',
            'price_per_hour': price,
            'source': source,
            'is_custom': source == SOURCE_CUSTOM,
            'rule_id': rule.pk if rule is not None else None,
        })
    return blocks


# Public alias matching the field-manage pricing helper name.
get_hourly_pricing_blocks_for_field = get_field_pricing_blocks


def parse_block_value(value):
    """Parse a ``HH:MM-HH:MM`` block value into ``(start_time, end_time)``.

    Raises ``ValueError`` for malformed input or non-positive ranges.
    """
    if not value or '-' not in value:
        raise ValueError('Khung giờ không hợp lệ.')
    start_raw, end_raw = value.split('-', 1)
    start_time = datetime.strptime(start_raw.strip(), TIME_LABEL_FORMAT).time()
    end_time = datetime.strptime(end_raw.strip(), TIME_LABEL_FORMAT).time()
    if _as_dt(end_time) <= _as_dt(start_time):
        raise ValueError('Giờ kết thúc phải sau giờ bắt đầu.')
    return start_time, end_time


def parse_price(raw):
    """Parse a price string into a non-negative ``Decimal``.

    Raises ``ValueError`` for malformed or negative input.
    """
    if raw is None or str(raw).strip() == '':
        raise ValueError('Vui lòng nhập giá.')
    try:
        price = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        raise ValueError('Giá không hợp lệ.')
    if price < 0:
        raise ValueError('Giá không được âm.')
    return price


def apply_field_prices(field, block_values, price):
    """Create or update ``FieldPriceRule`` rows for the selected blocks.

    Uses ``update_or_create`` keyed on ``(field, day_of_week=None, start, end)``
    so an existing rule for the same block is updated instead of duplicated.
    Returns the number of blocks processed.
    """
    from .models import FieldPriceRule

    processed = 0
    for value in block_values:
        start_time, end_time = parse_block_value(value)
        FieldPriceRule.objects.update_or_create(
            field=field,
            day_of_week=None,
            start_time=start_time,
            end_time=end_time,
            defaults={'price_per_hour': price},
        )
        processed += 1
    return processed
