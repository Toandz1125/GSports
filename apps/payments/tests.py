from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import OwnerProfile, Role, UserRole, Wallet, WalletTransaction
from apps.bookings.models import Booking, BookingPackage, BookingSlot
from apps.payments.models import Invoice, Payment, Promotion
from apps.venues.models import Field, FieldType, Sport, Venue


def future_date(days=14):
    return timezone.localdate() + timedelta(days=days)


class BookingCheckoutWalletPaymentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username='pay-customer',
            email='pay-customer@example.com',
            password='password',
        )
        self.other_customer = User.objects.create_user(
            username='pay-other',
            email='pay-other@example.com',
            password='password',
        )
        self.owner_user = User.objects.create_user(
            username='pay-owner',
            email='pay-owner@example.com',
            password='password',
        )
        self.admin_user = User.objects.create_user(
            username='pay-admin',
            email='pay-admin@example.com',
            password='password',
        )
        self.staff_user = User.objects.create_user(
            username='pay-staff',
            email='pay-staff@example.com',
            password='password',
        )
        self.owner_profile = OwnerProfile.objects.create(
            user=self.owner_user,
            business_name='Payment Owner',
        )
        owner_role, _ = Role.objects.get_or_create(name=Role.OWNER)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        staff_role, _ = Role.objects.get_or_create(name=Role.STAFF)
        UserRole.objects.update_or_create(user=self.owner_user, defaults={'role': owner_role})
        UserRole.objects.update_or_create(user=self.admin_user, defaults={'role': admin_role})
        UserRole.objects.update_or_create(user=self.staff_user, defaults={'role': staff_role})
        self.sport = Sport.objects.create(name='Payment Tennis', slug='payment-tennis')
        self.field_type = FieldType.objects.create(
            sport=self.sport,
            name='Outdoor',
            slug='payment-outdoor',
            player_count=2,
        )
        self.venue = Venue.objects.create(
            owner=self.owner_profile,
            name='Payment Venue',
            address='1 Payment Street',
            status='ACTIVE',
        )
        self.field = Field.objects.create(
            venue=self.venue,
            field_type=self.field_type,
            name='Payment Court',
            status='ACTIVE',
        )
        self.other_venue = Venue.objects.create(
            owner=self.owner_profile,
            name='Other Payment Venue',
            address='2 Payment Street',
            status='ACTIVE',
        )
        self.other_field = Field.objects.create(
            venue=self.other_venue,
            field_type=self.field_type,
            name='Other Payment Court',
            status='ACTIVE',
        )
        self.wallet = Wallet.objects.get(user=self.customer)
        self.other_wallet = Wallet.objects.get(user=self.other_customer)

    def _make_booking(
        self,
        user=None,
        *,
        status=Booking.PENDING,
        amount=Decimal('120000.50'),
        deadline_minutes=10,
        venue=None,
        field=None,
        days=14,
    ):
        user = user or self.customer
        venue = venue or self.venue
        field = field or self.field
        package = BookingPackage.objects.create(
            user=user,
            package_type=BookingPackage.SINGLE,
            start_date=future_date(days),
        )
        deadline = None
        if deadline_minutes is not None:
            deadline = timezone.now() + timedelta(minutes=deadline_minutes)
        booking = Booking.objects.create(
            booking_package=package,
            venue=venue,
            field=field,
            booking_date=future_date(days),
            status=status,
            booking_channel=Booking.WEB,
            total_amount=amount,
            payment_deadline=deadline,
        )
        BookingSlot.objects.create(
            booking=booking,
            start_time=time(9, 0),
            end_time=time(10, 0),
            price=amount,
        )
        return booking

    def _checkout_url(self, booking):
        return reverse('payments:booking_checkout', kwargs={'booking_pk': booking.pk})

    def _detail_url(self, booking):
        return reverse('bookings:booking_detail', kwargs={'pk': booking.pk})

    def _set_wallet_balance(self, amount):
        self.wallet.balance = Decimal(str(amount))
        self.wallet.save(update_fields=['balance'])

    def test_payment_tables_exist_in_migrated_database(self):
        table_names = connection.introspection.table_names()

        self.assertIn(Payment._meta.db_table, table_names)
        self.assertIn(Invoice._meta.db_table, table_names)
        self.assertIn(Promotion._meta.db_table, table_names)
        self.assertEqual(Payment._meta.db_table, 'payment')
        self.assertEqual(Invoice._meta.db_table, 'invoice')
        self.assertEqual(Promotion._meta.db_table, 'promotion')
        with connection.cursor() as cursor:
            payment_columns = {
                column.name
                for column in connection.introspection.get_table_description(cursor, Payment._meta.db_table)
            }
            invoice_columns = {
                column.name
                for column in connection.introspection.get_table_description(cursor, Invoice._meta.db_table)
            }
            promotion_columns = {
                column.name
                for column in connection.introspection.get_table_description(cursor, Promotion._meta.db_table)
            }
        self.assertIn('created_at', payment_columns)
        self.assertIn('subtotal_amount', invoice_columns)
        self.assertIn('total_amount', invoice_columns)
        self.assertIn('is_active', promotion_columns)

    def test_anonymous_checkout_redirects_to_login(self):
        booking = self._make_booking()
        response = self.client.get(self._checkout_url(booking))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dang-nhap/', response['Location'])

    def test_customer_can_open_own_checkout(self):
        booking = self._make_booking()
        self._set_wallet_balance('200000.00')
        self.client.force_login(self.customer)

        response = self.client.get(self._checkout_url(booking))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment Venue')
        self.assertContains(response, 'Thanh toán bằng ví')
        self.assertContains(response, 'Số dư sau thanh toán')

    def test_customer_cannot_open_other_customers_checkout(self):
        other_booking = self._make_booking(
            user=self.other_customer,
            venue=self.other_venue,
            field=self.other_field,
        )
        self.client.force_login(self.customer)

        response = self.client.get(self._checkout_url(other_booking))

        self.assertEqual(response.status_code, 404)

    def test_owner_role_user_can_open_checkout_for_own_booking(self):
        booking = self._make_booking(user=self.owner_user)
        self.owner_user.wallet.balance = Decimal('200000.00')
        self.owner_user.wallet.save(update_fields=['balance'])
        self.client.force_login(self.owner_user)

        response = self.client.get(self._checkout_url(booking))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Thanh toán bằng ví')

    def test_privileged_users_get_404_for_booking_they_do_not_own(self):
        booking = self._make_booking(user=self.customer)

        for user in (self.owner_user, self.admin_user, self.staff_user):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(self._checkout_url(booking))

                self.assertEqual(response.status_code, 404)
                self.client.logout()

    def test_get_checkout_does_not_mutate_payment_wallet_or_booking(self):
        booking = self._make_booking()
        self._set_wallet_balance('200000.00')
        before_balance = self.wallet.balance
        self.client.force_login(self.customer)

        response = self.client.get(self._checkout_url(booking))

        self.assertEqual(response.status_code, 200)
        self.wallet.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(self.wallet.balance, before_balance)
        self.assertEqual(booking.status, Booking.PENDING)
        self.assertFalse(Payment.objects.filter(booking=booking).exists())
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(WalletTransaction.objects.filter(wallet=self.wallet).exists())

    def test_wallet_pay_with_enough_balance_completes_all_records(self):
        booking = self._make_booking()
        self._set_wallet_balance('200000.00')
        self.client.force_login(self.customer)

        response = self.client.post(
            self._checkout_url(booking),
            {'action': 'wallet_pay', 'amount': '1', 'status': 'COMPLETED'},
        )

        self.assertRedirects(response, self._detail_url(booking))
        self.wallet.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('79999.50'))
        self.assertEqual(booking.status, Booking.PAID)

        payment = Payment.objects.get(booking=booking)
        self.assertEqual(payment.method, Payment.Method.WALLET)
        self.assertEqual(payment.payment_type, Payment.PaymentType.FINAL)
        self.assertEqual(payment.status, Payment.Status.COMPLETED)
        self.assertEqual(payment.amount, booking.total_amount)
        self.assertIsNotNone(payment.paid_at)
        self.assertTrue(payment.transaction_code.startswith('WALLET-'))

        wallet_tx = WalletTransaction.objects.get(wallet=self.wallet)
        self.assertEqual(wallet_tx.transaction_type, WalletTransaction.DEBIT)
        self.assertEqual(wallet_tx.reference_type, WalletTransaction.BOOKING)
        self.assertEqual(wallet_tx.reference_id, str(booking.pk))
        self.assertEqual(wallet_tx.status, 'COMPLETED')
        self.assertEqual(wallet_tx.final_amount, booking.total_amount)
        self.assertIn(f'Thanh toán booking {booking.pk}', wallet_tx.description)

        invoice = Invoice.objects.get(payment=payment)
        self.assertEqual(invoice.subtotal_amount, booking.total_amount)
        self.assertEqual(invoice.total_amount, booking.total_amount)

    def test_wallet_pay_with_insufficient_balance_rolls_back(self):
        booking = self._make_booking()
        self._set_wallet_balance('50000.00')
        self.client.force_login(self.customer)

        response = self.client.post(
            self._checkout_url(booking),
            {'action': 'wallet_pay'},
            follow=True,
        )

        self.assertContains(response, 'Số dư ví không đủ')
        self.wallet.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('50000.00'))
        self.assertEqual(booking.status, Booking.PENDING)
        self.assertFalse(Payment.objects.filter(booking=booking, status=Payment.Status.COMPLETED).exists())
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(WalletTransaction.objects.filter(wallet=self.wallet).exists())

    def test_double_post_debits_wallet_once(self):
        booking = self._make_booking()
        self._set_wallet_balance('300000.00')
        self.client.force_login(self.customer)

        first = self.client.post(self._checkout_url(booking), {'action': 'wallet_pay'})
        second = self.client.post(self._checkout_url(booking), {'action': 'wallet_pay'})

        self.assertRedirects(first, self._detail_url(booking))
        self.assertRedirects(second, self._detail_url(booking))
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('179999.50'))
        self.assertEqual(Payment.objects.filter(booking=booking, status=Payment.Status.COMPLETED).count(), 1)
        self.assertEqual(Invoice.objects.filter(payment__booking=booking).count(), 1)
        self.assertEqual(WalletTransaction.objects.filter(wallet=self.wallet, reference_id=str(booking.pk)).count(), 1)

    def test_paid_booking_post_does_not_debit_again(self):
        booking = self._make_booking(status=Booking.PAID)
        self._set_wallet_balance('200000.00')
        self.client.force_login(self.customer)

        response = self.client.post(self._checkout_url(booking), {'action': 'wallet_pay'})

        self.assertRedirects(response, self._detail_url(booking))
        self.wallet.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('200000.00'))
        self.assertEqual(booking.status, Booking.PAID)
        self.assertFalse(WalletTransaction.objects.filter(wallet=self.wallet).exists())

    def test_paid_booking_get_redirects_to_detail_without_checkout(self):
        booking = self._make_booking(status=Booking.PAID)
        self.client.force_login(self.customer)

        response = self.client.get(self._checkout_url(booking), follow=True)

        self.assertRedirects(response, self._detail_url(booking))
        self.assertContains(response, 'Booking đã được thanh toán')
        self.assertNotContains(response, 'Thanh toán bằng ví')

    def test_cancelled_booking_get_redirects_to_detail_without_checkout(self):
        booking = self._make_booking(status=Booking.CANCELLED)
        self.client.force_login(self.customer)

        response = self.client.get(self._checkout_url(booking), follow=True)

        self.assertRedirects(response, self._detail_url(booking))
        self.assertContains(response, 'Booking hiện không thể thanh toán')
        self.assertNotContains(response, 'Thanh toán bằng ví')

    def test_expired_booking_is_cancelled_and_not_paid(self):
        booking = self._make_booking(deadline_minutes=-1)
        self._set_wallet_balance('200000.00')
        self.client.force_login(self.customer)

        response = self.client.post(
            self._checkout_url(booking),
            {'action': 'wallet_pay'},
            follow=True,
        )

        self.assertContains(response, 'Không thể thanh toán')
        self.wallet.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('200000.00'))
        self.assertEqual(booking.status, Booking.CANCELLED)
        self.assertFalse(Payment.objects.filter(booking=booking, status=Payment.Status.COMPLETED).exists())
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(WalletTransaction.objects.filter(wallet=self.wallet).exists())

    def test_expired_booking_get_redirects_to_detail_and_cancels(self):
        booking = self._make_booking(deadline_minutes=-1)
        self.client.force_login(self.customer)

        response = self.client.get(self._checkout_url(booking), follow=True)

        self.assertRedirects(response, self._detail_url(booking))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.CANCELLED)
        self.assertContains(response, 'Đơn đặt sân đã quá hạn thanh toán và đã bị hủy.')
        self.assertNotContains(response, 'Thanh toán bằng ví')

    def test_payment_amount_ignores_fake_post_amount(self):
        booking = self._make_booking(amount=Decimal('135000.75'))
        self._set_wallet_balance('200000.00')
        self.client.force_login(self.customer)

        self.client.post(self._checkout_url(booking), {'action': 'wallet_pay', 'amount': '1'})

        payment = Payment.objects.get(booking=booking)
        self.wallet.refresh_from_db()
        self.assertEqual(payment.amount, Decimal('135000.75'))
        self.assertEqual(self.wallet.balance, Decimal('64999.25'))

    def test_template_disables_wallet_button_when_balance_is_low(self):
        booking = self._make_booking()
        self._set_wallet_balance('50000.00')
        self.client.force_login(self.customer)

        response = self.client.get(self._checkout_url(booking))

        self.assertContains(response, 'Số dư ví không đủ')
        self.assertContains(response, 'disabled aria-disabled="true"')

    def test_template_enables_wallet_button_when_balance_is_enough(self):
        booking = self._make_booking()
        self._set_wallet_balance('200000.00')
        self.client.force_login(self.customer)

        response = self.client.get(self._checkout_url(booking))

        self.assertContains(response, 'Thanh toán bằng ví')
        self.assertNotContains(response, 'disabled aria-disabled="true"')


class BookingInvoiceViewTests(TestCase):
    """Invoice / receipt page (payments:booking_invoice) scoped by role."""

    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username='inv-customer', email='inv-customer@example.com', password='password',
        )
        self.other_customer = User.objects.create_user(
            username='inv-other', email='inv-other@example.com', password='password',
        )
        self.owner_user = User.objects.create_user(
            username='inv-owner', email='inv-owner@example.com', password='password',
        )
        self.other_owner_user = User.objects.create_user(
            username='inv-owner2', email='inv-owner2@example.com', password='password',
        )
        self.admin_user = User.objects.create_user(
            username='inv-admin', email='inv-admin@example.com', password='password',
        )
        self.owner_profile = OwnerProfile.objects.create(
            user=self.owner_user, business_name='Invoice Owner',
        )
        self.other_owner_profile = OwnerProfile.objects.create(
            user=self.other_owner_user, business_name='Other Invoice Owner',
        )
        owner_role, _ = Role.objects.get_or_create(name=Role.OWNER)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        UserRole.objects.update_or_create(user=self.owner_user, defaults={'role': owner_role})
        UserRole.objects.update_or_create(user=self.other_owner_user, defaults={'role': owner_role})
        UserRole.objects.update_or_create(user=self.admin_user, defaults={'role': admin_role})
        self.sport = Sport.objects.create(name='Invoice Tennis', slug='invoice-tennis')
        self.field_type = FieldType.objects.create(
            sport=self.sport, name='Inv Outdoor', slug='inv-outdoor', player_count=2,
        )
        self.venue = Venue.objects.create(
            owner=self.owner_profile, name='Invoice Venue', address='1 Invoice St', status='ACTIVE',
        )
        self.field = Field.objects.create(
            venue=self.venue, field_type=self.field_type, name='Invoice Court', status='ACTIVE',
        )
        self.other_venue = Venue.objects.create(
            owner=self.other_owner_profile, name='Foreign Venue', address='9 Foreign St', status='ACTIVE',
        )
        self.other_field = Field.objects.create(
            venue=self.other_venue, field_type=self.field_type, name='Foreign Court', status='ACTIVE',
        )

    def _make_booking(self, user=None, *, status=Booking.PAID, deadline_minutes=10,
                      venue=None, field=None, amount=Decimal('120000.00'), days=14):
        user = user or self.customer
        venue = venue or self.venue
        field = field or self.field
        package = BookingPackage.objects.create(
            user=user, package_type=BookingPackage.SINGLE, start_date=future_date(days),
        )
        deadline = timezone.now() + timedelta(minutes=deadline_minutes) if deadline_minutes is not None else None
        booking = Booking.objects.create(
            booking_package=package, venue=venue, field=field, booking_date=future_date(days),
            status=status, booking_channel=Booking.WEB, total_amount=amount, payment_deadline=deadline,
        )
        BookingSlot.objects.create(
            booking=booking, start_time=time(9, 0), end_time=time(10, 0), price=amount,
        )
        return booking

    def _add_completed_payment(self, booking, with_invoice=True):
        payment = Payment.objects.create(
            booking=booking, method=Payment.Method.WALLET, payment_type=Payment.PaymentType.FINAL,
            amount=booking.total_amount, status=Payment.Status.COMPLETED,
            transaction_code=f'WALLET-{booking.pk.hex[:12]}', paid_at=timezone.now(),
        )
        if with_invoice:
            Invoice.objects.create(
                payment=payment, invoice_code=f'INV-{booking.pk.hex[:12]}',
                subtotal_amount=booking.total_amount, total_amount=booking.total_amount,
            )
        return payment

    def _invoice_url(self, booking):
        return reverse('payments:booking_invoice', kwargs={'booking_pk': booking.pk})

    def test_anonymous_invoice_redirects_to_login(self):
        booking = self._make_booking()
        response = self.client.get(self._invoice_url(booking))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dang-nhap/', response['Location'])

    def test_customer_can_view_own_paid_invoice(self):
        booking = self._make_booking()
        payment = self._add_completed_payment(booking)
        self.client.force_login(self.customer)

        response = self.client.get(self._invoice_url(booking))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invoice Venue')
        self.assertContains(response, payment.invoice.invoice_code)
        self.assertContains(response, payment.transaction_code)
        self.assertNotContains(response, 'Chưa có mã hóa đơn chính thức')

    def test_customer_cannot_view_other_customers_invoice(self):
        booking = self._make_booking(user=self.other_customer)
        self._add_completed_payment(booking)
        self.client.force_login(self.customer)

        response = self.client.get(self._invoice_url(booking))

        self.assertEqual(response.status_code, 404)

    def test_owner_can_view_invoice_for_own_venue_booking(self):
        booking = self._make_booking(user=self.customer)
        self._add_completed_payment(booking)
        self.client.force_login(self.owner_user)

        response = self.client.get(self._invoice_url(booking))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invoice Venue')

    def test_owner_cannot_view_invoice_for_other_owners_venue(self):
        booking = self._make_booking(user=self.other_customer, venue=self.other_venue, field=self.other_field)
        self._add_completed_payment(booking)
        self.client.force_login(self.owner_user)

        response = self.client.get(self._invoice_url(booking))

        self.assertEqual(response.status_code, 404)

    def test_admin_can_view_any_invoice(self):
        booking = self._make_booking(user=self.customer)
        self._add_completed_payment(booking)
        self.client.force_login(self.admin_user)

        response = self.client.get(self._invoice_url(booking))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invoice Venue')

    def test_paid_booking_without_invoice_record_renders_fallback(self):
        # PAID booking, no Payment/Invoice rows at all -> fallback receipt, no crash.
        booking = self._make_booking(status=Booking.PAID)
        self.client.force_login(self.customer)

        response = self.client.get(self._invoice_url(booking))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Chưa có mã hóa đơn chính thức')
        self.assertContains(response, 'Invoice Venue')

    def test_completed_payment_without_invoice_renders_fallback(self):
        booking = self._make_booking(status=Booking.PAID)
        self._add_completed_payment(booking, with_invoice=False)
        self.client.force_login(self.customer)

        response = self.client.get(self._invoice_url(booking))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Chưa có mã hóa đơn chính thức')

    def test_payable_booking_redirects_owner_to_checkout(self):
        booking = self._make_booking(status=Booking.PENDING, deadline_minutes=10)
        self.client.force_login(self.customer)

        response = self.client.get(self._invoice_url(booking), follow=True)

        self.assertRedirects(response, reverse('payments:booking_checkout', kwargs={'booking_pk': booking.pk}))
        self.assertContains(response, 'Vui lòng tiếp tục thanh toán')

    def test_cancelled_booking_renders_receipt_without_pay_button(self):
        booking = self._make_booking(status=Booking.CANCELLED, deadline_minutes=None)
        self.client.force_login(self.customer)

        response = self.client.get(self._invoice_url(booking))

        checkout_url = reverse('payments:booking_checkout', kwargs={'booking_pk': booking.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invoice Venue')
        self.assertNotContains(response, f'href="{checkout_url}"')

    def test_expired_pending_booking_is_cancelled_and_renders_receipt(self):
        # An expired hold is flipped to CANCELLED on view (timeout logic), so the
        # owner is not redirected to checkout and the receipt shows no pay button.
        booking = self._make_booking(status=Booking.PENDING, deadline_minutes=-1)
        self.client.force_login(self.customer)

        response = self.client.get(self._invoice_url(booking))
        booking.refresh_from_db()

        self.assertEqual(booking.status, Booking.CANCELLED)
        self.assertEqual(response.status_code, 200)
        # Cancelled receipt has no checkout link.
        checkout_url = reverse('payments:booking_checkout', kwargs={'booking_pk': booking.pk})
        self.assertNotContains(response, f'href="{checkout_url}"')

    def test_invoice_view_does_not_create_payment_or_invoice(self):
        booking = self._make_booking(status=Booking.PAID)
        self.client.force_login(self.customer)

        self.client.get(self._invoice_url(booking))

        self.assertFalse(Payment.objects.filter(booking=booking).exists())
        self.assertFalse(Invoice.objects.exists())
