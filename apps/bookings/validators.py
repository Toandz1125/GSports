from datetime import date as date_class, datetime, timedelta

from django.core.exceptions import ValidationError


START_TIME_STEP_ERROR = 'Thời gian bắt đầu phải là mốc :00 hoặc :30.'
END_TIME_STEP_ERROR = 'Thời gian kết thúc phải là mốc :00 hoặc :30.'
END_TIME_AFTER_START_ERROR = 'Thời gian kết thúc phải muộn hơn thời gian bắt đầu.'
MAX_BOOKING_DURATION_ERROR = 'Thời lượng đặt sân không được vượt quá 4 tiếng.'

MAX_BOOKING_DURATION = timedelta(hours=4)
VALID_TIME_BLOCK_MINUTES = (0, 30)


def validate_booking_time_range(start_time, end_time):
    errors = {}

    if start_time and (
        start_time.minute not in VALID_TIME_BLOCK_MINUTES
        or start_time.second
        or start_time.microsecond
    ):
        errors['start_time'] = [START_TIME_STEP_ERROR]

    if end_time and (
        end_time.minute not in VALID_TIME_BLOCK_MINUTES
        or end_time.second
        or end_time.microsecond
    ):
        errors['end_time'] = [END_TIME_STEP_ERROR]

    if start_time and end_time:
        if end_time <= start_time:
            errors.setdefault('end_time', []).append(END_TIME_AFTER_START_ERROR)
        else:
            start_dt = datetime.combine(date_class.min, start_time)
            end_dt = datetime.combine(date_class.min, end_time)
            if end_dt - start_dt > MAX_BOOKING_DURATION:
                errors.setdefault('end_time', []).append(MAX_BOOKING_DURATION_ERROR)

    if errors:
        raise ValidationError(errors)
