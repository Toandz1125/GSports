# Bóc tách thuật ngữ theo từng lớp

> Từ Front-end đến Back-end và Quy trình làm việc

---

## 1. Lớp Front-end (Giao diện)

### Django Template Engine
Đây là hệ thống tạo giao diện động của Django. Thay vì viết file HTML tĩnh, bạn dùng cú pháp của Django (như `{{ user.username }}` hoặc `{% if user.is_authenticated %}`) để hiển thị dữ liệu truyền từ Back-end sang.

### Responsive Design
Thiết kế giao diện **"co giãn"** tự động. Website của bạn phải hiển thị đẹp, không bị vỡ chữ/tràn viền khi xem trên cả máy tính (PC), máy tính bảng (Tablet) và điện thoại (Mobile).

### Bootstrap / Tailwind CSS / CSS thuần
Các thư viện CSS có sẵn giúp bạn làm giao diện cực nhanh mà không cần tự viết từng dòng CSS thuần.
- **Bootstrap** — dễ dùng hơn cho người mới.
- **Tailwind CSS** — giúp tùy biến giao diện sâu hơn.
- Tuy nhiên, hãy cố gắng dùng **CSS thuần** nhất có thể.

### UI/UX
- **UI (User Interface)** — Giao diện người dùng (màu sắc, nút bấm, font chữ đẹp hay xấu).
- **UX (User Experience)** — Trải nghiệm người dùng (mạng chạy mượt không, nút bấm có dễ tìm không, các bước mua hàng/đăng ký có bị rườm rà không).

### Quy tắc đặt tên Template
Đặt tên các file giao diện HTML trong thư mục `templates/tasks/` tuân thủ nghiêm ngặt theo quy ước đặt tên mặc định của **Django Class-based Views**.

Ví dụ:
- `[model_name]_list.html`
- `[model_name]_form.html`

> Điều này giúp hạn chế việc cấu hình thủ công trong file `views.py`.

---

## 2. Lớp Back-end (Logic xử lý)

### Xác thực và Phân quyền (Authentication & Authorization)

- **Xác thực (Authentication):** Kiểm tra xem người dùng *là ai* (Đăng nhập, đăng xuất, đăng ký).
- **Phân quyền (Authorization):** Kiểm tra người dùng đó *có quyền làm gì* (Ví dụ: khách chỉ được xem bài viết, thành viên được bình luận, còn Admin mới được xóa bài viết).

### Django Forms
Thay vì tự viết thẻ `<form>` trong HTML và tự dùng JavaScript để kiểm tra xem người dùng có nhập đúng email, đúng độ dài mật khẩu hay không, bạn định nghĩa Form trong Python. Django sẽ tự động:
1. Tạo ra form HTML.
2. Kiểm tra tính hợp lệ của dữ liệu cực kỳ an toàn.

### Class-based Views (CBV)
Cách viết code xử lý logic bằng cấu trúc **Lớp (Class)** thay vì cấu trúc **Hàm (Function-based Views)**.

CBV giúp bạn tận dụng các mẫu có sẵn của Django:
- `ListView` — hiện danh sách
- `DetailView` — hiện chi tiết

> Giúp code ngắn gọn, sạch sẽ và tái sử dụng được.

### Validation dữ liệu
Quá trình kiểm tra dữ liệu người dùng gửi lên có hợp lệ và an toàn không.

Ví dụ:
- Tuổi phải là số dương.
- Email phải đúng định dạng `@gmail.com`.
- Không chứa mã độc tấn công **SQL Injection**.

---

## 3. Lớp Cơ sở dữ liệu (Database)

### Models
Trong Django, bạn không cần vào MySQL hay SQL Server để gõ lệnh tạo bảng. Bạn sẽ định nghĩa các bảng dữ liệu bằng code Python trong file `models.py`.

Ví dụ: tạo class `Product` gồm tên, giá, ngày tạo.

### Django ORM (Object-Relational Mapping)
Công cụ **"dịch thuật"** giúp bạn tương tác với database bằng code Python thay vì viết câu lệnh SQL thuần.

**Thay vì viết SQL:**
```sql
SELECT * FROM Product WHERE price > 100;
```

**Bạn chỉ cần viết bằng Django ORM:**
```python
Product.objects.filter(price__gt=100)
```

---

## 4. Lớp Quản lý dự án

### Sử dụng Git hiệu quả
Git là công cụ quản lý các phiên bản code. Khi làm việc nhóm, Git giúp các thành viên code chung một dự án mà không bị đè code lên nhau.

Bạn cần biết:
- Tạo nhánh — `git branch`
- Đẩy code — `git push`
- Gộp code — `git merge` / **Pull Request** trên GitHub hoặc GitLab

---

> [!IMPORTANT]
> **Quan trọng:** Khi làm xong phần việc của mình, hãy cập nhật vào `docs` những gì mình đã làm.