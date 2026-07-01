from datetime import time
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.shortcuts import resolve_url
from django.test import TestCase, override_settings
from django.urls import include, path, reverse

from apps.accounts.models import OwnerProfile, OwnerRegistrationRequest, Role, UserRole
from apps.services.models import ServiceItem
from apps.venues.models import (
    Field,
    FieldCreationRequest,
    FieldPriceRule,
    FieldType,
    OwnerVenueRequest,
    Sport,
    Venue,
    VenueOperatingHour,
)


def _stub_view(request, *args, **kwargs):
    return HttpResponse('ok')


_ACCOUNT_URLPATTERNS = ([
    path('dang-nhap/', _stub_view, name='login'),
    path('dashboard/', _stub_view, name='dashboard'),
], 'accounts')

urlpatterns = [
    path('', include(_ACCOUNT_URLPATTERNS, namespace='accounts')),
    path('dang-nhap/', _stub_view, name='login'),
    path('co-so/', include('apps.venues.urls')),
]


# Flat locmem stubs so we exercise the real views/context without pulling in the
# dashboard base template, static files, or custom template tags.
_FIELD_MANAGE_STUB = (
    'TAB:{{ active_tab }}|'
    'FIELD:{{ field.name }}|'
    '{% for b in pricing_blocks %}[{{ b.start_label }}-{{ b.end_label }}:'
    '{{ b.price_per_hour|floatformat:0 }}:{{ b.source }}]{% endfor %}|'
    '{% for item in service_items %}<svc>{{ item.name }}:{{ item.price|floatformat:0 }}:'
    '{% if item.is_active %}ON{% else %}OFF{% endif %}</svc>{% endfor %}|'
    'NAMEVAL:{{ form.name.value }}|'
    '{% for e in form.non_field_errors %}ERR:{{ e }}{% endfor %}'
    '{% for e in form.name.errors %}NAMEERR:{{ e }}{% endfor %}'
)

_PRICING_PANEL_STUB = (
    '{% for b in pricing_blocks %}[{{ b.start_label }}-{{ b.end_label }}:'
    '{{ b.price_per_hour|floatformat:0 }}:{{ b.source }}]{% endfor %}'
)

_SERVICES_PANEL_STUB = (
    '{% for item in service_items %}<svc>{{ item.name }}:{{ item.price|floatformat:0 }}:'
    '{% if item.is_active %}ON{% else %}OFF{% endif %}</svc>{% endfor %}'
)

_SCOPED_TEMPLATE_MAP = {
    'venues/field_manage.html': _FIELD_MANAGE_STUB,
    'venues/partials/_field_pricing_panel.html': _PRICING_PANEL_STUB,
    'venues/partials/_field_services_panel.html': _SERVICES_PANEL_STUB,
}

_SCOPED_TEST_TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': False,
    'OPTIONS': {
        'context_processors': [
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
class FieldManageTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner_a_user = User.objects.create_user(
            username='fm-owner-a', email='fm-owner-a@example.com', password='password',
        )
        self.owner_a = OwnerProfile.objects.create(
            user=self.owner_a_user, business_name='Owner A',
        )
        self.owner_b_user = User.objects.create_user(
            username='fm-owner-b', email='fm-owner-b@example.com', password='password',
        )
        self.owner_b = OwnerProfile.objects.create(
            user=self.owner_b_user, business_name='Owner B',
        )
        self.plain_user = User.objects.create_user(
            username='fm-plain', email='fm-plain@example.com', password='password',
        )

        self.sport = Sport.objects.create(name='Football', slug='fm-football')
        self.field_type = FieldType.objects.create(
            sport=self.sport, name='5-a-side', slug='fm-5-a-side', player_count=10,
        )
        self.venue_a = Venue.objects.create(
            owner=self.owner_a, name='Venue A', address='1 A Street',
        )
        self.venue_b = Venue.objects.create(
            owner=self.owner_b, name='Venue B', address='2 B Street',
        )
        self.field_a = Field.objects.create(
            venue=self.venue_a, field_type=self.field_type, name='Field A1', status='ACTIVE',
        )
        self.field_b = Field.objects.create(
            venue=self.venue_b, field_type=self.field_type, name='Field B1', status='ACTIVE',
        )
        self.service_a = ServiceItem.objects.create(
            venue=self.venue_a, name='Water A', category=ServiceItem.DRINK,
            price=Decimal('10000.00'), stock=20, is_active=True,
        )
        self.service_b = ServiceItem.objects.create(
            venue=self.venue_b, name='Water B', category=ServiceItem.DRINK,
            price=Decimal('10000.00'), stock=20, is_active=True,
        )

    def edit_url(self, field):
        return reverse('venues:field_edit', kwargs={'pk': field.pk})

    # 1. Owner accesses own field manage screen -> 200.
    def test_owner_can_open_own_field_manage_screen(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self.edit_url(self.field_a))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TAB:info')
        self.assertContains(response, 'FIELD:Field A1')

    def test_field_manage_respects_tab_query_param(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self.edit_url(self.field_a) + '?tab=pricing')
        self.assertContains(response, 'TAB:pricing')

    # 2. Owner cannot access another owner's field -> 403.
    def test_owner_cannot_open_other_owners_field(self):
        self.client.force_login(self.owner_b_user)
        response = self.client.get(self.edit_url(self.field_a))
        self.assertEqual(response.status_code, 403)

    def test_non_owner_is_redirected_away(self):
        self.client.force_login(self.plain_user)
        response = self.client.get(self.edit_url(self.field_a))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('accounts:dashboard'))

    # 3. Panel info submit updates the field.
    def test_info_submit_updates_field(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(self.edit_url(self.field_a), {
            'name': 'Field A1 Renamed',
            'field_type': self.field_type.pk,
            'surface_type': 'Cỏ nhân tạo',
            'capacity': '10',
            'status': 'MAINTENANCE',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.edit_url(self.field_a) + '?tab=info')
        self.field_a.refresh_from_db()
        self.assertEqual(self.field_a.name, 'Field A1 Renamed')
        self.assertEqual(self.field_a.status, 'MAINTENANCE')

    def test_info_submit_invalid_returns_400_with_errors(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(self.edit_url(self.field_a), {
            'name': '',
            'field_type': self.field_type.pk,
            'status': 'ACTIVE',
        })
        self.assertEqual(response.status_code, 400)
        self.field_a.refresh_from_db()
        self.assertEqual(self.field_a.name, 'Field A1')

    def test_owner_cannot_post_info_for_other_owners_field(self):
        self.client.force_login(self.owner_b_user)
        response = self.client.post(self.edit_url(self.field_a), {
            'name': 'Hacked', 'field_type': self.field_type.pk, 'status': 'ACTIVE',
        })
        self.assertEqual(response.status_code, 403)
        self.field_a.refresh_from_db()
        self.assertEqual(self.field_a.name, 'Field A1')

    # 4. Field without custom rules renders the default price table.
    def test_pricing_panel_renders_default_prices_when_no_rules(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self.edit_url(self.field_a) + '?tab=pricing')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(':DEFAULT]', content)
        self.assertNotIn(':CUSTOM]', content)
        # Default daytime price is 100000đ/h, evening peak 150000đ/h.
        self.assertIn(':100000:DEFAULT]', content)
        self.assertIn(':150000:DEFAULT]', content)

    # 4b. Pricing panel uses one-hour blocks (matches the booking slot UI).
    def test_pricing_panel_renders_hourly_blocks(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self.edit_url(self.field_a) + '?tab=pricing')
        content = response.content.decode()
        # Hourly block present, no 30-minute blocks anymore.
        self.assertIn('[06:00-07:00:', content)
        self.assertIn('[21:00-22:00:', content)
        self.assertNotIn('[06:00-06:30:', content)
        self.assertNotIn('[06:30-07:00:', content)

    # 4c. A half-hour open_time (05:30) is normalised up to whole hours so the
    #     pricing blocks line up with the booking slot grid (06:00-07:00, ...).
    def test_pricing_panel_normalizes_half_hour_open_to_whole_hours(self):
        VenueOperatingHour.objects.create(
            venue=self.venue_a, weekday=0,
            open_time=time(5, 30), close_time=time(22, 30),
        )
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self.edit_url(self.field_a) + '?tab=pricing')
        content = response.content.decode()
        self.assertNotIn('[05:30-06:30:', content)
        self.assertNotIn('[06:30-07:30:', content)
        self.assertIn('[06:00-07:00:', content)
        self.assertIn('[07:00-08:00:', content)
        self.assertIn('[21:00-22:00:', content)

    # 5. Bulk price update creates/updates rules without duplicates.
    def test_bulk_price_update_creates_rules_without_duplicates(self):
        self.client.force_login(self.owner_a_user)
        blocks = ['06:00-07:00', '07:00-08:00']
        response = self.client.post(
            reverse('venues:field_pricing_update', kwargs={'pk': self.field_a.pk}),
            {'blocks': blocks, 'price_per_hour': '120000'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.edit_url(self.field_a) + '?tab=pricing')
        rules = FieldPriceRule.objects.filter(field=self.field_a)
        self.assertEqual(rules.count(), 2)
        for rule in rules:
            self.assertIsNone(rule.day_of_week)
            self.assertEqual(rule.price_per_hour, Decimal('120000'))

        # Re-submitting the same blocks updates instead of duplicating.
        self.client.post(
            reverse('venues:field_pricing_update', kwargs={'pk': self.field_a.pk}),
            {'blocks': blocks, 'price_per_hour': '130000'},
        )
        rules = FieldPriceRule.objects.filter(field=self.field_a)
        self.assertEqual(rules.count(), 2)
        self.assertTrue(all(r.price_per_hour == Decimal('130000') for r in rules))

    # 5b. A single one-hour block creates exactly one rule (not two 30' rules).
    def test_single_hour_block_creates_one_rule(self):
        self.client.force_login(self.owner_a_user)
        self.client.post(
            reverse('venues:field_pricing_update', kwargs={'pk': self.field_a.pk}),
            {'blocks': ['06:00-07:00'], 'price_per_hour': '120000'},
        )
        rules = FieldPriceRule.objects.filter(field=self.field_a)
        self.assertEqual(rules.count(), 1)
        rule = rules.get()
        self.assertEqual(rule.start_time, time(6, 0))
        self.assertEqual(rule.end_time, time(7, 0))
        self.assertIsNone(rule.day_of_week)

    def test_saved_custom_price_shows_as_custom_source(self):
        self.client.force_login(self.owner_a_user)
        self.client.post(
            reverse('venues:field_pricing_update', kwargs={'pk': self.field_a.pk}),
            {'blocks': ['06:00-07:00'], 'price_per_hour': '99000'},
        )
        response = self.client.get(self.edit_url(self.field_a) + '?tab=pricing')
        self.assertContains(response, '[06:00-07:00:99000:CUSTOM]')

    # 6. Negative price is rejected.
    def test_negative_price_is_rejected(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_pricing_update', kwargs={'pk': self.field_a.pk}),
            {'blocks': ['06:00-07:00'], 'price_per_hour': '-1000'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload['ok'])
        self.assertFalse(FieldPriceRule.objects.filter(field=self.field_a).exists())

    def test_pricing_requires_at_least_one_block(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_pricing_update', kwargs={'pk': self.field_a.pk}),
            {'blocks': [], 'price_per_hour': '120000'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FieldPriceRule.objects.filter(field=self.field_a).exists())

    def test_owner_cannot_update_pricing_for_other_owners_field(self):
        self.client.force_login(self.owner_b_user)
        response = self.client.post(
            reverse('venues:field_pricing_update', kwargs={'pk': self.field_a.pk}),
            {'blocks': ['06:00-07:00'], 'price_per_hour': '120000'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(FieldPriceRule.objects.filter(field=self.field_a).exists())

    # 7. Services panel only shows the field venue's items.
    def test_services_panel_only_shows_field_venue_items(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self.edit_url(self.field_a) + '?tab=services')
        content = response.content.decode()
        self.assertIn('Water A', content)
        self.assertNotIn('Water B', content)

    # 8. Owner cannot edit a service item from another venue.
    def test_owner_cannot_edit_foreign_service_item(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_service_price', kwargs={
                'pk': self.field_a.pk, 'item_id': self.service_b.pk,
            }),
            {'price': '5000'},
        )
        self.assertEqual(response.status_code, 404)
        self.service_b.refresh_from_db()
        self.assertEqual(self.service_b.price, Decimal('10000.00'))

    # 9. Service price update succeeds.
    def test_service_price_update_success(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_service_price', kwargs={
                'pk': self.field_a.pk, 'item_id': self.service_a.pk,
            }),
            {'price': '7000'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.edit_url(self.field_a) + '?tab=services')
        self.service_a.refresh_from_db()
        self.assertEqual(self.service_a.price, Decimal('7000'))

    def test_service_price_negative_rejected(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_service_price', kwargs={
                'pk': self.field_a.pk, 'item_id': self.service_a.pk,
            }),
            {'price': '-1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 400)
        self.service_a.refresh_from_db()
        self.assertEqual(self.service_a.price, Decimal('10000.00'))

    # 10. Toggling service status succeeds.
    def test_service_toggle_status_success(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_service_toggle', kwargs={
                'pk': self.field_a.pk, 'item_id': self.service_a.pk,
            }),
            {'is_active': '0'},
        )
        self.assertEqual(response.status_code, 302)
        self.service_a.refresh_from_db()
        self.assertFalse(self.service_a.is_active)

    def test_owner_cannot_toggle_foreign_service_item(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_service_toggle', kwargs={
                'pk': self.field_a.pk, 'item_id': self.service_b.pk,
            }),
            {'is_active': '0'},
        )
        self.assertEqual(response.status_code, 404)
        self.service_b.refresh_from_db()
        self.assertTrue(self.service_b.is_active)

    # 11. AJAX responses return the expected JSON + partial html.
    def test_ajax_pricing_update_returns_json_and_html(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_pricing_update', kwargs={'pk': self.field_a.pk}),
            {'blocks': ['06:00-07:00'], 'price_per_hour': '88000'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIn('message', payload)
        self.assertIn('[06:00-07:00:88000:CUSTOM]', payload['html'])

    def test_ajax_service_toggle_returns_json_and_html(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_service_toggle', kwargs={
                'pk': self.field_a.pk, 'item_id': self.service_a.pk,
            }),
            {'is_active': '0'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertFalse(payload['is_active'])
        self.assertIn('<svc>Water A:10000:OFF</svc>', payload['html'])

    # 12. Non-AJAX fallback redirects to the right tab and sets a message.
    def test_non_ajax_pricing_update_redirects_with_message(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_pricing_update', kwargs={'pk': self.field_a.pk}),
            {'blocks': ['06:00-07:00'], 'price_per_hour': '88000'},
        )
        self.assertRedirects(
            response,
            self.edit_url(self.field_a) + '?tab=pricing',
            fetch_redirect_response=False,
        )
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any('khung giờ' in str(m) for m in messages))

    def test_non_ajax_service_toggle_redirects_with_message(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_service_toggle', kwargs={
                'pk': self.field_a.pk, 'item_id': self.service_a.pk,
            }),
            {'is_active': '0'},
        )
        self.assertRedirects(
            response,
            self.edit_url(self.field_a) + '?tab=services',
            fetch_redirect_response=False,
        )
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any('Water A' in str(m) for m in messages))


class OwnerFieldListViewTests(TestCase):
    """`/co-so/owner/venues/<venue_id>/fields/` renders the owner's field list.

    Uses the real templates/URLconf (no stubs) to guard against the
    TemplateDoesNotExist regression in OwnerFieldListView.
    """

    def setUp(self):
        User = get_user_model()
        self.owner_role, _ = Role.objects.get_or_create(name=Role.OWNER)

        self.owner_a_user = User.objects.create_user(
            username='ofl-owner-a', email='ofl-owner-a@example.com', password='password',
        )
        UserRole.objects.create(user=self.owner_a_user, role=self.owner_role)
        self.owner_a = OwnerProfile.objects.create(
            user=self.owner_a_user, business_name='Owner A', is_verified=True,
        )
        self.owner_b_user = User.objects.create_user(
            username='ofl-owner-b', email='ofl-owner-b@example.com', password='password',
        )
        UserRole.objects.create(user=self.owner_b_user, role=self.owner_role)
        self.owner_b = OwnerProfile.objects.create(
            user=self.owner_b_user, business_name='Owner B', is_verified=True,
        )

        self.sport = Sport.objects.create(name='Football', slug='ofl-football')
        self.field_type = FieldType.objects.create(
            sport=self.sport, name='5-a-side', slug='ofl-5-a-side', player_count=10,
        )
        self.venue_a = Venue.objects.create(
            owner=self.owner_a, name='Sân Owner A', address='1 A Street', status='ACTIVE',
        )
        self.venue_b = Venue.objects.create(
            owner=self.owner_b, name='Sân Owner B', address='2 B Street', status='ACTIVE',
        )
        self.field_a1 = Field.objects.create(
            venue=self.venue_a, field_type=self.field_type, name='Sân A Số 1', status='ACTIVE',
        )
        self.field_a2 = Field.objects.create(
            venue=self.venue_a, field_type=self.field_type, name='Sân A Số 2', status='MAINTENANCE',
        )
        self.field_b1 = Field.objects.create(
            venue=self.venue_b, field_type=self.field_type, name='Sân B Số 1', status='ACTIVE',
        )

    def _url(self, venue):
        return reverse('venues:owner_field_list', kwargs={'venue_pk': venue.pk})

    def test_owner_can_open_own_venue_field_list(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self._url(self.venue_a))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'venues/owner_field_list.html')
        self.assertContains(response, 'Sân Owner A')
        self.assertContains(response, 'Sân A Số 1')
        self.assertContains(response, 'Sân A Số 2')

    def test_action_button_links_to_field_manage_screen(self):
        # The action column must open the full 3-panel field management screen
        # (venues:field_edit), not the price-rule-only page.
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self._url(self.venue_a))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Quản lý sân')
        self.assertNotContains(response, 'Quản lý giá')
        manage_url = reverse('venues:field_edit', kwargs={'pk': self.field_a1.pk})
        self.assertContains(response, f'href="{manage_url}"')

    def test_field_list_excludes_other_venue_fields(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self._url(self.venue_a))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Sân B Số 1')

    def test_owner_cannot_open_other_owners_venue(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self._url(self.venue_b))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        url = self._url(self.venue_a)
        response = self.client.get(url)
        self.assertRedirects(response, f'{resolve_url(settings.LOGIN_URL)}?next={url}')


class OwnerPriceRuleListViewTests(TestCase):
    """`/co-so/owner/fields/<field_id>/price-rules/` renders the field's price
    rules. Uses the real templates/URLconf to guard the TemplateDoesNotExist
    regression in OwnerPriceRuleListView."""

    def setUp(self):
        from datetime import time

        User = get_user_model()
        self.owner_role, _ = Role.objects.get_or_create(name=Role.OWNER)

        self.owner_a_user = User.objects.create_user(
            username='prl-owner-a', email='prl-owner-a@example.com', password='password',
        )
        UserRole.objects.create(user=self.owner_a_user, role=self.owner_role)
        self.owner_a = OwnerProfile.objects.create(
            user=self.owner_a_user, business_name='Owner A', is_verified=True,
        )
        self.owner_b_user = User.objects.create_user(
            username='prl-owner-b', email='prl-owner-b@example.com', password='password',
        )
        UserRole.objects.create(user=self.owner_b_user, role=self.owner_role)
        self.owner_b = OwnerProfile.objects.create(
            user=self.owner_b_user, business_name='Owner B', is_verified=True,
        )

        self.sport = Sport.objects.create(name='Football', slug='prl-football')
        self.field_type = FieldType.objects.create(
            sport=self.sport, name='5-a-side', slug='prl-5-a-side', player_count=10,
        )
        self.venue_a = Venue.objects.create(
            owner=self.owner_a, name='Cơ sở A', address='1 A Street', status='ACTIVE',
        )
        self.venue_b = Venue.objects.create(
            owner=self.owner_b, name='Cơ sở B', address='2 B Street', status='ACTIVE',
        )
        self.field_a = Field.objects.create(
            venue=self.venue_a, field_type=self.field_type, name='Sân Giá A', status='ACTIVE',
        )
        self.field_a_empty = Field.objects.create(
            venue=self.venue_a, field_type=self.field_type, name='Sân Chưa Có Giá', status='ACTIVE',
        )
        self.field_b = Field.objects.create(
            venue=self.venue_b, field_type=self.field_type, name='Sân Giá B', status='ACTIVE',
        )
        self.rule_a = FieldPriceRule.objects.create(
            field=self.field_a, day_of_week=None,
            start_time=time(6, 0), end_time=time(22, 0),
            price_per_hour=Decimal('150000.00'), priority=1,
        )

    def _url(self, field):
        return reverse('venues:owner_price_rule_list', kwargs={'field_pk': field.pk})

    def test_owner_can_open_own_field_price_rules(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self._url(self.field_a))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'venues/owner_price_rule_list.html')
        self.assertContains(response, 'Quản lý giá sân')
        self.assertContains(response, 'Sân Giá A')
        self.assertContains(response, '150000đ')
        self.assertContains(response, 'Tất cả các ngày')

    def test_field_without_rules_shows_empty_state(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self._url(self.field_a_empty))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Chưa có bảng giá riêng')

    def test_owner_cannot_open_other_owners_field(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.get(self._url(self.field_b))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        url = self._url(self.field_a)
        response = self.client.get(url)
        self.assertRedirects(response, f'{resolve_url(settings.LOGIN_URL)}?next={url}')

    def test_create_price_rule_form_renders(self):
        # The "Thêm giá" button targets this route; its template must exist too.
        self.client.force_login(self.owner_a_user)
        response = self.client.get(
            reverse('venues:owner_price_rule_create', kwargs={'field_pk': self.field_a.pk}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'venues/owner_price_rule_form.html')
        self.assertContains(response, 'Thêm mức giá')


class PublicVenueRouteTests(TestCase):
    """Public venue navigation must not resolve to owner-only management URLs."""

    def setUp(self):
        User = get_user_model()
        self.owner_role, _ = Role.objects.get_or_create(name=Role.OWNER)
        self.customer_role, _ = Role.objects.get_or_create(name=Role.CUSTOMER)
        self.admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)

        self.owner_user = User.objects.create_user(
            username='public-owner',
            email='public-owner@example.com',
            password='password',
        )
        UserRole.objects.update_or_create(
            user=self.owner_user,
            defaults={'role': self.owner_role},
        )
        self.owner = OwnerProfile.objects.create(
            user=self.owner_user,
            business_name='Public Owner',
            is_verified=True,
        )
        self.customer_user = User.objects.create_user(
            username='public-customer',
            email='public-customer@example.com',
            password='password',
        )
        UserRole.objects.update_or_create(
            user=self.customer_user,
            defaults={'role': self.customer_role},
        )
        self.admin_user = User.objects.create_user(
            username='public-admin',
            email='public-admin@example.com',
            password='password',
        )
        UserRole.objects.update_or_create(
            user=self.admin_user,
            defaults={'role': self.admin_role},
        )
        self.venue = Venue.objects.create(
            owner=self.owner,
            name='Public Venue',
            address='1 Public Street',
            status=Venue.ACTIVE,
        )
        self.other_owner_user = User.objects.create_user(
            username='public-other-owner',
            email='public-other-owner@example.com',
            password='password',
        )
        UserRole.objects.update_or_create(
            user=self.other_owner_user,
            defaults={'role': self.owner_role},
        )
        self.other_owner = OwnerProfile.objects.create(
            user=self.other_owner_user,
            business_name='Other Public Owner',
            is_verified=True,
        )
        self.other_venue = Venue.objects.create(
            owner=self.other_owner,
            name='Other Owner Venue',
            address='2 Public Street',
            status=Venue.ACTIVE,
        )

    def test_public_venue_list_name_uses_public_route(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('venues:venue_list'))

        self.assertEqual(reverse('venues:venue_list'), '/co-so/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'venues/venue_list.html')
        self.assertContains(response, 'Public Venue')

    def test_public_venue_detail_name_uses_public_route(self):
        self.client.force_login(self.customer_user)
        response = self.client.get(reverse('venues:venue_detail', kwargs={'pk': self.venue.pk}))

        self.assertEqual(reverse('venues:venue_detail', kwargs={'pk': self.venue.pk}), f'/co-so/{self.venue.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'venues/venue_detail.html')
        self.assertContains(response, 'Public Venue')

    def test_public_venue_detail_shows_booking_cta_for_active_venue(self):
        self.client.force_login(self.customer_user)

        response = self.client.get(reverse('venues:venue_detail', kwargs={'pk': self.venue.pk}))

        booking_url = f"{reverse('bookings:booking_create')}?venue={self.venue.pk}"
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Đặt sân tại đây')
        self.assertContains(response, f'href="{booking_url}"')

    def test_public_venue_detail_excludes_inactive_or_deleted_venues(self):
        self.client.force_login(self.customer_user)

        self.venue.status = Venue.INACTIVE
        self.venue.save(update_fields=['status'])
        response = self.client.get(reverse('venues:venue_detail', kwargs={'pk': self.venue.pk}))
        self.assertEqual(response.status_code, 404)

        self.venue.status = Venue.ACTIVE
        self.venue.is_deleted = True
        self.venue.save(update_fields=['status', 'is_deleted'])
        response = self.client.get(reverse('venues:venue_detail', kwargs={'pk': self.venue.pk}))
        self.assertEqual(response.status_code, 404)

    def test_owner_root_venue_list_renders_owner_management(self):
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('venues:venue_list'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'venues/owner_venue_list.html')
        self.assertContains(response, 'Quản lý cơ sở')
        self.assertContains(response, 'Public Venue')
        self.assertNotContains(response, 'Other Owner Venue')

    def test_owner_venue_detail_shows_management_actions_not_booking_cta(self):
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('venues:venue_detail', kwargs={'pk': self.venue.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public Venue')
        self.assertContains(response, 'Sửa cơ sở')
        self.assertContains(response, 'Quản lý sân con')
        self.assertContains(response, 'Thêm sân con')
        self.assertNotContains(response, 'Đặt sân tại đây')

    def test_owner_cannot_open_other_owners_venue_detail(self):
        self.client.force_login(self.owner_user)

        response = self.client.get(reverse('venues:venue_detail', kwargs={'pk': self.other_venue.pk}))

        self.assertEqual(response.status_code, 404)

    def test_owner_can_update_own_venue(self):
        self.client.force_login(self.owner_user)
        url = reverse('venues:owner_venue_update', kwargs={'pk': self.venue.pk})

        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertTemplateUsed(get_response, 'venues/owner_venue_form.html')

        response = self.client.post(url, {
            'name': 'Public Venue Updated',
            'description': 'Updated description',
            'address': 'Updated Street',
            'latitude': '',
            'longitude': '',
        })

        self.assertRedirects(
            response,
            reverse('venues:venue_detail', kwargs={'pk': self.venue.pk}),
            fetch_redirect_response=False,
        )
        self.venue.refresh_from_db()
        self.assertEqual(self.venue.name, 'Public Venue Updated')

    def test_owner_cannot_update_other_owners_venue(self):
        self.client.force_login(self.owner_user)

        response = self.client.get(
            reverse('venues:owner_venue_update', kwargs={'pk': self.other_venue.pk}),
        )

        self.assertEqual(response.status_code, 404)

    def test_owner_venue_list_redirects_non_owner_sessions(self):
        owner_url = reverse('venues:owner_venue_list')

        self.client.force_login(self.customer_user)
        response = self.client.get(owner_url)
        self.assertRedirects(response, reverse('venues:venue_list'), fetch_redirect_response=False)

        self.client.force_login(self.admin_user)
        response = self.client.get(owner_url)
        self.assertRedirects(response, reverse('venues:admin_venue_list'), fetch_redirect_response=False)

    def test_owner_venue_list_still_allows_owners(self):
        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('venues:owner_venue_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public Venue')


class VenueFieldApprovalFlowTests(TestCase):
    """Owner create requests must go through admin approval before a real
    ``Venue``/``Field`` is created. Uses the real templates/URLconf so the
    ``TemplateDoesNotExist`` regression on the owner create form stays fixed.
    """

    def setUp(self):
        User = get_user_model()
        self.owner_role, _ = Role.objects.get_or_create(name=Role.OWNER)
        self.admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)

        # Owner A (the acting owner).
        self.owner_user = User.objects.create_user(
            username='ap-owner', email='ap-owner@example.com', password='password',
        )
        UserRole.objects.create(user=self.owner_user, role=self.owner_role)
        self.owner = OwnerProfile.objects.create(
            user=self.owner_user, business_name='Owner Approval', is_verified=True,
        )

        # Owner B (used to prove cross-owner field requests are blocked).
        self.other_owner_user = User.objects.create_user(
            username='ap-owner-b', email='ap-owner-b@example.com', password='password',
        )
        UserRole.objects.create(user=self.other_owner_user, role=self.owner_role)
        self.other_owner = OwnerProfile.objects.create(
            user=self.other_owner_user, business_name='Owner B', is_verified=True,
        )

        # Admin reviewer.
        self.admin_user = User.objects.create_user(
            username='ap-admin', email='ap-admin@example.com', password='password',
        )
        UserRole.objects.create(user=self.admin_user, role=self.admin_role)

        self.sport = Sport.objects.create(name='Football', slug='ap-football')
        self.field_type = FieldType.objects.create(
            sport=self.sport, name='5-a-side', slug='ap-5-a-side', player_count=10,
        )
        self.venue = Venue.objects.create(
            owner=self.owner, name='Cơ sở Owner A', address='1 A Street', status='ACTIVE',
        )
        self.other_venue = Venue.objects.create(
            owner=self.other_owner, name='Cơ sở Owner B', address='2 B Street', status='ACTIVE',
        )

    def create_owner_registration_request(self, email, status=OwnerRegistrationRequest.PENDING):
        return OwnerRegistrationRequest.objects.create(
            email=email,
            first_name='Owner',
            last_name=email.split('@')[0].replace('-', ' ').title(),
            phone='0901234567',
            business_name=f'Business {email}',
            bank_account_number='123456789',
            bank_name='Test Bank',
            password_hash=make_password('Password123!'),
            status=status,
        )

    # --- 0. Admin request list renders both request tables without 500. ---
    def test_admin_request_list_empty_returns_200(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('venues:admin_request_list'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'venues/admin_request_list.html')
        self.assertContains(response, 'Yêu cầu làm chủ sân')
        self.assertContains(response, 'Không có yêu cầu làm chủ sân nào.')
        self.assertContains(response, 'Không có yêu cầu tạo cơ sở.')
        self.assertContains(response, 'Không có yêu cầu tạo sân.')

    def test_admin_request_list_with_owner_request_returns_200(self):
        self.create_owner_registration_request('owner-pending-list@example.com')
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('venues:admin_request_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Yêu cầu làm chủ sân')
        self.assertContains(response, 'owner-pending-list@example.com')
        self.assertContains(response, 'Business owner-pending-list@example.com')
        self.assertEqual(response.context['owner_request_count'], 1)

    def test_admin_request_list_with_venue_request_returns_200(self):
        OwnerVenueRequest.objects.create(
            requested_by=self.owner_user,
            request_type=OwnerVenueRequest.CREATE,
            payload={'name': 'Cơ sở Chờ List', 'address': '100 List Street', 'description': ''},
        )
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('venues:admin_request_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cơ sở Chờ List')

    def test_admin_request_list_with_field_request_returns_200(self):
        FieldCreationRequest.objects.create(
            owner=self.owner,
            venue=self.venue,
            field_type=self.field_type,
            name='Sân Chờ List',
            field_status='ACTIVE',
            pricing_payload={'mode': 'default', 'rules': []},
        )
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('venues:admin_request_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sân Chờ List')

    def test_admin_request_list_exposes_filter_and_pending_counts(self):
        OwnerVenueRequest.objects.create(
            requested_by=self.owner_user,
            request_type=OwnerVenueRequest.CREATE,
            payload={'name': 'Cơ sở Count', 'address': '101 Count Street', 'description': ''},
        )
        FieldCreationRequest.objects.create(
            owner=self.owner,
            venue=self.venue,
            field_type=self.field_type,
            name='Sân Count',
            field_status='ACTIVE',
            pricing_payload={'mode': 'default', 'rules': []},
        )
        self.client.force_login(self.admin_user)
        response = self.client.get(
            reverse('venues:admin_request_list'),
            {'status': OwnerVenueRequest.PENDING},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['status_filter'], OwnerVenueRequest.PENDING)
        self.assertEqual(response.context['pending_venue_request_count'], 1)
        self.assertEqual(response.context['pending_field_request_count'], 1)
        self.assertEqual(response.context['pending_owner_request_count'], 0)

    def test_admin_request_list_filters_owner_requests_by_status(self):
        pending = self.create_owner_registration_request(
            'owner-filter-pending@example.com',
            OwnerRegistrationRequest.PENDING,
        )
        approved = self.create_owner_registration_request(
            'owner-filter-approved@example.com',
            OwnerRegistrationRequest.APPROVED,
        )
        rejected = self.create_owner_registration_request(
            'owner-filter-rejected@example.com',
            OwnerRegistrationRequest.REJECTED,
        )
        self.client.force_login(self.admin_user)

        cases = [
            (OwnerRegistrationRequest.PENDING, [pending]),
            (OwnerRegistrationRequest.APPROVED, [approved]),
            (OwnerRegistrationRequest.REJECTED, [rejected]),
        ]
        for status, expected in cases:
            with self.subTest(status=status):
                response = self.client.get(reverse('venues:admin_request_list'), {'status': status})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context['owner_requests']), expected)
                self.assertEqual(response.context['owner_request_count'], 1)

        response = self.client.get(reverse('venues:admin_request_list'))
        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(
            list(response.context['owner_requests']),
            [pending, approved, rejected],
        )

        response = self.client.get(reverse('venues:admin_request_list'), {'status': 'all'})
        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(
            list(response.context['owner_requests']),
            [pending, approved, rejected],
        )

    # --- 1. Owner create form renders (no TemplateDoesNotExist / 500). ---
    def test_owner_venue_create_get_returns_200(self):
        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('venues:owner_venue_create'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'venues/owner_venue_form.html')

    def test_owner_venue_create_short_alias_returns_200(self):
        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('venues:owner_venue_create_short'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'venues/owner_venue_form.html')

    # --- 2. Owner submit creates a pending request, not a real venue. ---
    def test_owner_venue_create_post_creates_pending_request_only(self):
        self.client.force_login(self.owner_user)
        venue_count_before = Venue.objects.count()
        response = self.client.post(reverse('venues:owner_venue_create'), {
            'name': 'Cơ sở Chờ Duyệt',
            'address': '99 Pending Street',
            'description': 'Mô tả',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Venue.objects.count(), venue_count_before)
        request = OwnerVenueRequest.objects.get(requested_by=self.owner_user)
        self.assertEqual(request.request_type, OwnerVenueRequest.CREATE)
        self.assertEqual(request.status, OwnerVenueRequest.PENDING)
        self.assertEqual(request.payload.get('name'), 'Cơ sở Chờ Duyệt')

    # --- 3. Admin approve creates the real venue and marks APPROVED. ---
    def test_admin_approve_venue_request_creates_venue(self):
        request = OwnerVenueRequest.objects.create(
            requested_by=self.owner_user,
            request_type=OwnerVenueRequest.CREATE,
            payload={'name': 'Cơ sở Mới', 'address': '12 New Street', 'description': ''},
        )
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('venues:admin_request_venue_approve', kwargs={'pk': request.pk}),
        )
        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, OwnerVenueRequest.APPROVED)
        self.assertEqual(request.reviewed_by, self.admin_user)
        self.assertIsNotNone(request.reviewed_at)
        venue = Venue.objects.get(name='Cơ sở Mới', owner=self.owner)
        self.assertEqual(request.target_venue_id, venue.pk)

    def test_admin_approve_venue_request_twice_creates_no_duplicate(self):
        request = OwnerVenueRequest.objects.create(
            requested_by=self.owner_user,
            request_type=OwnerVenueRequest.CREATE,
            payload={'name': 'Không Duplicate', 'address': '1 Street', 'description': ''},
        )
        self.client.force_login(self.admin_user)
        self.client.post(
            reverse('venues:admin_request_venue_approve', kwargs={'pk': request.pk}),
        )
        self.client.post(
            reverse('venues:admin_request_venue_approve', kwargs={'pk': request.pk}),
        )
        self.assertEqual(Venue.objects.filter(name='Không Duplicate').count(), 1)

    # --- 4. Admin reject does not create a venue. ---
    def test_admin_reject_venue_request_creates_no_venue(self):
        request = OwnerVenueRequest.objects.create(
            requested_by=self.owner_user,
            request_type=OwnerVenueRequest.CREATE,
            payload={'name': 'Cơ sở Bị Từ Chối', 'address': '13 Street', 'description': ''},
        )
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('venues:admin_request_venue_reject', kwargs={'pk': request.pk}),
            {'admin_note': 'Thiếu giấy phép.'},
        )
        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, OwnerVenueRequest.REJECTED)
        self.assertEqual(request.admin_note, 'Thiếu giấy phép.')
        self.assertFalse(Venue.objects.filter(name='Cơ sở Bị Từ Chối').exists())

    def _field_create_payload(self, **overrides):
        data = {
            'name': 'Sân Chờ Duyệt',
            'field_type': self.field_type.pk,
            'surface_type': 'Cỏ nhân tạo',
            'capacity': '10',
            'status': 'ACTIVE',
            'pricing-pricing_mode': 'default',
            'price_rules-TOTAL_FORMS': '0',
            'price_rules-INITIAL_FORMS': '0',
            'price_rules-MIN_NUM_FORMS': '0',
            'price_rules-MAX_NUM_FORMS': '1000',
        }
        data.update(overrides)
        return data

    # --- 5. Owner submit creates a pending field request, not a real field. ---
    def test_owner_field_create_short_alias_returns_200(self):
        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('venues:field_create', kwargs={'venue_pk': self.venue.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'venues/owner_field_form.html')

    def test_owner_field_create_post_creates_pending_request_only(self):
        self.client.force_login(self.owner_user)
        field_count_before = Field.objects.count()
        response = self.client.post(
            reverse('venues:owner_field_create', kwargs={'venue_pk': self.venue.pk}),
            self._field_create_payload(),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Field.objects.count(), field_count_before)
        request = FieldCreationRequest.objects.get(owner=self.owner, venue=self.venue)
        self.assertEqual(request.status, FieldCreationRequest.PENDING)
        self.assertEqual(request.name, 'Sân Chờ Duyệt')

    # --- 6. Owner cannot request a field in another owner's venue. ---
    def test_owner_cannot_request_field_in_other_owners_venue(self):
        self.client.force_login(self.owner_user)
        response = self.client.post(
            reverse('venues:owner_field_create', kwargs={'venue_pk': self.other_venue.pk}),
            self._field_create_payload(),
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            FieldCreationRequest.objects.filter(venue=self.other_venue).exists(),
        )

    # --- 7. Admin approve field request creates the real field. ---
    def test_admin_approve_field_request_creates_field(self):
        request = FieldCreationRequest.objects.create(
            owner=self.owner,
            venue=self.venue,
            field_type=self.field_type,
            name='Sân Được Duyệt',
            capacity=10,
            field_status='ACTIVE',
            pricing_payload={'mode': 'default', 'rules': []},
        )
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('venues:admin_request_field_approve', kwargs={'pk': request.pk}),
        )
        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, FieldCreationRequest.APPROVED)
        self.assertEqual(request.reviewed_by, self.admin_user)
        self.assertTrue(
            Field.objects.filter(venue=self.venue, name='Sân Được Duyệt').exists(),
        )

    def test_admin_approve_field_request_twice_creates_no_duplicate(self):
        request = FieldCreationRequest.objects.create(
            owner=self.owner,
            venue=self.venue,
            field_type=self.field_type,
            name='Sân Không Duplicate',
            capacity=10,
            field_status='ACTIVE',
            pricing_payload={'mode': 'default', 'rules': []},
        )
        self.client.force_login(self.admin_user)
        self.client.post(
            reverse('venues:admin_request_field_approve', kwargs={'pk': request.pk}),
        )
        self.client.post(
            reverse('venues:admin_request_field_approve', kwargs={'pk': request.pk}),
        )
        self.assertEqual(
            Field.objects.filter(venue=self.venue, name='Sân Không Duplicate').count(),
            1,
        )

    # --- 8. Admin reject field request creates no field. ---
    def test_admin_reject_field_request_creates_no_field(self):
        request = FieldCreationRequest.objects.create(
            owner=self.owner,
            venue=self.venue,
            field_type=self.field_type,
            name='Sân Bị Từ Chối',
            field_status='ACTIVE',
            pricing_payload={'mode': 'default', 'rules': []},
        )
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('venues:admin_request_field_reject', kwargs={'pk': request.pk}),
            {'reject_reason': 'Sân không đạt chuẩn.'},
        )
        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, FieldCreationRequest.REJECTED)
        self.assertEqual(request.reject_reason, 'Sân không đạt chuẩn.')
        self.assertFalse(
            Field.objects.filter(venue=self.venue, name='Sân Bị Từ Chối').exists(),
        )

    # --- 9. Non-admin cannot reach the admin request list. ---
    def test_non_admin_cannot_access_admin_request_list(self):
        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('venues:admin_request_list'))
        self.assertEqual(response.status_code, 403)

    # --- 10. Admin sidebar shows the "Duyệt yêu cầu" link; owners do not. ---
    def test_admin_sidebar_shows_review_link(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('venues:admin_request_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Duyệt yêu cầu')

    def test_owner_sidebar_hides_review_link(self):
        self.client.force_login(self.owner_user)
        response = self.client.get(reverse('venues:owner_venue_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Duyệt yêu cầu')
