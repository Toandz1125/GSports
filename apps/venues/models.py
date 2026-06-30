from django.db import models


class Sport(models.Model):
    """Môn thể thao."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    icon = models.CharField(max_length=50, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'sport'

    def __str__(self):
        return self.name


class Venue(models.Model):
    """Cơ sở thể thao."""

    owner = models.ForeignKey(
        'accounts.OwnerProfile',
        on_delete=models.CASCADE,
        related_name='venues',
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    address = models.CharField(max_length=500)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    status = models.CharField(max_length=20, default='ACTIVE')
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'venue'

    def __str__(self):
        return self.name

    @property
    def rating_avg(self):
        avg_rating = self.reviews.aggregate(models.Avg('rating'))['rating__avg']
        return round(avg_rating, 1) if avg_rating is not None else 0.0

    @property
    def reviews_count(self):
        return self.reviews.count()

    @property
    def stars_list(self):
        avg = self.rating_avg
        stars = []
        for i in range(1, 6):
            if avg >= i:
                stars.append('full')
            elif avg >= i - 0.5:
                stars.append('half')
            else:
                stars.append('empty')
        return stars


class VenueOperatingHour(models.Model):
    """Giờ hoạt động theo ngày trong tuần."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='operating_hours')
    weekday = models.SmallIntegerField(help_text='0=Monday, 6=Sunday')
    open_time = models.TimeField()
    close_time = models.TimeField()

    class Meta:
        db_table = 'venue_operating_hour'
        unique_together = ('venue', 'weekday')

    def __str__(self):
        days = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
        return f'{self.venue.name} — {days[self.weekday]}: {self.open_time}-{self.close_time}'


class VenueImage(models.Model):
    """Ảnh cơ sở."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='venue_images/')
    is_thumbnail = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'venue_image'
        ordering = ['sort_order']

    def __str__(self):
        return f'{self.venue.name} — img#{self.sort_order}'


class FieldType(models.Model):
    """Loại sân (Sân 5, Sân 7, Sân đơn...)."""

    sport = models.ForeignKey(Sport, on_delete=models.CASCADE, related_name='field_types')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    icon = models.CharField(max_length=50, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    player_count = models.IntegerField()
    status = models.CharField(max_length=20, default='ACTIVE')

    class Meta:
        db_table = 'field_type'
        unique_together = ('sport', 'name')

    def __str__(self):
        return f'{self.sport.name} — {self.name}'


class Field(models.Model):
    """Sân con thuộc cơ sở."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='fields')
    field_type = models.ForeignKey(FieldType, on_delete=models.CASCADE, related_name='fields')
    name = models.CharField(max_length=100)
    capacity = models.IntegerField(blank=True, null=True)
    surface_type = models.CharField(max_length=50, blank=True, null=True)
    length = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    width = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    status = models.CharField(max_length=20, default='ACTIVE')

    class Meta:
        db_table = 'field'

    def __str__(self):
        return f'{self.venue.name} — {self.name}'


class FieldPriceRule(models.Model):
    """Bảng giá sân theo khung giờ và ngày."""

    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='price_rules')
    day_of_week = models.SmallIntegerField(blank=True, null=True, help_text='Null = tất cả các ngày')
    start_time = models.TimeField()
    end_time = models.TimeField()
    price_per_hour = models.DecimalField(max_digits=10, decimal_places=2)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    priority = models.IntegerField(default=0)
    is_holiday = models.BooleanField(default=False)
    special_event = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'field_price_rule'
        indexes = [
            models.Index(fields=['field', 'day_of_week', 'start_time']),
        ]

    def __str__(self):
        return f'{self.field.name}: {self.start_time}-{self.end_time} = {self.price_per_hour:,.0f}đ/h'


class VenuePolicy(models.Model):
    """Chính sách huỷ/hoàn tiền của cơ sở."""

    venue = models.OneToOneField(Venue, on_delete=models.CASCADE, related_name='policy')
    cancel_before_hours = models.IntegerField()
    refund_percent = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        db_table = 'venue_policy'

    def __str__(self):
        return f'{self.venue.name}: huỷ trước {self.cancel_before_hours}h → hoàn {self.refund_percent}%'
