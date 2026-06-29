"""Helpers for the owner field pricing panel.

The project intentionally has no "default price" model. Instead of adding a
migration, the shared default price table lives here as a constant. When a
``Field`` has no custom :class:`~apps.venues.models.FieldPriceRule` covering a
30-minute block, the panel renders the matching default price from this helper.
The owner only persists a ``FieldPriceRule`` when they save a custom price.

This reuses the system-wide 30-minute time-block convention used by the booking
flow (see ``apps.bookings.services.TIME_BLOCK_INTERVAL_MINUTES``).
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from .models import FieldPriceRule

# Same 30-minute granularity used by the booking time blocks.
PRICING_BLOCK_MINUTES = 30
TIME_LABEL_FORMAT = '%H:%M'

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


def get_default_price_per_hour(block_start):
    """Default per-hour price for a block based on its start time."""
    for start, end, price in DEFAULT_FIELD_PRICE_RULES:
        if start <= block_start < end:
            return price
    return DEFAULT_FIELD_PRICE_PER_HOUR


def _find_custom_rule(rules, block_start, block_end):
    """Most specific custom rule (day_of_week NULL) covering the block."""
    matches = [
        rule
        for rule in rules
        if rule.day_of_week is None
        and rule.start_time <= block_start
        and rule.end_time >= block_end
    ]
    if not matches:
        return None
    # Prefer the tightest range, then highest priority, then newest.
    matches.sort(key=lambda r: (
        _as_dt(r.end_time) - _as_dt(r.start_time),
        -r.priority,
        -r.pk,
    ))
    return matches[0]


def get_field_pricing_blocks(field, start=None, end=None):
    """Build the pricing-table rows for ``field``.

    Each row: ``start``/``end`` (time), labels, ``value`` (``HH:MM-HH:MM``),
    ``price_per_hour`` (Decimal), ``source`` (``DEFAULT``/``CUSTOM``),
    ``is_custom`` and ``rule_id``.
    """
    if start is None or end is None:
        window_start, window_end = get_pricing_window(field)
        start = start or window_start
        end = end or window_end

    rules = [rule for rule in field.price_rules.all() if rule.day_of_week is None]
    blocks = []
    for block_start, block_end in iter_pricing_blocks(start, end):
        rule = _find_custom_rule(rules, block_start, block_end)
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
