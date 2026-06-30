import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_http_methods

from apps.accounts.models import UserRole, Wallet, WalletTransaction
from apps.bookings.models import Booking
from apps.bookings.permissions import get_owner_profile
from apps.bookings.services import cancel_expired_booking_if_needed
from .models import Payment, Promotion
from .services import (
    InsufficientWalletBalance,
    PaymentServiceError,
    get_payable_booking_for_user,
    pay_booking_with_wallet,
)


# A booking counts as paid when it carries any of these payment statuses, in
# addition to Booking.PAID. The wallet flow stores COMPLETED; PAID/SUCCESS are
# accepted defensively so other payment channels remain compatible.
COMPLETED_PAYMENT_STATUSES = ('COMPLETED', 'PAID', 'SUCCESS')


def _error_message(exc):
    if hasattr(exc, 'messages') and exc.messages:
        return exc.messages[0]
    return str(exc)


def _get_wallet(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def _booking_checkout_context(request, booking):
    wallet = _get_wallet(request.user)
    amount = Decimal(booking.total_amount or Decimal('0.00'))
    can_pay_booking = booking.can_pay()
    has_sufficient_balance = wallet.balance >= amount
    return {
        'booking': booking,
        'wallet': wallet,
        'wallet_balance': wallet.balance,
        'has_sufficient_balance': has_sufficient_balance,
        'balance_after_payment': wallet.balance - amount if has_sufficient_balance else None,
        'can_pay_booking': can_pay_booking,
        'can_cancel_booking': booking.can_cancel(),
        'payment_expired': bool(
            booking.status == Booking.CANCELLED
            and booking.payment_deadline
            and booking.payment_deadline <= timezone.now()
        ),
    }


class BookingCheckoutView(LoginRequiredMixin, View):
    template_name = 'payments/booking_checkout.html'

    def _get_booking_or_404(self, request, booking_pk):
        try:
            return get_payable_booking_for_user(request.user, booking_pk)
        except Booking.DoesNotExist as exc:
            raise Http404('Không tìm thấy booking.') from exc

    def _redirect_if_not_payable(self, request, booking):
        if booking.status == Booking.PAID:
            messages.info(request, 'Booking đã được thanh toán')
            return redirect('bookings:booking_detail', pk=booking.pk)
        if not booking.can_pay():
            if (
                booking.status == Booking.CANCELLED
                and booking.payment_deadline
                and booking.payment_deadline <= timezone.now()
            ):
                messages.warning(request, 'Đơn đặt sân đã quá hạn thanh toán và đã bị hủy.')
            else:
                messages.error(request, 'Booking hiện không thể thanh toán.')
            return redirect('bookings:booking_detail', pk=booking.pk)
        return None

    def get(self, request, *args, **kwargs):
        booking = self._get_booking_or_404(request, kwargs['booking_pk'])
        redirect_response = self._redirect_if_not_payable(request, booking)
        if redirect_response:
            return redirect_response
        return render(request, self.template_name, _booking_checkout_context(request, booking))

    def post(self, request, *args, **kwargs):
        booking_pk = kwargs['booking_pk']
        action = request.POST.get('action')
        if action != 'wallet_pay':
            messages.error(request, 'Phương thức thanh toán này chưa hỗ trợ cho khách hàng.')
            return redirect('payments:booking_checkout', booking_pk=booking_pk)

        try:
            result = pay_booking_with_wallet(request.user, booking_pk)
        except Booking.DoesNotExist as exc:
            raise Http404('Không tìm thấy booking.') from exc
        except InsufficientWalletBalance as exc:
            messages.error(request, _error_message(exc))
            return redirect('payments:booking_checkout', booking_pk=booking_pk)
        except PaymentServiceError as exc:
            try:
                booking = Booking.objects.get(pk=booking_pk, booking_package__user=request.user)
                cancel_expired_booking_if_needed(booking)
            except Booking.DoesNotExist as missing:
                raise Http404('Không tìm thấy booking.') from missing
            messages.error(request, _error_message(exc))
            if booking.status == Booking.PAID or not booking.can_pay():
                return redirect('bookings:booking_detail', pk=booking.pk)
            return redirect('payments:booking_checkout', booking_pk=booking_pk)

        if result.already_paid:
            messages.info(request, 'Booking đã được thanh toán trước đó.')
        else:
            messages.success(request, 'Thanh toán thành công.')
        return redirect('bookings:booking_detail', pk=result.booking.pk)


def _invoice_booking_queryset_for_user(user):
    """Role-scoped Booking queryset for invoice/receipt viewing.

    Mirrors the history scoping so the invoice page never leaks bookings outside
    the viewer's role scope: customer = own bookings, owner = own venues, staff =
    assigned venue/owner, admin/superuser = all. ``.get(pk=...)`` therefore
    raises ``Booking.DoesNotExist`` (translated to 404) for anything else.
    """
    queryset = Booking.objects.select_related(
        'booking_package__user',
        'venue',
        'field',
    ).prefetch_related(
        'slots',
        'services_ordered__service_item',
        'payments__invoice',
    )
    if not user or not user.is_authenticated:
        return queryset.none()

    roles = set(
        UserRole.objects.filter(user=user).values_list('role__name', flat=True)
    )
    if user.is_superuser or 'ADMIN' in roles:
        return queryset
    if 'OWNER' in roles:
        owner_profile = get_owner_profile(user)
        if owner_profile:
            return queryset.filter(venue__owner=owner_profile)
        return queryset.none()
    if 'STAFF' in roles:
        staff_profile = getattr(user, 'staff_profile', None)
        if staff_profile and staff_profile.venue_id:
            return queryset.filter(venue=staff_profile.venue)
        if staff_profile and staff_profile.owner_id:
            return queryset.filter(venue__owner=staff_profile.owner)
        return queryset.none()
    return queryset.filter(booking_package__user=user)


def _completed_payment(booking):
    """Return the most recent completed Payment for a booking (prefetch-aware)."""
    completed = [
        payment for payment in booking.payments.all()
        if payment.status in COMPLETED_PAYMENT_STATUSES
    ]
    completed.sort(key=lambda payment: payment.paid_at or payment.created_at, reverse=True)
    return completed[0] if completed else None


class BookingInvoiceView(LoginRequiredMixin, View):
    """Invoice / receipt page for a booking, scoped to the viewer's role.

    This view only reads; it never creates Payment/Invoice records and never
    marks anything paid. A still-payable booking opened by its owner is sent to
    the checkout instead of showing an empty receipt.
    """

    template_name = 'payments/booking_invoice.html'

    def get(self, request, *args, **kwargs):
        try:
            booking = _invoice_booking_queryset_for_user(request.user).get(pk=kwargs['booking_pk'])
        except Booking.DoesNotExist as exc:
            raise Http404('Không tìm thấy hóa đơn.') from exc

        # Keep the 10-minute hold consistent: an expired PENDING hold is cancelled
        # here too, so the receipt never shows a payable state past its deadline.
        if cancel_expired_booking_if_needed(booking):
            booking.refresh_from_db()

        is_owner_self = booking.booking_package.user_id == request.user.id

        # Still payable and viewed by its owner -> finish the payment first.
        if is_owner_self and booking.can_pay():
            messages.info(request, 'Đơn này chưa thanh toán. Vui lòng tiếp tục thanh toán.')
            return redirect('payments:booking_checkout', booking_pk=booking.pk)

        payment = _completed_payment(booking)
        invoice = getattr(payment, 'invoice', None) if payment else None
        is_paid = booking.status == Booking.PAID or payment is not None

        return render(request, self.template_name, {
            'booking': booking,
            'payment': payment,
            'invoice': invoice,
            'is_paid': is_paid,
            'is_cancelled': booking.status == Booking.CANCELLED,
            'is_owner_self': is_owner_self,
            'can_pay_booking': booking.can_pay(),
            # PAID booking without an Invoice row -> fallback receipt with a note.
            'no_official_invoice': is_paid and invoice is None,
        })


@login_required
def wallet_page(request):
    """Trang quản lý ví tài khoản đang dùng trong dashboard."""
    wallet = _get_wallet(request.user)
    transactions = wallet.transactions.all()[:20]
    return render(request, 'payments/wallet_page.html', {
        'wallet': wallet,
        'transactions': transactions,
    })


@login_required
def checkout_page(request, booking_id):
    """Legacy URL compatibility: redirect to the real booking checkout."""
    return redirect('payments:booking_checkout', booking_pk=booking_id)


@login_required
@require_http_methods(['POST'])
def process_payment(request):
    """Legacy JSON endpoint kept inert so client-supplied amounts cannot pay."""
    return JsonResponse({
        'success': False,
        'error': 'Vui lòng thanh toán từ trang checkout booking.',
    }, status=400)


@login_required
def payment_success(request):
    """Trang thanh toán thành công cũ, giữ để không gãy route legacy."""
    return render(request, 'payments/payment_success.html')


@login_required
def deposit_wallet(request):
    """Nạp tiền thủ công vào ví tài khoản."""
    if request.method != 'POST':
        return redirect('payments:wallet_page')

    try:
        amount = Decimal(str(request.POST.get('amount', '0')))
    except (InvalidOperation, TypeError):
        amount = Decimal('0')

    if amount <= 0:
        messages.error(request, 'Số tiền phải lớn hơn 0')
        return redirect('payments:wallet_page')

    with transaction.atomic():
        wallet, _ = Wallet.objects.select_for_update().get_or_create(user=request.user)
        wallet.balance += amount
        wallet.save(update_fields=['balance'])
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=WalletTransaction.CREDIT,
            sub_total=amount,
            final_amount=amount,
            reference_type=WalletTransaction.TOPUP,
            reference_id=f'TOPUP-{timezone.now().strftime("%Y%m%d%H%M%S%f")}',
            status='COMPLETED',
            description=f'Nạp tiền {amount}đ',
        )

    messages.success(request, f'Nạp {amount}đ thành công!')
    return redirect('payments:wallet_page')


@login_required
def apply_promotion(request):
    """Áp dụng mã giảm giá cho phần hiển thị, không dùng để quyết định amount thanh toán."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        code = data.get('code')
        amount = Decimal(str(data.get('amount', 0)))

        promotion = Promotion.objects.get(code=code)
        if not promotion.is_valid():
            return JsonResponse({
                'success': False,
                'error': 'Mã giảm giá không hợp lệ hoặc đã hết hạn',
            })

        if amount < promotion.min_order_value:
            return JsonResponse({
                'success': False,
                'error': f'Đơn hàng tối thiểu {promotion.min_order_value}đ',
            })

        if promotion.discount_type == Promotion.DiscountType.PERCENTAGE:
            discount = amount * promotion.discount_value / 100
            if promotion.max_discount_amount:
                discount = min(discount, promotion.max_discount_amount)
        else:
            discount = promotion.discount_value

        final_amount = amount - discount
        return JsonResponse({
            'success': True,
            'discount_amount': discount,
            'final_amount': final_amount,
            'promo': {
                'code': promotion.code,
                'discount_type': promotion.discount_type,
                'discount_value': promotion.discount_value,
            },
        })
    except Promotion.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Mã giảm giá không tồn tại',
        }, status=404)
    except Exception as exc:
        return JsonResponse({
            'success': False,
            'error': str(exc),
        }, status=400)
