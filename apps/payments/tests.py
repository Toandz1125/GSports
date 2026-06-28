from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import OwnerProfile
from apps.bookings.models import Booking, BookingPackage, BookingSlot
from apps.services.models import BookingService, ServiceItem
from apps.venues.models import Field, FieldType, Sport, Venue


class PaymentCheckoutPlaceholderTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username='customer', email='customer@example.com', password='password',
        )
        self.other_customer = User.objects.create_user(
            username='intruder', email='intruder@example.com', password='password',
        )
        self.owner_user = User.objects.create_user(
            username='owner', email='owner@example.com', password='password',
        )
        self.owner_profile = OwnerProfile.objects.create(
            user=self.owner_user, business_name='Owner Business',
        )
        self.sport = Sport.objects.create(name='Football', slug='football')
        self.field_type = FieldType.objects.create(
            sport=self.sport, name='5 a side', slug='football-5', player_count=10,
        )
        self.venue = Venue.objects.create(
            owner=self.owner_profile, name='Main Venue', address='123 Test Street',
        )
        self.field = Field.objects.create(
            venue=self.venue, field_type=self.field_type, name='Field 1',
        )
        self.booking_date = date(2026, 6, 10)
        self.booking = self._make_booking(Booking.PENDING, Decimal('100000.00'))

        self.service_item = ServiceItem.objects.create(
            venue=self.venue, name='Nước suối', category=ServiceItem.DRINK,
            price=Decimal('10000.00'), stock=50,
        )
        BookingService.objects.create(
            booking=self.booking, service_item=self.service_item,
            quantity=2, unit_price=Decimal('10000.00'),
        )

    def _make_booking(self, status, amount):
        package = BookingPackage.objects.create(
            user=self.customer, package_type=BookingPackage.SINGLE,
            start_date=self.booking_date,
        )
        booking = Booking.objects.create(
            booking_package=package, venue=self.venue, field=self.field,
            booking_date=self.booking_date, status=status,
            booking_channel=Booking.WEB, total_amount=amount,
        )
        BookingSlot.objects.create(
            booking=booking, start_time=time(9, 0), end_time=time(10, 0), price=amount,
        )
        return booking

    def _checkout_url(self, booking):
        return reverse('payments:checkout', kwargs={'booking_id': booking.pk})

    def test_anonymous_redirected_to_login(self):
        url = self._checkout_url(self.booking)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_owner_customer_can_load_checkout(self):
        self.client.force_login(self.customer)
        response = self.client.get(self._checkout_url(self.booking))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Thanh toán hoá đơn')
        self.assertContains(response, str(self.booking.id))
        self.assertContains(response, 'Main Venue')
        self.assertContains(response, 'Field 1')
        self.assertContains(response, 'Nước suối')
        self.assertContains(response, 'Chức năng thanh toán đang được phát triển')

    def test_other_user_cannot_access_checkout(self):
        self.client.force_login(self.other_customer)
        response = self.client.get(self._checkout_url(self.booking))
        self.assertEqual(response.status_code, 403)

    def test_venue_owner_can_access_checkout(self):
        self.client.force_login(self.owner_user)
        response = self.client.get(self._checkout_url(self.booking))
        self.assertEqual(response.status_code, 200)

    def test_missing_booking_returns_404(self):
        import uuid
        self.client.force_login(self.customer)
        url = reverse('payments:checkout', kwargs={'booking_id': uuid.uuid4()})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_checkout_does_not_change_booking_status(self):
        self.client.force_login(self.customer)
        self.client.get(self._checkout_url(self.booking))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.PENDING)


class BookingDetailPaymentButtonTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username='customer2', email='customer2@example.com', password='password',
        )
        self.owner_user = User.objects.create_user(
            username='owner2', email='owner2@example.com', password='password',
        )
        self.owner_profile = OwnerProfile.objects.create(
            user=self.owner_user, business_name='Owner Business 2',
        )
        self.sport = Sport.objects.create(name='Tennis', slug='tennis')
        self.field_type = FieldType.objects.create(
            sport=self.sport, name='Outdoor', slug='tennis-outdoor', player_count=2,
        )
        self.venue = Venue.objects.create(
            owner=self.owner_profile, name='Tennis Venue', address='456 Street',
        )
        self.field = Field.objects.create(
            venue=self.venue, field_type=self.field_type, name='Court 1',
        )
        self.booking_date = date(2026, 6, 11)

    def _make_booking(self, status):
        package = BookingPackage.objects.create(
            user=self.customer, package_type=BookingPackage.SINGLE,
            start_date=self.booking_date,
        )
        return Booking.objects.create(
            booking_package=package, venue=self.venue, field=self.field,
            booking_date=self.booking_date, status=status,
            booking_channel=Booking.WEB, total_amount=Decimal('100000.00'),
        )

    def test_payable_booking_shows_payment_link(self):
        booking = self._make_booking(Booking.PENDING)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('bookings:booking_detail', kwargs={'pk': booking.pk}))
        self.assertContains(
            response,
            f'/payments/bookings/{booking.pk}/',
        )
        self.assertContains(response, 'Thanh toán')

    def test_cancelled_booking_hides_payment_link(self):
        booking = self._make_booking(Booking.CANCELLED)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('bookings:booking_detail', kwargs={'pk': booking.pk}))
        self.assertNotContains(
            response,
            f'/payments/bookings/{booking.pk}/',
        )

    def test_paid_booking_hides_payment_link(self):
        booking = self._make_booking(Booking.PAID)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('bookings:booking_detail', kwargs={'pk': booking.pk}))
        self.assertNotContains(
            response,
            f'/payments/bookings/{booking.pk}/',
        )

    def test_waiting_booking_hides_payment_link(self):
        booking = self._make_booking(Booking.WAITING)
        self.client.force_login(self.customer)
        response = self.client.get(reverse('bookings:booking_detail', kwargs={'pk': booking.pk}))
        self.assertNotContains(
            response,
            f'/payments/bookings/{booking.pk}/',
        )
