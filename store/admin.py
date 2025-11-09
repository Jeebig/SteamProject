from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Game,
    Developer,
    Genre,
    Screenshot,
    SupportTicket,
    CartItem,
    Order,
    OrderItem,
    Review,
    UserProfile,
    CurrencyRate,
    Notification,
    PriceSnapshot,
)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'price', 'original_price', 'discount_percent', 'currency', 'developer', 'supports_windows', 'supports_mac', 'supports_linux', 'created_at'
    )
    list_filter = (
        'supports_windows', 'supports_mac', 'supports_linux', 'genres', 'developer', 'currency'
    )
    search_fields = ('title', 'description', 'developer__name')
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ('genres',)

    def cover_preview(self, obj):
        if not obj or not getattr(obj, 'cover_image', None):
            return ''
        try:
            url = obj.cover_image.url
            return format_html('<img src="{}" style="width:120px;height:auto;object-fit:cover;border-radius:4px;"/>', url)
        except Exception:
            return ''
    cover_preview.short_description = 'Cover'


@admin.register(Developer)
class DeveloperAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Screenshot)
class ScreenshotAdmin(admin.ModelAdmin):
    list_display = ('game', 'caption', 'order')
    list_editable = ('order',)

@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'subject', 'category', 'email', 'user', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('subject', 'message', 'email', 'user__username', 'category', 'category_other')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'game', 'quantity', 'added_at')


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("game", "quantity", "price", "currency")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'total_price', 'currency', 'created_at')
    list_filter = ('status', 'currency')
    inlines = [OrderItemInline]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('user', 'game', 'rating', 'created_at')
    list_filter = ('rating',)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'preferred_language', 'preferred_currency')


@admin.register(CurrencyRate)
class CurrencyRateAdmin(admin.ModelAdmin):
    list_display = ('base', 'target', 'rate', 'fetched_at')
    list_filter = ('base', 'target')
    ordering = ('-fetched_at',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'kind', 'is_read', 'created_at', 'expires_at')
    list_filter = ('kind', 'is_read')
    search_fields = ('user__username',)


@admin.register(PriceSnapshot)
class PriceSnapshotAdmin(admin.ModelAdmin):
    list_display = ('game', 'price', 'currency', 'snapshot_date')
    list_filter = ('currency', 'snapshot_date')
    search_fields = ('game__title', 'game__slug')
