// static/js/checkout.js
console.log('checkout.js đã được tải thành công!');

// Biến toàn cục
var selectedMethod = null;
var currentBookingId = null;
var finalAmount = 0;

// Tự động chạy khi trang load
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM đã load xong!');
    var container = document.querySelector('.checkout-container');
    if (container) {
        currentBookingId = container.getAttribute('data-booking-id');
        finalAmount = parseFloat(container.getAttribute('data-total-amount'));
        console.log('Booking ID:', currentBookingId);
        console.log('Total amount:', finalAmount);
    } else {
        console.log('Không tìm thấy container!');
    }
});

// Hàm chọn phương thức thanh toán
function selectMethod(event, method) {
    console.log('Selected method:', method);
    selectedMethod = method;
    var options = document.querySelectorAll('.method-option');
    for (var i = 0; i < options.length; i++) {
        options[i].style.borderColor = '#eef2f7';
    }
    event.currentTarget.style.borderColor = '#00b894';
}

// Hàm áp dụng mã giảm giá
function applyPromo() {
    console.log('applyPromo called!');
    var code = document.getElementById('promoCode').value;
    if (!code) {
        alert('Vui lòng nhập mã giảm giá');
        return;
    }

    var csrfToken = document.querySelector('input[name="csrfmiddlewaretoken"]');
    var token = csrfToken ? csrfToken.value : '';
    console.log('CSRF Token:', token);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/apply-promo/', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.setRequestHeader('X-CSRFToken', token);
    
    xhr.onreadystatechange = function() {
        if (xhr.readyState === 4) {
            console.log('Response status:', xhr.status);
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    console.log('Response data:', data);
                    if (data.success) {
                        finalAmount = data.final_amount;
                        document.getElementById('finalAmount').textContent = finalAmount.toFixed(0) + 'đ';
                        document.getElementById('promoResult').innerHTML = 
                            '<div class="promo-success">' +
                                '<i class="fas fa-check-circle"></i>' +
                                ' Áp dụng thành công! Giảm ' + data.discount_amount.toFixed(0) + 'đ' +
                            '</div>';
                    } else {
                        document.getElementById('promoResult').innerHTML = 
                            '<div class="promo-error">' +
                                '<i class="fas fa-exclamation-circle"></i>' +
                                ' ' + data.error +
                            '</div>';
                    }
                } catch (e) {
                    console.error('Parse error:', e);
                    alert('Lỗi: ' + e.message);
                }
            } else {
                console.error('HTTP Error:', xhr.status);
                alert('Lỗi kết nối đến server');
            }
        }
    };
    
    var requestData = JSON.stringify({
        code: code,
        amount: finalAmount
    });
    console.log('Sending request:', requestData);
    xhr.send(requestData);
}

// Hàm xử lý thanh toán
function processPayment() {
    console.log('processPayment called!');
    console.log('Selected method:', selectedMethod);
    console.log('Booking ID:', currentBookingId);
    console.log('Final amount:', finalAmount);
    
    if (!selectedMethod) {
        alert('Vui lòng chọn phương thức thanh toán');
        return;
    }

    var confirmBtn = document.getElementById('confirmBtn');
    confirmBtn.disabled = true;
    confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Đang xử lý...';

    var csrfToken = document.querySelector('input[name="csrfmiddlewaretoken"]');
    var token = csrfToken ? csrfToken.value : '';
    console.log('CSRF Token:', token);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/process-payment/', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.setRequestHeader('X-CSRFToken', token);
    
    xhr.onreadystatechange = function() {
        if (xhr.readyState === 4) {
            console.log('Response status:', xhr.status);
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    console.log('Response data:', data);
                    if (data.success) {
                        if (data.redirect_url) {
                            window.location.href = data.redirect_url;
                        } else {
                            alert('Thanh toán thành công!');
                            window.location.href = '/payment/success/';
                        }
                    } else {
                        alert('Lỗi: ' + data.error);
                        confirmBtn.disabled = false;
                        confirmBtn.innerHTML = '<i class="fas fa-check"></i> Xác nhận thanh toán';
                    }
                } catch (e) {
                    console.error('Parse error:', e);
                    alert('Lỗi: ' + e.message);
                    confirmBtn.disabled = false;
                    confirmBtn.innerHTML = '<i class="fas fa-check"></i> Xác nhận thanh toán';
                }
            } else {
                console.error('HTTP Error:', xhr.status);
                alert('Lỗi kết nối đến server (Status: ' + xhr.status + ')');
                confirmBtn.disabled = false;
                confirmBtn.innerHTML = '<i class="fas fa-check"></i> Xác nhận thanh toán';
            }
        }
    };
    
    var requestData = JSON.stringify({
        booking_id: currentBookingId,
        payment_method: selectedMethod,
        promo_code: document.getElementById('promoCode').value || null,
        final_amount: finalAmount
    });
    console.log('Sending request:', requestData);
    xhr.send(requestData);
}