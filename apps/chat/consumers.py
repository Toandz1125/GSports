import json

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from .models import ChatRoom, ChatParticipant, ChatMessage


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket Consumer cho realtime chat."""

    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'
        self.user = self.scope['user']

        # Từ chối nếu user chưa đăng nhập
        if self.user.is_anonymous:
            await self.close()
            return

        # Kiểm tra quyền tham gia room
        has_access = await self._check_room_access()
        if not has_access:
            await self.close()
            return

        # Join channel group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        # Rời channel group
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name,
            )

    async def receive(self, text_data):
        """Nhận tin nhắn từ client → lưu DB → broadcast cho cả room."""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        message_text = data.get('message', '').strip()
        if not message_text:
            return

        # Lưu tin nhắn vào DB
        message_data = await self._save_message(message_text)

        # Broadcast cho tất cả participants trong room
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message_data,
            }
        )

    async def chat_message(self, event):
        """Handler nhận broadcast → gửi message tới WebSocket client."""
        await self.send(text_data=json.dumps(event['message'], ensure_ascii=False))

    # ─── Database helpers ────────────────────────────────────────

    @database_sync_to_async
    def _check_room_access(self):
        """Kiểm tra user có quyền tham gia phòng chat này không."""
        try:
            room = ChatRoom.objects.select_related('venue', 'venue__owner').get(id=self.room_id)
        except ChatRoom.DoesNotExist:
            return False

        user = self.user

        # Customer: chỉ vào room mà mình là customer
        if room.customer_id == user.id:
            return True

        # Owner: vào room thuộc Venue mình sở hữu
        if hasattr(user, 'owner_profile') and room.venue.owner_id == user.owner_profile.id:
            return True

        # Staff: vào room thuộc Venue mình là nhân viên
        from apps.core.models import VenueStaff
        if VenueStaff.objects.filter(staff=user, venue=room.venue).exists():
            return True

        return False

    @database_sync_to_async
    def _save_message(self, message_text):
        """Lưu tin nhắn vào DB và trả về dữ liệu để broadcast."""
        room = ChatRoom.objects.get(id=self.room_id)
        message = ChatMessage.objects.create(
            room=room,
            sender=self.user,
            message_text=message_text,
        )

        # Cập nhật last_message của room
        room.last_message = message
        room.save(update_fields=['last_message'])

        return {
            'id': message.id,
            'room_id': room.id,
            'sender_id': self.user.id,
            'sender_name': self.user.get_full_name() or self.user.email,
            'message_text': message.message_text,
            'created_at': message.created_at.strftime('%H:%M %d/%m'),
        }
