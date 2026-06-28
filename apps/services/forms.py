from django import forms
from django.core.exceptions import ValidationError

from .models import BookingService, ServiceItem


class ServiceItemForm(forms.ModelForm):
    class Meta:
        model = ServiceItem
        # `is_active` is intentionally excluded from the UI: new services default
        # to active (model default `is_active=True`) and deactivation happens via
        # the dedicated delete/disable flow, not this create/update form.
        fields = ['venue', 'name', 'category', 'image', 'price', 'stock']
        widgets = {
            'price': forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
            'stock': forms.NumberInput(attrs={'min': 0}),
        }

    def __init__(self, *args, **kwargs):
        self.owner_profile = kwargs.pop('owner_profile', None)
        super().__init__(*args, **kwargs)
        if self.owner_profile:
            self.fields['venue'].queryset = self.owner_profile.venues.filter(is_deleted=False).order_by('name')

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise ValidationError('Vui lòng nhập tên dịch vụ.')
        return name

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None and price <= 0:
            raise ValidationError('Giá dịch vụ phải lớn hơn 0.')
        return price

    def clean_stock(self):
        stock = self.cleaned_data.get('stock')
        if stock is not None and stock < 0:
            raise ValidationError('Tồn kho không được âm.')
        return stock

    def clean_venue(self):
        venue = self.cleaned_data.get('venue')
        if self.owner_profile and venue and venue.owner_id != self.owner_profile.pk:
            raise ValidationError('Bạn chỉ được chọn cơ sở thuộc sở hữu của mình.')
        return venue


class BookingServiceForm(forms.ModelForm):
    class Meta:
        model = BookingService
        fields = ['service_item', 'quantity']
        widgets = {
            'quantity': forms.NumberInput(attrs={'min': 1}),
        }

    def __init__(self, *args, **kwargs):
        self.booking = kwargs.pop('booking', None)
        super().__init__(*args, **kwargs)
        queryset = ServiceItem.objects.filter(is_active=True).select_related('venue')
        if self.booking:
            queryset = queryset.filter(venue=self.booking.venue)
        self.fields['service_item'].queryset = queryset

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        if quantity <= 0:
            raise ValidationError('Quantity must be greater than 0.')
        return quantity

    def clean(self):
        cleaned_data = super().clean()
        if self.booking:
            message = self.booking.get_service_modification_block_message()
            if message:
                raise ValidationError(message)

        service_item = cleaned_data.get('service_item')
        quantity = cleaned_data.get('quantity')
        if service_item and quantity:
            available_stock = service_item.stock
            if self.instance.pk and self.instance.service_item_id == service_item.pk:
                available_stock += self.instance.quantity
            if available_stock < quantity:
                raise ValidationError('Insufficient stock for this service item.')
        return cleaned_data
