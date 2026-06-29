import json
import uuid
import redis
from datetime import date as date_class, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError, ImproperlyConfigured
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from apps.venues.models import Field, FieldPriceRule, VenueOperatingHour
from .models import Booking, BookingPackage, BookingSlot, SlotLock
from .validators import validate_booking_time_range


MONEY_QUANTIZER = Decimal('0.01')
DEFAULT_OPEN_TIME = time(5, 30)
DEFAULT_CLOSE_TIME = time(23, 30)
TIME_BLOCK_FORMAT = '%H:%M'
TIME_BLOCK_INTERVAL_MINUTES = 30
BOOKING_UNAVAILABLE_ERROR = (
    'Khung giờ đã chọn có thời gian đã được đặt. Vui lòng chọn khung giờ khác.'
)
BOOKING_PRICE_RULE_MISSING_ERROR = (
    'Không tìm thấy bảng giá phù hợp cho sân và khung giờ đã chọn.'
)
SLOT_CONFLICT_ERROR = 'SLOT_CONFLICT'


def get_redis_client():
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.exceptions.ConnectionError as e:
        raise ImproperlyConfigured(
            f"Unable to connect to Redis at {settings.REDIS_URL}. "
            "Please ensure the Redis server is running, as it is required for booking slot locks."
        ) from e
    return client


def is_time_overlap(start_1, end_1, start_2, end_2):
    return start_1 < end_2 and start_2 < end_1


def _time_to_datetime(value):
    return datetime.combine(date_class.min, value)


def _add_minutes(value, minutes):
    return (_time_to_datetime(value) + timedelta(minutes=minutes)).time()


def _format_time(value):
    return value.strftime(TIME_BLOCK_FORMAT)


def _resolve_operating_hours(field, booking_date):
    if not field or not booking_date:
        return None, None

    operating_hour = VenueOperatingHour.objects.filter(
        venue=field.venue,
        weekday=booking_date.weekday(),
    ).first()
    if not operating_hour:
        return None, None
    return operating_hour.open_time, operating_hour.close_time


def generate_time_blocks(start_time, end_time, block_minutes=30):
    """
    Slices a time range into blocks of `block_minutes`.
    Used for Redis locking. Example: 06:00 to 08:00 returns ["06:00", "06:30", "07:00", "07:30"].
    """
    if block_minutes <= 0:
        raise ValueError('block_minutes must be greater than 0.')

    start_dt = _time_to_datetime(start_time)
    end_dt = _time_to_datetime(end_time)

    if end_dt <= start_dt:
        raise ValidationError('End time must be greater than start time.')

    # Validate align
    if start_dt.minute % block_minutes != 0 or end_dt.minute % block_minutes != 0:
        raise ValidationError(f'Time must align with {block_minutes}-minute blocks.')

    blocks = []
    current = start_dt
    while current < end_dt:
        blocks.append(current.strftime(TIME_BLOCK_FORMAT))
        current += timedelta(minutes=block_minutes)
    return blocks


def get_time_blocks_for_field_date(field, booking_date):
    open_time, close_time = _resolve_operating_hours(field, booking_date)
    start_time = open_time if open_time and close_time else DEFAULT_OPEN_TIME
    end_time = close_time if open_time and close_time else DEFAULT_CLOSE_TIME
    start_dt = _time_to_datetime(start_time)
    end_dt = _time_to_datetime(end_time)

    if end_dt < start_dt:
        start_dt = _time_to_datetime(DEFAULT_OPEN_TIME)
        end_dt = _time_to_datetime(DEFAULT_CLOSE_TIME)

    blocks = []
    current = start_dt
    while current <= end_dt:
        blocks.append(current.strftime(TIME_BLOCK_FORMAT))
        current += timedelta(minutes=TIME_BLOCK_INTERVAL_MINUTES)
    return blocks


def check_booking_slot_conflict(field, booking_date, start_time, end_time):
    """
    Check database BookingSlot overlap.
    """
    overlapping_slots = BookingSlot.objects.filter(
        booking__field=field,
        booking__booking_date=booking_date,
        start_time__lt=end_time,
        end_time__gt=start_time,
        booking__status__in=[Booking.PENDING, Booking.PAID, Booking.WAITING]
    )
    return overlapping_slots.exists()


def get_bookable_fields_queryset():
    return Field.objects.select_related(
        'venue',
        'field_type',
        'field_type__sport',
    ).filter(
        status='ACTIVE',
        venue__status='ACTIVE',
        venue__is_deleted=False,
    )


def find_applicable_price_rule(field, booking_date, start_time, end_time):
    if not field or not booking_date or not start_time or not end_time:
        return None

    booking_day = booking_date.weekday()
    exact_day_first = Case(
        When(day_of_week=booking_day, then=Value(0)),
        default=Value(1),
        output_field=IntegerField(),
    )
    return (
        FieldPriceRule.objects.filter(
            field=field,
            start_time__lte=start_time,
            end_time__gte=end_time,
        )
        .filter(
            Q(day_of_week=booking_day) | Q(day_of_week__isnull=True),
            Q(start_date__isnull=True) | Q(start_date__lte=booking_date),
            Q(end_date__isnull=True) | Q(end_date__gte=booking_date),
        )
        .annotate(day_match_rank=exact_day_first)
        .order_by('day_match_rank', '-priority', '-pk')
        .first()
    )


def calculate_booking_price(field, booking_date, start_time, end_time):
    start_dt = datetime.combine(date_class.min, start_time)
    end_dt = datetime.combine(date_class.min, end_time)
    minutes = Decimal(str((end_dt - start_dt).total_seconds() / 60))
    if minutes <= 0:
        raise ValidationError('Thời gian kết thúc phải sau thời gian bắt đầu.')

    rule = find_applicable_price_rule(field, booking_date, start_time, end_time)
    if not rule:
        raise ValidationError(BOOKING_PRICE_RULE_MISSING_ERROR)

    price = (rule.price_per_hour * (minutes / Decimal('60'))).quantize(
        MONEY_QUANTIZER,
        rounding=ROUND_HALF_UP,
    )
    return price, rule


def get_unavailable_time_blocks(field, booking_date, time_blocks=None):
    if not field or not booking_date:
        return []

    blocks = time_blocks or get_time_blocks_for_field_date(field, booking_date)
    
    # 1. Check DB booked slots
    booked_slots = list(
        BookingSlot.objects.filter(
            booking__field=field,
            booking__booking_date=booking_date,
            booking__status__in=[Booking.PENDING, Booking.PAID, Booking.WAITING]
        )
    )

    # 2. Check Redis locked blocks
    redis_client = get_redis_client()
    pattern = f"booking_lock:field:{field.pk}:date:{booking_date.isoformat()}:block:*"
    locked_keys = redis_client.keys(pattern)
    locked_block_times = set()
    for key in locked_keys:
        # Extract HH:MM from key
        # booking_lock:field:5:date:2026-05-29:block:07:30
        block_time = key.split(':block:')[-1]
        locked_block_times.add(block_time)

    unavailable_blocks = []
    for block in blocks:
        block_start = datetime.strptime(block, TIME_BLOCK_FORMAT).time()
        block_end = _add_minutes(block_start, TIME_BLOCK_INTERVAL_MINUTES)

        is_booked = any(
            is_time_overlap(slot.start_time, slot.end_time, block_start, block_end)
            for slot in booked_slots
        )
        is_locked = block in locked_block_times

        if is_booked or is_locked:
            unavailable_blocks.append(block)

    return unavailable_blocks


def is_time_range_available(field, booking_date, start_time, end_time):
    if check_booking_slot_conflict(field, booking_date, start_time, end_time):
        return False
        
    try:
        blocks = generate_time_blocks(start_time, end_time, TIME_BLOCK_INTERVAL_MINUTES)
    except ValidationError:
        return False

    redis_client = get_redis_client()
    for block in blocks:
        key = f"booking_lock:field:{field.pk}:date:{booking_date.isoformat()}:block:{block}"
        if redis_client.exists(key):
            return False
    return True


def acquire_slot_lock(user, field, booking_date, start_time, end_time):
    """
    Acquire Redis locks for 30-min blocks.
    """
    validate_booking_time_range(start_time, end_time)

    if check_booking_slot_conflict(field, booking_date, start_time, end_time):
        raise ValidationError(SLOT_CONFLICT_ERROR)

    blocks = generate_time_blocks(start_time, end_time, TIME_BLOCK_INTERVAL_MINUTES)
    redis_client = get_redis_client()
    lock_session_id = str(uuid.uuid4())
    lock_duration = 600  # 10 minutes

    acquired_keys = []
    
    for block in blocks:
        key = f"booking_lock:field:{field.pk}:date:{booking_date.isoformat()}:block:{block}"
        value = json.dumps({
            'user_id': user.pk,
            'lock_session_id': lock_session_id,
            'field_id': field.pk,
            'booking_date': booking_date.isoformat(),
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'created_at': timezone.now().isoformat()
        })
        
        acquired = redis_client.set(key, value, nx=True, ex=lock_duration)
        if not acquired:
            # Rollback
            if acquired_keys:
                redis_client.delete(*acquired_keys)
            raise ValidationError(SLOT_CONFLICT_ERROR)
        acquired_keys.append(key)

    # Store the keys associated with this session for easy release
    session_key = f"lock_session:{lock_session_id}:keys"
    redis_client.sadd(session_key, *acquired_keys)
    redis_client.expire(session_key, lock_duration)

    expires_at = timezone.now() + timedelta(seconds=lock_duration)
    return lock_session_id, expires_at


def release_slot_lock(lock_session_id):
    """
    Release Redis locks for a given session.
    """
    redis_client = get_redis_client()
    session_key = f"lock_session:{lock_session_id}:keys"
    
    keys = redis_client.smembers(session_key)
    if keys:
        redis_client.delete(*keys)
    redis_client.delete(session_key)


@transaction.atomic
def confirm_booking_from_lock(
    user,
    lock_session_id,
    field,
    booking_date,
    start_time,
    end_time,
    price,
    note='',
    service_quantities=None,
):
    """
    Confirm booking from a valid lock.
    """
    redis_client = get_redis_client()
    session_key = f"lock_session:{lock_session_id}:keys"
    keys = redis_client.smembers(session_key)
    
    if not keys:
        raise ValidationError('Khung giờ giữ chỗ đã hết hạn hoặc không tồn tại. Vui lòng chọn lại.')
    
    # Re-check DB conflicts within transaction
    field = Field.objects.select_related('venue').select_for_update().get(pk=field.pk)
    
    if check_booking_slot_conflict(field, booking_date, start_time, end_time):
        release_slot_lock(lock_session_id)
        raise ValidationError(SLOT_CONFLICT_ERROR)

    price = Decimal(str(price)).quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)

    package = BookingPackage(
        user=user,
        package_type=BookingPackage.SINGLE,
        start_date=booking_date,
    )
    package.full_clean()
    package.save()

    booking = Booking(
        booking_package=package,
        venue=field.venue,
        field=field,
        booking_date=booking_date,
        status=Booking.PENDING,
        booking_channel=Booking.WEB,
        total_amount=price,
        note=note or '',
    )
    booking.full_clean()
    booking.save()

    slot = BookingSlot(
        booking=booking,
        start_time=start_time,
        end_time=end_time,
        price=price,
    )
    slot.full_clean()
    slot.save()

    if service_quantities:
        from apps.services.services import add_services_to_booking
        add_services_to_booking(booking, service_quantities)

    # Release lock
    release_slot_lock(lock_session_id)

    return booking


# Keep create_booking to not break other things, but make it use the new flow
@transaction.atomic
def create_booking(user, field, booking_date, start_time, end_time, price, note='', service_quantities=None):
    lock_session_id, _ = acquire_slot_lock(user, field, booking_date, start_time, end_time)
    try:
        return confirm_booking_from_lock(
            user,
            lock_session_id,
            field,
            booking_date,
            start_time,
            end_time,
            price,
            note,
            service_quantities=service_quantities,
        )
    except Exception:
        release_slot_lock(lock_session_id)
        raise


def lock_slot(user, field, booking_date, start_time, end_time, created_by=None, minutes=15):
    # Fallback to old behavior if something still calls this?
    # Or just raise NotImplementedError
    pass

def expire_old_locks():
    pass
