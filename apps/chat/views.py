import json

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Q

from .models import ChatRoom, ChatParticipant, ChatMessage
from apps.venues.models import Venue
from apps.core.models import VenueStaff


@login_required
@require_GET
def room_list(request):
    """GET /api/chat/rooms/ — Danh sách phòng chat của user hiện tại."""
    user = request.user

    # Lấy danh sách room dựa trên role
    rooms = _get_user_rooms(user)

    rooms_data = []
    for room in rooms:
        last_msg = None
        needs_reply = False
        if room.last_message_id:
            last_msg = {
                'text': room.last_message.message_text[:80],
                'sender_id': room.last_message.sender_id,
                'sender_name': room.last_message.sender.get_full_name() or room.last_message.sender.email,
                'created_at': room.last_message.created_at.strftime('%H:%M %d/%m'),
            }
            # Nếu người gửi cuối là khách hàng → phía cơ sở cần rep
            # Nếu người gửi cuối là staff/owner → phía khách cần rep
            needs_reply = (room.last_message.sender_id == room.customer_id)

        rooms_data.append({
            'id': room.id,
            'venue_id': room.venue_id,
            'venue_name': room.venue.name,
            'customer_id': room.customer_id,
            'customer_name': room.customer.get_full_name() or room.customer.email,
            'last_message': last_msg,
            'last_message_id': room.last_message_id or 0,
            'needs_reply': needs_reply,
            'created_at': room.created_at.strftime('%d/%m/%Y'),
        })

    return JsonResponse({'rooms': rooms_data})


@login_required
@require_POST
def room_create(request):
    """POST /api/chat/rooms/create/ — Tạo phòng chat mới (Customer → Venue)."""
    user = request.user

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    venue_id = body.get('venue_id')
    if not venue_id:
        return JsonResponse({'error': 'venue_id is required'}, status=400)

    try:
        venue = Venue.objects.select_related('owner').get(id=venue_id, is_deleted=False)
    except Venue.DoesNotExist:
        return JsonResponse({'error': 'Venue not found'}, status=404)

    # Kiểm tra đã có phòng chat giữa customer và venue chưa
    room, created = ChatRoom.objects.get_or_create(
        venue=venue,
        customer=user,
    )

    if created:
        # Thêm customer làm participant
        ChatParticipant.objects.get_or_create(
            user=user, room=room,
            defaults={'role_in_room': ChatParticipant.CUSTOMER},
        )
        # Thêm owner làm participant
        ChatParticipant.objects.get_or_create(
            user=venue.owner.user, room=room,
            defaults={'role_in_room': ChatParticipant.OWNER},
        )

    return JsonResponse({
        'id': room.id,
        'venue_id': room.venue_id,
        'venue_name': venue.name,
        'created': created,
    }, status=201 if created else 200)


@login_required
@require_GET
def room_messages(request, room_id):
    """GET /api/chat/rooms/<id>/messages/ — Lịch sử tin nhắn (phân trang)."""
    user = request.user

    try:
        room = ChatRoom.objects.get(id=room_id)
    except ChatRoom.DoesNotExist:
        return JsonResponse({'error': 'Room not found'}, status=404)

    # Kiểm tra quyền truy cập room
    if not _user_has_room_access(user, room):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    # Phân trang: lấy 50 tin nhắn gần nhất, hỗ trợ before_id để load thêm
    before_id = request.GET.get('before_id')
    messages_qs = room.messages.select_related('sender').order_by('-created_at')

    if before_id:
        try:
            messages_qs = messages_qs.filter(id__lt=int(before_id))
        except (ValueError, TypeError):
            pass

    messages = list(messages_qs[:50])
    messages.reverse()  # Đảo về thứ tự cũ → mới

    messages_data = []
    for msg in messages:
        messages_data.append({
            'id': msg.id,
            'sender_id': msg.sender_id,
            'sender_name': msg.sender.get_full_name() or msg.sender.email,
            'message_text': msg.message_text,
            'created_at': msg.created_at.strftime('%H:%M %d/%m'),
        })

    has_more = messages_qs.count() > 50

    return JsonResponse({
        'messages': messages_data,
        'has_more': has_more,
    })


@login_required
@require_POST
def room_send_message(request, room_id):
    """POST /api/chat/rooms/<id>/messages/send/ — Gửi tin nhắn qua HTTP (fallback khi WS lỗi)."""
    user = request.user

    try:
        room = ChatRoom.objects.get(id=room_id)
    except ChatRoom.DoesNotExist:
        return JsonResponse({'error': 'Room not found'}, status=404)

    if not _user_has_room_access(user, room):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    message_text = body.get('message', '').strip()
    if not message_text:
        return JsonResponse({'error': 'Message cannot be empty'}, status=400)

    message = ChatMessage.objects.create(
        room=room,
        sender=user,
        message_text=message_text,
    )
    room.last_message = message
    room.save(update_fields=['last_message'])

    return JsonResponse({
        'id': message.id,
        'sender_id': user.id,
        'sender_name': user.get_full_name() or user.email,
        'message_text': message.message_text,
        'created_at': message.created_at.strftime('%H:%M %d/%m'),
    }, status=201)



def _get_user_rooms(user):
    """Lấy danh sách phòng chat dựa trên role của user."""
    rooms = ChatRoom.objects.select_related(
        'venue', 'customer', 'last_message', 'last_message__sender'
    )

    if user.is_owner:
        # Owner: phòng chat của các Venue mình sở hữu
        rooms = rooms.filter(venue__owner__user=user)
    elif user.is_staff_member:
        # Staff: phòng chat của Venue mình là nhân viên
        staff_venue_ids = VenueStaff.objects.filter(
            staff=user
        ).values_list('venue_id', flat=True)
        rooms = rooms.filter(venue_id__in=staff_venue_ids)
    else:
        # Customer: phòng mình tham gia
        rooms = rooms.filter(customer=user)

    return rooms.order_by('-created_at')


def _user_has_room_access(user, room):
    """Kiểm tra user có quyền truy cập phòng chat không."""
    # Customer
    if room.customer_id == user.id:
        return True

    # Owner
    if user.is_owner and hasattr(user, 'owner_profile'):
        if room.venue.owner_id == user.owner_profile.id:
            return True

    # Staff
    if user.is_staff_member:
        if VenueStaff.objects.filter(staff=user, venue=room.venue).exists():
            return True

    return False
