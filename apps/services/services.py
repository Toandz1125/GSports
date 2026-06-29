from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.bookings.models import BookingSlot
from .models import BookingService, ServiceItem


def calculate_booking_court_total(booking):
    return sum(
        (slot.price for slot in BookingSlot.objects.filter(booking=booking).only('price')),
        Decimal('0.00'),
    )


def calculate_booking_service_total(booking):
    total = Decimal('0.00')
    for booking_service in BookingService.objects.filter(booking=booking).only('quantity', 'unit_price'):
        total += booking_service.total_price
    return total


def recalculate_booking_total(booking):
    booking.total_amount = calculate_booking_court_total(booking) + calculate_booking_service_total(booking)
    booking.save(update_fields=['total_amount', 'updated_at'])
    return booking.total_amount


def ensure_booking_services_modifiable(booking):
    message = booking.get_service_modification_block_message()
    if message:
        raise ValidationError(message)


def _create_booking_service(booking, service_item, quantity):
    ensure_booking_services_modifiable(booking)

    if quantity is None or quantity <= 0:
        raise ValidationError('Quantity must be greater than 0.')

    service_item = ServiceItem.objects.select_for_update().get(pk=service_item.pk)
    if not service_item.is_active:
        raise ValidationError('Service item is not active.')
    if service_item.venue_id != booking.venue_id:
        raise ValidationError('Service item venue must match booking venue.')
    if service_item.stock is not None and service_item.stock < quantity:
        raise ValidationError('Insufficient stock for this service item.')

    if service_item.stock is not None:
        service_item.stock -= quantity
        service_item.full_clean()
        service_item.save(update_fields=['stock', 'updated_at'])

    booking_service = BookingService(
        booking=booking,
        service_item=service_item,
        quantity=quantity,
        unit_price=service_item.price,
    )
    booking_service.full_clean()
    booking_service.save()
    return booking_service


@transaction.atomic
def add_service_to_booking(booking, service_item, quantity):
    booking_service = _create_booking_service(booking, service_item, quantity)
    recalculate_booking_total(booking)
    return booking_service


@transaction.atomic
def add_services_to_booking(booking, service_quantities):
    booking_services = []
    for service_item, quantity in service_quantities:
        booking_services.append(_create_booking_service(booking, service_item, quantity))
    recalculate_booking_total(booking)
    return booking_services


@transaction.atomic
def update_booking_service(booking_service, service_item, quantity):
    if quantity is None or quantity <= 0:
        raise ValidationError('Quantity must be greater than 0.')

    booking_service = BookingService.objects.select_for_update().select_related(
        'booking',
        'service_item',
    ).get(pk=booking_service.pk)
    ensure_booking_services_modifiable(booking_service.booking)

    old_service_item = ServiceItem.objects.select_for_update().get(pk=booking_service.service_item_id)
    new_service_item = ServiceItem.objects.select_for_update().get(pk=service_item.pk)

    if not new_service_item.is_active:
        raise ValidationError('Service item is not active.')
    if new_service_item.venue_id != booking_service.booking.venue_id:
        raise ValidationError('Service item venue must match booking venue.')

    if old_service_item.pk == new_service_item.pk:
        stock_delta = quantity - booking_service.quantity
        if stock_delta > old_service_item.stock:
            raise ValidationError('Insufficient stock for this service item.')
        old_service_item.stock -= stock_delta
        old_service_item.full_clean()
        old_service_item.save(update_fields=['stock', 'updated_at'])
    else:
        if new_service_item.stock < quantity:
            raise ValidationError('Insufficient stock for this service item.')
        old_service_item.stock += booking_service.quantity
        new_service_item.stock -= quantity
        old_service_item.full_clean()
        new_service_item.full_clean()
        old_service_item.save(update_fields=['stock', 'updated_at'])
        new_service_item.save(update_fields=['stock', 'updated_at'])

    booking_service.service_item = new_service_item
    booking_service.quantity = quantity
    booking_service.unit_price = new_service_item.price
    booking_service.full_clean()
    booking_service.save(update_fields=['service_item', 'quantity', 'unit_price'])
    recalculate_booking_total(booking_service.booking)
    return booking_service


@transaction.atomic
def remove_service_from_booking(booking_service):
    booking_service = BookingService.objects.select_for_update().select_related(
        'booking',
        'service_item',
    ).get(pk=booking_service.pk)
    booking = booking_service.booking
    ensure_booking_services_modifiable(booking)

    service_item = ServiceItem.objects.select_for_update().get(pk=booking_service.service_item_id)
    if service_item.stock is not None:
        service_item.stock += booking_service.quantity
        service_item.full_clean()
        service_item.save(update_fields=['stock', 'updated_at'])
    booking_service.delete()
    recalculate_booking_total(booking)
