from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import CustomerProfile, Role, UserRole, Wallet

User = get_user_model()


@receiver(post_save, sender=User)
def create_user_related_objects(sender, instance, created, **kwargs):
    """
    Signal to automatically create related objects (Wallet, Profile, Role)
    when a User is created outside the standard views (e.g., createsuperuser or django admin).
    """
    if created:
        # 1. Create Wallet if it doesn't exist
        Wallet.objects.get_or_create(user=instance)

        # 2. Determine and assign Role
        if instance.is_superuser or instance.is_staff:
            admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
            UserRole.objects.get_or_create(user=instance, role=admin_role)
        elif not getattr(instance, '_is_owner_registration', False) and not getattr(instance, '_is_staff_registration', False):
            # For non-admin/staff created outside the view (e.g. via admin), default to CUSTOMER
            customer_role, _ = Role.objects.get_or_create(name=Role.CUSTOMER)
            UserRole.objects.get_or_create(user=instance, role=customer_role)

        # 3. Create default CustomerProfile if neither profile exists and it's not an owner/staff registration
        if not getattr(instance, '_is_owner_registration', False) and not getattr(instance, '_is_staff_registration', False):
            if not hasattr(instance, 'customer_profile') and not hasattr(instance, 'owner_profile'):
                CustomerProfile.objects.get_or_create(user=instance)
