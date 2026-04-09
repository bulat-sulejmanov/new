from django.contrib import admin

from .models import (
    Batch,
    Location,
    MaterialGroup,
    Object,
    PickTask,
    POItem,
    Product,
    ProductPrice,
    PurchaseOrder,
    Reservation,
    Stock,
    StockMove,
    Supplier,
    SupplyRequest,
    SupplyRequestItem,
)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'inn', 'kpp', 'ogrn', 'is_approved')
    search_fields = ('name', 'inn', 'kpp', 'ogrn')
    list_filter = ('is_approved',)


@admin.register(MaterialGroup)
class MaterialGroupAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'category')
    search_fields = ('code', 'name')
    list_filter = ('category',)


@admin.register(Object)
class ObjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'object_type', 'location', 'is_active')
    search_fields = ('code', 'name', 'location')
    list_filter = ('object_type', 'is_active')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'sku', 'name', 'unit', 'supplier', 'material_group',
        'abc_class', 'is_active', 'min_stock', 'reorder_point'
    )
    search_fields = ('sku', 'name', 'barcode', 'tnvd_code')
    list_filter = ('is_active', 'abc_class', 'unit', 'material_group', 'supplier')
    autocomplete_fields = ('supplier', 'material_group')


@admin.register(ProductPrice)
class ProductPriceAdmin(admin.ModelAdmin):
    list_display = ('product', 'supplier', 'price', 'currency', 'is_preferred', 'valid_from', 'valid_until')
    search_fields = ('product__sku', 'product__name', 'supplier__name')
    list_filter = ('currency', 'is_preferred', 'valid_from')
    autocomplete_fields = ('product', 'supplier', 'created_by')


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('product', 'lot_number', 'expiry_date', 'manufacture_date', 'cert_number')
    search_fields = ('product__sku', 'product__name', 'lot_number', 'serial_number', 'cert_number')
    list_filter = ('expiry_date',)
    autocomplete_fields = ('product',)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('code', 'area', 'capacity', 'storage_conditions')
    search_fields = ('code', 'description', 'storage_conditions')
    list_filter = ('area',)


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('product', 'location', 'batch', 'quantity')
    search_fields = ('product__sku', 'product__name', 'location__code', 'batch__lot_number')
    list_filter = ('location__area',)
    autocomplete_fields = ('product', 'location', 'batch')


@admin.register(StockMove)
class StockMoveAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'move_type', 'product', 'quantity', 'from_location', 'to_location', 'created_by')
    search_fields = ('product__sku', 'product__name', 'reference', 'batch__lot_number')
    list_filter = ('move_type', 'created_at')
    autocomplete_fields = ('product', 'from_location', 'to_location', 'batch', 'created_by')


class POItemInline(admin.TabularInline):
    model = POItem
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('number', 'supplier', 'status', 'expected_date', 'created_at')
    search_fields = ('number', 'supplier__name')
    list_filter = ('status', 'expected_date', 'created_at')
    autocomplete_fields = ('supplier',)
    inlines = [POItemInline]


@admin.register(POItem)
class POItemAdmin(admin.ModelAdmin):
    list_display = ('po', 'product', 'quantity', 'price')
    search_fields = ('po__number', 'product__sku', 'product__name')
    autocomplete_fields = ('po', 'product')


class SupplyRequestItemInline(admin.TabularInline):
    model = SupplyRequestItem
    extra = 0


@admin.register(SupplyRequest)
class SupplyRequestAdmin(admin.ModelAdmin):
    list_display = ('number', 'object', 'created_by', 'required_date', 'priority', 'status', 'created_at')
    search_fields = ('number', 'delivery_address', 'contact_person', 'created_by__username', 'object__code')
    list_filter = ('status', 'priority', 'required_date', 'created_at')
    autocomplete_fields = ('object', 'created_by')
    inlines = [SupplyRequestItemInline]


@admin.register(SupplyRequestItem)
class SupplyRequestItemAdmin(admin.ModelAdmin):
    list_display = ('request', 'product', 'quantity_requested', 'quantity_issued')
    search_fields = ('request__number', 'product__sku', 'product__name')
    autocomplete_fields = ('request', 'product')


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('product', 'object', 'supply_request', 'batch', 'quantity', 'planned_date', 'status', 'reserved_by')
    search_fields = (
        'product__sku', 'product__name', 'object__code',
        'supply_request__number', 'batch__lot_number', 'reserved_by__username'
    )
    list_filter = ('status', 'planned_date')
    autocomplete_fields = ('product', 'object', 'supply_request', 'batch', 'reserved_by')


@admin.register(PickTask)
class PickTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'supply_request', 'product', 'batch', 'quantity', 'from_location', 'to_location', 'is_done', 'assigned_to')
    search_fields = ('supply_request__number', 'product__sku', 'product__name', 'batch__lot_number')
    list_filter = ('is_done', 'created_at', 'completed_at')
    autocomplete_fields = ('supply_request', 'product', 'batch', 'from_location', 'to_location', 'assigned_to')