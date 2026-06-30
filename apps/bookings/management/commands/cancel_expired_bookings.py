"""Cancel PENDING bookings whose 10-minute payment hold has expired.

Booking-module only: it uses the bookings service/model exclusively and never
touches ``apps.payments``. Safe to run from cron, e.g.::

    python manage.py cancel_expired_bookings
"""
from django.core.management.base import BaseCommand

from apps.bookings.services import cancel_expired_pending_bookings


class Command(BaseCommand):
    help = 'Cancel PENDING bookings whose payment deadline has passed.'

    def handle(self, *args, **options):
        cancelled = cancel_expired_pending_bookings()
        self.stdout.write(
            self.style.SUCCESS(f'Cancelled {cancelled} expired pending booking(s).')
        )
