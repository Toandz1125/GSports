from django import forms
from .models import Venue, Field

class VenueForm(forms.ModelForm):
    class Meta:
        model = Venue
        fields = ['name', 'description', 'address']
        labels = {
            'name': 'Tên cơ sở thể thao',
            'description': 'Mô tả chi tiết',
            'address': 'Địa chỉ',
        }
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập tên cơ sở thể thao (ví dụ: Sân bóng GSports)...'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Nhập mô tả giới thiệu về cơ sở thể thao...'
            }),
            'address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập địa chỉ chi tiết...'
            }),
        }

class FieldForm(forms.ModelForm):
    class Meta:
        model = Field
        fields = ['name', 'field_type', 'surface_type', 'capacity', 'length', 'width', 'status']
        labels = {
            'name': 'Tên sân con',
            'field_type': 'Loại sân',
            'surface_type': 'Loại mặt sân',
            'capacity': 'Sức chứa (người)',
            'length': 'Chiều dài (m)',
            'width': 'Chiều rộng (m)',
            'status': 'Trạng thái',
        }
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập tên sân con (ví dụ: Sân 5A, Sân 7B)...'
            }),
            'field_type': forms.Select(attrs={
                'class': 'form-control'
            }),
            'surface_type': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ví dụ: Cỏ nhân tạo, Cỏ tự nhiên, Sàn gỗ...'
            }),
            'capacity': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập số lượng người chơi tối đa'
            }),
            'length': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập chiều dài sân (m)'
            }),
            'width': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nhập chiều rộng sân (m)'
            }),
            'status': forms.Select(choices=[
                ('ACTIVE', 'Hoạt động'),
                ('MAINTENANCE', 'Bảo trì'),
                ('INACTIVE', 'Ngừng hoạt động'),
            ], attrs={
                'class': 'form-control'
            }),
        }
