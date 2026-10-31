from django.contrib import admin

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'quantity', 'unit_price')
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer_name', 'customer_email', 'status', 'shipping_fee', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('id', 'customer_name', 'customer_email', 'customer_cpf')
    ordering = ('-created_at',)
    inlines = [OrderItemInline]