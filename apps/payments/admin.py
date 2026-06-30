from django.contrib import admin
from .models import Invoice, Wallet, WalletTransaction, Payment, Promotion

admin.site.register(Wallet)
admin.site.register(WalletTransaction)
admin.site.register(Payment)
admin.site.register(Invoice)
admin.site.register(Promotion)
