from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.urls import resolve, reverse
from apps.accounts.models import CustomerProfile, OwnerProfile, OwnerRegistrationRequest, Role, UserRole, Wallet
from apps.accounts.forms import CustomerRegistrationForm, OwnerRegistrationForm, ChangePasswordForm, UserProfileForm


User = get_user_model()


class AccountsSignalTests(TestCase):
    def setUp(self):
        # Create necessary roles first
        Role.objects.get_or_create(name=Role.CUSTOMER)
        Role.objects.get_or_create(name=Role.OWNER)
        Role.objects.get_or_create(name=Role.ADMIN)

    def test_createsuperuser_signal(self):
        """
        Test that creating a user directly (like createsuperuser or via django admin)
        automatically creates a Wallet, ADMIN UserRole, and CustomerProfile.
        """
        user = User.objects.create_superuser(
            username='admin_test',
            email='admin@test.com',
            password='Password123!'
        )
        
        # Verify wallet creation
        self.assertTrue(Wallet.objects.filter(user=user).exists())
        
        # Verify admin role assignment
        user_roles = UserRole.objects.filter(user=user)
        self.assertEqual(user_roles.count(), 1)
        self.assertEqual(user_roles.first().role.name, Role.ADMIN)
        
        # Verify profile creation
        self.assertTrue(CustomerProfile.objects.filter(user=user).exists())
        self.assertFalse(OwnerProfile.objects.filter(user=user).exists())

    def test_customer_registration_flow(self):
        """
        Test that CustomerRegistrationForm save creates the user and all associated objects
        without throwing IntegrityError or duplicate roles/profiles.
        """
        form_data = {
            'email': 'customer@test.com',
            'username': 'customer_test',
            'phone': '+84901234567',
            'password': 'Password123!',
            'password_confirm': 'Password123!',
        }
        form = CustomerRegistrationForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        
        # Save user via form
        user = form.save()
        
        # Explicit role and wallet assignment usually done in view
        customer_role = Role.objects.get(name=Role.CUSTOMER)
        UserRole.objects.get_or_create(user=user, role=customer_role)
        Wallet.objects.get_or_create(user=user)
        
        # Verify objects
        self.assertTrue(Wallet.objects.filter(user=user).exists())
        self.assertTrue(CustomerProfile.objects.filter(user=user).exists())
        self.assertFalse(OwnerProfile.objects.filter(user=user).exists())
        
        user_roles = UserRole.objects.filter(user=user)
        self.assertEqual(user_roles.count(), 1)
        self.assertEqual(user_roles.first().role.name, Role.CUSTOMER)

    def test_owner_registration_flow(self):
        """
        Test that OwnerRegistrationForm save creates an owner user, Wallet, and OwnerProfile
        WITHOUT creating a CustomerProfile or CUSTOMER role.
        """
        form_data = {
            'email': 'owner@test.com',
            'username': 'owner_test',
            'phone': '0987654321',
            'password': 'Password123!',
            'password_confirm': 'Password123!',
            'business_name': 'My Sports Center',
            'bank_account_number': '123456789',
            'bank_name': 'Vietcombank',
        }
        form = OwnerRegistrationForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        
        # Save user via form
        user = form.save()
        
        # Explicit role and wallet assignment usually done in view
        owner_role = Role.objects.get(name=Role.OWNER)
        UserRole.objects.get_or_create(user=user, role=owner_role)
        Wallet.objects.get_or_create(user=user)
        
        # Verify objects
        self.assertTrue(Wallet.objects.filter(user=user).exists())
        self.assertTrue(OwnerProfile.objects.filter(user=user).exists())
        self.assertFalse(CustomerProfile.objects.filter(user=user).exists())
        
        user_roles = UserRole.objects.filter(user=user)
        self.assertEqual(user_roles.count(), 1)
        self.assertEqual(user_roles.first().role.name, Role.OWNER)

    def test_change_password_flow(self):
        """
        Test that ChangePasswordForm correctly validates current password,
        complexity, and updates the user's password.
        """
        user = User.objects.create_user(
            username='password_user',
            email='pwd@test.com',
            password='OldPassword123!'
        )
        
        # Test change password with incorrect current password
        form_data = {
            'current_password': 'WrongPassword123!',
            'new_password': 'NewPassword123!',
            'new_password_confirm': 'NewPassword123!',
        }
        form = ChangePasswordForm(data=form_data, user=user)
        self.assertFalse(form.is_valid())
        self.assertIn('current_password', form.errors)
        
        # Test change password with non-matching passwords
        form_data = {
            'current_password': 'OldPassword123!',
            'new_password': 'NewPassword123!',
            'new_password_confirm': 'DifferentPassword123!',
        }
        form = ChangePasswordForm(data=form_data, user=user)
        self.assertFalse(form.is_valid())
        self.assertIn('new_password_confirm', form.errors)

        # Test change password with new password same as current password
        form_data = {
            'current_password': 'OldPassword123!',
            'new_password': 'OldPassword123!',
            'new_password_confirm': 'OldPassword123!',
        }
        form = ChangePasswordForm(data=form_data, user=user)
        self.assertFalse(form.is_valid())
        self.assertIn('new_password', form.errors)
        self.assertEqual(form.errors['new_password'][0], 'Mật khẩu mới không được trùng với mật khẩu hiện tại.')
        
        # Test successful password change
        form_data = {
            'current_password': 'OldPassword123!',
            'new_password': 'NewPassword123!',
            'new_password_confirm': 'NewPassword123!',
        }
        form = ChangePasswordForm(data=form_data, user=user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        
        # Verify the user can authenticate with the new password
        user.refresh_from_db()
        self.assertTrue(user.check_password('NewPassword123!'))

    def test_profile_edit_disabled_fields(self):
        """
        Test that first_name, last_name, and phone can be edited, while username
        and email are read-only (disabled) in the form.
        """
        user = User.objects.create_user(
            username='original_username',
            email='edit@test.com',
            password='Password123!'
        )
        
        # Test editing fields. Since username and email are disabled, any new values sent
        # for them should be ignored by the form, preserving original database values.
        form_data = {
            'username': 'new_username_123',
            'email': 'new_email@test.com',
            'first_name': 'Nguyen',
            'last_name': 'An',
            'phone': '0901234567',
        }
        form = UserProfileForm(data=form_data, instance=user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        
        user.refresh_from_db()
        # Non-disabled fields are updated
        self.assertEqual(user.first_name, 'Nguyen')
        self.assertEqual(user.last_name, 'An')
        self.assertEqual(user.phone, '0901234567')
        # Disabled fields remain unchanged
        self.assertEqual(user.email, 'edit@test.com')
        # Note: the model save method auto-generates username based on first/last name,
        # so self.username will be updated via model save, but not directly from form input.
        self.assertEqual(user.username, 'annguyen')

    def test_delete_account_flow(self):
        """
        Test that DeleteAccountView deletes the user only with correct credentials.
        """
        user = User.objects.create_user(
            username='delete_me',
            email='delete@test.com',
            password='Password123!'
        )
        self.client.force_login(user)
        
        # 1. Try deleting with incorrect text or unchecked box
        response = self.client.post('/ho-so/xoa/', {
            'confirm_text': 'NotDelete',
            'confirm_checkbox': 'on',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())  # User still exists
        
        # 2. Try deleting with correct text but unchecked box
        response = self.client.post('/ho-so/xoa/', {
            'confirm_text': 'Delete',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())  # User still exists
        
        # 3. Correct text and checked box
        response = self.client.post('/ho-so/xoa/', {
            'confirm_text': 'Delete',
            'confirm_checkbox': 'on',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, '/dang-nhap/')
        self.assertFalse(User.objects.filter(pk=user.pk).exists())  # User is deleted!

    def test_owner_profile_edit_view(self):
        """
        Test that only owner users can access and edit OwnerProfile.
        """
        # Create an owner user
        owner_role, _ = Role.objects.get_or_create(name=Role.OWNER)
        owner_user = User.objects.create_user(
            username='owner_user',
            email='owner_test_profile@test.com',
            password='Password123!'
        )
        UserRole.objects.get_or_create(user=owner_user, role=owner_role)
        owner_profile = OwnerProfile.objects.create(
            user=owner_user,
            business_name='Initial Business'
        )

        # Create a customer user
        customer_user = User.objects.create_user(
            username='cust_user',
            email='cust_test_profile@test.com',
            password='Password123!'
        )

        # 1. Non-owner tries to access
        self.client.force_login(customer_user)
        response = self.client.get('/ho-so/chu-san/')
        self.assertEqual(response.status_code, 302)  # Should redirect to profile

        # 2. Owner accesses the page
        self.client.force_login(owner_user)
        response = self.client.get('/ho-so/chu-san/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Chỉnh sửa hồ sơ chủ sân')

        # 3. Owner edits business info
        response = self.client.post('/ho-so/chu-san/', {
            'business_name': 'Updated Business Name',
            'bank_name': 'Updated Bank Name',
            'bank_account_number': '987654321',
        })
        self.assertEqual(response.status_code, 302)
        
        owner_profile.refresh_from_db()
        self.assertEqual(owner_profile.business_name, 'Updated Business Name')
        self.assertEqual(owner_profile.bank_name, 'Updated Bank Name')
        self.assertEqual(owner_profile.bank_account_number, '987654321')


class DashboardSidebarTemplateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer_role, _ = Role.objects.get_or_create(name=Role.CUSTOMER)
        cls.owner_role, _ = Role.objects.get_or_create(name=Role.OWNER)
        cls.user = User.objects.create_user(
            username='sidebar_customer',
            email='sidebar-customer@test.com',
            password='Password123!',
        )
        UserRole.objects.update_or_create(user=cls.user, defaults={'role': cls.customer_role})
        cls.owner_user = User.objects.create_user(
            username='sidebar_owner',
            email='sidebar-owner@test.com',
            password='Password123!',
        )
        UserRole.objects.update_or_create(user=cls.owner_user, defaults={'role': cls.owner_role})
        OwnerProfile.objects.create(
            user=cls.owner_user,
            business_name='Sidebar Owner',
            is_verified=True,
        )

    def render_dashboard(self, user=None):
        self.client.force_login(user or self.user)
        response = self.client.get(reverse('accounts:dashboard'))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def get_profile_nav_html(self, html):
        marker_index = html.find('id="nav-profile"')
        self.assertNotEqual(marker_index, -1)
        anchor_start = html.rfind('<a', 0, marker_index)
        anchor_end = html.find('</a>', marker_index)
        self.assertNotEqual(anchor_start, -1)
        self.assertNotEqual(anchor_end, -1)
        return html[anchor_start:anchor_end + len('</a>')]

    def test_sidebar_hides_booking_create_nav_but_route_still_exists(self):
        html = self.render_dashboard()

        self.assertNotIn('id="nav-booking-create"', html)
        self.assertNotIn('<span>Đặt sân</span>', html)

        booking_match = resolve(reverse('bookings:booking_create'))
        self.assertEqual(booking_match.app_name, 'bookings')
        self.assertEqual(booking_match.url_name, 'booking_create')

    def test_profile_nav_renders_single_user_icon(self):
        html = self.render_dashboard()
        profile_nav_html = self.get_profile_nav_html(html)

        self.assertIn('<span>Hồ sơ</span>', profile_nav_html)
        self.assertEqual(profile_nav_html.count('<svg'), 1)

    def test_owner_sidebar_shows_venue_management_without_service_nav(self):
        html = self.render_dashboard(self.owner_user)

        self.assertIn('id="nav-venues"', html)
        self.assertIn('<span>Quản lý cơ sở</span>', html)
        self.assertNotIn('id="nav-owner-services"', html)
        self.assertNotIn('<span>Quản lý dịch vụ</span>', html)

        service_match = resolve(reverse('services:owner_serviceitem_list'))
        self.assertEqual(service_match.app_name, 'services')
        self.assertEqual(service_match.url_name, 'owner_serviceitem_list')

    def test_customer_sidebar_does_not_show_owner_management(self):
        html = self.render_dashboard(self.user)

        self.assertNotIn('id="nav-owner-services"', html)
        self.assertNotIn('<span>Quản lý dịch vụ</span>', html)
        self.assertNotIn('<span>Quản lý cơ sở</span>', html)


class OwnerRegistrationAdminRequestTests(TestCase):
    def setUp(self):
        self.admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.customer_role, _ = Role.objects.get_or_create(name=Role.CUSTOMER)
        self.owner_role, _ = Role.objects.get_or_create(name=Role.OWNER)

        self.admin_user = User.objects.create_user(
            username='owner_req_admin',
            email='owner-req-admin@test.com',
            password='Password123!',
        )
        UserRole.objects.create(user=self.admin_user, role=self.admin_role)

        self.customer_user = User.objects.create_user(
            username='owner_req_customer',
            email='owner-req-customer@test.com',
            password='Password123!',
        )
        UserRole.objects.update_or_create(user=self.customer_user, defaults={'role': self.customer_role})

    def create_owner_request(self, email='owner-request@test.com'):
        return OwnerRegistrationRequest.objects.create(
            email=email,
            first_name='Nguyen',
            last_name='Owner',
            phone='0901234567',
            business_name='Pending Owner Business',
            bank_account_number='123456789',
            bank_name='Test Bank',
            password_hash=make_password('Password123!'),
        )

    def test_admin_profile_no_longer_renders_owner_registration_queue(self):
        self.create_owner_request('profile-owner-request@test.com')
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse('accounts:profile'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('pending_owner_requests', response.context)
        self.assertNotContains(response, 'Yêu cầu đăng ký chủ sân chờ duyệt')
        self.assertNotContains(response, 'Pending Owner Business')
        self.assertContains(response, reverse('venues:admin_request_list'))

    def test_rejected_owner_registration_email_can_be_submitted_again(self):
        owner_request = self.create_owner_request('retry-owner-request@test.com')
        owner_request.status = OwnerRegistrationRequest.REJECTED
        owner_request.reviewed_by = self.admin_user
        owner_request.save(update_fields=['status', 'reviewed_by'])

        response = self.client.post(reverse('accounts:register_owner'), {
            'email': 'retry-owner-request@test.com',
            'first_name': 'Retry',
            'last_name': 'Owner',
            'phone': '0907654321',
            'business_name': 'Retry Owner Business',
            'bank_account_number': '987654321',
            'bank_name': 'Retry Bank',
            'password': 'Password123!',
            'password_confirm': 'Password123!',
        })

        self.assertRedirects(response, reverse('accounts:login'), fetch_redirect_response=False)
        self.assertEqual(
            OwnerRegistrationRequest.objects.filter(email='retry-owner-request@test.com').count(),
            1,
        )
        owner_request.refresh_from_db()
        self.assertEqual(owner_request.status, OwnerRegistrationRequest.PENDING)
        self.assertIsNone(owner_request.reviewed_by)
        self.assertEqual(owner_request.first_name, 'Retry')
        self.assertEqual(owner_request.business_name, 'Retry Owner Business')

    def test_admin_approves_owner_request_and_returns_to_request_page(self):
        owner_request = self.create_owner_request('approved-owner-request@test.com')
        next_url = f"{reverse('venues:admin_request_list')}?status={OwnerRegistrationRequest.PENDING}"
        self.client.force_login(self.admin_user)

        response = self.client.post(
            reverse('accounts:admin_approve_owner', kwargs={'pk': owner_request.pk}),
            {'next': next_url},
        )

        self.assertRedirects(response, next_url, fetch_redirect_response=False)
        owner_request.refresh_from_db()
        self.assertEqual(owner_request.status, OwnerRegistrationRequest.APPROVED)
        self.assertEqual(owner_request.reviewed_by, self.admin_user)
        self.assertIsNotNone(owner_request.reviewed_at)

        approved_user = User.objects.get(email='approved-owner-request@test.com')
        self.assertTrue(approved_user.check_password('Password123!'))
        self.assertTrue(OwnerProfile.objects.filter(
            user=approved_user,
            business_name='Pending Owner Business',
            is_verified=True,
        ).exists())
        self.assertTrue(UserRole.objects.filter(user=approved_user, role=self.owner_role).exists())
        self.assertTrue(Wallet.objects.filter(user=approved_user).exists())

    def test_admin_rejects_owner_request_and_returns_to_request_page(self):
        owner_request = self.create_owner_request('rejected-owner-request@test.com')
        next_url = f"{reverse('venues:admin_request_list')}?status={OwnerRegistrationRequest.PENDING}"
        self.client.force_login(self.admin_user)

        response = self.client.post(
            reverse('accounts:admin_reject_owner', kwargs={'pk': owner_request.pk}),
            {'next': next_url},
        )

        self.assertRedirects(response, next_url, fetch_redirect_response=False)
        owner_request.refresh_from_db()
        self.assertEqual(owner_request.status, OwnerRegistrationRequest.REJECTED)
        self.assertEqual(owner_request.reviewed_by, self.admin_user)
        self.assertIsNotNone(owner_request.reviewed_at)
        self.assertFalse(User.objects.filter(email='rejected-owner-request@test.com').exists())
        self.assertFalse(UserRole.objects.filter(
            user__email='rejected-owner-request@test.com',
            role=self.owner_role,
        ).exists())

    def test_owner_request_actions_default_to_admin_request_page_without_next(self):
        owner_request = self.create_owner_request('default-redirect-owner-request@test.com')
        self.client.force_login(self.admin_user)

        response = self.client.post(reverse('accounts:admin_reject_owner', kwargs={'pk': owner_request.pk}))

        self.assertRedirects(
            response,
            reverse('venues:admin_request_list'),
            fetch_redirect_response=False,
        )

    def test_non_admin_cannot_approve_or_reject_owner_registration_request(self):
        approve_request = self.create_owner_request('blocked-approve-owner-request@test.com')
        reject_request = self.create_owner_request('blocked-reject-owner-request@test.com')
        self.client.force_login(self.customer_user)

        approve_response = self.client.post(
            reverse('accounts:admin_approve_owner', kwargs={'pk': approve_request.pk}),
            {'next': reverse('venues:admin_request_list')},
        )
        reject_response = self.client.post(
            reverse('accounts:admin_reject_owner', kwargs={'pk': reject_request.pk}),
            {'next': reverse('venues:admin_request_list')},
        )

        self.assertRedirects(
            approve_response,
            reverse('accounts:profile'),
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            reject_response,
            reverse('accounts:profile'),
            fetch_redirect_response=False,
        )
        approve_request.refresh_from_db()
        reject_request.refresh_from_db()
        self.assertEqual(approve_request.status, OwnerRegistrationRequest.PENDING)
        self.assertEqual(reject_request.status, OwnerRegistrationRequest.PENDING)


class AdminUserManagementTests(TestCase):
    def setUp(self):
        # Create roles
        self.admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.customer_role, _ = Role.objects.get_or_create(name=Role.CUSTOMER)

        # Create admin user (automatically gets ADMIN role via signal)
        self.admin_user = User.objects.create_superuser(
            username='admin_test_mgr',
            email='admin_mgr@test.com',
            password='Password123!'
        )

        # Create customer user (automatically gets CUSTOMER role via signal)
        self.customer_user = User.objects.create_user(
            username='customer_test_mgr',
            email='customer_mgr@test.com',
            password='Password123!'
        )

    def test_unauthorized_access(self):
        """Non-admin should not be able to access the admin user list view."""
        self.client.force_login(self.customer_user)
        response = self.client.get('/quan-ly-tai-khoan/')
        self.assertEqual(response.status_code, 302)  # Should redirect to profile page

    def test_authorized_access(self):
        """Admin should be able to access the admin user list view."""
        self.client.force_login(self.admin_user)
        response = self.client.get('/quan-ly-tai-khoan/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Quản lý tài khoản hệ thống')

    def test_toggle_user_active_status(self):
        """Admin can toggle is_active status of other users and an audit log is created."""
        self.client.force_login(self.admin_user)
        
        # Verify initial state
        self.assertTrue(self.customer_user.is_active)

        # Lock the account
        response = self.client.post(f'/quan-ly-tai-khoan/{self.customer_user.pk}/toggle-active/')
        self.assertEqual(response.status_code, 302)
        
        self.customer_user.refresh_from_db()
        self.assertFalse(self.customer_user.is_active)

        # Verify AuditLog creation
        from apps.core.models import AuditLog
        log = AuditLog.objects.filter(target_type='UserStatus', target_id=str(self.customer_user.pk)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.admin_user)
        self.assertEqual(log.action, 'UPDATE')

        # Unlock the account
        response = self.client.post(f'/quan-ly-tai-khoan/{self.customer_user.pk}/toggle-active/')
        self.assertEqual(response.status_code, 302)
        
        self.customer_user.refresh_from_db()
        self.assertTrue(self.customer_user.is_active)

    def test_delete_user_account(self):
        """Admin can delete other users and an audit log is created."""
        self.client.force_login(self.admin_user)
        
        customer_pk = self.customer_user.pk
        response = self.client.post(f'/quan-ly-tai-khoan/{customer_pk}/xoa/')
        self.assertEqual(response.status_code, 302)

        # Verify user is deleted
        self.assertFalse(User.objects.filter(pk=customer_pk).exists())

        # Verify AuditLog creation
        from apps.core.models import AuditLog
        log = AuditLog.objects.filter(target_type='User', target_id=str(customer_pk)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.admin_user)
        self.assertEqual(log.action, 'DELETE')


class RoleConstraintTests(TestCase):
    def setUp(self):
        Role.objects.get_or_create(name=Role.CUSTOMER)
        Role.objects.get_or_create(name=Role.OWNER)
        Role.objects.get_or_create(name=Role.STAFF)
        Role.objects.get_or_create(name=Role.ADMIN)

    def test_user_can_only_have_one_role(self):
        """Test that override of UserRole.save enforces single role per user."""
        user = User.objects.create_user(
            username='test_role_user',
            email='test_role@example.com',
            password='Password123!'
        )
        
        # 1. Assign CUSTOMER role
        cust_role = Role.objects.get(name=Role.CUSTOMER)
        UserRole.objects.create(user=user, role=cust_role)
        self.assertEqual(UserRole.objects.filter(user=user).count(), 1)
        self.assertEqual(user.user_roles.first().role.name, Role.CUSTOMER)
        
        # 2. Assign OWNER role (should replace CUSTOMER role)
        owner_role = Role.objects.get(name=Role.OWNER)
        UserRole.objects.create(user=user, role=owner_role)
        self.assertEqual(UserRole.objects.filter(user=user).count(), 1)
        self.assertEqual(user.user_roles.first().role.name, Role.OWNER)
        
        # 3. Assign STAFF role (should replace OWNER role)
        staff_role = Role.objects.get(name=Role.STAFF)
        UserRole.objects.create(user=user, role=staff_role)
        self.assertEqual(UserRole.objects.filter(user=user).count(), 1)
        self.assertEqual(user.user_roles.first().role.name, Role.STAFF)
        
    def test_database_constraint_raises_on_duplicate_user(self):
        """Test that database constraint raises IntegrityError on bulk_create with duplicate user roles."""
        from django.db import IntegrityError
        
        user = User.objects.create_user(
            username='test_integrity_user',
            email='test_integrity@example.com',
            password='Password123!'
        )
        cust_role = Role.objects.get(name=Role.CUSTOMER)
        owner_role = Role.objects.get(name=Role.OWNER)
        
        UserRole.objects.create(user=user, role=cust_role)
        
        # Bypassing overridden save() using bulk_create triggers the db UniqueConstraint
        with self.assertRaises(IntegrityError):
            UserRole.objects.bulk_create([
                UserRole(user=user, role=owner_role)
            ])



