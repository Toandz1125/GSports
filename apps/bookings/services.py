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
# Pending bookings hold their slots for this long before being auto-cancelled.
# This is purely a booking-side hold; it does not touch the payments module.
BOOKING_PAYMENT_TIMEOUT_MINUTES = Booking.PAYMENT_TIMEOUT_MINUTES
TIME_BLOCK_FORMAT = '%H:%M'
# Internal lock granularity stays at 30 minutes because existing Redis keys and
# validators are built around :00/:30 boundaries.
TIME_BLOCK_INTERVAL_MINUTES = 30
BOOKING_SLOT_INTERVAL_MINUTES = 60
BOOKING_NO_SLOT_SELECTED_ERROR = 'Vui lòng chọn ít nhất một khung giờ.'
BOOKING_INVALID_SLOT_ERROR = 'Khung giờ đã chọn không hợp lệ.'
BOOKING_UNAVAILABLE_ERROR = (
    'Khung giờ đã chọn có thời gian đã được đặt. Vui lòng chọn khung giờ khác.'
)
BOOKING_PRICE_RULE_MISSING_ERROR = (
    'Không tìm thấy bảng giá phù hợp cho sân và khung giờ đã chọn.'
)
BOOKING_PAST_SLOT_ERROR = 'Không thể đặt khung giờ trong quá khứ.'
BOOKING_FIELD_UNAVAILABLE_ERROR = 'Sân hoặc cơ sở hiện không khả dụng để đặt.'
SLOT_CONFLICT_ERROR = 'SLOT_CONFLICT'

ACTIVE_BOOKING_STATUSES = (Booking.PENDING, Booking.PAID, Booking.WAITING)
SLOT_STATUS_AVAILABLE = 'AVAILABLE'
SLOT_STATUS_BOOKED = 'BOOKED'
SLOT_STATUS_LOCKED = 'LOCKED'
SLOT_STATUS_PAST = 'PAST'
SLOT_STATUS_NO_PRICE = 'NO_PRICE'


def get_redis_client():
    redis_url = getattr(settings, 'REDIS_URL', None)
    if not redis_url:
        raise ImproperlyConfigured(
            'REDIS_URL is not configured. Redis slot locks will be skipped; '
            'database transaction validation is still required before creating bookings.'
        )
    client = redis.from_url(redis_url, decode_responses=True)
    try:
        client.ping()
    except redis.exceptions.ConnectionError as e:
        raise ImproperlyConfigured(
            f"Unable to connect to Redis at {redis_url}. "
            "Please ensure the Redis server is running, as it is required for booking slot locks."
        ) from e
    return client


def _get_redis_client_or_none():
    try:
        return get_redis_client()
    except (ImproperlyConfigured, redis.exceptions.RedisError):
        return None


def get_payment_deadline(now=None):
    """Return the payment hold deadline for a freshly created pending booking."""
    now = now or timezone.now()
    return now + timedelta(minutes=BOOKING_PAYMENT_TIMEOUT_MINUTES)


def cancel_expired_pending_bookings(now=None):
    """Cancel every PENDING booking whose payment hold has expired.

    Slots of CANCELLED bookings are excluded from ``ACTIVE_BOOKING_STATUSES`` so
    they become free again automatically. Booking-only; never touches payments.
    Returns the number of bookings cancelled.
    """
    now = now or timezone.now()
    SlotLock.objects.filter(
        status=SlotLock.ACTIVE,
        expires_at__lte=now,
    ).update(status=SlotLock.EXPIRED)

    legacy_deadline_cutoff = now - timedelta(minutes=BOOKING_PAYMENT_TIMEOUT_MINUTES)
    expired_by_deadline = Q(
        payment_deadline__isnull=False,
        payment_deadline__lte=now,
    )
    expired_legacy_null_deadline = Q(
        payment_deadline__isnull=True,
        created_at__lte=legacy_deadline_cutoff,
    )
    expired_ids = list(
        Booking.objects.filter(
            status=Booking.PENDING,
        ).filter(
            expired_by_deadline | expired_legacy_null_deadline,
        ).values_list('pk', flat=True)
    )
    if not expired_ids:
        return 0
    return Booking.objects.filter(pk__in=expired_ids).update(
        status=Booking.CANCELLED,
        updated_at=now,
    )


def cancel_expired_booking_if_needed(booking, now=None):
    """Cancel a single booking if it is a PENDING booking past its deadline.

    Returns True when the booking was just cancelled, False otherwise.
    """
    if booking is None:
        return False
    now = now or timezone.now()
    deadline = booking.get_effective_payment_deadline()
    if (
        booking.status == Booking.PENDING
        and deadline
        and deadline <= now
    ):
        booking.status = Booking.CANCELLED
        booking.save(update_fields=['status', 'updated_at'])
        return True
    return False


def is_time_overlap(start_1, end_1, start_2, end_2):
    return start_1 < end_2 and start_2 < end_1


def _time_to_datetime(value):
    return datetime.combine(date_class.min, value)


def _add_minutes(value, minutes):
    return (_time_to_datetime(value) + timedelta(minutes=minutes)).time()


def _format_time(value):
    return value.strftime(TIME_BLOCK_FORMAT)


def get_booking_start_datetime(booking_date, start_time):
    if not booking_date or not start_time:
        return None
    naive_value = datetime.combine(booking_date, start_time)
    return timezone.make_aware(naive_value, timezone.get_current_timezone())


def is_booking_time_in_past(booking_date, start_time):
    start_at = get_booking_start_datetime(booking_date, start_time)
    return bool(start_at and start_at <= timezone.now())


def validate_booking_not_in_past(booking_date, start_time):
    if is_booking_time_in_past(booking_date, start_time):
        raise ValidationError(BOOKING_PAST_SLOT_ERROR)


def validate_bookable_field(field):
    if not field:
        raise ValidationError(BOOKING_FIELD_UNAVAILABLE_ERROR)

    venue = getattr(field, 'venue', None)
    field_status = (getattr(field, 'status', '') or '').upper()
    venue_status = (getattr(venue, 'status', '') or '').upper()
    if (
        field_status != 'ACTIVE'
        or not venue
        or venue_status != 'ACTIVE'
        or getattr(venue, 'is_deleted', False)
    ):
        raise ValidationError(BOOKING_FIELD_UNAVAILABLE_ERROR)


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
        current += timedelta(minutes=BOOKING_SLOT_INTERVAL_MINUTES)
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
        booking__status__in=ACTIVE_BOOKING_STATUSES,
    )
    return overlapping_slots.exists()


def check_active_slot_lock_conflict(field, booking_date, start_time, end_time):
    return SlotLock.objects.filter(
        field=field,
        booking_date=booking_date,
        status=SlotLock.ACTIVE,
        expires_at__gt=timezone.now(),
        start_time__lt=end_time,
        end_time__gt=start_time,
    ).exists()


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
            booking__status__in=ACTIVE_BOOKING_STATUSES,
        )
    )

    # 2. Check DB-backed slot locks.
    active_locks = list(
        SlotLock.objects.filter(
            field=field,
            booking_date=booking_date,
            status=SlotLock.ACTIVE,
            expires_at__gt=timezone.now(),
        )
    )

    # 3. Check Redis locked blocks when Redis is configured and reachable.
    locked_block_ranges = []
    redis_client = _get_redis_client_or_none()
    if redis_client:
        pattern = f"booking_lock:field:{field.pk}:date:{booking_date.isoformat()}:block:*"
        locked_keys = redis_client.keys(pattern)
        for key in locked_keys:
            # Extract HH:MM from key:
            # booking_lock:field:5:date:2026-05-29:block:07:30
            block_time = key.split(':block:')[-1]
            try:
                lock_start = datetime.strptime(block_time, TIME_BLOCK_FORMAT).time()
            except ValueError:
                continue
            locked_block_ranges.append((
                lock_start,
                _add_minutes(lock_start, TIME_BLOCK_INTERVAL_MINUTES),
            ))

    unavailable_blocks = []
    for block in blocks:
        block_start = datetime.strptime(block, TIME_BLOCK_FORMAT).time()
        block_end = _add_minutes(block_start, BOOKING_SLOT_INTERVAL_MINUTES)

        is_booked = any(
            is_time_overlap(slot.start_time, slot.end_time, block_start, block_end)
            for slot in booked_slots
        )
        is_db_locked = any(
            is_time_overlap(lock.start_time, lock.end_time, block_start, block_end)
            for lock in active_locks
        )
        is_redis_locked = any(
            is_time_overlap(lock_start, lock_end, block_start, block_end)
            for lock_start, lock_end in locked_block_ranges
        )

        if is_booked or is_db_locked or is_redis_locked:
            unavailable_blocks.append(block)

    return unavailable_blocks


def is_time_range_available(field, booking_date, start_time, end_time):
    if check_booking_slot_conflict(field, booking_date, start_time, end_time):
        return False
    if check_active_slot_lock_conflict(field, booking_date, start_time, end_time):
        return False
        
    try:
        blocks = generate_time_blocks(start_time, end_time, TIME_BLOCK_INTERVAL_MINUTES)
    except ValidationError:
        return False

    redis_client = _get_redis_client_or_none()
    if not redis_client:
        return True
    for block in blocks:
        key = f"booking_lock:field:{field.pk}:date:{booking_date.isoformat()}:block:{block}"
        if redis_client.exists(key):
            return False
    return True


def get_booking_slot_options(field, booking_date, time_blocks=None, unavailable_blocks=None):
    if not field or not booking_date:
        return []

    blocks = time_blocks or get_time_blocks_for_field_date(field, booking_date)
    unavailable_set = set(
        unavailable_blocks
        if unavailable_blocks is not None
        else get_unavailable_time_blocks(field, booking_date, blocks)
    )
    slot_options = []

    for start_label, end_label in zip(blocks, blocks[1:]):
        start_time = datetime.strptime(start_label, TIME_BLOCK_FORMAT).time()
        end_time = datetime.strptime(end_label, TIME_BLOCK_FORMAT).time()
        status = SLOT_STATUS_AVAILABLE
        status_label = 'Còn trống'
        price = None

        if is_booking_time_in_past(booking_date, start_time):
            status = SLOT_STATUS_PAST
            status_label = 'Quá hạn'
        elif check_booking_slot_conflict(field, booking_date, start_time, end_time):
            status = SLOT_STATUS_BOOKED
            status_label = 'Đã đặt'
        elif check_active_slot_lock_conflict(field, booking_date, start_time, end_time):
            status = SLOT_STATUS_LOCKED
            status_label = 'Đang giữ'
        elif start_label in unavailable_set:
            status = SLOT_STATUS_LOCKED
            status_label = 'Đang giữ'
        else:
            try:
                price, _ = calculate_booking_price(field, booking_date, start_time, end_time)
            except ValidationError:
                status = SLOT_STATUS_NO_PRICE
                status_label = 'Chưa có giá'

        slot_options.append({
            'start_label': start_label,
            'end_label': end_label,
            'value': f'{start_label}|{end_label}',
            'start_time': start_time,
            'end_time': end_time,
            'status': status,
            'status_label': status_label,
            'is_bookable': status == SLOT_STATUS_AVAILABLE,
            'price': price,
        })

    return slot_options


def acquire_slot_lock(user, field, booking_date, start_time, end_time):
    """
    Acquire Redis locks for 30-min blocks.
    """
    validate_bookable_field(field)
    validate_booking_not_in_past(booking_date, start_time)
    validate_booking_time_range(start_time, end_time)

    if check_booking_slot_conflict(field, booking_date, start_time, end_time):
        raise ValidationError(SLOT_CONFLICT_ERROR)
    if check_active_slot_lock_conflict(field, booking_date, start_time, end_time):
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


def _normalize_price(price):
    return Decimal(str(price)).quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


def _normalize_slot_ranges(slot_ranges):
    normalized = []
    for slot_range in slot_ranges or []:
        if isinstance(slot_range, dict):
            start_time = slot_range.get('start_time')
            end_time = slot_range.get('end_time')
        else:
            try:
                start_time, end_time = slot_range
            except (TypeError, ValueError) as exc:
                raise ValidationError(BOOKING_INVALID_SLOT_ERROR) from exc

        if not start_time or not end_time:
            raise ValidationError(BOOKING_INVALID_SLOT_ERROR)
        normalized.append((start_time, end_time))

    if not normalized:
        raise ValidationError(BOOKING_NO_SLOT_SELECTED_ERROR)

    normalized.sort(key=lambda slot_range: slot_range[0])
    for index, (start_time, end_time) in enumerate(normalized):
        validate_booking_time_range(start_time, end_time)
        for previous_start, previous_end in normalized[:index]:
            if is_time_overlap(previous_start, previous_end, start_time, end_time):
                raise ValidationError(BOOKING_UNAVAILABLE_ERROR)
    return normalized


def _acquire_slot_lock_sessions(user, field, booking_date, slot_ranges):
    lock_session_ids = []
    try:
        for start_time, end_time in slot_ranges:
            lock_session_id, _ = acquire_slot_lock(
                user,
                field,
                booking_date,
                start_time,
                end_time,
            )
            lock_session_ids.append(lock_session_id)
    except Exception:
        for lock_session_id in lock_session_ids:
            release_slot_lock(lock_session_id)
        raise
    return lock_session_ids


def _release_slot_lock_sessions(lock_session_ids):
    for lock_session_id in lock_session_ids:
        try:
            release_slot_lock(lock_session_id)
        except (ImproperlyConfigured, redis.exceptions.RedisError):
            pass


def _create_booking_records(
    user,
    field,
    booking_date,
    start_time,
    end_time,
    price,
    note='',
    service_quantities=None,
):
    field = Field.objects.select_related('venue').select_for_update().get(pk=field.pk)
    validate_bookable_field(field)
    validate_booking_not_in_past(booking_date, start_time)
    validate_booking_time_range(start_time, end_time)

    if check_booking_slot_conflict(field, booking_date, start_time, end_time):
        raise ValidationError(SLOT_CONFLICT_ERROR)
    if check_active_slot_lock_conflict(field, booking_date, start_time, end_time):
        raise ValidationError(SLOT_CONFLICT_ERROR)

    price = _normalize_price(price)

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
        payment_deadline=get_payment_deadline(),
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

    return booking


@transaction.atomic
def _create_booking_records_for_slots(
    user,
    field,
    booking_date,
    slot_ranges,
    note='',
    service_quantities=None,
):
    slot_ranges = _normalize_slot_ranges(slot_ranges)
    field = Field.objects.select_related('venue').select_for_update().get(pk=field.pk)
    validate_bookable_field(field)

    priced_slots = []
    for start_time, end_time in slot_ranges:
        validate_booking_not_in_past(booking_date, start_time)
        validate_booking_time_range(start_time, end_time)

        if check_booking_slot_conflict(field, booking_date, start_time, end_time):
            raise ValidationError(SLOT_CONFLICT_ERROR)
        if check_active_slot_lock_conflict(field, booking_date, start_time, end_time):
            raise ValidationError(SLOT_CONFLICT_ERROR)

        price, _ = calculate_booking_price(field, booking_date, start_time, end_time)
        priced_slots.append((start_time, end_time, _normalize_price(price)))

    court_total = sum((price for _, _, price in priced_slots), Decimal('0.00'))

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
        total_amount=court_total,
        note=note or '',
        payment_deadline=get_payment_deadline(),
    )
    booking.full_clean()
    booking.save()

    for start_time, end_time, price in priced_slots:
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

    return booking


def create_booking_for_slots(user, field, booking_date, slot_ranges, note='', service_quantities=None):
    slot_ranges = _normalize_slot_ranges(slot_ranges)
    try:
        lock_session_ids = _acquire_slot_lock_sessions(user, field, booking_date, slot_ranges)
    except (ImproperlyConfigured, redis.exceptions.RedisError):
        return _create_booking_records_for_slots(
            user=user,
            field=field,
            booking_date=booking_date,
            slot_ranges=slot_ranges,
            note=note,
            service_quantities=service_quantities,
        )

    try:
        return _create_booking_records_for_slots(
            user=user,
            field=field,
            booking_date=booking_date,
            slot_ranges=slot_ranges,
            note=note,
            service_quantities=service_quantities,
        )
    finally:
        _release_slot_lock_sessions(lock_session_ids)


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
    validate_bookable_field(field)
    validate_booking_not_in_past(booking_date, start_time)

    if check_booking_slot_conflict(field, booking_date, start_time, end_time):
        release_slot_lock(lock_session_id)
        raise ValidationError(SLOT_CONFLICT_ERROR)
    if check_active_slot_lock_conflict(field, booking_date, start_time, end_time):
        release_slot_lock(lock_session_id)
        raise ValidationError(SLOT_CONFLICT_ERROR)

    booking = _create_booking_records(
        user=user,
        field=field,
        booking_date=booking_date,
        start_time=start_time,
        end_time=end_time,
        price=price,
        note=note,
        service_quantities=service_quantities,
    )

    # Release lock
    release_slot_lock(lock_session_id)

    return booking


@transaction.atomic
def _create_booking_without_redis_lock(
    user,
    field,
    booking_date,
    start_time,
    end_time,
    price,
    note='',
    service_quantities=None,
):
    return _create_booking_records(
        user=user,
        field=field,
        booking_date=booking_date,
        start_time=start_time,
        end_time=end_time,
        price=price,
        note=note,
        service_quantities=service_quantities,
    )


# Keep create_booking to not break other things, but make it use the new flow
@transaction.atomic
def create_booking(user, field, booking_date, start_time, end_time, price, note='', service_quantities=None):
    try:
        lock_session_id, _ = acquire_slot_lock(user, field, booking_date, start_time, end_time)
    except (ImproperlyConfigured, redis.exceptions.RedisError):
        return _create_booking_without_redis_lock(
            user,
            field,
            booking_date,
            start_time,
            end_time,
            price,
            note,
            service_quantities=service_quantities,
        )

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
