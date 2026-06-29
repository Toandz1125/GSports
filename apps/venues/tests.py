from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import include, path, reverse

from apps.accounts.models import OwnerProfile
from apps.services.models import ServiceItem
from apps.venues.models import Field, FieldPriceRule, FieldType, Sport, Venue


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

    # 5. Bulk price update creates/updates rules without duplicates.
    def test_bulk_price_update_creates_rules_without_duplicates(self):
        self.client.force_login(self.owner_a_user)
        blocks = ['06:00-06:30', '06:30-07:00']
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

    def test_saved_custom_price_shows_as_custom_source(self):
        self.client.force_login(self.owner_a_user)
        self.client.post(
            reverse('venues:field_pricing_update', kwargs={'pk': self.field_a.pk}),
            {'blocks': ['06:00-06:30'], 'price_per_hour': '99000'},
        )
        response = self.client.get(self.edit_url(self.field_a) + '?tab=pricing')
        self.assertContains(response, '[06:00-06:30:99000:CUSTOM]')

    # 6. Negative price is rejected.
    def test_negative_price_is_rejected(self):
        self.client.force_login(self.owner_a_user)
        response = self.client.post(
            reverse('venues:field_pricing_update', kwargs={'pk': self.field_a.pk}),
            {'blocks': ['06:00-06:30'], 'price_per_hour': '-1000'},
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
            {'blocks': ['06:00-06:30'], 'price_per_hour': '120000'},
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
            {'blocks': ['06:00-06:30'], 'price_per_hour': '88000'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertIn('message', payload)
        self.assertIn('[06:00-06:30:88000:CUSTOM]', payload['html'])

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
            {'blocks': ['06:00-06:30'], 'price_per_hour': '88000'},
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
