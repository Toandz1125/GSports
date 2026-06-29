from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from decimal import Decimal
import json

from .models import Wallet, WalletTransaction, Payment, Promotion
from core.models import MockBooking

@login_required
def wallet_page(request):
    """Trang quản lý ví"""
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    transactions = wallet.transactions.all()[:20]
    
    context = {
        'wallet': wallet,
        'transactions': transactions,
    }
    return render(request, 'payments/wallet_page.html', context)

@login_required
def checkout_page(request, booking_id):
    """Trang thanh toán"""
    booking = get_object_or_404(MockBooking, id=booking_id, user=request.user)
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    
    context = {
        'booking': booking,
        'wallet_balance': wallet.balance,
        'total_amount': booking.total_amount,
        'deposit_amount': booking.deposit_amount,
    }
    return render(request, 'payments/checkout.html', context)

@login_required
@require_http_methods(["POST"])
def process_payment(request):
    """Xử lý thanh toán"""
    try:
        data = json.loads(request.body)
        booking_id = data.get('booking_id')
        method = data.get('payment_method')
        promo_code = data.get('promo_code')
        final_amount = Decimal(str(data.get('final_amount', 0)))
        
        booking = get_object_or_404(MockBooking, id=booking_id, user=request.user)
        wallet = Wallet.objects.get(user=request.user)
        
        if method == 'WALLET' and wallet.balance < final_amount:
            return JsonResponse({
                'success': False,
                'error': 'Số dư không đủ để thanh toán'
            })
        
        payment = Payment.objects.create(
            booking=booking,
            method=method,
            payment_type='FINAL',
            amount=final_amount,
            status='PAID' if method == 'WALLET' else 'PENDING',
            paid_at=timezone.now() if method == 'WALLET' else None
        )
        
        if method == 'WALLET':
            wallet.withdraw(final_amount)
            
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=-final_amount,
                transaction_type='PAYMENT',
                status='COMPLETED',
                description=f"Thanh toán booking {booking.id}",
                reference_id=str(payment.id)
            )
            
            booking.payment_status = 'PAID'
            booking.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Thanh toán thành công',
                'redirect_url': '/payment/success/'
            })
        
        return JsonResponse({
            'success': True,
            'message': 'Chờ xác nhận thanh toán',
            'payment_id': str(payment.id)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def payment_success(request):
    """Trang thanh toán thành công"""
    return render(request, 'payments/payment_success.html')

@login_required
def deposit_wallet(request):
    """Nạp tiền vào ví"""
    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount', 0))
            if amount <= 0:
                messages.error(request, 'Số tiền phải lớn hơn 0')
                return redirect('wallet_page')
            
            wallet = Wallet.objects.get(user=request.user)
            wallet.deposit(amount)
            
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=amount,
                transaction_type='DEPOSIT',
                status='COMPLETED',
                description=f"Nạp tiền {amount}đ"
            )
            
            messages.success(request, f'Nạp {amount}đ thành công!')
        except Exception as e:
            messages.error(request, f'Lỗi: {str(e)}')
        
        return redirect('wallet_page')
    
    return redirect('wallet_page')

@login_required
def apply_promotion(request):
    """Áp dụng mã giảm giá"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            code = data.get('code')
            amount = Decimal(str(data.get('amount', 0)))
            
            promotion = get_object_or_404(Promotion, code=code)
            
            if not promotion.is_valid():
                return JsonResponse({
                    'success': False,
                    'error': 'Mã giảm giá không hợp lệ hoặc đã hết hạn'
                })
            
            if amount < promotion.min_order_value:
                return JsonResponse({
                    'success': False,
                    'error': f'Đơn hàng tối thiểu {promotion.min_order_value}đ'
                })
            
            if promotion.discount_type == 'PERCENTAGE':
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
                    'discount_value': promotion.discount_value
                }
            })
            
        except Promotion.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Mã giảm giá không tồn tại'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Method not allowed'})