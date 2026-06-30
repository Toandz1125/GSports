from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.http import JsonResponse
from apps.venues.models import Venue
from .models import Review


class CreateReviewView(LoginRequiredMixin, View):
    """View xử lý việc gửi bình luận & đánh giá cơ sở từ người dùng."""

    def post(self, request, venue_id, *args, **kwargs):
        venue = get_object_or_404(Venue, pk=venue_id, is_deleted=False)
        rating_val = request.POST.get('rating')
        comment_val = request.POST.get('comment', '').strip()

        if not rating_val:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'ok': False, 'error': 'Vui lòng chọn số sao đánh giá.'}, status=400)
            return redirect('venues:venue_detail', pk=venue.pk)

        try:
            rating = int(rating_val)
            if rating < 0 or rating > 5:
                raise ValueError()
        except ValueError:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'ok': False, 'error': 'Số sao không hợp lệ (0-5).'}, status=400)
            return redirect('venues:venue_detail', pk=venue.pk)

        # Tạo mới hoặc cập nhật đánh giá của user đối với cơ sở này
        review, created = Review.objects.update_or_create(
            user=request.user,
            venue=venue,
            defaults={
                'rating': rating,
                'comment': comment_val
            }
        )

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({
                'ok': True,
                'message': 'Cảm ơn bạn đã gửi đánh giá!' if created else 'Đánh giá của bạn đã được cập nhật!',
                'rating': review.rating,
                'comment': review.comment,
                'user': review.user.email,
            })
        return redirect('venues:venue_detail', pk=venue.pk)
