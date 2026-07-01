from datetime import date, time, timedelta
from decimal import Decimal

try:
    import fakeredis
except ModuleNotFoundError:
    import fnmatch

    class _FakeStrictRedis:
        def __init__(self, *args, **kwargs):
            self._values = {}
            self._sets = {}

        def set(self, key, value, nx=False, ex=None):
            if nx and (key in self._values or key in self._sets):
                return False
            self._values[key] = value
            return True

        def keys(self, pattern):
            keys = list(self._values.keys()) + list(self._sets.keys())
            return [key for key in keys if fnmatch.fnmatch(key, pattern)]

        def sadd(self, key, *values):
            current = self._sets.setdefault(key, set())
            before = len(current)
            current.update(values)
            return len(current) - before

        def expire(self, key, seconds):
            return key in self._values or key in self._sets

        def smembers(self, key):
            return set(self._sets.get(key, set()))

        def delete(self, *keys):
            deleted = 0
            for key in keys:
                if key in self._values:
                    del self._values[key]
                    deleted += 1
                if key in self._sets:
                    del self._sets[key]
                    deleted += 1
            return deleted

        def exists(self, key):
            return key in self._values or key in self._sets

        def flushdb(self):
            self._values.clear()
            self._sets.clear()

    class fakeredis:
        FakeStrictRedis = _FakeStrictRedis
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import include, path, reverse
from django.utils import timezone

from apps.accounts.models import OwnerProfile, Role, UserRole
from apps.bookings.models import Booking, BookingPackage, BookingSlot
from apps.bookings.services import create_booking
from apps.venues.models import Field, FieldType, Sport, Venue
from .models import BookingService, ServiceItem
from .services import add_service_to_booking, remove_service_from_booking, update_booking_service


def _test_login_view(request):
    return HttpResponse('login')


_ACCOUNT_URLPATTERNS = ([
    path('dang-nhap/', _test_login_view, name='login'),
], 'accounts')

urlpatterns = [
    path('', include(_ACCOUNT_URLPATTERNS, namespace='accounts')),
    path('dang-nhap/', _test_login_view, name='login'),
    path('dat-san/', include('apps.bookings.urls')),
    path('services/', include('apps.services.urls')),
]

_SCOPED_TEMPLATE_MAP = {
    'bookings/booking_list.html': (
        '{% load booking_nav %}'
        '{% if user|can_manage_owner_services %}'
        '<a href="{% url "services:owner_serviceitem_list" %}">Owner services</a>'
        '{% endif %}'
        '{% for booking in bookings %}'
        '{{ booking.pk }} {{ booking.venue.name }} {{ booking.field.name }}'
        '{% endfor %}'
    ),
    'bookings/booking_detail.html': (
        '{% for message in messages %}{{ message }}{% endfor %}'
        '{% for service in booking.services_ordered.all %}'
        '<a href="{% url "services:bookingservice_edit" service.pk %}">Chỉnh sửa</a>'
        '<form action="{% url "services:bookingservice_remove" service.pk %}">'
        '<button>Hủy dịch vụ</button></form>'
        '{% empty %}Chưa có dịch vụ.{% endfor %}'
    ),
    'bookings/booking_form.html': '{{ form.as_p }}',
    'bookings/staff_booking_list.html': '',
    'bookings/owner_booking_list.html': '',
    'bookings/partials/_booking_detail_content.html': '{{ booking.status }}',
    'bookings/partials/_booking_management_table.html': (
        '{% for booking in bookings %}{{ booking.pk }} {{ booking.venue.name }}{% endfor %}'
    ),
    'services/serviceitem_list.html': (
        '{% for service in service_items %}{{ service.name }}{% endfor %}'
    ),
    'services/owner_serviceitem_list.html': (
        '<div id="owner-service-item-list">'
        '{% include "services/partials/_owner_serviceitem_list.html" %}'
        '</div>'
    ),
    'services/owner_serviceitem_form.html': '{{ form.as_p }}',
    'services/owner_serviceitem_confirm_delete.html': '{{ service_item.name }}',
    'services/bookingservice_form.html': '{{ form.as_p }}',
    'services/partials/_owner_serviceitem_list.html': (
        '{% for item in service_items %}'
        '{{ item.name }} {% if item.is_active %}ACTIVE{% else %}INACTIVE{% endif %}'
        '<form data-ajax-form action="{% url "services:owner_serviceitem_toggle" item.pk %}"></form>'
        '{% endfor %}'
    ),
}

_SCOPED_TEST_TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': False,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.debug',
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
        'loaders': [
            ('django.template.loaders.locmem.Loader', _SCOPED_TEMPLATE_MAP),
        ],
    },
}]


@override_settings(ROOT_URLCONF=__name__, TEMPLATES=_SCOPED_TEST_TEMPLATES)
class ScopedServiceTestCase(TestCase):
    pass


def future_date(days=30):
    return timezone.localdate() + timedelta(days=days)


class BookingServiceItemTests(ScopedServiceTestCase):
    def setUp(self):
        self.redis_client = fakeredis.FakeStrictRedis(decode_responses=True)
        self.redis_patcher = patch('apps.bookings.services.get_redis_client', return_value=self.redis_client)
        self.redis_patcher.start()
        self.addCleanup(self.redis_patcher.stop)
        self.addCleanup(self.redis_client.flushdb)
        self.redis_client.flushdb()

        User = get_user_model()
        self.customer = User.objects.create_user(
            username='service-customer',
            email='service-customer@example.com',
            password='password',
        )
        self.other_customer = User.objects.create_user(
            username='service-other-customer',
            email='service-other-customer@example.com',
            password='password',
        )
        self.owner_user = User.objects.create_user(
            username='service-owner',
            email='service-owner@example.com',
            password='password',
        )
        self.owner_profile = OwnerProfile.objects.create(
            user=self.owner_user,
            business_name='Service Owner Business',
        )
        self.sport = Sport.objects.create(name='Tennis', slug='tennis')
        self.field_type = FieldType.objects.create(
            sport=self.sport,
            name='Tennis court',
            slug='tennis-court',
            player_count=2,
        )
        self.venue = Venue.objects.create(
            owner=self.owner_profile,
            name='Service Venue',
            address='456 Test Street',
        )
        self.field = Field.objects.create(
            venue=self.venue,
            field_type=self.field_type,
            name='Court 1',
        )
        self.booking = create_booking(
            user=self.customer,
            field=self.field,
            booking_date=future_date(30),
            start_time=time(9, 0),
            end_time=time(10, 0),
            price=Decimal('100000.00'),
        )
        other_package = BookingPackage.objects.create(
            user=self.other_customer,
            package_type=BookingPackage.SINGLE,
            start_date=future_date(31),
        )
        self.other_booking = Booking.objects.create(
            booking_package=other_package,
            venue=self.venue,
            field=self.field,
            booking_date=future_date(31),
            status=Booking.PENDING,
            booking_channel=Booking.WEB,
            total_amount=Decimal('100000.00'),
        )
        BookingSlot.objects.create(
            booking=self.other_booking,
            start_time=time(9, 0),
            end_time=time(10, 0),
            price=Decimal('100000.00'),
        )
        self.service_item = ServiceItem.objects.create(
            venue=self.venue,
            name='Water',
            category=ServiceItem.DRINK,
            price=Decimal('10000.00'),
            stock=10,
        )

    def _detail_url(self):
        return reverse('bookings:booking_detail', kwargs={'pk': self.booking.pk})

    def _lock_booking(self, status):
        self.booking.status = status
        self.booking.save(update_fields=['status', 'updated_at'])

    def _assert_locked_redirect(self, response, message):
        self.assertEqual(response.redirect_chain[-1][0], self._detail_url())
        self.assertContains(response, message)

    def test_add_service_to_booking_success(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=2,
        )

        self.service_item.refresh_from_db()
        self.assertEqual(booking_service.quantity, 2)
        self.assertEqual(booking_service.unit_price, Decimal('10000.00'))
        self.assertEqual(self.service_item.stock, 8)

    def test_prevent_add_service_when_stock_insufficient(self):
        with self.assertRaises(ValidationError):
            add_service_to_booking(
                booking=self.booking,
                service_item=self.service_item,
                quantity=11,
            )

        self.service_item.refresh_from_db()
        self.assertEqual(self.service_item.stock, 10)

    def test_unit_price_is_snapshotted(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=1,
        )

        self.service_item.price = Decimal('20000.00')
        self.service_item.save(update_fields=['price'])
        booking_service.refresh_from_db()
        self.assertEqual(booking_service.unit_price, Decimal('10000.00'))

    def test_update_service_quantity_adjusts_stock(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=2,
        )

        update_booking_service(
            booking_service=booking_service,
            service_item=self.service_item,
            quantity=5,
        )

        booking_service.refresh_from_db()
        self.service_item.refresh_from_db()
        self.assertEqual(booking_service.quantity, 5)
        self.assertEqual(self.service_item.stock, 5)

    def test_update_service_item_restores_old_stock(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=2,
        )
        towel = ServiceItem.objects.create(
            venue=self.venue,
            name='Towel',
            category=ServiceItem.EQUIPMENT,
            price=Decimal('15000.00'),
            stock=4,
        )

        update_booking_service(
            booking_service=booking_service,
            service_item=towel,
            quantity=3,
        )

        booking_service.refresh_from_db()
        self.service_item.refresh_from_db()
        towel.refresh_from_db()
        self.assertEqual(booking_service.service_item, towel)
        self.assertEqual(booking_service.quantity, 3)
        self.assertEqual(booking_service.unit_price, Decimal('15000.00'))
        self.assertEqual(self.service_item.stock, 10)
        self.assertEqual(towel.stock, 1)

    def test_remove_service_restores_stock(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=2,
        )

        remove_service_from_booking(booking_service)

        self.service_item.refresh_from_db()
        self.assertEqual(self.service_item.stock, 10)
        self.assertFalse(BookingService.objects.filter(pk=booking_service.pk).exists())

    def test_customer_cannot_add_service_to_other_customers_booking(self):
        original_stock = self.service_item.stock
        original_total = self.other_booking.total_amount
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('services:bookingservice_add', kwargs={'booking_pk': self.other_booking.pk}),
            {'service_item': self.service_item.pk, 'quantity': 2},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(BookingService.objects.filter(booking=self.other_booking).exists())
        self.service_item.refresh_from_db()
        self.other_booking.refresh_from_db()
        self.assertEqual(self.service_item.stock, original_stock)
        self.assertEqual(self.other_booking.total_amount, original_total)

    def test_customer_cannot_edit_other_customers_booking_service(self):
        booking_service = BookingService.objects.create(
            booking=self.other_booking,
            service_item=self.service_item,
            quantity=2,
            unit_price=Decimal('10000.00'),
        )
        original_stock = self.service_item.stock
        original_total = self.other_booking.total_amount
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('services:bookingservice_edit', kwargs={'pk': booking_service.pk}),
            {'service_item': self.service_item.pk, 'quantity': 4},
        )

        self.assertEqual(response.status_code, 403)
        booking_service.refresh_from_db()
        self.service_item.refresh_from_db()
        self.other_booking.refresh_from_db()
        self.assertEqual(booking_service.quantity, 2)
        self.assertEqual(self.service_item.stock, original_stock)
        self.assertEqual(self.other_booking.total_amount, original_total)

    def test_customer_cannot_remove_other_customers_booking_service(self):
        booking_service = BookingService.objects.create(
            booking=self.other_booking,
            service_item=self.service_item,
            quantity=2,
            unit_price=Decimal('10000.00'),
        )
        original_stock = self.service_item.stock
        original_total = self.other_booking.total_amount
        self.client.force_login(self.customer)

        response = self.client.post(reverse('services:bookingservice_remove', kwargs={'pk': booking_service.pk}))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(BookingService.objects.filter(pk=booking_service.pk).exists())
        self.service_item.refresh_from_db()
        self.other_booking.refresh_from_db()
        self.assertEqual(self.service_item.stock, original_stock)
        self.assertEqual(self.other_booking.total_amount, original_total)

    def test_paid_booking_cannot_add_service(self):
        self._lock_booking(Booking.PAID)
        original_total = self.booking.total_amount
        original_stock = self.service_item.stock
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('services:bookingservice_add', kwargs={'booking_pk': self.booking.pk}),
            {'service_item': self.service_item.pk, 'quantity': 2},
            follow=True,
        )

        self._assert_locked_redirect(response, 'Booking đã thanh toán, không thể chỉnh sửa dịch vụ.')
        self.assertFalse(BookingService.objects.filter(booking=self.booking).exists())
        self.booking.refresh_from_db()
        self.service_item.refresh_from_db()
        self.assertEqual(self.booking.total_amount, original_total)
        self.assertEqual(self.service_item.stock, original_stock)

    def test_paid_booking_cannot_edit_service(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=2,
        )
        self.booking.refresh_from_db()
        self.service_item.refresh_from_db()
        self._lock_booking(Booking.PAID)
        original_total = self.booking.total_amount
        original_stock = self.service_item.stock
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('services:bookingservice_edit', kwargs={'pk': booking_service.pk}),
            {'service_item': self.service_item.pk, 'quantity': 4},
            follow=True,
        )

        self._assert_locked_redirect(response, 'Booking đã thanh toán, không thể chỉnh sửa dịch vụ.')
        booking_service.refresh_from_db()
        self.booking.refresh_from_db()
        self.service_item.refresh_from_db()
        self.assertEqual(booking_service.quantity, 2)
        self.assertEqual(self.booking.total_amount, original_total)
        self.assertEqual(self.service_item.stock, original_stock)

    def test_paid_booking_cannot_remove_service(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=2,
        )
        self.booking.refresh_from_db()
        self.service_item.refresh_from_db()
        self._lock_booking(Booking.PAID)
        original_total = self.booking.total_amount
        original_stock = self.service_item.stock
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('services:bookingservice_remove', kwargs={'pk': booking_service.pk}),
            follow=True,
        )

        self._assert_locked_redirect(response, 'Booking đã thanh toán, không thể chỉnh sửa dịch vụ.')
        booking_service.refresh_from_db()
        self.booking.refresh_from_db()
        self.service_item.refresh_from_db()
        self.assertTrue(BookingService.objects.filter(pk=booking_service.pk).exists())
        self.assertEqual(self.booking.total_amount, original_total)
        self.assertEqual(self.service_item.stock, original_stock)

    def test_cancelled_booking_cannot_add_service(self):
        self._lock_booking(Booking.CANCELLED)
        original_total = self.booking.total_amount
        original_stock = self.service_item.stock
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('services:bookingservice_add', kwargs={'booking_pk': self.booking.pk}),
            {'service_item': self.service_item.pk, 'quantity': 2},
            follow=True,
        )

        self._assert_locked_redirect(response, 'Booking đã hủy, không thể chỉnh sửa dịch vụ.')
        self.assertFalse(BookingService.objects.filter(booking=self.booking).exists())
        self.booking.refresh_from_db()
        self.service_item.refresh_from_db()
        self.assertEqual(self.booking.total_amount, original_total)
        self.assertEqual(self.service_item.stock, original_stock)

    def test_cancelled_booking_cannot_edit_service(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=2,
        )
        self.booking.refresh_from_db()
        self.service_item.refresh_from_db()
        self._lock_booking(Booking.CANCELLED)
        original_total = self.booking.total_amount
        original_stock = self.service_item.stock
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('services:bookingservice_edit', kwargs={'pk': booking_service.pk}),
            {'service_item': self.service_item.pk, 'quantity': 4},
            follow=True,
        )

        self._assert_locked_redirect(response, 'Booking đã hủy, không thể chỉnh sửa dịch vụ.')
        booking_service.refresh_from_db()
        self.booking.refresh_from_db()
        self.service_item.refresh_from_db()
        self.assertEqual(booking_service.quantity, 2)
        self.assertEqual(self.booking.total_amount, original_total)
        self.assertEqual(self.service_item.stock, original_stock)

    def test_cancelled_booking_cannot_remove_service(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=2,
        )
        self.booking.refresh_from_db()
        self.service_item.refresh_from_db()
        self._lock_booking(Booking.CANCELLED)
        original_total = self.booking.total_amount
        original_stock = self.service_item.stock
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('services:bookingservice_remove', kwargs={'pk': booking_service.pk}),
            follow=True,
        )

        self._assert_locked_redirect(response, 'Booking đã hủy, không thể chỉnh sửa dịch vụ.')
        booking_service.refresh_from_db()
        self.booking.refresh_from_db()
        self.service_item.refresh_from_db()
        self.assertTrue(BookingService.objects.filter(pk=booking_service.pk).exists())
        self.assertEqual(self.booking.total_amount, original_total)
        self.assertEqual(self.service_item.stock, original_stock)

    def test_booking_detail_shows_edit_and_remove_service_buttons(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=2,
        )
        self.client.force_login(self.customer)

        response = self.client.get(reverse('bookings:booking_detail', kwargs={'pk': self.booking.pk}))

        self.assertContains(response, reverse('services:bookingservice_edit', kwargs={'pk': booking_service.pk}))
        self.assertContains(response, reverse('services:bookingservice_remove', kwargs={'pk': booking_service.pk}))
        self.assertContains(response, 'Chỉnh sửa')
        self.assertContains(response, 'Hủy dịch vụ')

    def test_edit_booking_service_view_updates_service(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=2,
        )
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('services:bookingservice_edit', kwargs={'pk': booking_service.pk}),
            {'service_item': self.service_item.pk, 'quantity': 4},
        )

        self.assertRedirects(response, reverse('bookings:booking_detail', kwargs={'pk': self.booking.pk}))
        booking_service.refresh_from_db()
        self.service_item.refresh_from_db()
        self.assertEqual(booking_service.quantity, 4)
        self.assertEqual(self.service_item.stock, 6)

    def test_remove_booking_service_view_deletes_service(self):
        booking_service = add_service_to_booking(
            booking=self.booking,
            service_item=self.service_item,
            quantity=2,
        )
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('services:bookingservice_remove', kwargs={'pk': booking_service.pk}),
        )

        self.assertRedirects(response, reverse('bookings:booking_detail', kwargs={'pk': self.booking.pk}))
        self.service_item.refresh_from_db()
        self.assertEqual(self.service_item.stock, 10)
        self.assertFalse(BookingService.objects.filter(pk=booking_service.pk).exists())


class OwnerServiceItemCrudTests(ScopedServiceTestCase):
    def setUp(self):
        User = get_user_model()
        self.owner_role = Role.objects.create(name=Role.OWNER)
        self.customer_role = Role.objects.create(name=Role.CUSTOMER)
        self.admin_role = Role.objects.create(name=Role.ADMIN)

        self.owner_a_user = User.objects.create_user(
            username='service-owner-a',
            email='service-owner-a@example.com',
            password='password',
        )
        UserRole.objects.create(user=self.owner_a_user, role=self.owner_role)
        self.owner_a = OwnerProfile.objects.create(
            user=self.owner_a_user,
            business_name='Service Owner A',
            is_verified=True,
        )

        self.owner_b_user = User.objects.create_user(
            username='service-owner-b',
            email='service-owner-b@example.com',
            password='password',
        )
        UserRole.objects.create(user=self.owner_b_user, role=self.owner_role)
        self.owner_b = OwnerProfile.objects.create(
            user=self.owner_b_user,
            business_name='Service Owner B',
            is_verified=True,
        )

        self.customer = User.objects.create_user(
            username='service-customer-crud',
            email='service-customer-crud@example.com',
            password='password',
        )
        UserRole.objects.create(user=self.customer, role=self.customer_role)

        self.admin = User.objects.create_user(
            username='service-admin',
            email='service-admin@example.com',
            password='password',
        )
        UserRole.objects.create(user=self.admin, role=self.admin_role)

        self.sport = Sport.objects.create(name='Badminton', slug='badminton-service-crud')
        self.field_type = FieldType.objects.create(
            sport=self.sport,
            name='Indoor',
            slug='badminton-service-crud-indoor',
            player_count=4,
        )
        self.venue_a = Venue.objects.create(
            owner=self.owner_a,
            name='Service Venue A',
            address='1 Service Street',
        )
        self.venue_b = Venue.objects.create(
            owner=self.owner_b,
            name='Service Venue B',
            address='2 Service Street',
        )

    def _payload(self, **overrides):
        payload = {
            'venue': self.venue_a.pk,
            'name': '  Sports Drink  ',
            'category': ServiceItem.DRINK,
            'price': '12000.00',
            'stock': '10',
        }
        payload.update(overrides)
        return payload

    def test_owner_creates_service_item_for_own_venue(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.post(reverse('services:owner_serviceitem_create'), self._payload())

        self.assertRedirects(response, reverse('services:owner_serviceitem_list'))
        service_item = ServiceItem.objects.get(name='Sports Drink')
        self.assertEqual(service_item.venue, self.venue_a)
        self.assertEqual(service_item.price, Decimal('12000.00'))
        self.assertEqual(service_item.stock, 10)

    def test_service_create_form_does_not_render_is_active_field(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.get(reverse('services:owner_serviceitem_create'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('is_active', response.context['form'].fields)
        self.assertNotContains(response, 'name="is_active"')

    def test_new_service_item_defaults_to_active(self):
        self.client.force_login(self.owner_a_user)

        self.client.post(reverse('services:owner_serviceitem_create'), self._payload(name='Defaulted Item'))

        service_item = ServiceItem.objects.get(name='Defaulted Item')
        self.assertTrue(service_item.is_active)

    def test_owner_cannot_create_service_item_for_other_owner_venue(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.post(
            reverse('services:owner_serviceitem_create'),
            self._payload(venue=self.venue_b.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ServiceItem.objects.filter(name='Sports Drink').exists())
        self.assertTrue(response.context['form'].has_error('venue', code='invalid_choice'))

    def test_non_owner_cannot_access_owner_service_item_create(self):
        self.client.force_login(self.customer)

        response = self.client.post(reverse('services:owner_serviceitem_create'), self._payload())

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ServiceItem.objects.exists())

    def test_owner_sees_owner_service_menu_link(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.get(reverse('bookings:booking_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("services:owner_serviceitem_list")}"')

    def test_admin_does_not_see_owner_service_menu_link(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('bookings:booking_list'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, f'href="{reverse("services:owner_serviceitem_list")}"')

    def test_service_item_price_must_be_positive(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.post(
            reverse('services:owner_serviceitem_create'),
            self._payload(price='0'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ServiceItem.objects.exists())
        self.assertIn('Giá dịch vụ phải lớn hơn 0.', response.context['form'].errors['price'])

    def test_service_item_stock_cannot_be_negative(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.post(
            reverse('services:owner_serviceitem_create'),
            self._payload(stock='-1'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ServiceItem.objects.exists())
        self.assertIn('Tồn kho không được âm.', response.context['form'].errors['stock'])

    def test_owner_service_list_renders_ajax_refresh_target_and_toggle_form(self):
        ServiceItem.objects.create(
            venue=self.venue_a,
            name='Water',
            category=ServiceItem.DRINK,
            price=Decimal('10000.00'),
            stock=10,
        )
        self.client.force_login(self.owner_a_user)

        response = self.client.get(reverse('services:owner_serviceitem_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="owner-service-item-list"')
        self.assertContains(response, 'data-ajax-form')
        self.assertContains(response, reverse('services:owner_serviceitem_toggle', kwargs={'item_id': ServiceItem.objects.get().pk}))

    def test_owner_service_list_ajax_returns_partial_html(self):
        ServiceItem.objects.create(
            venue=self.venue_a,
            name='Water',
            category=ServiceItem.DRINK,
            price=Decimal('10000.00'),
            stock=10,
        )
        self.client.force_login(self.owner_a_user)

        response = self.client.get(
            reverse('services:owner_serviceitem_list'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIn('Water', payload['html'])
        self.assertNotIn('<html', payload['html'].lower())

    def test_owner_ajax_toggles_service_item_active_state_and_returns_updated_list(self):
        service_item = ServiceItem.objects.create(
            venue=self.venue_a,
            name='Water',
            category=ServiceItem.DRINK,
            price=Decimal('10000.00'),
            stock=10,
        )
        self.client.force_login(self.owner_a_user)

        response = self.client.post(
            reverse('services:owner_serviceitem_toggle', kwargs={'item_id': service_item.pk}),
            {'is_active': '0'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIn('INACTIVE', payload['html'])
        service_item.refresh_from_db()
        self.assertFalse(service_item.is_active)

    def test_owner_cannot_ajax_toggle_other_owner_service_item(self):
        service_item = ServiceItem.objects.create(
            venue=self.venue_b,
            name='Foreign Water',
            category=ServiceItem.DRINK,
            price=Decimal('10000.00'),
            stock=10,
        )
        self.client.force_login(self.owner_a_user)

        response = self.client.post(
            reverse('services:owner_serviceitem_toggle', kwargs={'item_id': service_item.pk}),
            {'is_active': '0'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 404)
        service_item.refresh_from_db()
        self.assertTrue(service_item.is_active)

    def test_owner_ajax_create_service_item_returns_updated_list(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.post(
            reverse('services:owner_serviceitem_create'),
            self._payload(name='Energy Drink'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIn('Energy Drink', payload['html'])
        self.assertTrue(ServiceItem.objects.filter(name='Energy Drink', venue=self.venue_a).exists())

    def test_owner_ajax_create_service_item_validation_error_returns_400(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.post(
            reverse('services:owner_serviceitem_create'),
            self._payload(price='0'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload['ok'])
        self.assertIn('errors', payload)
        self.assertFalse(ServiceItem.objects.exists())


class OwnerServiceCreateRealTemplateTests(TestCase):
    """Feature #6 — owner service management with the real templates/URLs.

    Uses the project's real settings (no stub templates / scoped urlconf) so the
    create button, list page and create form are exercised end to end through
    ``config.urls`` (which now includes ``apps.services.urls``).
    """

    def setUp(self):
        User = get_user_model()
        self.owner_role = Role.objects.create(name=Role.OWNER)
        self.customer_role = Role.objects.create(name=Role.CUSTOMER)

        self.owner_user = User.objects.create_user(
            username='svc-real-owner', email='svc-real-owner@example.com', password='password',
        )
        UserRole.objects.create(user=self.owner_user, role=self.owner_role)
        self.owner = OwnerProfile.objects.create(
            user=self.owner_user, business_name='Real Owner', is_verified=True,
        )

        self.other_owner_user = User.objects.create_user(
            username='svc-real-owner-b', email='svc-real-owner-b@example.com', password='password',
        )
        UserRole.objects.create(user=self.other_owner_user, role=self.owner_role)
        self.other_owner = OwnerProfile.objects.create(
            user=self.other_owner_user, business_name='Other Real Owner', is_verified=True,
        )

        self.customer = User.objects.create_user(
            username='svc-real-customer', email='svc-real-customer@example.com', password='password',
        )
        UserRole.objects.create(user=self.customer, role=self.customer_role)

        self.venue = Venue.objects.create(owner=self.owner, name='Real Venue', address='1 Real Street')
        self.other_venue = Venue.objects.create(owner=self.other_owner, name='Other Real Venue', address='2 Real Street')

    def _payload(self, **overrides):
        payload = {
            'venue': self.venue.pk,
            'name': 'Fresh Juice',
            'category': ServiceItem.DRINK,
            'price': '15000',
            'stock': '8',
        }
        payload.update(overrides)
        return payload

    def test_owner_sees_create_button_on_list(self):
        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('services:owner_serviceitem_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Thêm dịch vụ')
        self.assertContains(response, f'href="{reverse("services:owner_serviceitem_create")}"')

    def test_owner_service_root_renders_owner_management(self):
        ServiceItem.objects.create(
            venue=self.venue, name='Sting', category=ServiceItem.DRINK,
            price=Decimal('12000'), stock=5, is_active=True,
        )
        ServiceItem.objects.create(
            venue=self.other_venue, name='Other Sting', category=ServiceItem.DRINK,
            price=Decimal('13000'), stock=5, is_active=True,
        )
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('services:serviceitem_list'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'services/owner_serviceitem_list.html')
        self.assertContains(response, 'Quản lý dịch vụ')
        self.assertContains(response, 'Sting')
        self.assertNotContains(response, 'Other Sting')

    def test_owner_create_form_page_renders(self):
        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('services:owner_serviceitem_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="name"')
        self.assertContains(response, 'name="price"')

    def test_owner_creates_service_for_own_venue(self):
        self.client.force_login(self.owner_user)
        response = self.client.post(reverse('services:owner_serviceitem_create'), self._payload())
        self.assertRedirects(response, reverse('services:owner_serviceitem_list'))
        item = ServiceItem.objects.get(name='Fresh Juice')
        self.assertEqual(item.venue, self.venue)
        self.assertEqual(item.price, Decimal('15000'))

    def test_owner_cannot_create_for_other_owner_venue(self):
        self.client.force_login(self.owner_user)
        response = self.client.post(
            reverse('services:owner_serviceitem_create'),
            self._payload(venue=self.other_venue.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ServiceItem.objects.filter(name='Fresh Juice').exists())

    def test_non_owner_cannot_access_owner_service_pages(self):
        self.client.force_login(self.customer)
        list_response = self.client.get(reverse('services:owner_serviceitem_list'))
        create_response = self.client.post(reverse('services:owner_serviceitem_create'), self._payload())
        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(create_response.status_code, 403)
        self.assertFalse(ServiceItem.objects.exists())

    def test_owner_list_shows_created_item(self):
        ServiceItem.objects.create(
            venue=self.venue, name='Sting', category=ServiceItem.DRINK,
            price=Decimal('12000'), stock=5, is_active=True,
        )
        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('services:owner_serviceitem_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sting')
