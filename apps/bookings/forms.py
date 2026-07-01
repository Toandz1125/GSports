import json
from datetime import datetime
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from apps.services.models import ServiceItem
from apps.venues.models import Field, Venue
from .services import (
    BOOKING_INVALID_SLOT_ERROR,
    BOOKING_NO_SLOT_SELECTED_ERROR,
    BOOKING_UNAVAILABLE_ERROR,
    calculate_booking_price,
    generate_time_blocks,
    get_bookable_fields_queryset,
    is_time_range_available,
    validate_bookable_field,
    validate_booking_not_in_past,
    DEFAULT_OPEN_TIME,
    DEFAULT_CLOSE_TIME,
)
from .validators import validate_booking_time_range


def generate_time_block_choices(open_time=None, close_time=None):
    return [(value, value) for value in generate_time_blocks(open_time or DEFAULT_OPEN_TIME, close_time or DEFAULT_CLOSE_TIME)]


class BookingCreateForm(forms.Form):
    SERVICE_FIELD_PREFIX = 'service_quantity_'
    FIELD_VENUE_MISMATCH_MESSAGE = 'Vui lòng chọn sân thuộc cơ sở đã chọn.'

    venue = forms.ModelChoiceField(label='Cơ sở', queryset=Venue.objects.none(), required=False)
    field = forms.ModelChoiceField(label='Sân', queryset=Field.objects.none())
    booking_date = forms.DateField(label='Ngày đặt', widget=forms.DateInput(attrs={'type': 'date'}))
    start_time = forms.TimeField(
        required=False,
        input_formats=['%H:%M'],
        error_messages={
            'required': 'Vui lòng chọn giờ bắt đầu.',
            'invalid': 'Thời gian không hợp lệ.',
        },
        widget=forms.HiddenInput(),
    )
    end_time = forms.TimeField(
        required=False,
        input_formats=['%H:%M'],
        error_messages={
            'required': 'Vui lòng chọn giờ kết thúc.',
            'invalid': 'Thời gian không hợp lệ.',
        },
        widget=forms.HiddenInput(),
    )
    note = forms.CharField(label='Ghi chú', required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        field_queryset = kwargs.pop('field_queryset', None)
        venue_queryset = kwargs.pop('venue_queryset', None)
        selected_venue_id = kwargs.pop('venue_id', None)
        selected_field_id = kwargs.pop('field_id', None)
        super().__init__(*args, **kwargs)
        self.base_field_queryset = (
            field_queryset
            if field_queryset is not None
            else get_bookable_fields_queryset()
        )
        self.fields['venue'].queryset = (
            venue_queryset
            if venue_queryset is not None
            else Venue.objects.filter(status=Venue.ACTIVE, is_deleted=False).order_by('name')
        )
        self.selected_venue = None
        self.resolved_field = None
        self.field_venue_mismatch = False
        self._configure_field_queryset(selected_venue_id, selected_field_id)
        self.calculated_price = None
        self.price_rule = None
        self.selected_slot_ranges = []
        self.slot_prices = []
        self.service_items = self._resolve_service_items()
        self.service_quantities = []
        for service_item in self.service_items:
            field_name = self.get_service_quantity_field_name(service_item.pk)
            self.fields[field_name] = forms.IntegerField(
                label=service_item.name,
                required=False,
                min_value=0,
                initial=0,
                widget=forms.NumberInput(attrs={
                    'min': 0,
                    'max': service_item.stock,
                    'data-service-quantity': service_item.pk,
                    'data-service-price': str(service_item.price or 0),
                }),
            )

    def _raw_selected_venue_id(self, selected_venue_id=None):
        if selected_venue_id:
            return selected_venue_id
        field_name = self.add_prefix('venue')
        if self.is_bound:
            return self.data.get(field_name)
        initial_venue = self.initial.get('venue')
        return getattr(initial_venue, 'pk', initial_venue)

    def _raw_selected_field_id(self, selected_field_id=None):
        if selected_field_id:
            return selected_field_id
        field_name = self.add_prefix('field')
        if self.is_bound:
            return self.data.get(field_name)
        initial_field = self.initial.get('field')
        return getattr(initial_field, 'pk', initial_field)

    def _resolve_field_from_base_queryset(self, field_id):
        if not field_id:
            return None
        try:
            return self.base_field_queryset.get(pk=field_id)
        except (Field.DoesNotExist, TypeError, ValueError):
            return None

    def _configure_field_queryset(self, selected_venue_id=None, selected_field_id=None):
        venue_id = self._raw_selected_venue_id(selected_venue_id)
        field_id = self._raw_selected_field_id(selected_field_id)
        resolved_field = self._resolve_field_from_base_queryset(field_id)
        self.resolved_field = resolved_field

        if not venue_id and resolved_field:
            venue_id = resolved_field.venue_id

        if venue_id:
            try:
                self.selected_venue = self.fields['venue'].queryset.get(pk=venue_id)
            except (Venue.DoesNotExist, TypeError, ValueError):
                self.selected_venue = None

        if self.selected_venue:
            self.fields['field'].queryset = self.base_field_queryset.filter(
                venue=self.selected_venue,
            ).order_by('name')
            self.initial.setdefault('venue', self.selected_venue.pk)
            if resolved_field and resolved_field.venue_id == self.selected_venue.pk:
                self.initial.setdefault('field', resolved_field.pk)
            elif resolved_field:
                self.field_venue_mismatch = True
        else:
            self.fields['field'].queryset = self.base_field_queryset.none()

    @classmethod
    def get_service_quantity_field_name(cls, service_item_id):
        return f'{cls.SERVICE_FIELD_PREFIX}{service_item_id}'

    def _resolve_service_items(self):
        field_id = self._raw_selected_field_id()
        if not field_id:
            return ServiceItem.objects.none()
        try:
            field = self.fields['field'].queryset.select_related('venue').get(pk=field_id)
        except (Field.DoesNotExist, TypeError, ValueError):
            return ServiceItem.objects.none()
        return (
            ServiceItem.objects.filter(
                venue=field.venue,
                is_active=True,
                stock__gt=0,
            )
            .select_related('venue')
            .order_by('category', 'name')
        )

    @property
    def service_quantity_fields(self):
        return [
            {
                'item': service_item,
                'field': self[self.get_service_quantity_field_name(service_item.pk)],
            }
            for service_item in self.service_items
        ]

    def _add_validation_errors(self, exc):
        if hasattr(exc, 'message_dict'):
            for field, messages in exc.message_dict.items():
                for message in messages:
                    self.add_error(field, message)
            return
        for message in exc.messages:
            self.add_error(None, message)

    def _data_getlist(self, key):
        if not self.is_bound:
            return []
        if hasattr(self.data, 'getlist'):
            return self.data.getlist(key)
        value = self.data.get(key)
        return [value] if value else []

    def _raw_slot_values(self):
        values = []
        for field_name in ('slots', 'slot', 'selected_slots'):
            for raw_value in self._data_getlist(self.add_prefix(field_name)):
                if raw_value in (None, ''):
                    continue
                raw_value = str(raw_value).strip()
                if not raw_value:
                    continue
                if raw_value.startswith('['):
                    try:
                        parsed_values = json.loads(raw_value)
                    except json.JSONDecodeError:
                        values.append(raw_value)
                    else:
                        if isinstance(parsed_values, list):
                            values.extend(str(value).strip() for value in parsed_values if str(value).strip())
                        else:
                            values.append(raw_value)
                else:
                    values.append(raw_value)
        return values

    def _parse_slot_value(self, value):
        separator = '|' if '|' in value else '-'
        parts = value.split(separator, 1)
        if len(parts) != 2:
            raise ValidationError(BOOKING_INVALID_SLOT_ERROR)
        try:
            start_time = datetime.strptime(parts[0].strip(), '%H:%M').time()
            end_time = datetime.strptime(parts[1].strip(), '%H:%M').time()
        except ValueError as exc:
            raise ValidationError(BOOKING_INVALID_SLOT_ERROR) from exc
        return start_time, end_time

    def _build_slot_ranges(self, cleaned_data):
        raw_slot_values = self._raw_slot_values()
        if raw_slot_values:
            return [self._parse_slot_value(value) for value in raw_slot_values]

        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        if start_time and end_time:
            return [(start_time, end_time)]
        return []

    def clean(self):
        cleaned_data = super().clean()
        venue = cleaned_data.get('venue')
        field = cleaned_data.get('field')
        booking_date = cleaned_data.get('booking_date')
        slot_ranges = []

        if field and not venue:
            venue = field.venue
            cleaned_data['venue'] = venue

        if venue:
            venue_status = (getattr(venue, 'status', '') or '').upper()
            if venue_status != Venue.ACTIVE or getattr(venue, 'is_deleted', False):
                self.add_error('venue', 'Cơ sở không khả dụng để đặt sân.')

        if field and venue and field.venue_id != venue.pk:
            self.add_error('field', self.FIELD_VENUE_MISMATCH_MESSAGE)
            field = None
            cleaned_data['field'] = None
        elif self.field_venue_mismatch:
            self.add_error('field', self.FIELD_VENUE_MISMATCH_MESSAGE)

        booking_request_is_valid = True
        try:
            slot_ranges = self._build_slot_ranges(cleaned_data)
        except ValidationError as exc:
            booking_request_is_valid = False
            self._add_validation_errors(exc)

        if not slot_ranges and booking_request_is_valid:
            booking_request_is_valid = False
            self.add_error(None, BOOKING_NO_SLOT_SELECTED_ERROR)

        if slot_ranges:
            cleaned_data['start_time'] = slot_ranges[0][0]
            cleaned_data['end_time'] = slot_ranges[0][1]

        for index, (start_time, end_time) in enumerate(slot_ranges):
            if not booking_request_is_valid:
                break
            try:
                validate_booking_time_range(start_time, end_time)
            except ValidationError as exc:
                booking_request_is_valid = False
                self._add_validation_errors(exc)
                break
            for previous_start, previous_end in slot_ranges[:index]:
                if previous_start < end_time and start_time < previous_end:
                    booking_request_is_valid = False
                    self.add_error(None, BOOKING_UNAVAILABLE_ERROR)
                    break

        if field and booking_date and slot_ranges and booking_request_is_valid:
            try:
                validate_bookable_field(field)
                for start_time, _ in slot_ranges:
                    validate_booking_not_in_past(booking_date, start_time)
            except ValidationError as exc:
                booking_request_is_valid = False
                self._add_validation_errors(exc)

        if field and booking_date and slot_ranges and booking_request_is_valid:
            total_price = Decimal('0.00')
            slot_prices = []
            for start_time, end_time in slot_ranges:
                if not is_time_range_available(field, booking_date, start_time, end_time):
                    booking_request_is_valid = False
                    self.add_error(None, BOOKING_UNAVAILABLE_ERROR)
                    break
                try:
                    price, price_rule = calculate_booking_price(
                        field,
                        booking_date,
                        start_time,
                        end_time,
                    )
                except ValidationError as exc:
                    booking_request_is_valid = False
                    self._add_validation_errors(exc)
                    break
                total_price += price
                slot_prices.append((start_time, end_time, price))
                self.price_rule = price_rule
            if booking_request_is_valid:
                self.calculated_price = total_price
                self.slot_prices = slot_prices
                self.selected_slot_ranges = [
                    (start_time, end_time)
                    for start_time, end_time, _ in slot_prices
                ]

        # Strict server-side guard: reject any submitted service quantity that is
        # not part of the active, same-venue service list. The dynamic form only
        # registers fields for allowed services, so this catches tampered/hidden
        # inputs that reference a foreign-venue or deleted/inactive service.
        if field and self.is_bound:
            allowed_ids = {item.pk for item in self.service_items}
            for key in self.data:
                if not key.startswith(self.SERVICE_FIELD_PREFIX):
                    continue
                try:
                    service_item_id = int(key[len(self.SERVICE_FIELD_PREFIX):])
                    quantity = int(self.data.get(key) or 0)
                except (TypeError, ValueError):
                    continue
                if quantity > 0 and service_item_id not in allowed_ids:
                    self.add_error(None, 'Dịch vụ đã chọn không hợp lệ cho sân này.')
                    break

        self.service_quantities = []
        for service_item in self.service_items:
            quantity = cleaned_data.get(self.get_service_quantity_field_name(service_item.pk)) or 0
            if quantity <= 0:
                continue
            if field and service_item.venue_id != field.venue_id:
                self.add_error(None, 'Dịch vụ đã chọn không thuộc cơ sở của sân.')
                continue
            if quantity > service_item.stock:
                self.add_error(
                    self.get_service_quantity_field_name(service_item.pk),
                    f'Tồn kho không đủ. Hiện còn {service_item.stock}.',
                )
                continue
            self.service_quantities.append((service_item, quantity))

        return cleaned_data
