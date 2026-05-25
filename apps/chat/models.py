from django.db import models


class ChatRoom(models.Model):
    """Phòng chat giữa khách hàng và cơ sở."""

    venue = models.ForeignKey('venues.Venue', on_delete=models.CASCADE, related_name='chat_rooms')
    customer = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='chat_rooms')
    last_message = models.ForeignKey(
        'ChatMessage', on_delete=models.SET_NULL,
        blank=True, null=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_room'
        unique_together = ('venue', 'customer')

    def __str__(self):
        return f'{self.customer.email} ↔ {self.venue.name}'


class ChatParticipant(models.Model):
    """Người tham gia phòng chat."""

    CUSTOMER = 'CUSTOMER'
    STAFF = 'STAFF'
    OWNER = 'OWNER'
    ROLE_CHOICES = [
        (CUSTOMER, 'Customer'),
        (STAFF, 'Staff'),
        (OWNER, 'Owner'),
    ]

    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='chat_participations')
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='participants')
    role_in_room = models.CharField(max_length=10, choices=ROLE_CHOICES)

    class Meta:
        db_table = 'chat_participant'
        unique_together = ('user', 'room')

    def __str__(self):
        return f'{self.user.email} [{self.role_in_room}]'


class ChatMessage(models.Model):
    """Tin nhắn."""

    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='sent_messages')
    message_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_message'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.sender.email}: {self.message_text[:50]}'
