"""
Management command: python manage.py seed_data [--flush]

Seed dữ liệu mẫu thực tế cho hệ thống GSports.
"""

import uuid
import random
from datetime import date, time, timedelta, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import (
    User, Role, UserRole, OwnerProfile, CustomerProfile,
    Wallet, WalletTransaction, Notification, FavoriteVenue,
)
from apps.venues.models import (
    Sport, Venue, VenueOperatingHour, VenueImage,
    FieldType, Field, FieldPriceRule, VenuePolicy,
)
from apps.bookings.models import (
    BookingPackage, BookingRecurrenceDay, Booking,
    BookingSlot, SlotLock, BookingPromotion,
)
from apps.payments.models import Payment, Invoice, Promotion
from apps.services.models import ServiceItem, BookingService
from apps.reviews.models import Review
from apps.chat.models import ChatRoom, ChatParticipant, ChatMessage
from apps.core.models import VenueStaff, StaffShift, DailyVenueStats, AuditLog, SystemEvent


DEFAULT_PASSWORD = make_password('GSports@123')


class Command(BaseCommand):
    help = 'Seed dữ liệu mẫu cho GSports'

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush', action='store_true',
            help='Xoá toàn bộ dữ liệu trước khi seed',
        )

    def handle(self, *args, **options):
        if options['flush']:
            self.stdout.write(self.style.WARNING('Đang xoá dữ liệu cũ...'))
            self._flush()

        self.stdout.write(self.style.NOTICE('Bắt đầu seed data...'))

        with transaction.atomic():
            roles = self._seed_roles()
            users = self._seed_users()
            self._seed_user_roles(users, roles)
            owner_profiles = self._seed_owner_profiles(users)
            self._seed_customer_profiles(users)
            wallets = self._seed_wallets(users)
            sports = self._seed_sports()
            field_types = self._seed_field_types(sports)
            venues = self._seed_venues(owner_profiles)
            self._seed_operating_hours(venues)
            self._seed_venue_policies(venues)
            fields = self._seed_fields(venues, field_types)
            self._seed_price_rules(fields)
            promotions = self._seed_promotions(venues)
            service_items = self._seed_service_items(venues)
            venue_staff_list = self._seed_venue_staff(users, venues)
            self._seed_staff_shifts(venue_staff_list)
            bookings, packages = self._seed_bookings(users, venues, fields)
            self._seed_booking_slots(bookings)
            self._seed_slot_locks(fields, users, bookings)
            self._seed_booking_promotions(bookings, promotions)
            self._seed_booking_services(bookings, service_items)
            payments = self._seed_payments(bookings)
            self._seed_invoices(payments)
            self._seed_wallet_transactions(wallets, bookings)
            self._seed_reviews(users, venues, bookings)
            self._seed_chat(users, venues)
            self._seed_notifications(users)
            self._seed_favorites(users, venues)
            self._seed_daily_stats(venues)
            self._seed_audit_logs(users)
            self._seed_system_events()

        self._print_summary()

    def _flush(self):
        """Xoá dữ liệu theo thứ tự FK dependency."""
        models = [
            SystemEvent, AuditLog, DailyVenueStats, StaffShift, VenueStaff,
            ChatMessage, ChatParticipant, ChatRoom, Review, BookingService,
            Invoice, Payment, BookingPromotion, SlotLock, BookingSlot,
            Booking, BookingRecurrenceDay, BookingPackage, Promotion,
            ServiceItem, FieldPriceRule, Field, FieldType,
            VenuePolicy, VenueImage, VenueOperatingHour, Venue, Sport,
            FavoriteVenue, Notification, WalletTransaction, Wallet,
            CustomerProfile, OwnerProfile, UserRole, Role,
        ]
        for m in models:
            m.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()
        self.stdout.write(self.style.SUCCESS('  ✓ Đã xoá dữ liệu cũ'))

    # ──────────────── ROLES ────────────────

    def _seed_roles(self):
        roles = {}
        for name in ['CUSTOMER', 'OWNER', 'STAFF', 'ADMIN']:
            role, _ = Role.objects.get_or_create(name=name)
            roles[name] = role
        self.stdout.write(self.style.SUCCESS(f'  ✓ Roles: {len(roles)}'))
        return roles

    # ──────────────── USERS ────────────────

    def _seed_users(self):
        user_data = [
            # Admins
            {'email': 'admin1@gsports.vn', 'username': 'admin_tuan', 'first_name': 'Tuấn', 'last_name': 'Nguyễn', 'phone': '0901000001', 'role': 'ADMIN'},
            {'email': 'admin2@gsports.vn', 'username': 'admin_linh', 'first_name': 'Linh', 'last_name': 'Trần', 'phone': '0901000002', 'role': 'ADMIN'},
            # Owners
            {'email': 'owner.minh@gmail.com', 'username': 'owner_minh', 'first_name': 'Minh', 'last_name': 'Lê', 'phone': '0902000001', 'role': 'OWNER'},
            {'email': 'owner.hoa@gmail.com', 'username': 'owner_hoa', 'first_name': 'Hoa', 'last_name': 'Phạm', 'phone': '0902000002', 'role': 'OWNER'},
            {'email': 'owner.duc@gmail.com', 'username': 'owner_duc', 'first_name': 'Đức', 'last_name': 'Võ', 'phone': '0902000003', 'role': 'OWNER'},
            # Staff
            {'email': 'staff.phuc@gmail.com', 'username': 'staff_phuc', 'first_name': 'Phúc', 'last_name': 'Hoàng', 'phone': '0903000001', 'role': 'STAFF'},
            {'email': 'staff.quan@gmail.com', 'username': 'staff_quan', 'first_name': 'Quân', 'last_name': 'Đặng', 'phone': '0903000002', 'role': 'STAFF'},
            {'email': 'staff.mai@gmail.com', 'username': 'staff_mai', 'first_name': 'Mai', 'last_name': 'Bùi', 'phone': '0903000003', 'role': 'STAFF'},
            {'email': 'staff.nam@gmail.com', 'username': 'staff_nam', 'first_name': 'Nam', 'last_name': 'Lý', 'phone': '0903000004', 'role': 'STAFF'},
            # Customers
            {'email': 'an.nguyen@gmail.com', 'username': 'customer_an', 'first_name': 'An', 'last_name': 'Nguyễn', 'phone': '0904000001', 'role': 'CUSTOMER'},
            {'email': 'binh.tran@gmail.com', 'username': 'customer_binh', 'first_name': 'Bình', 'last_name': 'Trần', 'phone': '0904000002', 'role': 'CUSTOMER'},
            {'email': 'cuong.le@gmail.com', 'username': 'customer_cuong', 'first_name': 'Cường', 'last_name': 'Lê', 'phone': '0904000003', 'role': 'CUSTOMER'},
            {'email': 'dung.pham@gmail.com', 'username': 'customer_dung', 'first_name': 'Dũng', 'last_name': 'Phạm', 'phone': '0904000004', 'role': 'CUSTOMER'},
            {'email': 'em.vo@gmail.com', 'username': 'customer_em', 'first_name': 'Em', 'last_name': 'Võ', 'phone': '0904000005', 'role': 'CUSTOMER'},
            {'email': 'giang.hoang@gmail.com', 'username': 'customer_giang', 'first_name': 'Giang', 'last_name': 'Hoàng', 'phone': '0904000006', 'role': 'CUSTOMER'},
            {'email': 'hung.dang@gmail.com', 'username': 'customer_hung', 'first_name': 'Hùng', 'last_name': 'Đặng', 'phone': '0904000007', 'role': 'CUSTOMER'},
            {'email': 'khoa.bui@gmail.com', 'username': 'customer_khoa', 'first_name': 'Khoa', 'last_name': 'Bùi', 'phone': '0904000008', 'role': 'CUSTOMER'},
            {'email': 'lan.ly@gmail.com', 'username': 'customer_lan', 'first_name': 'Lan', 'last_name': 'Lý', 'phone': '0904000009', 'role': 'CUSTOMER'},
            {'email': 'minh.do@gmail.com', 'username': 'customer_minh2', 'first_name': 'Minh', 'last_name': 'Đỗ', 'phone': '0904000010', 'role': 'CUSTOMER'},
        ]

        users = {}
        for d in user_data:
            user, created = User.objects.get_or_create(
                email=d['email'],
                defaults={
                    'username': d['username'],
                    'first_name': d['first_name'],
                    'last_name': d['last_name'],
                    'phone': d['phone'],
                    'password': DEFAULT_PASSWORD,
                    'is_active': True,
                    'is_staff': d['role'] == 'ADMIN',
                    'is_superuser': d['role'] == 'ADMIN',
                },
            )
            users[d['username']] = {'user': user, 'role': d['role']}

        self.stdout.write(self.style.SUCCESS(f'  ✓ Users: {len(users)}'))
        return users

    def _seed_user_roles(self, users, roles):
        count = 0
        for udata in users.values():
            UserRole.objects.get_or_create(
                user=udata['user'], role=roles[udata['role']],
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ UserRoles: {count}'))

    # ──────────────── PROFILES ────────────────

    def _seed_owner_profiles(self, users):
        owner_data = [
            ('owner_minh', 'Sân Bóng Minh Phát', '1234567890', 'Vietcombank'),
            ('owner_hoa', 'CLB Thể Thao Hoa Phượng', '0987654321', 'Techcombank'),
            ('owner_duc', 'Trung Tâm TT Đức Thịnh', '1122334455', 'BIDV'),
        ]
        profiles = {}
        for uname, bname, bank_acc, bank_name in owner_data:
            profile, _ = OwnerProfile.objects.get_or_create(
                user=users[uname]['user'],
                defaults={
                    'business_name': bname,
                    'bank_account_number': bank_acc,
                    'bank_name': bank_name,
                    'is_verified': True,
                },
            )
            profiles[uname] = profile
        self.stdout.write(self.style.SUCCESS(f'  ✓ OwnerProfiles: {len(profiles)}'))
        return profiles

    def _seed_customer_profiles(self, users):
        count = 0
        for uname, udata in users.items():
            if udata['role'] == 'CUSTOMER':
                CustomerProfile.objects.get_or_create(
                    user=udata['user'],
                    defaults={'loyalty_points': random.randint(0, 500)},
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ CustomerProfiles: {count}'))

    def _seed_wallets(self, users):
        wallets = {}
        for uname, udata in users.items():
            wallet, _ = Wallet.objects.get_or_create(
                user=udata['user'],
                defaults={'balance': Decimal(random.randint(50, 500) * 1000)},
            )
            wallets[uname] = wallet
        self.stdout.write(self.style.SUCCESS(f'  ✓ Wallets: {len(wallets)}'))
        return wallets

    # ──────────────── SPORTS & FIELD TYPES ────────────────

    def _seed_sports(self):
        sport_data = [
            ('Bóng đá', 'bong-da', '⚽'),
            ('Cầu lông', 'cau-long', '🏸'),
            ('Tennis', 'tennis', '🎾'),
            ('Pickleball', 'pickleball', '🏓'),
        ]
        sports = {}
        for name, slug, icon in sport_data:
            sport, _ = Sport.objects.get_or_create(
                slug=slug, defaults={'name': name, 'icon': icon},
            )
            sports[slug] = sport
        self.stdout.write(self.style.SUCCESS(f'  ✓ Sports: {len(sports)}'))
        return sports

    def _seed_field_types(self, sports):
        ft_data = [
            ('bong-da', 'Sân 5 người', 'san-5', 10, '⚽'),
            ('bong-da', 'Sân 7 người', 'san-7', 14, '⚽'),
            ('bong-da', 'Sân 11 người', 'san-11', 22, '⚽'),
            ('cau-long', 'Sân đơn', 'cau-long-don', 2, '🏸'),
            ('cau-long', 'Sân đôi', 'cau-long-doi', 4, '🏸'),
            ('tennis', 'Sân đơn', 'tennis-don', 2, '🎾'),
            ('tennis', 'Sân đôi', 'tennis-doi', 4, '🎾'),
            ('pickleball', 'Sân Pickleball', 'pickleball-std', 4, '🏓'),
        ]
        field_types = {}
        for sport_slug, name, slug, players, icon in ft_data:
            ft, _ = FieldType.objects.get_or_create(
                slug=slug,
                defaults={
                    'sport': sports[sport_slug],
                    'name': name,
                    'player_count': players,
                    'icon': icon,
                },
            )
            field_types[slug] = ft
        self.stdout.write(self.style.SUCCESS(f'  ✓ FieldTypes: {len(field_types)}'))
        return field_types

    # ──────────────── VENUES ────────────────

    def _seed_venues(self, owner_profiles):
        venue_data = [
            {
                'owner': 'owner_minh',
                'name': 'Sân Bóng Đá Phú Thọ',
                'desc': 'Sân bóng đá chất lượng cao tại quận 11, mặt cỏ nhân tạo, có đèn chiếu sáng.',
                'address': '1 Lý Thường Kiệt, Phường 7, Quận 11, TP.HCM',
                'lat': Decimal('10.7625480'), 'lng': Decimal('106.6572640'),
            },
            {
                'owner': 'owner_hoa',
                'name': 'CLB Cầu Lông Tân Bình',
                'desc': 'Câu lạc bộ cầu lông tiêu chuẩn quốc tế, sàn gỗ cao cấp, máy lạnh.',
                'address': '220 Hoàng Hoa Thám, Phường 5, Quận Tân Bình, TP.HCM',
                'lat': Decimal('10.7991230'), 'lng': Decimal('106.6521170'),
            },
            {
                'owner': 'owner_duc',
                'name': 'Trung Tâm Tennis & Pickleball Thủ Đức',
                'desc': 'Trung tâm đa năng: tennis, pickleball. Sân hard-court tiêu chuẩn.',
                'address': '10 Võ Văn Ngân, Phường Bình Thọ, TP. Thủ Đức, TP.HCM',
                'lat': Decimal('10.8488650'), 'lng': Decimal('106.7718250'),
            },
        ]
        venues = {}
        for vd in venue_data:
            venue, _ = Venue.objects.get_or_create(
                name=vd['name'],
                defaults={
                    'owner': owner_profiles[vd['owner']],
                    'description': vd['desc'],
                    'address': vd['address'],
                    'latitude': vd['lat'],
                    'longitude': vd['lng'],
                    'status': 'ACTIVE',
                },
            )
            venues[vd['name']] = venue
        self.stdout.write(self.style.SUCCESS(f'  ✓ Venues: {len(venues)}'))
        return venues

    def _seed_operating_hours(self, venues):
        count = 0
        for venue in venues.values():
            for day in range(7):
                open_t = time(6, 0) if day < 5 else time(5, 30)
                close_t = time(22, 0) if day < 5 else time(23, 0)
                VenueOperatingHour.objects.get_or_create(
                    venue=venue, weekday=day,
                    defaults={'open_time': open_t, 'close_time': close_t},
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ OperatingHours: {count}'))

    def _seed_venue_policies(self, venues):
        policies = [
            (24, Decimal('80.00')),
            (12, Decimal('50.00')),
            (6, Decimal('30.00')),
        ]
        count = 0
        for (name, venue), (hours, pct) in zip(venues.items(), policies):
            VenuePolicy.objects.get_or_create(
                venue=venue,
                defaults={'cancel_before_hours': hours, 'refund_percent': pct},
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ VenuePolicies: {count}'))

    # ──────────────── FIELDS ────────────────

    def _seed_fields(self, venues, field_types):
        venue_list = list(venues.values())
        # Venue 0: Sân bóng đá — 2 sân 5, 1 sân 7, 1 sân 11
        # Venue 1: CLB Cầu lông — 3 sân đơn, 1 sân đôi
        # Venue 2: Tennis/Pickleball — 2 sân tennis đơn, 1 tennis đôi, 1 pickleball
        field_map = [
            (venue_list[0], [
                ('Sân 5A', 'san-5', 'Cỏ nhân tạo', Decimal('25'), Decimal('15')),
                ('Sân 5B', 'san-5', 'Cỏ nhân tạo', Decimal('25'), Decimal('15')),
                ('Sân 7A', 'san-7', 'Cỏ nhân tạo', Decimal('40'), Decimal('25')),
                ('Sân 11', 'san-11', 'Cỏ nhân tạo', Decimal('90'), Decimal('45')),
            ]),
            (venue_list[1], [
                ('Sân Đơn 1', 'cau-long-don', 'Sàn gỗ', Decimal('13.4'), Decimal('5.18')),
                ('Sân Đơn 2', 'cau-long-don', 'Sàn gỗ', Decimal('13.4'), Decimal('5.18')),
                ('Sân Đơn 3', 'cau-long-don', 'Sàn gỗ', Decimal('13.4'), Decimal('5.18')),
                ('Sân Đôi 1', 'cau-long-doi', 'Sàn gỗ', Decimal('13.4'), Decimal('6.1')),
            ]),
            (venue_list[2], [
                ('Tennis 1', 'tennis-don', 'Hard-court', Decimal('23.77'), Decimal('8.23')),
                ('Tennis 2', 'tennis-don', 'Hard-court', Decimal('23.77'), Decimal('8.23')),
                ('Tennis Đôi', 'tennis-doi', 'Hard-court', Decimal('23.77'), Decimal('10.97')),
                ('Pickleball 1', 'pickleball-std', 'Composite', Decimal('13.41'), Decimal('6.1')),
            ]),
        ]

        fields = []
        for venue, flist in field_map:
            for fname, ft_slug, surface, length, width in flist:
                field, _ = Field.objects.get_or_create(
                    venue=venue, name=fname,
                    defaults={
                        'field_type': field_types[ft_slug],
                        'surface_type': surface,
                        'length': length,
                        'width': width,
                        'capacity': field_types[ft_slug].player_count,
                        'status': 'ACTIVE',
                    },
                )
                fields.append(field)
        self.stdout.write(self.style.SUCCESS(f'  ✓ Fields: {len(fields)}'))
        return fields

    def _seed_price_rules(self, fields):
        count = 0
        for field in fields:
            # Giờ thường (6h-17h)
            base = Decimal(random.choice([150, 200, 250, 300])) * 1000
            FieldPriceRule.objects.get_or_create(
                field=field, start_time=time(6, 0), end_time=time(17, 0), priority=0, is_holiday=False, day_of_week=None,
                defaults={'price_per_hour': base},
            )
            count += 1
            # Giờ vàng (17h-22h)
            peak = base + Decimal('150000')
            FieldPriceRule.objects.get_or_create(
                field=field, start_time=time(17, 0), end_time=time(22, 0), priority=1, is_holiday=False, day_of_week=None,
                defaults={'price_per_hour': peak},
            )
            count += 1
            # Cuối tuần (T7+CN) +50k
            for day in [5, 6]:
                FieldPriceRule.objects.get_or_create(
                    field=field, start_time=time(6, 0), end_time=time(22, 0),
                    priority=2, is_holiday=False, day_of_week=day,
                    defaults={'price_per_hour': base + Decimal('50000')},
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ PriceRules: {count}'))

    # ──────────────── PROMOTIONS ────────────────

    def _seed_promotions(self, venues):
        venue_list = list(venues.values())
        today = date.today()
        promo_data = [
            (None, 'WELCOME10', 'PERCENTAGE', Decimal('10'), Decimal('100000'), Decimal('200000'), 100),
            (None, 'SUMMER2025', 'PERCENTAGE', Decimal('15'), Decimal('150000'), Decimal('300000'), 50),
            (venue_list[0], 'BONGDA50K', 'FIXED', Decimal('50000'), None, Decimal('200000'), 30),
            (venue_list[1], 'CAULONG20', 'PERCENTAGE', Decimal('20'), Decimal('80000'), Decimal('100000'), 20),
            (venue_list[2], 'TENNIS30K', 'FIXED', Decimal('30000'), None, Decimal('150000'), 25),
        ]
        promotions = []
        for venue, code, dtype, value, max_disc, min_order, qty in promo_data:
            promo, _ = Promotion.objects.get_or_create(
                code=code,
                defaults={
                    'venue': venue,
                    'discount_type': dtype,
                    'discount_value': value,
                    'max_discount_amount': max_disc,
                    'min_order_value': min_order,
                    'start_date': today - timedelta(days=30),
                    'end_date': today + timedelta(days=90),
                    'quantity': qty,
                    'used_quantity': random.randint(0, qty // 3),
                },
            )
            promotions.append(promo)
        self.stdout.write(self.style.SUCCESS(f'  ✓ Promotions: {len(promotions)}'))
        return promotions

    # ──────────────── SERVICE ITEMS ────────────────

    def _seed_service_items(self, venues):
        items_template = [
            ('Nước suối', 'DRINK', Decimal('10000'), 100),
            ('Nước ngọt Pepsi', 'DRINK', Decimal('15000'), 80),
            ('Trà đá', 'DRINK', Decimal('5000'), 200),
            ('Nước tăng lực Sting', 'DRINK', Decimal('12000'), 50),
            ('Cho thuê giày', 'RENTAL', Decimal('30000'), 20),
            ('Cho thuê áo bibs', 'RENTAL', Decimal('20000'), 30),
            ('Bóng đá size 5', 'EQUIPMENT', Decimal('50000'), 10),
            ('Vợt cầu lông', 'RENTAL', Decimal('40000'), 15),
            ('Quả cầu lông (ống 12)', 'EQUIPMENT', Decimal('60000'), 30),
            ('Khăn lạnh', 'OTHER', Decimal('5000'), 50),
        ]
        service_items = []
        for venue in venues.values():
            for name, cat, price, stock in items_template:
                item, _ = ServiceItem.objects.get_or_create(
                    venue=venue, name=name,
                    defaults={'category': cat, 'price': price, 'stock': stock},
                )
                service_items.append(item)
        self.stdout.write(self.style.SUCCESS(f'  ✓ ServiceItems: {len(service_items)}'))
        return service_items

    # ──────────────── STAFF ────────────────

    def _seed_venue_staff(self, users, venues):
        venue_list = list(venues.values())
        staff_assignments = [
            ('staff_phuc', venue_list[0], 'FULL_ACCESS'),
            ('staff_quan', venue_list[0], 'BOOKING_ONLY'),
            ('staff_mai', venue_list[1], 'FULL_ACCESS'),
            ('staff_nam', venue_list[2], 'FULL_ACCESS'),
        ]
        vs_list = []
        for uname, venue, perm in staff_assignments:
            vs, _ = VenueStaff.objects.get_or_create(
                venue=venue, staff=users[uname]['user'],
                defaults={'permission_level': perm},
            )
            vs_list.append(vs)
        self.stdout.write(self.style.SUCCESS(f'  ✓ VenueStaff: {len(vs_list)}'))
        return vs_list

    def _seed_staff_shifts(self, venue_staff_list):
        count = 0
        shifts = [
            (time(6, 0), time(14, 0)),    # Ca sáng
            (time(14, 0), time(22, 0)),   # Ca chiều
        ]
        for vs in venue_staff_list:
            for day in range(6):  # T2–T7
                shift = shifts[day % 2]
                StaffShift.objects.get_or_create(
                    venue_staff=vs, weekday=day, start_time=shift[0],
                    defaults={'end_time': shift[1], 'is_active': True},
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ StaffShifts: {count}'))

    # ──────────────── BOOKINGS ────────────────

    def _seed_bookings(self, users, venues, fields):
        customer_users = [u['user'] for u in users.values() if u['role'] == 'CUSTOMER']
        venue_list = list(venues.values())
        today = date.today()
        all_bookings = []
        all_packages = []

        # --- Single bookings (40 bookings) ---
        statuses = ['PAID'] * 20 + ['PENDING'] * 10 + ['CANCELLED'] * 10
        random.shuffle(statuses)

        for i, status in enumerate(statuses):
            customer = customer_users[i % len(customer_users)]
            field = fields[i % len(fields)]
            venue = field.venue
            booking_date = today + timedelta(days=random.randint(-14, 30))
            hour = random.choice([7, 8, 9, 10, 14, 15, 16, 17, 18, 19, 20])
            amount = Decimal(random.choice([200, 250, 300, 350, 400, 450])) * 1000

            pkg = BookingPackage.objects.create(
                user=customer,
                package_type='SINGLE',
                start_date=booking_date,
            )
            all_packages.append(pkg)

            booking = Booking.objects.create(
                booking_package=pkg,
                venue=venue,
                field=field,
                booking_date=booking_date,
                status=status,
                booking_channel='WEB' if i % 3 != 0 else 'WALKIN',
                total_amount=amount,
                payment_deadline=timezone.now() + timedelta(hours=2) if status == 'PENDING' else None,
            )
            all_bookings.append(booking)

        # --- Recurring bookings (2 packages, T2-T4-T6, 4 tuần) ---
        for idx in range(2):
            customer = customer_users[idx]
            field = fields[idx]
            venue = field.venue
            start = today + timedelta(days=1)
            end = start + timedelta(weeks=4)

            pkg = BookingPackage.objects.create(
                user=customer, package_type='RECURRING',
                start_date=start, end_date=end,
            )
            all_packages.append(pkg)

            for wd in [0, 2, 4]:  # T2, T4, T6
                BookingRecurrenceDay.objects.create(
                    booking_package=pkg, weekday=wd,
                )

            current = start
            while current <= end:
                if current.weekday() in [0, 2, 4]:
                    booking = Booking.objects.create(
                        booking_package=pkg, venue=venue, field=field,
                        booking_date=current, status='PAID',
                        booking_channel='WEB',
                        total_amount=Decimal('300000'),
                    )
                    all_bookings.append(booking)
                current += timedelta(days=1)

        # --- 5 bookings trùng giờ (test SlotLock) ---
        conflict_field = fields[0]
        conflict_date = today + timedelta(days=3)
        for i in range(5):
            customer = customer_users[i % len(customer_users)]
            pkg = BookingPackage.objects.create(
                user=customer, package_type='SINGLE', start_date=conflict_date,
            )
            all_packages.append(pkg)
            booking = Booking.objects.create(
                booking_package=pkg,
                venue=conflict_field.venue,
                field=conflict_field,
                booking_date=conflict_date,
                status='PENDING' if i < 3 else 'CANCELLED',
                booking_channel='WEB',
                total_amount=Decimal('350000'),
                note=f'Test conflict slot #{i+1}' if i > 0 else None,
            )
            all_bookings.append(booking)

        self.stdout.write(self.style.SUCCESS(f'  ✓ BookingPackages: {len(all_packages)}'))
        self.stdout.write(self.style.SUCCESS(f'  ✓ Bookings: {len(all_bookings)}'))
        return all_bookings, all_packages

    def _seed_booking_slots(self, bookings):
        count = 0
        for booking in bookings:
            hour = random.choice([7, 8, 9, 14, 15, 17, 18, 19])
            duration = random.choice([1, 2])
            price = booking.total_amount / duration
            for d in range(duration):
                BookingSlot.objects.create(
                    booking=booking,
                    start_time=time(hour + d, 0),
                    end_time=time(hour + d + 1, 0),
                    price=price,
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ BookingSlots: {count}'))

    def _seed_slot_locks(self, fields, users, bookings):
        conflict_bookings = [b for b in bookings if b.note and 'conflict' in str(b.note)]
        customer_users = [u['user'] for u in users.values() if u['role'] == 'CUSTOMER']
        count = 0
        for b in conflict_bookings[:5]:
            SlotLock.objects.create(
                field=b.field,
                booking_date=b.booking_date,
                start_time=time(18, 0),
                end_time=time(20, 0),
                user=customer_users[count % len(customer_users)],
                status='ACTIVE' if count < 2 else 'EXPIRED',
                lock_session_id=str(uuid.uuid4()),
                expires_at=timezone.now() + timedelta(minutes=10 if count < 2 else -5),
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ SlotLocks: {count}'))

    def _seed_booking_promotions(self, bookings, promotions):
        count = 0
        paid_bookings = [b for b in bookings if b.status == 'PAID']
        for i, booking in enumerate(paid_bookings[:8]):
            promo = promotions[i % len(promotions)]
            if promo.discount_type == 'PERCENTAGE':
                disc = min(
                    booking.total_amount * promo.discount_value / 100,
                    promo.max_discount_amount or Decimal('999999'),
                )
            else:
                disc = promo.discount_value
            BookingPromotion.objects.get_or_create(
                booking=booking, promotion=promo,
                defaults={'discount_amount_applied': disc},
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ BookingPromotions: {count}'))

    def _seed_booking_services(self, bookings, service_items):
        count = 0
        for booking in bookings[:20]:
            n = random.randint(1, 3)
            items = random.sample(service_items[:10], min(n, len(service_items[:10])))
            for item in items:
                qty = random.randint(1, 5)
                BookingService.objects.create(
                    booking=booking,
                    service_item=item,
                    quantity=qty,
                    unit_price=item.price,
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ BookingServices: {count}'))

    # ──────────────── PAYMENTS ────────────────

    def _seed_payments(self, bookings):
        payments = []
        paid_bookings = [b for b in bookings if b.status == 'PAID']
        pending_bookings = [b for b in bookings if b.status == 'PENDING']
        cancelled_bookings = [b for b in bookings if b.status == 'CANCELLED']

        # PAID → DEPOSIT + FINAL
        for b in paid_bookings:
            deposit = Payment.objects.create(
                booking=b, method='VIETQR', payment_type='DEPOSIT',
                transaction_code=f'TXN-DEP-{uuid.uuid4().hex[:8].upper()}',
                amount=b.total_amount * Decimal('0.3'),
                status='COMPLETED',
                paid_at=timezone.now() - timedelta(days=random.randint(1, 14)),
            )
            payments.append(deposit)
            final = Payment.objects.create(
                booking=b, method='CASH', payment_type='FINAL',
                transaction_code=f'TXN-FIN-{uuid.uuid4().hex[:8].upper()}',
                amount=b.total_amount * Decimal('0.7'),
                status='COMPLETED',
                paid_at=timezone.now() - timedelta(hours=random.randint(1, 48)),
            )
            payments.append(final)

        # PENDING → DEPOSIT only
        for b in pending_bookings[:5]:
            dep = Payment.objects.create(
                booking=b, method='VIETQR', payment_type='DEPOSIT',
                transaction_code=f'TXN-DEP-{uuid.uuid4().hex[:8].upper()}',
                amount=b.total_amount * Decimal('0.3'),
                status='PENDING',
            )
            payments.append(dep)

        # CANCELLED → REFUND
        for b in cancelled_bookings[:5]:
            refund = Payment.objects.create(
                booking=b, method='VIETQR', payment_type='REFUND',
                transaction_code=f'TXN-REF-{uuid.uuid4().hex[:8].upper()}',
                amount=b.total_amount * Decimal('0.5'),
                status='COMPLETED',
                paid_at=timezone.now() - timedelta(days=random.randint(1, 7)),
            )
            payments.append(refund)

        self.stdout.write(self.style.SUCCESS(f'  ✓ Payments: {len(payments)}'))
        return payments

    def _seed_invoices(self, payments):
        completed = [p for p in payments if p.status == 'COMPLETED' and p.payment_type != 'REFUND']
        count = 0
        for i, p in enumerate(completed[:15]):
            Invoice.objects.create(
                payment=p,
                invoice_code=f'INV-{2025}{i+1:04d}',
                tax_amount=p.amount * Decimal('0.1'),
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ Invoices: {count}'))

    # ──────────────── WALLET TRANSACTIONS ────────────────

    def _seed_wallet_transactions(self, wallets, bookings):
        count = 0
        customer_wallets = {k: v for k, v in wallets.items() if 'customer' in k}
        wallet_list = list(customer_wallets.values())

        # Topups
        for w in wallet_list:
            for _ in range(2):
                amt = Decimal(random.choice([100, 200, 500])) * 1000
                WalletTransaction.objects.create(
                    wallet=w, transaction_type='CREDIT',
                    sub_total=amt, final_amount=amt,
                    reference_type='TOPUP', reference_id=str(uuid.uuid4()),
                    status='COMPLETED', description='Nạp tiền vào ví',
                )
                count += 1

        # Booking debits
        for b in bookings[:10]:
            w = wallet_list[count % len(wallet_list)]
            WalletTransaction.objects.create(
                wallet=w, transaction_type='DEBIT',
                sub_total=b.total_amount, final_amount=b.total_amount,
                reference_type='BOOKING', reference_id=str(b.id),
                status='COMPLETED', description=f'Thanh toán booking {b.field.name}',
            )
            count += 1

        self.stdout.write(self.style.SUCCESS(f'  ✓ WalletTransactions: {count}'))

    # ──────────────── REVIEWS ────────────────

    def _seed_reviews(self, users, venues, bookings):
        customer_users = [u['user'] for u in users.values() if u['role'] == 'CUSTOMER']
        venue_list = list(venues.values())
        comments = [
            'Sân rất đẹp, sạch sẽ!', 'Nhân viên phục vụ nhiệt tình.',
            'Giá hơi cao nhưng chất lượng tốt.', 'Mặt sân hơi trơn khi mưa.',
            'Tuyệt vời! Sẽ quay lại.', 'Đèn chiếu sáng tốt, đá tối rất ok.',
            'Phòng thay đồ cần cải thiện.', 'Vị trí thuận tiện, dễ tìm.',
            'Nước uống miễn phí là điểm cộng.', 'Sân hơi nhỏ so với quảng cáo.',
            'Đặt sân online rất tiện.', 'Giá cuối tuần hơi cao.',
            'Chất lượng sân tốt, đáng tiền.', 'Thời gian chờ hơi lâu.',
            'Không gian thoáng mát, thoải mái.',
        ]
        paid_bookings = [b for b in bookings if b.status == 'PAID']
        count = 0
        for i in range(15):
            user = customer_users[i % len(customer_users)]
            venue = venue_list[i % len(venue_list)]
            booking = paid_bookings[i] if i < len(paid_bookings) else None
            Review.objects.create(
                user=user, venue=venue, booking=booking,
                rating=random.randint(3, 5),
                comment=comments[i],
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ Reviews: {count}'))

    # ──────────────── CHAT ────────────────

    def _seed_chat(self, users, venues):
        customer_users = [u['user'] for u in users.values() if u['role'] == 'CUSTOMER']
        owner_users = {name: u['user'] for name, u in users.items() if u['role'] == 'OWNER'}
        venue_list = list(venues.values())

        rooms = []
        for i in range(5):
            customer = customer_users[i]
            venue = venue_list[i % len(venue_list)]
            room, _ = ChatRoom.objects.get_or_create(
                venue=venue, customer=customer,
            )
            rooms.append(room)

            ChatParticipant.objects.get_or_create(
                user=customer, room=room,
                defaults={'role_in_room': 'CUSTOMER'},
            )
            # Owner joins
            owner_user = venue.owner.user
            ChatParticipant.objects.get_or_create(
                user=owner_user, room=room,
                defaults={'role_in_room': 'OWNER'},
            )

        messages_data = [
            'Xin chào, tôi muốn hỏi về sân.',
            'Dạ chào bạn! Bạn cần tư vấn gì ạ?',
            'Sân 5 người còn trống tối nay không?',
            'Để mình kiểm tra nhé, bạn đợi chút.',
            'Tối nay 19h-21h còn Sân 5A nha bạn.',
            'Ok, mình đặt luôn nhé. Cảm ơn!',
        ]
        for room in rooms:
            parts = list(room.participants.all())
            if len(parts) < 2:
                continue
            last_msg = None
            for j, text in enumerate(messages_data):
                sender = parts[j % len(parts)].user
                msg = ChatMessage.objects.create(
                    room=room, sender=sender, message_text=text,
                )
                last_msg = msg
            if last_msg:
                room.last_message = last_msg
                room.save()

        self.stdout.write(self.style.SUCCESS(f'  ✓ ChatRooms: {len(rooms)}'))
        self.stdout.write(self.style.SUCCESS(f'  ✓ ChatMessages: {len(rooms) * len(messages_data)}'))

    # ──────────────── NOTIFICATIONS ────────────────

    def _seed_notifications(self, users):
        customer_users = [u['user'] for u in users.values() if u['role'] == 'CUSTOMER']
        notif_templates = [
            ('Đặt sân thành công', 'Bạn đã đặt sân thành công. Vui lòng thanh toán trước thời hạn.', 'INAPP'),
            ('Thanh toán thành công', 'Thanh toán đã được xác nhận. Chúc bạn có trận đấu vui vẻ!', 'EMAIL'),
            ('Nhắc nhở', 'Bạn có lịch đặt sân vào ngày mai. Đừng quên nhé!', 'PUSH'),
            ('Khuyến mãi mới', 'Mã WELCOME10 giảm 10% cho lần đặt đầu tiên!', 'INAPP'),
        ]
        count = 0
        for user in customer_users:
            for title, content, ntype in notif_templates:
                Notification.objects.create(
                    user=user, title=title, content=content,
                    type=ntype, is_read=random.choice([True, False]),
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ Notifications: {count}'))

    # ──────────────── FAVORITES ────────────────

    def _seed_favorites(self, users, venues):
        customer_users = [u['user'] for u in users.values() if u['role'] == 'CUSTOMER']
        venue_list = list(venues.values())
        count = 0
        for user in customer_users[:6]:
            n = random.randint(1, len(venue_list))
            for venue in random.sample(venue_list, n):
                FavoriteVenue.objects.get_or_create(user=user, venue=venue)
                count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ FavoriteVenues: {count}'))

    # ──────────────── ANALYTICS ────────────────

    def _seed_daily_stats(self, venues):
        today = date.today()
        count = 0
        for venue in venues.values():
            for d in range(30):
                dt = today - timedelta(days=d)
                DailyVenueStats.objects.get_or_create(
                    venue=venue, date=dt,
                    defaults={
                        'revenue': Decimal(random.randint(500, 5000)) * 1000,
                        'booking_count': random.randint(3, 20),
                        'occupancy_rate': Decimal(str(round(random.uniform(30, 95), 2))),
                    },
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ DailyVenueStats: {count}'))

    # ──────────────── AUDIT & SYSTEM ────────────────

    def _seed_audit_logs(self, users):
        admin_users = [u['user'] for u in users.values() if u['role'] == 'ADMIN']
        actions = [
            ('CREATE', 'Venue', '1'), ('UPDATE', 'Venue', '1'),
            ('CREATE', 'Field', '1'), ('CREATE', 'Field', '2'),
            ('UPDATE', 'Promotion', '1'), ('CREATE', 'User', '10'),
            ('DELETE', 'BookingSlot', '5'), ('UPDATE', 'VenuePolicy', '1'),
            ('CREATE', 'Promotion', '3'), ('UPDATE', 'User', '5'),
        ]
        count = 0
        for action, target_type, target_id in actions:
            AuditLog.objects.create(
                user=admin_users[count % len(admin_users)],
                action=action,
                target_type=target_type,
                target_id=target_id,
                ip_address='127.0.0.1',
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f'  ✓ AuditLogs: {count}'))

    def _seed_system_events(self):
        events = [
            ('SYSTEM_START', '{"version": "1.0.0"}'),
            ('MIGRATION_COMPLETE', '{"migrations": 28}'),
            ('SEED_DATA_START', '{}'),
            ('CACHE_CLEARED', '{"scope": "all"}'),
            ('CELERY_WORKER_START', '{"worker": "default"}'),
        ]
        for etype, payload in events:
            SystemEvent.objects.create(event_type=etype, payload=payload)
        self.stdout.write(self.style.SUCCESS(f'  ✓ SystemEvents: {len(events)}'))

    # ──────────────── SUMMARY ────────────────

    def _print_summary(self):
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(self.style.SUCCESS('🎉 SEED DATA HOÀN TẤT!'))
        self.stdout.write('=' * 50)

        summary = [
            ('User', User.objects.filter(is_superuser=False).count()),
            ('Role', Role.objects.count()),
            ('UserRole', UserRole.objects.count()),
            ('OwnerProfile', OwnerProfile.objects.count()),
            ('CustomerProfile', CustomerProfile.objects.count()),
            ('Wallet', Wallet.objects.count()),
            ('WalletTransaction', WalletTransaction.objects.count()),
            ('Sport', Sport.objects.count()),
            ('FieldType', FieldType.objects.count()),
            ('Venue', Venue.objects.count()),
            ('Field', Field.objects.count()),
            ('FieldPriceRule', FieldPriceRule.objects.count()),
            ('VenuePolicy', VenuePolicy.objects.count()),
            ('BookingPackage', BookingPackage.objects.count()),
            ('Booking', Booking.objects.count()),
            ('BookingSlot', BookingSlot.objects.count()),
            ('SlotLock', SlotLock.objects.count()),
            ('Promotion', Promotion.objects.count()),
            ('BookingPromotion', BookingPromotion.objects.count()),
            ('ServiceItem', ServiceItem.objects.count()),
            ('BookingService', BookingService.objects.count()),
            ('Payment', Payment.objects.count()),
            ('Invoice', Invoice.objects.count()),
            ('Review', Review.objects.count()),
            ('ChatRoom', ChatRoom.objects.count()),
            ('ChatMessage', ChatMessage.objects.count()),
            ('Notification', Notification.objects.count()),
            ('VenueStaff', VenueStaff.objects.count()),
            ('StaffShift', StaffShift.objects.count()),
            ('DailyVenueStats', DailyVenueStats.objects.count()),
            ('AuditLog', AuditLog.objects.count()),
            ('SystemEvent', SystemEvent.objects.count()),
        ]

        total = 0
        for name, count in summary:
            self.stdout.write(f'  {name:.<30} {count:>5}')
            total += count
        self.stdout.write(f'\n  {"TỔNG":.<30} {total:>5}')
        self.stdout.write(f'\n  Mật khẩu mặc định: GSports@123')
        self.stdout.write('=' * 50 + '\n')
