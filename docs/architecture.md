# Kiến trúc Dự án GSports

Tài liệu này mô tả cấu trúc thư mục, cách tổ chức mã nguồn và vai trò của từng thành phần trong dự án quản lý sân thể thao **GSports**. Dự án được thiết kế theo kiến trúc **MVT (Model-View-Template)** tiêu chuẩn của Django, được tổ chức thành các module nhỏ gọn (8 ứng dụng độc lập) nhằm tối ưu hóa việc quản lý, mở rộng và bảo trì.

---

## 1. Sơ đồ cấu trúc thư mục Tổng quan

```text
GSports/
├── manage.py                  # Công cụ dòng lệnh quản lý Django
├── requirements.txt           # Danh sách các thư viện phụ thuộc của dự án
│
├── config/                    # Thư mục cấu hình chính của toàn bộ dự án
│   ├── __init__.py
│   ├── settings.py            # Thiết lập dự án (DB SQL Server, Apps, Middleware, Múi giờ, Ngôn ngữ)
│   ├── urls.py                # Định tuyến URL tổng
│   └── wsgi.py / asgi.py      # Cấu hình Web Server (hỗ trợ ASGI cho realtime chat)
│
├── apps/                      # Thư mục chứa các module nghiệp vụ (Django Apps)
│   ├── __init__.py
│   ├── accounts/              # Quản lý người dùng, vai trò, ví điện tử
│   ├── venues/                # Quản lý sân bãi, ca làm việc, môn thể thao, giá cả
│   ├── bookings/              # Xử lý đặt sân, kiểm tra lịch trống, khóa slot
│   ├── payments/              # Xử lý giao dịch thanh toán, hóa đơn, khuyến mãi
│   ├── services/              # Quản lý dịch vụ phụ trợ (nước uống, thuê áo, giày...)
│   ├── reviews/               # Hệ thống đánh giá, phản hồi về sân bãi
│   ├── chat/                  # Hệ thống tin nhắn thời gian thực (Realtime Chat)
│   └── core/                  # Chứa các xử lý chung (Log hệ thống, Seed Data)
│
├── static/                    # Chứa các tài nguyên tĩnh hệ thống (CSS, JS, Images)
├── media/                     # Thư mục chứa tệp tin do người dùng tải lên (ảnh đại diện, ảnh sân)
├── templates/                 # Thư mục chứa giao diện HTML tập trung
└── gsports_env/               # Môi trường ảo của Python
```

---

## 2. Chi tiết các Module Nghiệp vụ (Django Apps)

Dự án áp dụng mô hình phân tách ứng dụngdụng. Dưới đây là 8 module cốt lõi:

### 2.1. `accounts` (Quản trị Người dùng & Phân quyền)
- **Nhiệm vụ:** Xử lý xác thực, cấp quyền, và thông tin tài khoản người dùng.
- **Thực thể chính:** `User` (Custom Model), `Role`, `UserRole`, `OwnerProfile`, `CustomerProfile`, `Wallet`, `WalletTransaction`, `Notification`.

### 2.2. `venues` (Quản trị Cơ sở vật chất)
- **Nhiệm vụ:** Quản lý danh sách các cụm sân, sân con, chính sách, và giá thuê tùy chỉnh.
- **Thực thể chính:** `Venue`, `Field`, `Sport`, `FieldType`, `FieldPriceRule`, `VenueOperatingHour`, `VenuePolicy`.

### 2.3. `bookings` (Quản trị Đặt sân)
- **Nhiệm vụ:** Xử lý logic đặt sân, kiểm tra trùng lịch, khóa slot khi đang thanh toán.
- **Thực thể chính:** `Booking`, `BookingSlot`, `SlotLock`, `BookingPackage`, `BookingPromotion`.

### 2.4. `payments` (Quản trị Giao dịch & Thanh toán)
- **Nhiệm vụ:** Xử lý dòng tiền, lưu trữ hóa đơn, và áp dụng các chương trình khuyến mãi.
- **Thực thể chính:** `Payment`, `Invoice`, `Promotion`.

### 2.5. `services` (Dịch vụ Phụ trợ)
- **Nhiệm vụ:** Quản lý các dịch vụ đi kèm khi khách thuê sân (ví dụ: nước uống, bóng, áo bib).
- **Thực thể chính:** `ServiceItem`, `BookingService`.

### 2.6. `reviews` (Đánh giá)
- **Nhiệm vụ:** Cho phép người dùng đánh giá và phản hồi về chất lượng cơ sở vật chất.
- **Thực thể chính:** `Review`.

### 2.7. `chat` (Nhắn tin Realtime)
- **Nhiệm vụ:** Hỗ trợ trao đổi tin nhắn trực tiếp giữa khách hàng và nhân viên hoặc chủ sân.
- **Thực thể chính:** `ChatRoom`, `ChatParticipant`, `ChatMessage`.

### 2.8. `core` (Xử lý Hệ thống & Core Data)
- **Nhiệm vụ:** Chứa các lệnh (management commands) như `seed_data`, quản lý nhân sự chung và log hệ thống.
- **Thực thể chính:** `VenueStaff`, `StaffShift`, `DailyVenueStats`, `AuditLog`, `SystemEvent`.

---

## 3. Cấu hình Cốt lõi (settings.py)

Dự án GSports có các thiết lập đặc thù nhằm đảm bảo hoạt động tối ưu tại môi trường Việt Nam:

1. **Cơ sở dữ liệu (Database):**
   - Sử dụng **Microsoft SQL Server** (`mssql` engine).
   - Module kết nối: `mssql-django` và `ODBC Driver 18`.

2. **Custom User Model:**
   - Sử dụng `AUTH_USER_MODEL = 'accounts.User'` thay vì User mặc định của Django.
   - Hỗ trợ thêm các trường `phone`, `avatar` và cấu trúc linh hoạt để đăng nhập qua Email/OTP.

3. **Ngôn ngữ và Thời gian:**
   - Ngôn ngữ mặc định: `LANGUAGE_CODE = 'vi'` (Tiếng Việt).
   - Múi giờ: `TIME_ZONE = 'Asia/Ho_Chi_Minh'`. Hỗ trợ lưu trữ dữ liệu thời gian chính xác tại Việt Nam.

4. **Quản lý Media:**
   - `MEDIA_ROOT` và `MEDIA_URL` được thiết lập trỏ về thư mục `media/` ở thư mục gốc, giúp chuẩn hóa việc lưu trữ ảnh đại diện và ảnh sân bãi.