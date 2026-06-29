import uuid
from datetime import date, time, timedelta
from decimal import Decimal
import fakeredis
from unittest.mock import patch

from django import forms as django_forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import resolve_url
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import include, path, reverse
from django.utils import timezone

from apps.accounts.models import OwnerProfile, Role, UserRole
from apps.payments.models import Invoice, Payment
from apps.services.models import BookingService, ServiceItem
from apps.venues.models import Field, FieldPriceRule, FieldType, Sport, Venue
from .forms import BookingCreateForm, generate_time_block_choices
from .models import Booking, BookingPackage, BookingSlot
from .views import _management_base_queryset
from .services import (
    BOOKING_PRICE_RULE_MISSING_ERROR,
    BOOKING_UNAVAILABLE_ERROR,
    create_booking,
    get_unavailable_time_blocks,
    is_time_range_available,
    generate_time_blocks,
    check_booking_slot_conflict,
    acquire_slot_lock,
    release_slot_lock,
    confirm_booking_from_lock,
    get_redis_client,
)
from .validators import (
    END_TIME_STEP_ERROR,
    END_TIME_AFTER_START_ERROR,
    MAX_BOOKING_DURATION_ERROR,
    START_TIME_STEP_ERROR,
    validate_booking_time_range,
)


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
        '{% for message in messages %}{{ message }}{% endfor %}'
        '{% if user|can_manage_owner_bookings %}'
        '<a href="{% url "bookings:owner_booking_list" %}">Owner bookings</a>'
        '{% endif %}'
        '{% if user|can_manage_owner_services %}'
        '<a href="{% url "services:owner_serviceitem_list" %}">Owner services</a>'
        '{% endif %}'
        '{% for booking in bookings %}'
        '{{ booking.pk }} {{ booking.venue.name }} {{ booking.field.name }}'
        '{% endfor %}'
    ),
    'bookings/booking_history.html': (
        '{% for booking in bookings %}'
        '{{ booking.pk }} {{ booking.venue.name }} {{ booking.field.name }}'
        '{% endfor %}'
    ),
    'bookings/booking_detail.html': (
        '{% for message in messages %}{{ message }}{% endfor %}'
        '{{ booking.pk }} {{ booking.field.name }} {{ booking.status }} '
        '{% for service in booking.services_ordered.all %}'
        '<a href="{% url "services:bookingservice_edit" service.pk %}">Chỉnh sửa</a>'
        '<form action="{% url "services:bookingservice_remove" service.pk %}">'
        '<button>Hủy dịch vụ</button></form>'
        '{{ service.total_price|floatformat:0 }}đ'
        '{% empty %}Chưa có dịch vụ.{% endfor %}'
        'Tiền sân'
        '{% for slot in booking.slots.all %}{{ slot.price|floatformat:0 }}đ{% endfor %}'
        '{{ booking.grand_total|floatformat:0 }}đ'
        '{% if can_pay_booking %}'
        '<a href="/payments/bookings/{{ booking.pk }}/">Thanh toán</a>'
        '{% endif %}'
    ),
    'bookings/booking_form.html': (
        '{{ form.as_p }}'
        '<section data-service-section '
        'data-services-url-template="/dat-san/fields/__FIELD_ID__/services/">'
        '<tbody data-service-tbody>'
        '{% for service in form.service_items %}{{ service.name }}{% endfor %}'
        '</tbody></section>'
        '<script src="js/booking-time-blocks.js"></script>'
        '{% for block in time_blocks %}'
        '<button data-time="{{ block }}" '
        'class="time-block{% if block in unavailable_blocks %} is-unavailable{% endif %}"'
        '{% if block in unavailable_blocks %} disabled aria-disabled="true"{% endif %}>'
        '{{ block }}</button>'
        '{% endfor %}'
    ),
    'bookings/staff_booking_list.html': (
        '<div id="owner-booking-table">'
        '{% include "bookings/partials/_booking_management_table.html" %}'
        '</div>'
    ),
    'bookings/owner_booking_list.html': (
        '<select id="owner-venue-filter" data-owner-venue-select '
        'data-fields-url="{% url "bookings:owner_booking_fields" %}">'
        '{% for venue in venues %}<option>{{ venue.name }}</option>{% endfor %}'
        '</select>'
        '<select id="owner-field-filter" data-owner-field-select'
        '{% if not fields %} disabled{% endif %}>'
        '{% if not fields %}Vui lòng chọn cơ sở trước{% endif %}'
        '{% for field in fields %}<option>{{ field.name }}</option>{% endfor %}'
        '</select>'
        '<form data-ajax-form data-refresh-target="#owner-booking-table">'
        '<div id="owner-booking-table">'
        '{% include "bookings/partials/_booking_management_table.html" %}'
        '</div></form>'
        '{% if not owner_profile %}Chưa có hồ sơ chủ sân{% endif %}'
    ),
    'bookings/partials/_booking_detail_content.html': (
        '{{ booking.status }}'
        '{% if can_cancel_booking %}<button>Hủy booking</button>{% endif %}'
        '{% if can_pay_booking %}<a>Thanh toán</a>{% endif %}'
    ),
    'bookings/partials/_booking_management_table.html': (
        '{% for booking in bookings %}'
        '{{ booking.pk }} {{ booking.venue.name }} {{ booking.field.name }}'
        '{% for service in booking.services_ordered.all %}'
        '{{ service.total_price|floatformat:0 }}đ'
        '{% endfor %}'
        '{{ booking.grand_total|floatformat:0 }}đ'
        '{% endfor %}'
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
class ScopedBookingTestCase(TestCase):
    pass


def _login_redirect_url(url):
    return f'{resolve_url(settings.LOGIN_URL)}?next={url}'


class BookingTimeRangeValidationTests(SimpleTestCase):
    def test_valid_time_ranges(self):
        valid_ranges = [
            (time(5, 30), time(6, 0)),
            (time(6, 0), time(7, 30)),
            (time(5, 30), time(9, 30)),
            (time(8, 0), time(9, 0)),
            (time(8, 30), time(10, 0)),
            (time(8, 0), time(12, 0)),
        ]

        for start_time, end_time in valid_ranges:
            with self.subTest(start_time=start_time, end_time=end_time):
                validate_booking_time_range(start_time, end_time)

    def test_invalid_time_ranges(self):
        invalid_ranges = [
            (time(6, 15), time(7, 0), 'start_time', START_TIME_STEP_ERROR),
            (time(6, 0), time(6, 15), 'end_time', END_TIME_STEP_ERROR),
            (time(6, 0), time(6, 0), 'end_time', END_TIME_AFTER_START_ERROR),
            (time(7, 0), time(6, 30), 'end_time', END_TIME_AFTER_START_ERROR),
            (time(5, 30), time(10, 0), 'end_time', MAX_BOOKING_DURATION_ERROR),
            (time(8, 15), time(9, 0), 'start_time', START_TIME_STEP_ERROR),
            (time(9, 0), time(9, 0), 'end_time', END_TIME_AFTER_START_ERROR),
            (time(10, 0), time(9, 0), 'end_time', END_TIME_AFTER_START_ERROR),
            (time(8, 0), time(12, 30), 'end_time', MAX_BOOKING_DURATION_ERROR),
        ]

        for start_time, end_time, field, message in invalid_ranges:
            with self.subTest(start_time=start_time, end_time=end_time):
                with self.assertRaises(ValidationError) as exc:
                    validate_booking_time_range(start_time, end_time)
                self.assertIn(field, exc.exception.message_dict)
                self.assertIn(message, exc.exception.message_dict[field])

    def test_generate_time_block_choices_uses_24_hour_blocks(self):
        choices = generate_time_block_choices()
        choice_values = [value for value, label in choices]
        choice_labels = [label for value, label in choices]

        self.assertIn('05:30', choice_values)
        self.assertIn('06:00', choice_values)
        self.assertIn('06:30', choice_values)
        self.assertIn('07:00', choice_values)
        self.assertNotIn('AM', ' '.join(choice_labels))
        self.assertNotIn('PM', ' '.join(choice_labels))

        choice_minutes = [
            int(value.split(':')[0]) * 60 + int(value.split(':')[1])
            for value in choice_values
        ]
        intervals = [
            current - previous
            for previous, current in zip(choice_minutes, choice_minutes[1:])
        ]
        self.assertTrue(all(interval == 30 for interval in intervals))

    def test_booking_create_form_uses_hidden_widgets_for_time_fields(self):
        start_widget = BookingCreateForm.base_fields['start_time'].widget
        end_widget = BookingCreateForm.base_fields['end_time'].widget

        self.assertIsInstance(start_widget, django_forms.HiddenInput)
        self.assertIsInstance(end_widget, django_forms.HiddenInput)


class BookingAuthTests(ScopedBookingTestCase):
    def setUp(self):
        self.redis_client = fakeredis.FakeStrictRedis(decode_responses=True)
        self.redis_patcher = patch('apps.bookings.services.get_redis_client', return_value=self.redis_client)
        self.redis_patcher.start()
        self.addCleanup(self.redis_patcher.stop)
        self.addCleanup(self.redis_client.flushdb)
        self.redis_client.flushdb()

        User = get_user_model()
        self.customer = User.objects.create_user(
            username='customer-auth',
            email='customer-auth@example.com',
            password='password',
        )
        self.other_customer = User.objects.create_user(
            username='other-customer-auth',
            email='other-customer-auth@example.com',
            password='password',
        )
        self.owner_user = User.objects.create_user(
            username='owner-auth',
            email='owner-auth@example.com',
            password='password',
        )
        self.owner_profile = OwnerProfile.objects.create(
            user=self.owner_user,
            business_name='Auth Owner Business',
        )
        self.sport = Sport.objects.create(name='Tennis', slug='tennis')
        self.field_type = FieldType.objects.create(
            sport=self.sport,
            name='Outdoor',
            slug='tennis-outdoor',
            player_count=2,
        )
        self.venue = Venue.objects.create(
            owner=self.owner_profile,
            name='Auth Venue',
            address='456 Test Street',
        )
        self.field = Field.objects.create(
            venue=self.venue,
            field_type=self.field_type,
            name='Court 1',
        )
        self.other_venue = Venue.objects.create(
            owner=self.owner_profile,
            name='Private Other Venue',
            address='789 Other Street',
        )
        self.other_field = Field.objects.create(
            venue=self.other_venue,
            field_type=self.field_type,
            name='Private Other Court',
        )
        self.booking = create_booking(
            user=self.customer,
            field=self.field,
            booking_date=date(2026, 6, 3),
            start_time=time(8, 0),
            end_time=time(9, 0),
            price=Decimal('100000.00'),
        )
        other_package = BookingPackage.objects.create(
            user=self.other_customer,
            package_type=BookingPackage.SINGLE,
            start_date=date(2026, 6, 4),
        )
        self.other_booking = Booking.objects.create(
            booking_package=other_package,
            venue=self.other_venue,
            field=self.other_field,
            booking_date=date(2026, 6, 4),
            status=Booking.PENDING,
            booking_channel=Booking.WEB,
            total_amount=Decimal('200000.00'),
        )
        BookingSlot.objects.create(
            booking=self.other_booking,
            start_time=time(10, 0),
            end_time=time(11, 0),
            price=Decimal('200000.00'),
        )

    def assert_login_required(self, url):
        response = self.client.get(url)
        self.assertRedirects(response, _login_redirect_url(url))

    def test_anonymous_user_is_redirected_from_booking_pages(self):
        urls = [
            reverse('bookings:booking_list'),
            reverse('bookings:booking_create'),
            reverse('bookings:booking_availability'),
            reverse('bookings:booking_detail', kwargs={'pk': uuid.uuid4()}),
        ]

        for url in urls:
            with self.subTest(url=url):
                self.assert_login_required(url)

    def test_authenticated_user_can_access_booking_pages(self):
        self.client.force_login(self.customer)
        urls = [
            reverse('bookings:booking_list'),
            reverse('bookings:booking_create'),
            reverse('bookings:booking_detail', kwargs={'pk': self.booking.pk}),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_customer_cannot_access_other_customers_booking_detail(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('bookings:booking_detail', kwargs={'pk': self.other_booking.pk}))

        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'Private Other Venue', status_code=403)
        self.assertNotContains(response, str(self.other_booking.pk), status_code=403)

    def test_customer_booking_list_only_shows_own_bookings(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('bookings:booking_list'))

        self.assertEqual(response.status_code, 200)
        bookings = list(response.context['bookings'])
        self.assertIn(self.booking, bookings)
        self.assertNotIn(self.other_booking, bookings)
        self.assertContains(response, 'Auth Venue')
        self.assertNotContains(response, 'Private Other Venue')
        self.assertNotContains(response, 'Private Other Court')

    def test_other_customer_booking_list_only_shows_own_bookings(self):
        self.client.force_login(self.other_customer)

        response = self.client.get(reverse('bookings:booking_list'))

        self.assertEqual(response.status_code, 200)
        bookings = list(response.context['bookings'])
        self.assertIn(self.other_booking, bookings)
        self.assertNotIn(self.booking, bookings)
        self.assertContains(response, 'Private Other Venue')
        self.assertNotContains(response, 'Auth Venue')

    def test_customer_cannot_cancel_other_customers_booking(self):
        self.client.force_login(self.customer)

        response = self.client.post(reverse('bookings:booking_cancel', kwargs={'pk': self.other_booking.pk}))

        self.assertEqual(response.status_code, 403)
        self.other_booking.refresh_from_db()
        self.assertEqual(self.other_booking.status, Booking.PENDING)

    def test_logged_out_user_is_redirected_to_login(self):
        self.client.force_login(self.customer)
        self.client.logout()
        response = self.client.get(reverse('bookings:booking_list'))
        self.assertRedirects(response, _login_redirect_url(reverse('bookings:booking_list')))


class CancelBookingStatusTests(ScopedBookingTestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username='cancel-customer',
            email='cancel-customer@example.com',
            password='password',
        )
        self.owner_user = User.objects.create_user(
            username='cancel-owner',
            email='cancel-owner@example.com',
            password='password',
        )
        self.owner_profile = OwnerProfile.objects.create(
            user=self.owner_user,
            business_name='Cancel Owner Business',
        )
        self.sport = Sport.objects.create(name='Cancel Tennis', slug='cancel-tennis')
        self.field_type = FieldType.objects.create(
            sport=self.sport,
            name='Cancel Outdoor',
            slug='cancel-tennis-outdoor',
            player_count=2,
        )
        self.venue = Venue.objects.create(
            owner=self.owner_profile,
            name='Cancel Venue',
            address='1 Cancel Street',
        )
        self.field = Field.objects.create(
            venue=self.venue,
            field_type=self.field_type,
            name='Cancel Court 1',
        )
        self.booking_date = date(2026, 6, 12)

    def _make_booking(self, status):
        package = BookingPackage.objects.create(
            user=self.customer,
            package_type=BookingPackage.SINGLE,
            start_date=self.booking_date,
        )
        booking = Booking.objects.create(
            booking_package=package,
            venue=self.venue,
            field=self.field,
            booking_date=self.booking_date,
            status=status,
            booking_channel=Booking.WEB,
            total_amount=Decimal('100000.00'),
        )
        BookingSlot.objects.create(
            booking=booking,
            start_time=time(9, 0),
            end_time=time(10, 0),
            price=Decimal('100000.00'),
        )
        return booking

    def _cancel_url(self, booking):
        return reverse('bookings:booking_cancel', kwargs={'pk': booking.pk})

    def _detail_url(self, booking):
        return reverse('bookings:booking_detail', kwargs={'pk': booking.pk})

    def test_pending_booking_can_cancel(self):
        booking = self._make_booking(Booking.PENDING)
        self.client.force_login(self.customer)

        response = self.client.post(self._cancel_url(booking))

        self.assertRedirects(response, self._detail_url(booking))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.CANCELLED)

    def test_pending_booking_ajax_cancel_returns_updated_detail_partial(self):
        booking = self._make_booking(Booking.PENDING)
        self.client.force_login(self.customer)

        response = self.client.post(
            self._cancel_url(booking),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIn('html', payload)
        self.assertIn(Booking.CANCELLED, payload['html'])
        self.assertNotIn('Hủy booking</button>', payload['html'])
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.CANCELLED)

    def test_paid_booking_ajax_cancel_returns_error_without_redirect(self):
        booking = self._make_booking(Booking.PAID)
        self.client.force_login(self.customer)

        response = self.client.post(
            self._cancel_url(booking),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])
        self.assertIn('Booking đã thanh toán', response.json()['message'])
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.PAID)

    def test_waiting_booking_can_cancel(self):
        booking = self._make_booking(Booking.WAITING)
        self.client.force_login(self.customer)

        response = self.client.post(self._cancel_url(booking))

        self.assertRedirects(response, self._detail_url(booking))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.CANCELLED)

    def test_cancelled_booking_cannot_cancel_again(self):
        booking = self._make_booking(Booking.CANCELLED)
        self.client.force_login(self.customer)

        response = self.client.post(self._cancel_url(booking), follow=True)

        self.assertEqual(response.redirect_chain[-1][0], self._detail_url(booking))
        self.assertContains(response, 'Booking đã hủy, không thể hủy lại.')
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.CANCELLED)

    def test_paid_booking_cannot_cancel(self):
        booking = self._make_booking(Booking.PAID)
        self.client.force_login(self.customer)

        response = self.client.post(self._cancel_url(booking), follow=True)

        self.assertEqual(response.redirect_chain[-1][0], self._detail_url(booking))
        self.assertContains(response, 'Booking đã thanh toán, không thể hủy.')
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.PAID)


class BookingServiceTests(ScopedBookingTestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username='customer',
            email='customer@example.com',
            password='password',
        )
        self.owner_user = User.objects.create_user(
            username='owner',
            email='owner@example.com',
            password='password',
        )
        self.owner_profile = OwnerProfile.objects.create(
            user=self.owner_user,
            business_name='Owner Business',
        )
        self.sport = Sport.objects.create(name='Football', slug='football')
        self.field_type = FieldType.objects.create(
            sport=self.sport,
            name='5 a side',
            slug='football-5',
            player_count=10,
        )
        self.venue = Venue.objects.create(
            owner=self.owner_profile,
            name='Main Venue',
            address='123 Test Street',
        )
        self.field = Field.objects.create(
            venue=self.venue,
            field_type=self.field_type,
            name='Field 1',
        )
        self.price_rule = FieldPriceRule.objects.create(
            field=self.field,
            start_time=time(5, 30),
            end_time=time(23, 30),
            price_per_hour=Decimal('100000.00'),
        )
        self.booking_date = date(2026, 6, 1)

        self.redis_client = fakeredis.FakeStrictRedis(decode_responses=True)
        self.redis_patcher = patch('apps.bookings.services.get_redis_client', return_value=self.redis_client)
        self.redis_patcher.start()
        self.redis_client.flushdb()

    def tearDown(self):
        self.redis_client.flushdb()
        self.redis_patcher.stop()

    def test_create_booking_success(self):
        booking = create_booking(
            user=self.customer,
            field=self.field,
            booking_date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            price=Decimal('100000.00'),
        )

        self.assertEqual(booking.status, Booking.PENDING)
        self.assertEqual(booking.venue, self.venue)
        self.assertEqual(BookingSlot.objects.filter(booking=booking).count(), 1)

    def test_prevent_overlapping_booking(self):
        create_booking(
            user=self.customer,
            field=self.field,
            booking_date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            price=Decimal('100000.00'),
        )

        with self.assertRaises(ValidationError):
            create_booking(
                user=self.customer,
                field=self.field,
                booking_date=self.booking_date,
                start_time=time(9, 30),
                end_time=time(10, 30),
                price=Decimal('100000.00'),
            )

    def test_invalid_time_range(self):
        with self.assertRaises(ValidationError):
            create_booking(
                user=self.customer,
                field=self.field,
                booking_date=self.booking_date,
                start_time=time(10, 0),
                end_time=time(10, 0),
                price=Decimal('100000.00'),
            )

    def test_existing_booking_marks_block_unavailable(self):
        create_booking(
            user=self.customer,
            field=self.field,
            booking_date=self.booking_date,
            start_time=time(7, 0),
            end_time=time(7, 30),
            price=Decimal('100000.00'),
        )

        unavailable_blocks = get_unavailable_time_blocks(
            self.field,
            self.booking_date,
            ['06:30', '07:00', '07:30'],
        )

        self.assertIn('07:00', unavailable_blocks)
        self.assertNotIn('06:30', unavailable_blocks)
        self.assertNotIn('07:30', unavailable_blocks)

    def test_cancelled_booking_does_not_block_availability(self):
        booking = create_booking(
            user=self.customer,
            field=self.field,
            booking_date=self.booking_date,
            start_time=time(7, 0),
            end_time=time(7, 30),
            price=Decimal('100000.00'),
        )
        booking.status = Booking.CANCELLED
        booking.save(update_fields=['status', 'updated_at'])

        unavailable_blocks = get_unavailable_time_blocks(
            self.field,
            self.booking_date,
            ['07:00'],
        )

        self.assertNotIn('07:00', unavailable_blocks)

    def test_booking_form_rejects_unavailable_range(self):
        create_booking(
            user=self.customer,
            field=self.field,
            booking_date=self.booking_date,
            start_time=time(7, 0),
            end_time=time(7, 30),
            price=Decimal('100000.00'),
        )

        form = BookingCreateForm(data={
            'field': self.field.pk,
            'booking_date': self.booking_date.isoformat(),
            'start_time': '06:00',
            'end_time': '08:00',
            'note': '',
        })

        self.assertFalse(form.is_valid())
        self.assertIn(BOOKING_UNAVAILABLE_ERROR, form.non_field_errors())

    def test_booking_create_template_marks_unavailable_blocks(self):
        create_booking(
            user=self.customer,
            field=self.field,
            booking_date=self.booking_date,
            start_time=time(7, 0),
            end_time=time(7, 30),
            price=Decimal('100000.00'),
        )
        self.client.force_login(self.customer)

        response = self.client.get(reverse('bookings:booking_create'), {
            'field': self.field.pk,
            'booking_date': self.booking_date.isoformat(),
        })

        self.assertContains(response, 'data-time="07:00"')
        self.assertContains(response, 'class="time-block is-unavailable"')
        self.assertContains(response, 'disabled aria-disabled="true"')

    def test_availability_endpoint_returns_unavailable_blocks(self):
        create_booking(
            user=self.customer,
            field=self.field,
            booking_date=self.booking_date,
            start_time=time(7, 0),
            end_time=time(7, 30),
            price=Decimal('100000.00'),
        )
        self.client.force_login(self.customer)

        response = self.client.get(reverse('bookings:booking_availability'), {
            'field_id': self.field.pk,
            'booking_date': self.booking_date.isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('07:00', payload['unavailable_blocks'])
        self.assertIn('05:30', payload['time_blocks'])

    def test_create_booking_without_services_still_works(self):
        self.client.force_login(self.customer)

        response = self.client.post(reverse('bookings:booking_create'), {
            'field': self.field.pk,
            'booking_date': self.booking_date.isoformat(),
            'start_time': '10:00',
            'end_time': '11:00',
            'note': '',
        })

        booking = Booking.objects.get(field=self.field, booking_date=self.booking_date)
        self.assertRedirects(response, reverse('bookings:booking_detail', kwargs={'pk': booking.pk}))
        self.assertEqual(booking.total_amount, Decimal('100000.00'))
        self.assertFalse(BookingService.objects.filter(booking=booking).exists())

    def test_create_booking_creates_selected_services(self):
        service_item = ServiceItem.objects.create(
            venue=self.venue,
            name='Nước suối',
            category=ServiceItem.DRINK,
            price=Decimal('10000.00'),
            stock=10,
        )
        self.client.force_login(self.customer)

        response = self.client.post(reverse('bookings:booking_create'), {
            'field': self.field.pk,
            'booking_date': self.booking_date.isoformat(),
            'start_time': '10:00',
            'end_time': '11:00',
            'note': '',
            f'service_quantity_{service_item.pk}': '2',
        })

        booking = Booking.objects.get(field=self.field, booking_date=self.booking_date)
        service_item.refresh_from_db()
        self.assertRedirects(response, reverse('bookings:booking_detail', kwargs={'pk': booking.pk}))
        booking_service = BookingService.objects.get(booking=booking, service_item=service_item)
        self.assertEqual(booking_service.quantity, 2)
        self.assertEqual(booking_service.unit_price, Decimal('10000.00'))
        self.assertEqual(booking.total_amount, Decimal('120000.00'))
        self.assertEqual(service_item.stock, 8)

    def test_booking_detail_shows_empty_service_state_without_services(self):
        booking = create_booking(
            user=self.customer,
            field=self.field,
            booking_date=self.booking_date,
            start_time=time(10, 0),
            end_time=time(11, 0),
            price=Decimal('100000.00'),
        )
        self.client.force_login(self.customer)

        response = self.client.get(reverse('bookings:booking_detail', kwargs={'pk': booking.pk}))

        self.assertContains(response, 'Chưa có dịch vụ.')
        self.assertContains(response, 'Tiền sân')
        self.assertContains(response, '100000đ')

    # --- New Tests for Redis Slot Locking ---

    def test_generate_time_blocks(self):
        blocks = generate_time_blocks(time(6, 0), time(8, 0))
        self.assertEqual(blocks, ["06:00", "06:30", "07:00", "07:30"])

    def test_check_booking_slot_conflict(self):
        create_booking(
            user=self.customer,
            field=self.field,
            booking_date=self.booking_date,
            start_time=time(6, 0),
            end_time=time(8, 0),
            price=Decimal('100000.00'),
        )
        
        # 06:00-08:00 conflicts with 07:30-09:00
        self.assertTrue(check_booking_slot_conflict(self.field, self.booking_date, time(7, 30), time(9, 0)))
        # 06:00-08:00 does NOT conflict with 08:00-09:00
        self.assertFalse(check_booking_slot_conflict(self.field, self.booking_date, time(8, 0), time(9, 0)))
        # 06:00-08:00 conflicts with 05:30-06:30
        self.assertTrue(check_booking_slot_conflict(self.field, self.booking_date, time(5, 30), time(6, 30)))
        # 06:00-08:00 conflicts with 06:00-08:00
        self.assertTrue(check_booking_slot_conflict(self.field, self.booking_date, time(6, 0), time(8, 0)))

    def test_acquire_slot_lock_success(self):
        session_id, expires_at = acquire_slot_lock(self.customer, self.field, self.booking_date, time(6, 0), time(8, 0))
        self.assertIsNotNone(session_id)
        
        # Verify redis keys exist
        keys = self.redis_client.keys(f"booking_lock:field:{self.field.pk}:date:{self.booking_date.isoformat()}:block:*")
        self.assertEqual(len(keys), 4)

    def test_acquire_slot_lock_conflict(self):
        acquire_slot_lock(self.customer, self.field, self.booking_date, time(6, 0), time(8, 0))
        
        # Second user tries to lock overlapping time
        with self.assertRaises(ValidationError):
            acquire_slot_lock(self.customer, self.field, self.booking_date, time(7, 30), time(9, 0))

    def test_acquire_slot_lock_non_overlapping_success(self):
        acquire_slot_lock(self.customer, self.field, self.booking_date, time(6, 0), time(8, 0))
        
        # Second user tries to lock non-overlapping time
        session_id, _ = acquire_slot_lock(self.customer, self.field, self.booking_date, time(8, 0), time(9, 0))
        self.assertIsNotNone(session_id)

    def test_release_slot_lock(self):
        session_id, _ = acquire_slot_lock(self.customer, self.field, self.booking_date, time(6, 0), time(8, 0))
        release_slot_lock(session_id)
        
        # Verify redis keys are gone
        keys = self.redis_client.keys(f"booking_lock:field:{self.field.pk}:date:{self.booking_date.isoformat()}:block:*")
        self.assertEqual(len(keys), 0)

    def test_confirm_booking_from_lock_success(self):
        session_id, _ = acquire_slot_lock(self.customer, self.field, self.booking_date, time(6, 0), time(8, 0))
        
        booking = confirm_booking_from_lock(
            self.customer, session_id, self.field, self.booking_date, time(6, 0), time(8, 0), Decimal('100000.00')
        )
        self.assertEqual(booking.status, Booking.PENDING)
        
        # Lock should be released
        keys = self.redis_client.keys(f"booking_lock:field:{self.field.pk}:date:{self.booking_date.isoformat()}:block:*")
        self.assertEqual(len(keys), 0)

    def test_confirm_booking_from_lock_missing_lock(self):
        with self.assertRaisesMessage(ValidationError, "Khung giờ giữ chỗ đã hết hạn"):
            confirm_booking_from_lock(
                self.customer, "invalid-session", self.field, self.booking_date, time(6, 0), time(8, 0), Decimal('100000.00')
            )

    def test_confirm_booking_from_lock_db_conflict(self):
        session_id, _ = acquire_slot_lock(self.customer, self.field, self.booking_date, time(6, 0), time(8, 0))
        
        # Simulate a booking was created directly (e.g. walk-in bypassing Redis lock)
        from apps.bookings.models import BookingPackage, Booking, BookingSlot
        package = BookingPackage.objects.create(user=self.customer, package_type=BookingPackage.SINGLE, start_date=self.booking_date)
        booking = Booking.objects.create(booking_package=package, venue=self.venue, field=self.field, booking_date=self.booking_date, status=Booking.PENDING, booking_channel=Booking.WEB, total_amount=Decimal('100000.00'))
        BookingSlot.objects.create(booking=booking, start_time=time(7, 30), end_time=time(9, 0), price=Decimal('100000.00'))
        
        with self.assertRaises(ValidationError):
            confirm_booking_from_lock(
                self.customer, session_id, self.field, self.booking_date, time(6, 0), time(8, 0), Decimal('100000.00')
            )


class ManagementDashboardTests(ScopedBookingTestCase):
    """Role-based staff/owner booking dashboards (non-/admin)."""

    def setUp(self):
        User = get_user_model()
        self.staff_role, _ = Role.objects.get_or_create(name=Role.STAFF)
        self.owner_role, _ = Role.objects.get_or_create(name=Role.OWNER)
        self.admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)

        # Plain customer (no special roles).
        self.customer = User.objects.create_user(
            username='plain-customer', email='plain@example.com', password='password',
        )
        # Staff user.
        self.staff = User.objects.create_user(
            username='staff', email='staff@example.com', password='password',
        )
        UserRole.objects.create(user=self.staff, role=self.staff_role)

        self.admin = User.objects.create_user(
            username='booking-admin', email='booking-admin@example.com', password='password',
        )
        UserRole.objects.create(user=self.admin, role=self.admin_role)

        # Owner A + owner B.
        self.owner_a_user = User.objects.create_user(
            username='owner-a', email='owner-a@example.com', password='password',
        )
        UserRole.objects.create(user=self.owner_a_user, role=self.owner_role)
        self.owner_a = OwnerProfile.objects.create(
            user=self.owner_a_user, business_name='Owner A',
        )
        self.owner_b_user = User.objects.create_user(
            username='owner-b', email='owner-b@example.com', password='password',
        )
        UserRole.objects.create(user=self.owner_b_user, role=self.owner_role)
        self.owner_b = OwnerProfile.objects.create(
            user=self.owner_b_user, business_name='Owner B',
        )
        self.admin_owner_user = User.objects.create_user(
            username='admin-owner', email='admin-owner@example.com', password='password',
        )
        UserRole.objects.create(user=self.admin_owner_user, role=self.admin_role)
        self.admin_owner = OwnerProfile.objects.create(
            user=self.admin_owner_user, business_name='Admin Owner',
        )

        self.sport = Sport.objects.create(name='Football', slug='football')
        self.field_type = FieldType.objects.create(
            sport=self.sport, name='5 a side', slug='football-5', player_count=10,
        )
        self.venue_a = Venue.objects.create(
            owner=self.owner_a, name='Venue A', address='1 A Street',
        )
        self.field_a = Field.objects.create(
            venue=self.venue_a, field_type=self.field_type, name='Field A1',
        )
        self.venue_b = Venue.objects.create(
            owner=self.owner_b, name='Venue B', address='2 B Street',
        )
        self.field_b = Field.objects.create(
            venue=self.venue_b, field_type=self.field_type, name='Field B1',
        )
        self.booking_date = date(2026, 6, 10)

        # Bookings on venue A with a service attached + various statuses.
        self.booking_a_paid = self._make_booking(
            self.venue_a, self.field_a, self.customer, Booking.PAID, Decimal('200000.00'),
        )
        self.booking_a_waiting = self._make_booking(
            self.venue_a, self.field_a, self.customer, Booking.WAITING, Decimal('150000.00'),
        )
        self.booking_b_pending = self._make_booking(
            self.venue_b, self.field_b, self.customer, Booking.PENDING, Decimal('300000.00'),
        )

        self.service_item = ServiceItem.objects.create(
            venue=self.venue_a, name='Nước suối', category=ServiceItem.DRINK,
            price=Decimal('10000.00'), stock=50,
        )
        BookingService.objects.create(
            booking=self.booking_a_paid, service_item=self.service_item,
            quantity=3, unit_price=Decimal('10000.00'),
        )
        self.booking_a_paid.total_amount = Decimal('230000.00')
        self.booking_a_paid.save(update_fields=['total_amount', 'updated_at'])

    def _make_booking(self, venue, field, user, status, amount):
        package = BookingPackage.objects.create(
            user=user, package_type=BookingPackage.SINGLE, start_date=self.booking_date,
        )
        booking = Booking.objects.create(
            booking_package=package, venue=venue, field=field,
            booking_date=self.booking_date, status=status,
            booking_channel=Booking.WEB, total_amount=amount,
        )
        BookingSlot.objects.create(
            booking=booking, start_time=time(9, 0), end_time=time(10, 0), price=amount,
        )
        return booking

    # --- Permission tests -------------------------------------------------

    def test_normal_user_cannot_access_staff_dashboard(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse('bookings:staff_booking_list'))
        self.assertEqual(response.status_code, 403)

    def test_normal_user_cannot_access_owner_dashboard(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse('bookings:owner_booking_list'))
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_access_owner_dashboard(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('bookings:owner_booking_list'))
        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_access_owner_dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('bookings:owner_booking_list'))
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'Venue A', status_code=403)

    def test_admin_owner_cannot_access_owner_dashboard(self):
        self.client.force_login(self.admin_owner_user)
        response = self.client.get(reverse('bookings:owner_booking_list'))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        for name in ('bookings:staff_booking_list', 'bookings:owner_booking_list'):
            with self.subTest(name=name):
                url = reverse(name)
                response = self.client.get(url)
                self.assertRedirects(response, _login_redirect_url(url))

    # --- Staff dashboard --------------------------------------------------

    def test_staff_can_see_all_bookings(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('bookings:staff_booking_list'))
        self.assertEqual(response.status_code, 200)
        bookings = list(response.context['bookings'])
        self.assertIn(self.booking_a_paid, bookings)
        self.assertIn(self.booking_a_waiting, bookings)
        self.assertIn(self.booking_b_pending, bookings)

    def test_staff_filter_by_venue(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse('bookings:staff_booking_list'), {'venue': self.venue_b.pk},
        )
        bookings = list(response.context['bookings'])
        self.assertEqual(bookings, [self.booking_b_pending])

    # --- Owner dashboard --------------------------------------------------

    def test_owner_only_sees_own_venue_bookings(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(reverse('bookings:owner_booking_list'))
        self.assertEqual(response.status_code, 200)
        bookings = list(response.context['bookings'])
        venues = list(response.context['venues'])
        self.assertIn(self.booking_a_paid, bookings)
        self.assertNotIn(self.booking_b_pending, bookings)
        self.assertIn(self.venue_a, venues)
        self.assertNotIn(self.venue_b, venues)

    def test_owner_dashboard_initial_load_does_not_render_field_options(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.get(reverse('bookings:owner_booking_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['fields']), [])
        self.assertContains(response, 'id="owner-venue-filter"')
        self.assertContains(response, 'id="owner-field-filter"')
        self.assertContains(response, 'data-owner-venue-select')
        self.assertContains(response, 'data-owner-field-select')
        self.assertContains(response, f'data-fields-url="{reverse("bookings:owner_booking_fields")}"')
        self.assertContains(response, 'data-ajax-form')
        self.assertContains(response, 'data-refresh-target="#owner-booking-table"')
        self.assertContains(response, 'id="owner-booking-table"')
        self.assertContains(response, 'Vui lòng chọn cơ sở trước')
        self.assertContains(response, 'data-owner-field-select disabled')
        self.assertNotContains(response, f'>{self.field_a.name}</option>')
        self.assertNotContains(response, f'>{self.field_b.name}</option>')

    def test_owner_booking_ajax_filter_returns_table_partial(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.get(
            reverse('bookings:owner_booking_list'),
            {'venue': self.venue_a.pk},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIn('html', payload)
        self.assertIn(str(self.booking_a_paid.pk), payload['html'])
        self.assertIn(self.venue_a.name, payload['html'])
        self.assertNotIn('<html', payload['html'].lower())
        self.assertNotIn(self.venue_b.name, payload['html'])

    def test_owner_fields_endpoint_returns_only_fields_for_owned_venue(self):
        field_a2 = Field.objects.create(
            venue=self.venue_a,
            field_type=self.field_type,
            name='Field A2',
        )
        inactive_field = Field.objects.create(
            venue=self.venue_a,
            field_type=self.field_type,
            name='Inactive Field A',
            status='INACTIVE',
        )
        self.client.force_login(self.owner_a_user)

        response = self.client.get(
            reverse('bookings:owner_booking_fields'),
            {'venue_id': self.venue_a.pk},
        )

        self.assertEqual(response.status_code, 200)
        field_ids = {item['id'] for item in response.json()['fields']}
        self.assertIn('fields', response.json())
        self.assertGreaterEqual(len(response.json()['fields']), 1)
        self.assertEqual(field_ids, {self.field_a.pk, field_a2.pk})
        self.assertNotIn(self.field_b.pk, field_ids)
        self.assertNotIn(inactive_field.pk, field_ids)

    def test_owner_fields_endpoint_does_not_depend_on_existing_booking(self):
        empty_booking_venue = Venue.objects.create(
            owner=self.owner_a,
            name='Owner A No Booking Venue',
            address='3 Empty Street',
        )
        empty_booking_field = Field.objects.create(
            venue=empty_booking_venue,
            field_type=self.field_type,
            name='No Booking Field',
        )
        self.client.force_login(self.owner_a_user)

        response = self.client.get(
            reverse('bookings:owner_booking_fields'),
            {'venue_id': empty_booking_venue.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {'fields': [{'id': empty_booking_field.pk, 'name': empty_booking_field.name}]},
        )

    def test_owner_fields_endpoint_returns_model_active_status_case_insensitively(self):
        lower_case_active_field = Field.objects.create(
            venue=self.venue_a,
            field_type=self.field_type,
            name='Lowercase Active Field',
            status='active',
        )
        self.client.force_login(self.owner_a_user)

        response = self.client.get(
            reverse('bookings:owner_booking_fields'),
            {'venue_id': self.venue_a.pk},
        )

        self.assertEqual(response.status_code, 200)
        field_ids = {item['id'] for item in response.json()['fields']}
        self.assertIn(lower_case_active_field.pk, field_ids)

    def test_owner_fields_endpoint_blocks_foreign_venue(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.get(
            reverse('bookings:owner_booking_fields'),
            {'venue_id': self.venue_b.pk},
        )

        self.assertEqual(response.status_code, 403)

    def test_non_owner_cannot_access_owner_fields_endpoint(self):
        for user in (self.customer, self.staff, self.admin, self.admin_owner_user):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(
                    reverse('bookings:owner_booking_fields'),
                    {'venue_id': self.venue_a.pk},
                )
                self.assertEqual(response.status_code, 403)

    def test_owner_booking_filter_excludes_soft_deleted_venues(self):
        # Owner A also owns a soft-deleted venue (with an old booking) that must
        # not appear in the "Cơ sở"/"Sân" filter dropdowns, while history survives.
        deleted_venue = Venue.objects.create(
            owner=self.owner_a,
            name='Owner A Deleted Venue',
            address='9 Deleted Street',
            status='INACTIVE',
            is_deleted=True,
            deleted_at=timezone.now(),
        )
        deleted_field = Field.objects.create(
            venue=deleted_venue, field_type=self.field_type, name='Deleted Field',
        )
        old_booking = self._make_booking(
            deleted_venue, deleted_field, self.customer, Booking.PAID, Decimal('100000.00'),
        )
        self.client.force_login(self.owner_a_user)

        response = self.client.get(reverse('bookings:owner_booking_list'))

        self.assertEqual(response.status_code, 200)
        venues = list(response.context['venues'])
        fields = list(response.context['fields'])
        self.assertIn(self.venue_a, venues)
        self.assertNotIn(deleted_venue, venues)
        self.assertEqual(fields, [])
        # The venue filter <option> for the deleted venue must be absent
        # (the </option> label only appears inside the dropdown, not table cells).
        self.assertNotContains(
            response,
            f'>{deleted_venue.name}</option>',
        )
        # History preserved: the old booking on the soft-deleted venue still exists
        # and the page renders without crashing.
        self.assertTrue(Booking.objects.filter(pk=old_booking.pk).exists())
        self.assertIn(old_booking, list(response.context['bookings']))

    def test_owner_sees_owner_booking_menu_link(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(reverse('bookings:booking_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("bookings:owner_booking_list")}"')

    def test_admin_does_not_see_owner_booking_menu_link(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('bookings:booking_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, f'href="{reverse("bookings:owner_booking_list")}"')

    def test_admin_owner_does_not_see_owner_booking_menu_link(self):
        self.client.force_login(self.admin_owner_user)
        response = self.client.get(reverse('bookings:booking_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, f'href="{reverse("bookings:owner_booking_list")}"')

    def test_owner_cannot_see_other_owner_bookings_even_with_filter(self):
        self.client.force_login(self.owner_a_user)
        # Try to leak owner B's venue via the venue filter.
        response = self.client.get(
            reverse('bookings:owner_booking_list'), {'venue': self.venue_b.pk},
        )
        self.assertEqual(response.status_code, 403)

    def test_owner_filters_booking_by_owned_venue(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.get(
            reverse('bookings:owner_booking_list'),
            {'venue': self.venue_a.pk},
        )

        self.assertEqual(response.status_code, 200)
        bookings = list(response.context['bookings'])
        self.assertIn(self.booking_a_paid, bookings)
        self.assertNotIn(self.booking_b_pending, bookings)
        self.assertEqual(list(response.context['fields']), [self.field_a])

    def test_owner_filters_booking_by_field_in_selected_venue(self):
        field_a2 = Field.objects.create(
            venue=self.venue_a,
            field_type=self.field_type,
            name='Field A2',
        )
        booking_a2_paid = self._make_booking(
            self.venue_a,
            field_a2,
            self.customer,
            Booking.PAID,
            Decimal('180000.00'),
        )
        self.client.force_login(self.owner_a_user)

        response = self.client.get(
            reverse('bookings:owner_booking_list'),
            {'venue': self.venue_a.pk, 'field': self.field_a.pk},
        )

        self.assertEqual(response.status_code, 200)
        bookings = list(response.context['bookings'])
        self.assertIn(self.booking_a_paid, bookings)
        self.assertNotIn(booking_a2_paid, bookings)
        self.assertNotIn(self.booking_b_pending, bookings)

    def test_owner_field_filter_must_match_selected_owned_venue(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.get(
            reverse('bookings:owner_booking_list'),
            {'venue': self.venue_a.pk, 'field': self.field_b.pk},
        )

        self.assertEqual(response.status_code, 403)

    def test_owner_field_filter_requires_selected_venue(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.get(
            reverse('bookings:owner_booking_list'),
            {'field': self.field_a.pk},
        )

        self.assertEqual(response.status_code, 403)

    def test_management_base_queryset_prefetches_table_relations(self):
        queryset = _management_base_queryset()

        self.assertIn('venue', queryset.query.select_related)
        self.assertIn('field', queryset.query.select_related)
        self.assertIn('booking_package', queryset.query.select_related)
        self.assertIn('user', queryset.query.select_related['booking_package'])
        self.assertIn('slots', queryset._prefetch_related_lookups)
        self.assertTrue(
            any(
                getattr(prefetch, 'prefetch_through', None) == 'services_ordered'
                for prefetch in queryset._prefetch_related_lookups
            )
        )

    def test_owner_dashboard_excludes_waiting_status(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(reverse('bookings:owner_booking_list'))
        bookings = list(response.context['bookings'])
        self.assertIn(self.booking_a_paid, bookings)
        self.assertNotIn(self.booking_a_waiting, bookings)

    def test_owner_booking_list_v2_route_shows_own_bookings(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.get(reverse('bookings:owner_booking_list_v2'))

        self.assertEqual(response.status_code, 200)
        bookings = list(response.context['bookings'])
        self.assertIn(self.booking_a_paid, bookings)
        self.assertNotIn(self.booking_b_pending, bookings)

    def test_owner_can_view_own_venue_booking_detail(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.get(reverse('bookings:owner_booking_detail', kwargs={'pk': self.booking_a_paid.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.field_a.name)
        self.assertNotContains(response, 'Thanh toán</a>')

    def test_owner_cannot_view_other_owner_booking_detail(self):
        self.client.force_login(self.owner_a_user)

        response = self.client.get(reverse('bookings:owner_booking_detail', kwargs={'pk': self.booking_b_pending.pk}))

        self.assertEqual(response.status_code, 404)

    def test_non_owner_cannot_access_owner_booking_detail(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse('bookings:owner_booking_detail', kwargs={'pk': self.booking_a_paid.pk}))

        self.assertEqual(response.status_code, 403)

    def test_owner_without_profile_sees_empty_state(self):
        User = get_user_model()
        roleless_owner = User.objects.create_user(
            username='owner-noprofile', email='owner-np@example.com', password='password',
        )
        UserRole.objects.create(user=roleless_owner, role=self.owner_role)
        self.client.force_login(roleless_owner)
        response = self.client.get(reverse('bookings:owner_booking_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['bookings']), [])
        self.assertContains(response, 'Chưa có hồ sơ chủ sân')

    # --- Service totals ---------------------------------------------------

    def test_service_totals_render_in_staff_dashboard(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('bookings:staff_booking_list'))
        # Service line: 3 x 10000 = 30000; grand total: 200000 + 30000 = 230000.
        self.assertContains(response, '30000đ')
        self.assertContains(response, '230000đ')

    def test_grand_total_property(self):
        self.assertEqual(self.booking_a_paid.grand_total, Decimal('230000.00'))
        self.assertEqual(self.booking_b_pending.grand_total, Decimal('300000.00'))

class OwnerCreatedFieldBookingFlowTests(ScopedBookingTestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username='owner-created-booker',
            email='owner-created-booker@example.com',
            password='password',
        )
        self.owner_user = User.objects.create_user(
            username='owner-created-owner',
            email='owner-created-owner@example.com',
            password='password',
        )
        self.owner_profile = OwnerProfile.objects.create(
            user=self.owner_user,
            business_name='Owner Created Booking Venue',
            is_verified=True,
        )
        self.sport = Sport.objects.create(name='Padel', slug='padel-owner-created')
        self.field_type = FieldType.objects.create(
            sport=self.sport,
            name='Indoor',
            slug='padel-owner-created-indoor',
            player_count=4,
        )
        self.venue = Venue.objects.create(
            owner=self.owner_profile,
            name='Owner Created Active Venue',
            address='88 Booking Street',
            status='ACTIVE',
        )
        self.field = Field.objects.create(
            venue=self.venue,
            field_type=self.field_type,
            name='Owner Created Active Field',
            status='ACTIVE',
        )
        self.price_rule = FieldPriceRule.objects.create(
            field=self.field,
            start_time=time(8, 0),
            end_time=time(12, 0),
            price_per_hour=Decimal('120000.00'),
            priority=1,
        )
        self.booking_date = date(2026, 6, 1)

        self.redis_client = fakeredis.FakeStrictRedis(decode_responses=True)
        self.redis_patcher = patch('apps.bookings.services.get_redis_client', return_value=self.redis_client)
        self.redis_patcher.start()
        self.redis_client.flushdb()

    def tearDown(self):
        self.redis_client.flushdb()
        self.redis_patcher.stop()

    def _booking_payload(self, **overrides):
        payload = {
            'field': self.field.pk,
            'booking_date': self.booking_date.isoformat(),
            'start_time': '09:00',
            'end_time': '10:00',
            'note': '',
        }
        payload.update(overrides)
        return payload

    def test_customer_can_book_owner_created_active_field(self):
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field.pk}),
            self._booking_payload(),
        )

        booking = Booking.objects.get(field=self.field, booking_date=self.booking_date)
        self.assertRedirects(response, reverse('bookings:booking_detail', kwargs={'pk': booking.pk}))
        self.assertEqual(booking.status, Booking.PENDING)
        self.assertEqual(booking.venue, self.venue)
        self.assertEqual(booking.total_amount, Decimal('120000.00'))

    def test_booking_detail_shows_payment_handoff_button_without_creating_payment_records(self):
        self.client.force_login(self.customer)

        self.client.post(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field.pk}),
            self._booking_payload(),
        )
        booking = Booking.objects.get(field=self.field, booking_date=self.booking_date)
        detail_response = self.client.get(reverse('bookings:booking_detail', kwargs={'pk': booking.pk}))

        self.assertContains(detail_response, f'href="/payments/bookings/{booking.pk}/"')
        self.assertContains(detail_response, 'Thanh toán')
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(Invoice.objects.exists())
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.PENDING)

    def test_booking_total_uses_duration_times_price_rule(self):
        self.client.force_login(self.customer)

        self.client.post(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field.pk}),
            self._booking_payload(end_time='10:30'),
        )

        booking = Booking.objects.get(field=self.field, booking_date=self.booking_date)
        slot = booking.slots.get()
        self.assertEqual(booking.total_amount, Decimal('180000.00'))
        self.assertEqual(slot.price, Decimal('180000.00'))

    def test_customer_selects_service_when_booking(self):
        service_item = ServiceItem.objects.create(
            venue=self.venue,
            name='Water',
            category=ServiceItem.DRINK,
            price=Decimal('15000.00'),
            stock=5,
        )
        self.client.force_login(self.customer)

        self.client.post(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field.pk}),
            self._booking_payload(**{f'service_quantity_{service_item.pk}': '2'}),
        )

        booking = Booking.objects.get(field=self.field, booking_date=self.booking_date)
        booking_service = BookingService.objects.get(booking=booking, service_item=service_item)
        service_item.refresh_from_db()
        self.assertEqual(booking_service.quantity, 2)
        self.assertEqual(booking_service.unit_price, Decimal('15000.00'))
        self.assertEqual(booking.total_amount, Decimal('150000.00'))
        self.assertEqual(service_item.stock, 3)

    def test_cannot_book_when_service_quantity_exceeds_stock(self):
        service_item = ServiceItem.objects.create(
            venue=self.venue,
            name='Towel',
            category=ServiceItem.EQUIPMENT,
            price=Decimal('20000.00'),
            stock=1,
        )
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field.pk}),
            self._booking_payload(**{f'service_quantity_{service_item.pk}': '2'}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Booking.objects.exists())
        self.assertFalse(BookingService.objects.exists())
        service_item.refresh_from_db()
        self.assertEqual(service_item.stock, 1)

    def test_cannot_book_without_matching_price_rule(self):
        self.price_rule.delete()
        service_item = ServiceItem.objects.create(
            venue=self.venue,
            name='Water',
            category=ServiceItem.DRINK,
            price=Decimal('15000.00'),
            stock=5,
        )
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field.pk}),
            self._booking_payload(**{f'service_quantity_{service_item.pk}': '2'}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Booking.objects.exists())
        self.assertFalse(BookingService.objects.exists())
        service_item.refresh_from_db()
        self.assertEqual(service_item.stock, 5)
        self.assertIn(BOOKING_PRICE_RULE_MISSING_ERROR, response.context['form'].non_field_errors())

    def test_cannot_book_overlapping_existing_booking(self):
        service_item = ServiceItem.objects.create(
            venue=self.venue,
            name='Water',
            category=ServiceItem.DRINK,
            price=Decimal('15000.00'),
            stock=5,
        )
        create_booking(
            user=self.customer,
            field=self.field,
            booking_date=self.booking_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            price=Decimal('120000.00'),
        )
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field.pk}),
            self._booking_payload(
                start_time='09:30',
                end_time='10:30',
                **{f'service_quantity_{service_item.pk}': '2'},
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Booking.objects.filter(field=self.field, booking_date=self.booking_date).count(), 1)
        self.assertFalse(BookingService.objects.exists())
        service_item.refresh_from_db()
        self.assertEqual(service_item.stock, 5)
        self.assertIn(BOOKING_UNAVAILABLE_ERROR, response.context['form'].non_field_errors())

    def test_cannot_book_inactive_field(self):
        self.field.status = 'INACTIVE'
        self.field.save(update_fields=['status'])
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field.pk}),
            self._booking_payload(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Booking.objects.exists())
        self.assertTrue(response.context['form'].has_error('field', code='invalid_choice'))

    def test_cannot_book_inactive_venue(self):
        self.venue.status = 'INACTIVE'
        self.venue.save(update_fields=['status'])
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field.pk}),
            self._booking_payload(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Booking.objects.exists())
        self.assertTrue(response.context['form'].has_error('field', code='invalid_choice'))

    def test_anonymous_user_redirected_from_direct_field_booking(self):
        url = reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field.pk})

        response = self.client.get(url)

        self.assertRedirects(response, _login_redirect_url(url))


class BookingServiceQueryTests(ScopedBookingTestCase):
    """Service list on the booking form must be scoped to the selected field's venue."""

    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username='svc-query-customer',
            email='svc-query-customer@example.com',
            password='password',
        )
        self.owner_user = User.objects.create_user(
            username='svc-query-owner',
            email='svc-query-owner@example.com',
            password='password',
        )
        self.owner_profile = OwnerProfile.objects.create(
            user=self.owner_user,
            business_name='Service Query Owner',
            is_verified=True,
        )
        self.sport = Sport.objects.create(name='Futsal', slug='futsal-svc-query')
        self.field_type = FieldType.objects.create(
            sport=self.sport,
            name='Indoor',
            slug='futsal-svc-query-indoor',
            player_count=10,
        )
        self.venue_a = Venue.objects.create(
            owner=self.owner_profile,
            name='Venue A Query',
            address='1 A Street',
            status='ACTIVE',
        )
        self.venue_b = Venue.objects.create(
            owner=self.owner_profile,
            name='Venue B Query',
            address='2 B Street',
            status='ACTIVE',
        )
        self.field_a = Field.objects.create(
            venue=self.venue_a,
            field_type=self.field_type,
            name='Field A Query',
            status='ACTIVE',
        )
        self.field_b = Field.objects.create(
            venue=self.venue_b,
            field_type=self.field_type,
            name='Field B Query',
            status='ACTIVE',
        )
        for field in (self.field_a, self.field_b):
            FieldPriceRule.objects.create(
                field=field,
                start_time=time(8, 0),
                end_time=time(12, 0),
                price_per_hour=Decimal('100000.00'),
                priority=1,
            )
        self.service_a = ServiceItem.objects.create(
            venue=self.venue_a,
            name='Service A Active',
            category=ServiceItem.DRINK,
            price=Decimal('10000.00'),
            stock=10,
        )
        self.service_b = ServiceItem.objects.create(
            venue=self.venue_b,
            name='Service B Active',
            category=ServiceItem.DRINK,
            price=Decimal('10000.00'),
            stock=10,
        )
        self.service_a_inactive = ServiceItem.objects.create(
            venue=self.venue_a,
            name='Service A Inactive',
            category=ServiceItem.DRINK,
            price=Decimal('10000.00'),
            stock=10,
            is_active=False,
        )
        self.booking_date = date(2026, 6, 10)

        self.redis_client = fakeredis.FakeStrictRedis(decode_responses=True)
        self.redis_patcher = patch('apps.bookings.services.get_redis_client', return_value=self.redis_client)
        self.redis_patcher.start()
        self.redis_client.flushdb()

    def tearDown(self):
        self.redis_client.flushdb()
        self.redis_patcher.stop()

    def _booking_payload(self, **overrides):
        payload = {
            'field': self.field_a.pk,
            'booking_date': self.booking_date.isoformat(),
            'start_time': '09:00',
            'end_time': '10:00',
            'note': '',
        }
        payload.update(overrides)
        return payload

    def test_form_for_field_a_lists_only_active_same_venue_services(self):
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field_a.pk}),
        )

        self.assertEqual(response.status_code, 200)
        service_items = list(response.context['form'].service_items)
        self.assertIn(self.service_a, service_items)
        self.assertNotIn(self.service_b, service_items)
        self.assertNotIn(self.service_a_inactive, service_items)
        self.assertContains(response, 'Service A Active')
        self.assertNotContains(response, 'Service B Active')
        self.assertNotContains(response, 'Service A Inactive')

    def test_booking_form_includes_field_change_service_ajax_wiring(self):
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field_a.pk}),
        )

        self.assertEqual(response.status_code, 200)
        # Field change refreshes the service list via the AJAX endpoint using an
        # absolute URL template, so it never collides with the availability call.
        self.assertContains(response, 'data-service-section')
        self.assertContains(
            response,
            'data-services-url-template="/dat-san/fields/__FIELD_ID__/services/"',
        )
        self.assertContains(response, 'data-service-tbody')
        self.assertContains(response, 'js/booking-time-blocks.js')
        # No relative service URL that could resolve to the availability endpoint.
        self.assertNotContains(response, 'data-services-url="services/"')
        self.assertNotContains(response, 'data-services-url="/bookings/availability/"')

    def test_service_url_template_uses_app_route(self):
        url_template = reverse('bookings:field_services', kwargs={'field_id': 0}).replace('/0/', '/__FIELD_ID__/')

        self.assertEqual(url_template, '/dat-san/fields/__FIELD_ID__/services/')
        self.assertNotEqual(url_template, 'services/')

    def test_field_services_endpoint_returns_services_key_not_availability(self):
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse('bookings:field_services', kwargs={'field_id': self.field_a.pk}),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('services', data)
        self.assertNotIn('time_blocks', data)
        self.assertNotIn('unavailable_blocks', data)

    def test_field_services_endpoint_returns_only_same_venue_active_services(self):
        self.client.force_login(self.customer)

        response_a = self.client.get(
            reverse('bookings:field_services', kwargs={'field_id': self.field_a.pk}),
        )
        response_b = self.client.get(
            reverse('bookings:field_services', kwargs={'field_id': self.field_b.pk}),
        )

        self.assertEqual(response_a.status_code, 200)
        self.assertEqual(response_b.status_code, 200)
        ids_a = {svc['id'] for svc in response_a.json()['services']}
        ids_b = {svc['id'] for svc in response_b.json()['services']}
        self.assertIn(self.service_a.pk, ids_a)
        self.assertNotIn(self.service_b.pk, ids_a)
        self.assertIn(self.service_b.pk, ids_b)
        self.assertNotIn(self.service_a.pk, ids_b)

    def test_field_services_endpoint_excludes_inactive_services(self):
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse('bookings:field_services', kwargs={'field_id': self.field_a.pk}),
        )

        ids = {svc['id'] for svc in response.json()['services']}
        self.assertIn(self.service_a.pk, ids)
        self.assertNotIn(self.service_a_inactive.pk, ids)

    def test_field_services_endpoint_payload_shape(self):
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse('bookings:field_services', kwargs={'field_id': self.field_a.pk}),
        )

        service = next(
            svc for svc in response.json()['services'] if svc['id'] == self.service_a.pk
        )
        self.assertEqual(service['name'], 'Service A Active')
        self.assertEqual(service['stock'], 10)
        self.assertEqual(service['price'], '10000.00')
        self.assertIn('category', service)
        self.assertIn('image_url', service)

    def test_field_services_endpoint_returns_empty_for_soft_deleted_venue(self):
        self.venue_a.is_deleted = True
        self.venue_a.deleted_at = timezone.now()
        self.venue_a.status = 'INACTIVE'
        self.venue_a.save(update_fields=['is_deleted', 'deleted_at', 'status'])
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse('bookings:field_services', kwargs={'field_id': self.field_a.pk}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['services'], [])

    def test_field_services_endpoint_requires_login(self):
        response = self.client.get(
            reverse('bookings:field_services', kwargs={'field_id': self.field_a.pk}),
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(resolve_url(settings.LOGIN_URL), response['Location'])

    def test_post_booking_with_service_from_other_venue_is_rejected(self):
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field_a.pk}),
            self._booking_payload(**{f'service_quantity_{self.service_b.pk}': '2'}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Booking.objects.exists())
        self.assertFalse(BookingService.objects.exists())
        self.service_b.refresh_from_db()
        self.assertEqual(self.service_b.stock, 10)

    def test_post_booking_with_inactive_service_is_rejected(self):
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('bookings:booking_create_for_field', kwargs={'field_id': self.field_a.pk}),
            self._booking_payload(**{f'service_quantity_{self.service_a_inactive.pk}': '2'}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Booking.objects.exists())
        self.assertFalse(BookingService.objects.exists())
        self.service_a_inactive.refresh_from_db()
        self.assertEqual(self.service_a_inactive.stock, 10)
