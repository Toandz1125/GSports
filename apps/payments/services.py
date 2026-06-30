from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Wallet, WalletTransaction
from apps.bookings.models import Booking
from apps.bookings.services import cancel_expired_booking_if_needed
from .models import Invoice, Payment


class PaymentServiceError(ValidationError):
    """Business validation error raised by payment services."""


class InsufficientWalletBalance(PaymentServiceError):
    pass


@dataclass
class WalletPaymentResult:
    booking: Booking
    payment: Payment | None = None
    invoice: Invoice | None = None
    wallet_transaction: WalletTransaction | None = None
    already_paid: bool = False


def _booking_queryset():
    return Booking.objects.select_related(
        'booking_package',
        'booking_package__user',
        'venue',
        'field',
    ).prefetch_related(
        'slots',
        'services_ordered',
        'services_ordered__service_item',
    )


def get_payable_booking_for_user(user, booking_pk):
    """Return an accessible customer booking and refresh its timeout state."""
    if not user or not user.is_authenticated:
        raise Booking.DoesNotExist
    booking = _booking_queryset().get(pk=booking_pk, booking_package__user=user)
    cancel_expired_booking_if_needed(booking)
    return booking


def _payment_status(value):
    return getattr(Payment.Status, value, value)


def _payment_method(value):
    return getattr(Payment.Method, value, value)


def _payment_type(value):
    return getattr(Payment.PaymentType, value, value)


def _booking_amount(booking):
    return Decimal(booking.total_amount or Decimal('0'))


def _generate_payment_transaction_code(booking):
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S%f')
    return f'WALLET-{str(booking.pk).replace("-", "")[:12]}-{timestamp}'


def _generate_invoice_code(payment):
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S%f')
    return f'INV-{str(payment.pk).replace("-", "")[:12]}-{timestamp}'


def create_pending_payment(booking, method, payment_type='FINAL'):
    method = _payment_method(method)
    payment_type = _payment_type(payment_type)
    amount = _booking_amount(booking)
    pending_status = _payment_status('PENDING')
    completed_status = _payment_status('COMPLETED')

    payment = (
        Payment.objects.select_for_update()
        .filter(booking=booking, method=method, payment_type=payment_type)
        .exclude(status=completed_status)
        .order_by('-created_at')
        .first()
    )
    if payment is None:
        payment = Payment(
            booking=booking,
            method=method,
            payment_type=payment_type,
            amount=amount,
            status=pending_status,
        )
    else:
        payment.amount = amount
        payment.status = pending_status
        payment.paid_at = None

    payment.full_clean()
    payment.save()
    return payment


def complete_payment(payment, transaction_code=None):
    completed_status = _payment_status('COMPLETED')
    if payment.status == completed_status:
        return payment

    payment.status = completed_status
    payment.paid_at = timezone.now()
    payment.transaction_code = transaction_code or payment.transaction_code
    payment.full_clean()
    payment.save(update_fields=['status', 'paid_at', 'transaction_code', 'updated_at'])
    return payment


def create_invoice_for_payment(payment):
    completed_status = _payment_status('COMPLETED')
    if payment.status != completed_status:
        raise PaymentServiceError('Không thể tạo hóa đơn cho payment chưa hoàn tất.')

    amount = Decimal(payment.amount or Decimal('0'))
    invoice = getattr(payment, 'invoice', None)
    if invoice:
        changed_fields = []
        if invoice.subtotal_amount != amount:
            invoice.subtotal_amount = amount
            changed_fields.append('subtotal_amount')
        if invoice.total_amount != amount + invoice.tax_amount:
            invoice.total_amount = amount + invoice.tax_amount
            changed_fields.append('total_amount')
        if changed_fields:
            changed_fields.append('updated_at')
            invoice.save(update_fields=changed_fields)
        return invoice

    for _ in range(3):
        try:
            return Invoice.objects.create(
                payment=payment,
                invoice_code=_generate_invoice_code(payment),
                subtotal_amount=amount,
                tax_amount=Decimal('0'),
                total_amount=amount,
            )
        except IntegrityError:
            continue
    raise PaymentServiceError('Không thể tạo mã hóa đơn duy nhất.')


def _completed_final_wallet_payment(booking):
    return (
        Payment.objects.select_for_update()
        .filter(
            booking=booking,
            method=_payment_method('WALLET'),
            payment_type=_payment_type('FINAL'),
            status=_payment_status('COMPLETED'),
        )
        .order_by('-paid_at', '-created_at')
        .first()
    )


def pay_booking_with_wallet(user, booking_pk):
    """Atomically pay a pending booking from the customer's account wallet."""
    if not user or not user.is_authenticated:
        raise Booking.DoesNotExist

    with transaction.atomic():
        booking = (
            _booking_queryset()
            .select_for_update()
            .get(pk=booking_pk, booking_package__user=user)
        )

        cancel_expired_booking_if_needed(booking)
        if booking.status == Booking.PAID:
            payment = _completed_final_wallet_payment(booking)
            invoice = create_invoice_for_payment(payment) if payment else None
            return WalletPaymentResult(
                booking=booking,
                payment=payment,
                invoice=invoice,
                already_paid=True,
            )

        if not booking.can_pay():
            raise PaymentServiceError('Không thể thanh toán booking đã huỷ, đã thanh toán hoặc quá hạn.')

        wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
        amount = _booking_amount(booking)
        if wallet.balance < amount:
            raise InsufficientWalletBalance('Số dư ví không đủ')

        existing_completed = _completed_final_wallet_payment(booking)
        if existing_completed:
            booking.status = Booking.PAID
            booking.save(update_fields=['status', 'updated_at'])
            return WalletPaymentResult(
                booking=booking,
                payment=existing_completed,
                invoice=create_invoice_for_payment(existing_completed),
                already_paid=True,
            )

        wallet.balance -= amount
        if wallet.balance < Decimal('0'):
            raise InsufficientWalletBalance('Số dư ví không đủ')
        wallet.save(update_fields=['balance'])

        wallet_transaction = WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=WalletTransaction.DEBIT,
            sub_total=amount,
            final_amount=amount,
            reference_type=WalletTransaction.BOOKING,
            reference_id=str(booking.pk),
            status='COMPLETED',
            description=f'Thanh toán booking {booking.pk}',
        )

        payment = create_pending_payment(
            booking,
            method=_payment_method('WALLET'),
            payment_type=_payment_type('FINAL'),
        )
        payment = complete_payment(
            payment,
            transaction_code=_generate_payment_transaction_code(booking),
        )
        invoice = create_invoice_for_payment(payment)

        booking.status = Booking.PAID
        booking.save(update_fields=['status', 'updated_at'])

        return WalletPaymentResult(
            booking=booking,
            payment=payment,
            invoice=invoice,
            wallet_transaction=wallet_transaction,
        )
