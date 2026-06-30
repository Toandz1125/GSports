from django import forms
from django.forms import BaseFormSet, BaseModelFormSet, formset_factory, modelformset_factory

from apps.accounts.models import OwnerProfile

from .models import Field, FieldPriceRule, Venue
from .pricing import (
    PRICING_MODE_CHOICES,
    PRICING_MODE_DEFAULT,
    validate_price_rule_payloads,
)


FIELD_STATUS_CHOICES = [
    ('ACTIVE', 'Hoạt động'),
    ('MAINTENANCE', 'Bảo trì'),
    ('INACTIVE', 'Ngừng hoạt động'),
]

DAY_OF_WEEK_CHOICES = [
    ('', 'Tất cả các ngày'),
    ('0', 'Thứ 2'),
    ('1', 'Thứ 3'),
    ('2', 'Thứ 4'),
    ('3', 'Thứ 5'),
    ('4', 'Thứ 6'),
    ('5', 'Thứ 7'),
    ('6', 'Chủ nhật'),
]

class VenueForm(forms.ModelForm):
    class Meta:
        model = Venue
        fields = ['name', 'description', 'address']
        labels = {
            'name': 'Tên cơ sở thể thao',
            'description': 'Mô tả chi tiết',
            'address': 'Địa chỉ',
        }
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập tên cơ sở thể thao (ví dụ: Sân bóng GSports)...',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Nhập mô tả giới thiệu về cơ sở thể thao...',
            }),
            'address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập địa chỉ chi tiết...',
            }),
        }


class AdminVenueForm(forms.ModelForm):
    class Meta:
        model = Venue
        fields = [
            'owner',
            'name',
            'description',
            'address',
            'latitude',
            'longitude',
            'status',
        ]
        labels = {
            'owner': 'Chủ sân',
            'name': 'Tên cơ sở thể thao',
            'description': 'Mô tả chi tiết',
            'address': 'Địa chỉ',
            'latitude': 'Vĩ độ',
            'longitude': 'Kinh độ',
            'status': 'Trạng thái',
        }
        widgets = {
            'owner': forms.Select(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'latitude': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0000001'}),
            'longitude': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0000001'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['owner'].queryset = OwnerProfile.objects.select_related('user').order_by('business_name')


class VenueCreateForm(forms.ModelForm):
    class Meta:
        model = Venue
        fields = ['name', 'description', 'address', 'latitude', 'longitude']
        labels = {
            'name': 'Tên cơ sở thể thao',
            'description': 'Mô tả chi tiết',
            'address': 'Địa chỉ',
            'latitude': 'Vĩ độ',
            'longitude': 'Kinh độ',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'latitude': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0000001'}),
            'longitude': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0000001'}),
        }

    def to_payload(self):
        return {
            'name': self.cleaned_data['name'],
            'description': self.cleaned_data.get('description') or '',
            'address': self.cleaned_data['address'],
            'latitude': self.cleaned_data.get('latitude'),
            'longitude': self.cleaned_data.get('longitude'),
        }


class VenueRegistrationRequestForm(forms.Form):
    venue_name = forms.CharField(
        label='Tên cơ sở thể thao',
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    venue_address = forms.CharField(
        label='Địa chỉ',
        max_length=500,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    venue_note = forms.CharField(
        label='Ghi chú',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
    )

    def to_payload(self):
        return {
            'name': self.cleaned_data['venue_name'],
            'address': self.cleaned_data['venue_address'],
            'description': self.cleaned_data.get('venue_note') or '',
        }


class FieldForm(forms.ModelForm):
    class Meta:
        model = Field
        fields = ['name', 'field_type', 'surface_type', 'capacity', 'length', 'width', 'status']
        labels = {
            'name': 'Tên sân con',
            'field_type': 'Loại sân',
            'surface_type': 'Loại mặt sân',
            'capacity': 'Sức chứa (người)',
            'length': 'Chiều dài (m)',
            'width': 'Chiều rộng (m)',
            'status': 'Trạng thái',
        }
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập tên sân con (ví dụ: Sân 5A, Sân 7B)...',
            }),
            'field_type': forms.Select(attrs={'class': 'form-control'}),
            'surface_type': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ví dụ: Cỏ nhân tạo, Cỏ tự nhiên, Sàn gỗ...',
            }),
            'capacity': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập số lượng người chơi tối đa',
            }),
            'length': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập chiều dài sân (m)',
            }),
            'width': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập chiều rộng sân (m)',
            }),
            'status': forms.Select(choices=FIELD_STATUS_CHOICES, attrs={'class': 'form-control'}),
        }


class FieldCreateForm(FieldForm):
    def to_request_kwargs(self):
        return {
            'field_type': self.cleaned_data['field_type'],
            'name': self.cleaned_data['name'],
            'capacity': self.cleaned_data.get('capacity'),
            'surface_type': self.cleaned_data.get('surface_type') or '',
            'length': self.cleaned_data.get('length'),
            'width': self.cleaned_data.get('width'),
            'field_status': self.cleaned_data.get('status') or 'ACTIVE',
        }


class BaseVenueFieldFormSet(BaseModelFormSet):
    def _active_forms(self):
        for form in self.forms:
            if not getattr(form, 'cleaned_data', None):
                continue
            if self.can_delete and self._should_delete_form(form):
                continue
            yield form

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if not list(self._active_forms()):
            raise forms.ValidationError('Vui lòng nhập ít nhất 1 sân con.')

    def to_payload(self):
        payloads = []
        for form in self._active_forms():
            data = form.cleaned_data
            field_type = data['field_type']
            payloads.append({
                'name': data['name'],
                'field_type': field_type.pk,
                'capacity': data.get('capacity'),
                'surface_type': data.get('surface_type') or '',
                'length': data.get('length'),
                'width': data.get('width'),
                'status': data.get('status') or 'ACTIVE',
            })
        return payloads

    def save_for_venue(self, venue):
        fields = []
        for form in self._active_forms():
            field = form.save(commit=False)
            field.venue = venue
            field.status = field.status or 'ACTIVE'
            field.full_clean()
            field.save()
            fields.append(field)
        return fields


VenueFieldFormSet = modelformset_factory(
    Field,
    form=FieldCreateForm,
    formset=BaseVenueFieldFormSet,
    extra=1,
    can_delete=True,
)


class PriceRuleModeForm(forms.Form):
    pricing_mode = forms.ChoiceField(
        label='Cách nhập bảng giá',
        choices=PRICING_MODE_CHOICES,
        initial=PRICING_MODE_DEFAULT,
        widget=forms.RadioSelect,
    )


class ManualFieldPriceRuleForm(forms.Form):
    day_of_week = forms.ChoiceField(
        label='Ngày áp dụng',
        choices=DAY_OF_WEEK_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    start_time = forms.TimeField(
        label='Giờ bắt đầu',
        input_formats=['%H:%M', '%H:%M:%S'],
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
    )
    end_time = forms.TimeField(
        label='Giờ kết thúc',
        input_formats=['%H:%M', '%H:%M:%S'],
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
    )
    price_per_hour = forms.DecimalField(
        label='Giá mỗi giờ',
        min_value=0,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '1000'}),
    )
    priority = forms.IntegerField(
        label='Độ ưu tiên',
        required=False,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    is_holiday = forms.BooleanField(label='Ngày lễ', required=False)
    special_event = forms.CharField(
        label='Sự kiện đặc biệt',
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        if start_time and end_time and end_time <= start_time:
            raise forms.ValidationError('Giờ kết thúc phải sau giờ bắt đầu.')
        return cleaned_data


class BaseManualFieldPriceRuleFormSet(BaseFormSet):
    def _active_forms(self):
        for form in self.forms:
            if not getattr(form, 'cleaned_data', None):
                continue
            if self.can_delete and self._should_delete_form(form):
                continue
            yield form

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        payloads = self.to_payload()
        try:
            validate_price_rule_payloads(payloads)
        except forms.ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc

    def to_payload(self):
        payloads = []
        for form in self._active_forms():
            data = form.cleaned_data
            payloads.append({
                'day_of_week': data.get('day_of_week'),
                'start_time': data['start_time'],
                'end_time': data['end_time'],
                'price_per_hour': data['price_per_hour'],
                'priority': data.get('priority') or 0,
                'is_holiday': data.get('is_holiday') or False,
                'special_event': data.get('special_event') or '',
            })
        return payloads


ManualFieldPriceRuleFormSet = formset_factory(
    ManualFieldPriceRuleForm,
    formset=BaseManualFieldPriceRuleFormSet,
    extra=2,
    can_delete=True,
)


class FieldPriceRuleForm(forms.ModelForm):
    class Meta:
        model = FieldPriceRule
        fields = [
            'day_of_week',
            'start_time',
            'end_time',
            'price_per_hour',
            'start_date',
            'end_date',
            'priority',
            'is_holiday',
            'special_event',
        ]
        labels = {
            'day_of_week': 'Ngày trong tuần',
            'start_time': 'Giờ bắt đầu',
            'end_time': 'Giờ kết thúc',
            'price_per_hour': 'Giá mỗi giờ',
            'start_date': 'Ngày bắt đầu',
            'end_date': 'Ngày kết thúc',
            'priority': 'Độ ưu tiên',
            'is_holiday': 'Ngày lễ',
            'special_event': 'Sự kiện đặc biệt',
        }
        widgets = {
            'day_of_week': forms.Select(choices=DAY_OF_WEEK_CHOICES, attrs={'class': 'form-control'}),
            'start_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'end_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}, format='%H:%M'),
            'price_per_hour': forms.NumberInput(attrs={'class': 'form-control', 'step': '1000'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'priority': forms.NumberInput(attrs={'class': 'form-control'}),
            'special_event': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        if start_time and end_time and end_time <= start_time:
            raise forms.ValidationError('Giờ kết thúc phải sau giờ bắt đầu.')
        if start_date and end_date and end_date < start_date:
            raise forms.ValidationError('Ngày kết thúc phải sau ngày bắt đầu.')
        return cleaned_data
