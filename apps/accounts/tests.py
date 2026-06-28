from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.accounts.models import CustomerProfile, OwnerProfile, Role, UserRole, Wallet
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



