from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    # --- Xác thực (Authentication) ---
    path('dang-ky/',          views.CustomerRegisterView.as_view(), name='register'),
    path('dang-ky-chu-san/',  views.OwnerRegisterView.as_view(),    name='register_owner'),
    path('dang-nhap/',        views.LoginView.as_view(),             name='login'),
    path('dang-xuat/',        views.LogoutView.as_view(),            name='logout'),

    # --- Dashboard ---
    path('dashboard/',        views.DashboardView.as_view(),         name='dashboard'),

    # --- Hồ sơ (Profile) ---
    path('ho-so/',            views.ProfileView.as_view(),           name='profile'),
    path('ho-so/chinh-sua/',  views.ProfileUpdateView.as_view(),     name='profile_edit'),
    path('ho-so/avatar/',     views.AvatarUpdateView.as_view(),      name='avatar_edit'),
    path('ho-so/chu-san/',    views.OwnerProfileUpdateView.as_view(), name='owner_profile_edit'),
    path('ho-so/xoa/',        views.DeleteAccountView.as_view(),     name='delete_account'),
    # --- Nhân viên (Staff) ---
    path('nhan-vien/',            views.StaffListView.as_view(),         name='staff_list'),
    path('nhan-vien/them/',       views.StaffCreateView.as_view(),       name='staff_create'),
    path('nhan-vien/<int:pk>/sua/', views.StaffUpdateView.as_view(),     name='staff_edit'),
    path('nhan-vien/<int:pk>/xoa/', views.StaffDeleteView.as_view(),     name='staff_delete'),


    # --- Mật khẩu ---
    path('doi-mat-khau/',     views.ChangePasswordView.as_view(),    name='change_password'),
# Trigger reload
    # --- Duyệt đăng ký chủ sân (Admin) ---
    path('owner-request/<int:pk>/approve/', views.AdminApproveOwnerView.as_view(), name='admin_approve_owner'),
    path('owner-request/<int:pk>/reject/',  views.AdminRejectOwnerView.as_view(),  name='admin_reject_owner'),

    # --- Quản lý tài khoản (Admin) ---
    path('quan-ly-tai-khoan/', views.AdminUserListView.as_view(), name='admin_user_list'),
    path('quan-ly-tai-khoan/<int:pk>/toggle-active/', views.AdminUserToggleActiveView.as_view(), name='admin_user_toggle_active'),
    path('quan-ly-tai-khoan/<int:pk>/xoa/', views.AdminUserDeleteView.as_view(), name='admin_user_delete'),
]

