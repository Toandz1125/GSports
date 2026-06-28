from django import forms
from django.core.exceptions import ValidationError

from apps.services.models import ServiceItem
from apps.venues.models import Field
from .services import (
    BOOKING_UNAVAILABLE_ERROR,
    calculate_booking_price,
    generate_time_blocks,
    get_bookable_fields_queryset,
    is_time_range_available,
    DEFAULT_OPEN_TIME,
    DEFAULT_CLOSE_TIME,
)
from .validators import validate_booking_time_range


def generate_time_block_choices(open_time=None, close_time=None):
    return [(value, value) for value in generate_time_blocks(open_time or DEFAULT_OPEN_TIME, close_time or DEFAULT_CLOSE_TIME)]


class BookingCreateForm(forms.Form):
    SERVICE_FIELD_PREFIX = 'service_quantity_'

    field = forms.ModelChoiceField(label='Sân', queryset=Field.objects.none())
    booking_date = forms.DateField(label='Ngày đặt', widget=forms.DateInput(attrs={'type': 'date'}))
    start_time = forms.TimeField(
        input_formats=['%H:%M'],
        error_messages={
            'required': 'Vui lòng chọn giờ bắt đầu.',
            'invalid': 'Thời gian không hợp lệ.',
        },
        widget=forms.HiddenInput(),
    )
    end_time = forms.TimeField(
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
        super().__init__(*args, **kwargs)
        self.fields['field'].queryset = field_queryset or get_bookable_fields_queryset()
        self.calculated_price = None
        self.price_rule = None
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
                }),
            )

    @classmethod
    def get_service_quantity_field_name(cls, service_item_id):
        return f'{cls.SERVICE_FIELD_PREFIX}{service_item_id}'

    def _raw_selected_field_id(self):
        field_name = self.add_prefix('field')
        if self.is_bound:
            return self.data.get(field_name)
        initial_field = self.initial.get('field')
        return getattr(initial_field, 'pk', initial_field)

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

    def clean(self):
        cleaned_data = super().clean()
        field = cleaned_data.get('field')
        booking_date = cleaned_data.get('booking_date')
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')

        time_range_is_valid = True
        if start_time and end_time:
            try:
                validate_booking_time_range(start_time, end_time)
            except ValidationError as exc:
                time_range_is_valid = False
                self._add_validation_errors(exc)

        if field and booking_date and start_time and end_time and time_range_is_valid:
            if not is_time_range_available(field, booking_date, start_time, end_time):
                raise ValidationError(BOOKING_UNAVAILABLE_ERROR)
            try:
                self.calculated_price, self.price_rule = calculate_booking_price(
                    field,
                    booking_date,
                    start_time,
                    end_time,
                )
            except ValidationError as exc:
                self._add_validation_errors(exc)

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
