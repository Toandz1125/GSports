# Hướng dẫn Cài đặt & Vận hành (Windows, PowerShell)

Tài liệu này hướng dẫn cách thiết lập và chạy hệ thống **GSports** trên môi trường máy tính nội bộ (Local) sử dụng Windows và PowerShell.

---

## 1. Yêu cầu Hệ thống (Prerequisites)

- **Python 3.12** (Khuyến nghị: Bản 3.12 hỗ trợ tốt thư viện `Pillow` trên Windows mà không cần biên dịch lại mã nguồn C).
- **Git** (Dùng để tải mã nguồn dự án).
- **Microsoft SQL Server** (Bản Developer hoặc Express) đang chạy trên máy (`localhost` hoặc `.`).
- **ODBC Driver 18 for SQL Server** (Yêu cầu bắt buộc để Python có thể kết nối với SQL Server qua thư viện `pyodbc`).

---

## 2. Các bước Cài đặt (Quick Start)

### Bước 1: Tải mã nguồn và tạo thư mục cấu trúc

Mở PowerShell và chạy:
```powershell
git clone <your-repo-url>
cd GSports

# Tạo các thư mục lưu trữ tài nguyên tĩnh và media (nếu chưa có)
mkdir static 
mkdir static\css
mkdir static\js
mkdir static\img 
mkdir media
```

### Bước 2: Thiết lập Môi trường ảo (Virtual Environment)

Sử dụng môi trường ảo giúp tách biệt các thư viện của dự án với các phần mềm khác trên máy tính.

```powershell
py -3.12 -m venv gsports_env
.\gsports_env\Scripts\Activate
```

> [!NOTE]
> Nếu hệ thống chặn việc kích hoạt môi trường ảo (lỗi Execution Policy), hãy chạy lệnh sau một lần duy nhất rồi thử kích hoạt lại:
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> ```

### Bước 3: Cài đặt Thư viện phụ thuộc (Dependencies)

Cài đặt các gói phần mềm cần thiết từ tệp `requirements.txt`:

```powershell
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

*(Lưu ý: Các thư viện chính bao gồm `Django`, `mssql-django`, `pyodbc`, `pillow` và `python-decouple`).*

### Bước 4: Chạy Migrations (Khởi tạo Database)

Dự án sử dụng cơ sở dữ liệu **GSportsDB** trên SQL Server. Hãy mở SQL Server Management Studio (SSMS) và tạo một database trống có tên là `GSportsDB` trước (hoặc đảm bảo database này đã tồn tại trên `localhost`), sau đó chạy lệnh sau để khởi tạo cấu trúc bảng:

```powershell
python manage.py makemigrations
python manage.py migrate
```

### Bước 5: Đổ dữ liệu mẫu (Seed Data)

Dự án GSports có tích hợp sẵn lệnh tự động sinh ra dữ liệu mẫu thực tế (Users, Venues, Fields, Bookings, v.v.) để thuận tiện cho việc thiết kế giao diện và kiểm thử logic.

```powershell
# Cấu hình để PowerShell hiển thị đúng ngôn ngữ tiếng Việt (UTF-8) khi in log dữ liệu ra terminal
$env:PYTHONIOENCODING='utf-8'

# Chạy lệnh seed (dùng cờ --flush để xóa sạch dữ liệu cũ nếu muốn làm mới hoàn toàn)
python manage.py seed_data --flush
```

### Bước 6: Khởi chạy Máy chủ Phát triển (Development Server)

```powershell
python manage.py runserver
```

Mở trình duyệt và truy cập [http://127.0.0.1:8000/](http://127.0.0.1:8000/) để trải nghiệm hệ thống.

---

## 3. Các Lệnh Thông dụng Khác

```powershell
# Thoát khỏi môi trường ảo (Virtual Environment)
deactivate

# Tạo tài khoản Admin quản trị thủ công (trong trường hợp bạn không chạy seed_data)
python manage.py createsuperuser

# Chạy các ca kiểm thử tự động (Unit Tests) khi cần
python manage.py test
```
