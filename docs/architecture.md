# Kiến trúc Dự án

Tài liệu này mô tả cấu trúc thư mục, cách tổ chức mã nguồn và vai trò của từng thành phần trong dự án **tmds_project**. Dự án được thiết kế theo kiến trúc **MVT (Model-View-Template)** tiêu chuẩn của Django, có tùy biến gom nhóm ứng dụng (`apps/`) và tập trung hóa giao diện (`templates/`) để tối ưu hóa việc quản lý và mở rộng.

---

## 1. Sơ đồ cấu trúc thư mục Tổng quan

```text
GSports/
├── manage.py                  # Công cụ dòng lệnh quản lý Django
├── requirements.txt           # Danh sách các thư viện phụ thuộc của dự án
├── db.mysql                 # Cơ sở dữ liệu local (dùng để phát triển)
│
├── config/                    # Thư mục cấu hình chính của toàn bộ dự án
│   ├── __init__.py
│   └── settings.py            # Thiết lập dự án (DB, Apps, Middleware,...)
│
├── apps/                      # Thư mục chứa các ứng dụng (Apps) của hệ thống
│   ├── __init__.py
│   └── tasks/                 # Ứng dụng quản lý nhiệm vụ (Ví dụ cụ thể)
│       ├── migrations/        # Lưu trữ lịch sử thay đổi Database
│       ├── admin.py           # Cấu hình giao diện Admin cho app
│       ├── apps.py            # Cấu hình thông tin nội bộ của app
│       ├── forms.py           # Xử lý dữ liệu forms đầu vào và Validation
│       ├── models.py          # Định nghĩa các bảng dữ liệu (Models)
│       ├── tests.py           # Viết các ca kiểm thử (Unit test)
│       ├── urls.py            # Định tuyến URL nội bộ của app tasks
│       └── views.py           # Xử lý logic nghiệp vụ (Class-based Views)
│
├── templates/                 # Thư mục chứa giao diện HTML tập trung
│   └── tasks/                 # Giao diện dành riêng cho app tasks
│       ├── components/        # Các thành phần giao diện nhỏ tái sử dụng
│       │   ├── task_status_badge.html    # Hiển thị trạng thái nhiệm vụ
│       │   └── task_priority_badge.html  # Hiển thị mức độ ưu tiên
│       ├── base.html          # Template cơ sở (chứa Navbar, Footer, CSS chung)
│       ├── task_list.html     # Giao diện danh sách nhiệm vụ
│       ├── task_detail.html   # Giao diện chi tiết một nhiệm vụ
│       ├── task_form.html     # Giao diện Form tạo mới/Cập nhật nhiệm vụ
│       └── task_confirm_delete.html      # Giao diện xác nhận xóa nhiệm vụ
│
├── static/                    # Chứa các tài nguyên tĩnh hệ thống (CSS, JS, Images)
│   ├── css/
│   ├── js/
│   └── img/
│
├── media/                     # Thư mục chứa tệp tin do người dùng tải lên
│
└── GSports_evm/                  # Môi trường ảo của Python (Không commit lên Git)