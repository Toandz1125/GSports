from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class Review(models.Model):
    """Đánh giá cơ sở."""

    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='reviews')
    venue = models.ForeignKey('venues.Venue', on_delete=models.CASCADE, related_name='reviews')
    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.SET_NULL,
        blank=True, null=True, related_name='review',
    )
    rating = models.SmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        help_text='0-5 sao'
    )
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'review'
        indexes = [
            models.Index(fields=['venue', 'created_at']),
        ]

    def __str__(self):
        return f'{self.venue.name} — {self.rating}★ by {self.user.email}'
