# Kế hoạch Triển khai Hệ thống Auth (Đăng ký / Đăng nhập) — GSports

## Bối cảnh

Dự án GSports là hệ thống quản lý sân thể thao được xây dựng trên Django 4.2, sử dụng kiến trúc MVT và SQL Server. Hệ thống đã có sẵn:

- **Custom User Model** ([models.py](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/apps/accounts/models.py)) kế thừa `AbstractUser`, đăng nhập bằng **email** (`USERNAME_FIELD = 'email'`)
- **Role system** (`CUSTOMER`, `OWNER`, `STAFF`, `ADMIN`) với bảng trung gian `UserRole`
- **Profile** riêng cho Customer (`CustomerProfile`) và Owner (`OwnerProfile`)
- **Wallet** (ví nội bộ, tự động tạo cho mỗi user)
- Files [views.py](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/apps/accounts/views.py) và [urls.py](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/apps/accounts/urls.py) hiện đang **trống**

Phần auth cần triển khai bao gồm: **Đăng ký**, **Đăng nhập**, **Đăng xuất**, và **Redirect sau đăng nhập**.

---

## User Review Required

> [!IMPORTANT]
> **Lựa chọn vai trò khi đăng ký:** Plan hiện tại mặc định đăng ký sẽ tạo user với vai trò **CUSTOMER**. Nếu bạn muốn cho phép đăng ký **OWNER** (chủ sân) ngay từ form đăng ký (kèm thông tin `business_name`), hãy phản hồi để tôi bổ sung flow cho Owner.

> [!IMPORTANT]
> **Trang chủ sau đăng nhập:** Sau khi đăng nhập thành công, user sẽ được redirect đến đâu? Hiện chưa có trang chủ. Plan sẽ tạo một trang **dashboard placeholder** tạm thời. Bạn có muốn redirect đến URL cụ thể nào không?

---

## Open Questions

1. **Có cần hỗ trợ "Quên mật khẩu" (Password Reset) ngay trong lần triển khai đầu tiên không?** Plan hiện tại chưa bao gồm, nhưng có thể bổ sung dễ dàng dùng Django built-in views.
2. **Có yêu cầu xác thực email (Email Verification) sau khi đăng ký không?** Tài liệu đề cập hỗ trợ OTP nhưng chưa rõ scope ban đầu.

---

## Proposed Changes

### Component 1: Backend — Forms

#### [NEW] [forms.py](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/apps/accounts/forms.py)

Tạo 2 Django Forms sử dụng `django.contrib.auth.forms`:

**`CustomerRegistrationForm`** (kế thừa `UserCreationForm`):
- Fields: `email`, `username`, `phone` (optional), `password1`, `password2`
- Override `save()` để tự động:
  1. Tạo `User` với `is_active=True`
  2. Tạo `UserRole` gán vai trò `CUSTOMER`
  3. Tạo `CustomerProfile` (loyalty_points = 0)
  4. Tạo `Wallet` (balance = 0)
- Validation: Kiểm tra email unique, username unique, password strength (dùng Django validators có sẵn trong [settings.py](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/config/settings.py#L107-L120))

**`EmailLoginForm`** (kế thừa `AuthenticationForm`):
- Override để đăng nhập bằng **email** thay vì username
- Label tiếng Việt: "Email", "Mật khẩu"

---

### Component 2: Backend — Views (CBV)

#### [MODIFY] [views.py](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/apps/accounts/views.py)

Sử dụng **Class-based Views** theo đúng quy ước trong [requirements.md](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/docs/requirements.md#L48-L55):

| View | Class | Mô tả |
|------|-------|--------|
| `RegisterView` | `CreateView` | Form đăng ký, success → redirect login |
| `LoginView` | `django.contrib.auth.views.LoginView` | Override `form_class` dùng `EmailLoginForm` |
| `LogoutView` | `django.contrib.auth.views.LogoutView` | Redirect về login sau khi logout |
| `DashboardView` | `TemplateView` + `LoginRequiredMixin` | Trang dashboard tạm sau đăng nhập |

Logic đặc biệt trong `RegisterView.form_valid()`:
```python
# Wrap trong transaction.atomic() để đảm bảo tính toàn vẹn dữ liệu
with transaction.atomic():
    user = form.save()                              # Tạo User
    customer_role = Role.objects.get(name='CUSTOMER')
    UserRole.objects.create(user=user, role=customer_role)
    CustomerProfile.objects.create(user=user)
    Wallet.objects.create(user=user)
```

---

### Component 3: Backend — URL Routing

#### [MODIFY] [urls.py](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/apps/accounts/urls.py)

```python
app_name = 'accounts'
urlpatterns = [
    path('dang-ky/',    RegisterView.as_view(),  name='register'),
    path('dang-nhap/',  LoginView.as_view(),     name='login'),
    path('dang-xuat/',  LogoutView.as_view(),    name='logout'),
    path('dashboard/',  DashboardView.as_view(), name='dashboard'),
]
```

#### [MODIFY] [urls.py](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/config/urls.py)

Thêm `include('apps.accounts.urls')` vào URL tổng + cấu hình serve media files (phục vụ avatar):

```python
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.accounts.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

---

### Component 4: Backend — Settings bổ sung

#### [MODIFY] [settings.py](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/config/settings.py)

Thêm cấu hình redirect cho auth:
```python
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'accounts:dashboard'
LOGOUT_REDIRECT_URL = 'accounts:login'
```

---

### Component 5: Frontend — Templates

Tuân thủ quy ước đặt tên template trong [requirements.md](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/docs/requirements.md#L25-L33) và cấu trúc thư mục `templates/` tập trung trong [architecture.md](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/docs/architecture.md#L33).

#### [NEW] `templates/base.html`
- Layout chung: HTML5, meta viewport, load CSS/JS
- Sử dụng CSS thuần (theo khuyến nghị trong [requirements.md](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/docs/requirements.md#L15-L19))
- Block: `{% block title %}`, `{% block content %}`, `{% block extra_css %}`
- Tích hợp Django Messages framework để hiển thị thông báo (success, error)

#### [NEW] `templates/accounts/register.html`
- Kế thừa `base.html`
- Form đăng ký: Email, Username, Số điện thoại, Mật khẩu, Xác nhận mật khẩu
- Hiển thị lỗi validation inline
- Link "Đã có tài khoản? Đăng nhập"
- Giao diện: Card layout, gradient background, form styling hiện đại

#### [NEW] `templates/accounts/login.html`
- Kế thừa `base.html`
- Form đăng nhập: Email, Mật khẩu
- Hiển thị lỗi validation
- Link "Chưa có tài khoản? Đăng ký"
- Giao diện: Tương đồng với trang đăng ký

#### [NEW] `templates/accounts/dashboard.html`
- Kế thừa `base.html`
- Hiển thị: Chào mừng user, email, vai trò
- Nút Đăng xuất
- Placeholder cho các tính năng tương lai

---

### Component 6: Frontend — Static Files (CSS)

#### [NEW] `static/css/base.css`
- Reset CSS, typography (Google Font: Inter)
- Color variables (CSS custom properties) cho dark/light theme
- Layout utilities, container

#### [NEW] `static/css/auth.css`
- Styling cho form đăng ký / đăng nhập
- Card glassmorphism effect
- Input styling, button hover animations
- Responsive design (mobile-first)
- Error message styling

---

### Component 7: Signals (Auto-create related objects)

#### [MODIFY] [apps.py](file:///c:/Users/izanw/Desktop/project/Du_an_KHKT/GSports/apps/accounts/apps.py)

Thêm `ready()` method để import signals.

#### [NEW] `apps/accounts/signals.py`

Tạo Django signal `post_save` trên `User` model (optional, chỉ dùng khi tạo user ngoài flow đăng ký — ví dụ: `createsuperuser`). Logic chính nằm trong `RegisterView.form_valid()` để kiểm soát rõ ràng hơn.

---

## Tổng quan Files cần tạo/sửa

| Hành động | File | Mô tả |
|-----------|------|--------|
| **NEW** | `apps/accounts/forms.py` | Django Forms cho đăng ký và đăng nhập |
| **MODIFY** | `apps/accounts/views.py` | CBV: Register, Login, Logout, Dashboard |
| **MODIFY** | `apps/accounts/urls.py` | URL patterns cho auth |
| **MODIFY** | `apps/accounts/apps.py` | Import signals |
| **NEW** | `apps/accounts/signals.py` | Post-save signal (optional) |
| **MODIFY** | `config/urls.py` | Include accounts URLs + media config |
| **MODIFY** | `config/settings.py` | Login/Logout redirect settings |
| **NEW** | `templates/base.html` | Layout chung |
| **NEW** | `templates/accounts/register.html` | Form đăng ký |
| **NEW** | `templates/accounts/login.html` | Form đăng nhập |
| **NEW** | `templates/accounts/dashboard.html` | Trang dashboard sau đăng nhập |
| **NEW** | `static/css/base.css` | CSS chung |
| **NEW** | `static/css/auth.css` | CSS cho trang auth |

---

## Verification Plan

### Automated Tests
```powershell
# Chạy test cho app accounts
python manage.py test apps.accounts -v 2
```

### Manual Verification
1. **Đăng ký tài khoản mới:**
   - Truy cập `/dang-ky/` → Nhập thông tin → Submit
   - Kiểm tra DB: User, UserRole (CUSTOMER), CustomerProfile, Wallet đều được tạo
   - Redirect đến trang đăng nhập với thông báo thành công

2. **Đăng nhập:**
   - Truy cập `/dang-nhap/` → Nhập email + password
   - Redirect đến `/dashboard/` sau khi đăng nhập thành công
   - Thử đăng nhập sai → Hiển thị lỗi

3. **Đăng xuất:**
   - Click nút Đăng xuất trên dashboard → Redirect về trang đăng nhập

4. **Validation:**
   - Đăng ký email đã tồn tại → Lỗi
   - Đăng ký password quá ngắn → Lỗi
   - Truy cập `/dashboard/` khi chưa đăng nhập → Redirect về login

5. **Giao diện:**
   - Kiểm tra responsive trên desktop và mobile
   - Kiểm tra hiệu ứng hover, animation
   - Kiểm tra hiển thị lỗi validation inline
