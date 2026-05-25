from django.contrib import admin
from .models import ChatRoom, ChatParticipant, ChatMessage


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ('id', 'venue', 'customer', 'created_at')


@admin.register(ChatParticipant)
class ChatParticipantAdmin(admin.ModelAdmin):
    list_display = ('user', 'room', 'role_in_room')
    list_filter = ('role_in_room',)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('room', 'sender', 'message_text', 'created_at')
