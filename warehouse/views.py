from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F, Q, Sum, Count, Prefetch, OuterRef, Subquery
from django.db import transaction, models
from django.db.models.functions import TruncDate, Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, DetailView
from django.contrib.auth.views import LoginView
from django.contrib.auth import login
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import csv
from django.http import HttpResponse
from django.db.models import OuterRef, Subquery
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, reverse


from .documents import (
    build_purchase_order_docx,
    build_purchase_order_filename,
    build_purchase_order_pdf,
)

from .utils import (
    annotate_product_availability,
    get_cheapest_supplier,
    get_critical_stock_alerts,
    get_product_price,
    optimize_reorder_suggestions,
)

from .forms import (
    LocationForm,
    PickTaskForm,
    POItemForm,
    ProductForm,
    PurchaseOrderForm,
    StockMoveForm,
    SupplierForm,
    SignUpForm,
    ObjectForm,
    MaterialGroupForm,
    SupplyRequestForm,
    SupplyRequestItemForm,
    ReservationForm,
    ProductFilterForm,
    SupplierFilterForm,
    LocationFilterForm,
    SupplyRequestFilterForm,
    PickTaskFilterForm,
)
from .models import (
    Area,
    Location,
    MoveType,
    PickTask,
    POItem,
    Product,
    PurchaseOrder,
    Stock,
    StockMove,
    Supplier,
    Object,
    MaterialGroup,
    SupplyRequest,
    SupplyRequestItem,
    Reservation,
    Batch,
    ProductPrice,
)

from django.views.decorators.cache import cache_page, never_cache


# ==================== PERMISSIONS ====================

ROLE_ADMIN = "Администратор"
ROLE_PROCUREMENT = "Снабженец"
ROLE_WAREHOUSE = "Кладовщик"


def user_in_any_role(user, role_names):
    if not user.is_authenticated:
        return False
    return user.groups.filter(name__in=role_names).exists()


def can_manage_procurement(user):
    return (
        user.is_authenticated
        and (
            user.is_superuser
            or user_in_any_role(user, [ROLE_ADMIN, ROLE_PROCUREMENT])
            or user.is_staff
        )
    )


def can_manage_warehouse(user):
    return (
        user.is_authenticated
        and (
            user.is_superuser
            or user_in_any_role(user, [ROLE_ADMIN, ROLE_WAREHOUSE])
            or user.is_staff
        )
    )


def has_staff_access(user):
    return can_manage_procurement(user) or can_manage_warehouse(user)

class StaffRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return has_staff_access(self.request.user)
    
    def handle_no_permission(self):
        messages.error(self.request, "Доступ запрещен. Требуются права администратора.")
        raise PermissionDenied("Доступ запрещен. Требуются права администратора.")


def can_user_print_supply_request(user, supply_request):
    if not user.is_authenticated:
        return False
    if has_staff_access(user) or user.is_superuser:
        return True
    early_statuses = {'DRAFT', 'APPROVED'}
    return supply_request.created_by == user and supply_request.status in early_statuses


def build_query_params_without_page(request):
    query_params = request.GET.copy()
    query_params.pop("page", None)
    encoded_query_params = query_params.urlencode()
    return f"&{encoded_query_params}" if encoded_query_params else ""


# ==================== AUTH ====================

class CustomLoginView(LoginView):
    template_name = 'warehouse/login.html'
    redirect_authenticated_user = True
    next_page = 'dashboard'

class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = 'warehouse/signup.html'
    
    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        messages.success(self.request, "Регистрация успешна! Добро пожаловать.")
        return redirect('dashboard')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Регистрация'
        return context


# ==================== DASHBOARD ====================

@login_required
@never_cache
def dashboard(request):
    """Дашборд для отдела снабжения - ОПТИМИЗИРОВАННЫЙ"""

    stats = {
        'total_products': Product.objects.filter(is_active=True).count(),
        'suppliers': Supplier.objects.count(),
        'locations': Location.objects.count(),
        'open_pos': PurchaseOrder.objects.exclude(status="RECEIVED").count(),
        'moves_today': StockMove.objects.filter(
            created_at__date=timezone.now().date()
        ).count(),
    }

    moves_query = StockMove.objects.select_related(
        "product", "from_location", "to_location", "created_by"
    )
    if not has_staff_access(request.user):
        moves_query = moves_query.filter(created_by=request.user)
    last_moves = moves_query.order_by("-created_at")[:10]

    low_stock = Stock.objects.select_related(
        "product", "location"
    ).filter(
        product__min_stock__gt=0,
        quantity__lt=F("product__min_stock")
    ).order_by('product__sku')[:10]

    group_stats = MaterialGroup.objects.annotate(
        products_count=Count('product', distinct=True),
        stock_sum=Sum('product__stock_levels__quantity', filter=Q(product__stock_levels__quantity__gt=0))
    ).filter(products_count__gt=0)

    open_requests_count = SupplyRequest.objects.exclude(
        status__in=['COMPLETED', 'CANCELLED']
    ).count()

    active_requests = SupplyRequest.objects.filter(
        status__in=['APPROVED', 'IN_WORK', 'PARTIAL']
    ).select_related('object', 'created_by').prefetch_related(
        Prefetch('items', queryset=SupplyRequestItem.objects.select_related('product'))
    ).order_by('required_date')[:5]

    expired_batches = Batch.objects.filter(
        expiry_date__lt=timezone.now().date(),
        stock__quantity__gt=0
    ).distinct().count()

    try:
        alerts = get_critical_stock_alerts()[:5]
    except Exception:
        alerts = []

    reorder_suggestions = []
    if can_manage_procurement(request.user):
        try:
            reorder_suggestions = optimize_reorder_suggestions()[:10]
        except Exception:
            pass

    status_labels = {
        PurchaseOrder.DRAFT: 'Черновики',
        PurchaseOrder.PLACED: 'Размещены',
        PurchaseOrder.RECEIVED: 'Получены',
        PurchaseOrder.CANCELLED: 'Отменены',
    }
    status_counts_raw = {
        row['status']: row['total']
        for row in PurchaseOrder.objects.values('status').annotate(total=Count('id'))
    }
    po_status_chart = {
        'labels': [status_labels[code] for code in status_labels],
        'values': [status_counts_raw.get(code, 0) for code in status_labels],
        'total': sum(status_counts_raw.values()),
    }

    days_back = 14
    today = timezone.localdate()
    start_day = today - timedelta(days=days_back - 1)
    move_labels = [(start_day + timedelta(days=i)).strftime('%d.%m') for i in range(days_back)]
    move_days = [start_day + timedelta(days=i) for i in range(days_back)]
    move_type_map = [
        (MoveType.RECEIPT, 'Приход'),
        (MoveType.PICK, 'Отбор'),
        (MoveType.SHIP, 'Отгрузка'),
    ]
    move_chart_rows = moves_query.filter(
        created_at__date__gte=start_day
    ).annotate(
        day=TruncDate('created_at')
    ).values('day', 'move_type').annotate(
        total_qty=Sum('quantity')
    )
    move_lookup = {
        (row['day'], row['move_type']): float(row['total_qty'] or 0)
        for row in move_chart_rows
    }
    move_activity_chart = {
        'labels': move_labels,
        'datasets': [
            {
                'label': label,
                'values': [move_lookup.get((day, move_type), 0) for day in move_days],
            }
            for move_type, label in move_type_map
        ],
    }

    zero_decimal = models.Value(0, output_field=models.DecimalField(max_digits=12, decimal_places=2))
    deficit_rows = Product.objects.filter(
        is_active=True,
        min_stock__gt=0,
    ).annotate(
        total_stock=Coalesce(Sum('stock_levels__quantity'), zero_decimal),
        deficit=F('min_stock') - Coalesce(Sum('stock_levels__quantity'), zero_decimal),
    ).filter(
        total_stock__lt=F('min_stock')
    ).order_by('-deficit', 'sku')[:8]
    low_stock_chart = {
        'labels': [item.sku for item in deficit_rows],
        'stock': [float(item.total_stock or 0) for item in deficit_rows],
        'minimum': [float(item.min_stock or 0) for item in deficit_rows],
        'names': [item.name for item in deficit_rows],
    }

    context = {
        **stats,
        'last_moves': last_moves,
        'low_stock': low_stock,
        'group_stats': group_stats,
        'open_requests': open_requests_count,
        'active_requests': active_requests,
        'expired_batches': expired_batches,
        'alerts': alerts,
        'reorder_suggestions': reorder_suggestions,
        'po_status_chart': po_status_chart,
        'move_activity_chart': move_activity_chart,
        'low_stock_chart': low_stock_chart,
    }

    return render(request, 'warehouse/dashboard.html', context)

# ==================== OBJECTS ====================

class ObjectList(LoginRequiredMixin, ListView):
    model = Object
    paginate_by = 20
    template_name = "warehouse/object_list.html"
    context_object_name = "objects"

class ObjectCreate(StaffRequiredMixin, CreateView):
    model = Object
    form_class = ObjectForm
    success_url = reverse_lazy("object_list")
    template_name = "warehouse/object_form.html"

class ObjectUpdate(StaffRequiredMixin, UpdateView):
    model = Object
    form_class = ObjectForm
    success_url = reverse_lazy("object_list")
    template_name = "warehouse/object_form.html"

class ObjectDelete(StaffRequiredMixin, DeleteView):
    model = Object
    success_url = reverse_lazy("object_list")
    template_name = "warehouse/confirm_delete.html"


# ==================== MATERIAL GROUPS ====================

class MaterialGroupList(LoginRequiredMixin, ListView):
    model = MaterialGroup
    template_name = "warehouse/materialgroup_list.html"
    context_object_name = "material_groups"
    ordering = ["code"]

class MaterialGroupCreate(StaffRequiredMixin, CreateView):
    model = MaterialGroup
    form_class = MaterialGroupForm
    success_url = reverse_lazy("materialgroup_list")
    template_name = "warehouse/materialgroup_form.html"

class MaterialGroupUpdate(StaffRequiredMixin, UpdateView):
    model = MaterialGroup
    form_class = MaterialGroupForm
    success_url = reverse_lazy("materialgroup_list")
    template_name = "warehouse/materialgroup_form.html"


# ==================== SUPPLIERS ====================

class SupplierList(LoginRequiredMixin, ListView):
    model = Supplier
    paginate_by = 20
    template_name = "warehouse/supplier_list.html"
    context_object_name = "suppliers"

    def get_queryset(self):
        queryset = Supplier.objects.all()

        search_query = (self.request.GET.get('q') or '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query)
                | Q(inn__icontains=search_query)
                | Q(kpp__icontains=search_query)
                | Q(ogrn__icontains=search_query)
                | Q(email__icontains=search_query)
                | Q(phone__icontains=search_query)
                | Q(contact_person__icontains=search_query)
            )

        approval_filter = (self.request.GET.get('is_approved') or '').strip()
        if approval_filter == '1':
            queryset = queryset.filter(is_approved=True)
        elif approval_filter == '0':
            queryset = queryset.filter(is_approved=False)

        return queryset.order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = SupplierFilterForm(self.request.GET or None)
        context['query_params'] = build_query_params_without_page(self.request)
        return context

class SupplierCreate(StaffRequiredMixin, CreateView):
    model = Supplier
    form_class = SupplierForm
    success_url = reverse_lazy("supplier_list")
    template_name = "warehouse/supplier_form.html"

class SupplierUpdate(StaffRequiredMixin, UpdateView):
    model = Supplier
    form_class = SupplierForm
    success_url = reverse_lazy("supplier_list")
    template_name = "warehouse/supplier_form.html"

class SupplierDelete(StaffRequiredMixin, DeleteView):
    model = Supplier
    success_url = reverse_lazy("supplier_list")
    template_name = "warehouse/confirm_delete.html"


# ==================== PRODUCTS ====================

class ProductList(LoginRequiredMixin, ListView):
    model = Product
    paginate_by = 20
    template_name = "warehouse/product_list.html"
    context_object_name = "products"
    
    def get_queryset(self):
        # Подзапрос для получения текущей цены
        latest_price_subquery = ProductPrice.objects.filter(
            product=OuterRef('pk'),
            valid_from__lte=timezone.now().date()
        ).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.now().date())
        ).order_by('-is_preferred', '-valid_from').values('price')[:1]
        
        # Подзапрос для поставщика цены
        price_supplier_subquery = ProductPrice.objects.filter(
            product=OuterRef('pk'),
            valid_from__lte=timezone.now().date()
        ).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.now().date())
        ).order_by('-is_preferred', '-valid_from').values('supplier__name')[:1]
        
        queryset = Product.objects.select_related('supplier', 'material_group').prefetch_related(
            'stock_levels__location'
        ).annotate(
            total_quantity=Sum('stock_levels__quantity', filter=Q(stock_levels__quantity__gt=0)),
            current_price=Subquery(latest_price_subquery),
            price_supplier=Subquery(price_supplier_subquery)
        )
        
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(
                Q(sku__icontains=q) | 
                Q(name__icontains=q) | 
                Q(barcode__icontains=q)
            )
        
        supplier = self.request.GET.get('supplier')
        if supplier:
            queryset = queryset.filter(supplier_id=supplier)
        
        abc_class = self.request.GET.get('abc_class')
        if abc_class:
            queryset = queryset.filter(abc_class=abc_class)
        
        is_active = self.request.GET.get('is_active')
        if is_active == '1':
            queryset = queryset.filter(is_active=True)
        elif is_active == '0':
            queryset = queryset.filter(is_active=False)
        
        if self.request.GET.get('has_stock'):
            queryset = queryset.filter(total_quantity__gt=0)
        
        return queryset.order_by('sku')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = ProductFilterForm(self.request.GET or None)
        context['query_params'] = '&' + self.request.GET.urlencode() if self.request.GET else ''
        # Добавляем всех поставщиков для модального окна
        context['all_suppliers'] = Supplier.objects.filter(is_approved=True).order_by('name')
        return context


@login_required
@transaction.atomic
def product_set_price(request):
    """Быстрая установка цены товара из списка"""
    if not can_manage_procurement(request.user):
        messages.error(request, "Нет прав для установки цен.")
        return redirect('product_list')
    
    if request.method != 'POST':
        return redirect('product_list')
    
    product_id = request.POST.get('product_id')
    price_value = request.POST.get('price')
    supplier_id = request.POST.get('price_supplier')
    is_preferred = request.POST.get('is_preferred') == '1'
    
    if not product_id or not price_value:
        messages.error(request, "Укажите товар и цену.")
        return redirect('product_list')
    
    try:
        product = Product.objects.get(pk=product_id)
        price_decimal = Decimal(price_value)
        
        # Определяем поставщика
        if supplier_id:
            supplier = Supplier.objects.get(pk=supplier_id)
        elif product.supplier:
            supplier = product.supplier
        else:
            messages.error(request, "Укажите поставщика для цены.")
            return redirect('product_list')
        
        # Если нужно сделать предпочтительной — сбрасываем другие
        if is_preferred:
            ProductPrice.objects.filter(product=product, is_preferred=True).update(is_preferred=False)
        
        # Создаём новую цену
        ProductPrice.objects.create(
            product=product,
            supplier=supplier,
            price=price_decimal,
            currency='RUB',
            is_preferred=is_preferred,
            valid_from=timezone.now().date(),
            notes=f'Установлено из списка товаров ({request.user.username})'
        )
        
        messages.success(
            request, 
            f"✅ Цена для {product.sku} установлена: {price_decimal} ₽"
        )
        
    except Product.DoesNotExist:
        messages.error(request, "Товар не найден.")
    except Supplier.DoesNotExist:
        messages.error(request, "Поставщик не найден.")
    except Exception as e:
        messages.error(request, f"Ошибка: {str(e)}")
    
    return redirect('product_list')

class ProductCreate(StaffRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    success_url = reverse_lazy("product_list")
    template_name = "warehouse/product_form.html"

class ProductUpdate(StaffRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    success_url = reverse_lazy("product_list")
    template_name = "warehouse/product_form.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self.get_object()
        
        # Текущая цена
        context['current_price'] = ProductPrice.objects.filter(
            product=product,
            valid_from__lte=timezone.now().date()
        ).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.now().date())
        ).order_by('-is_preferred', '-valid_from').first()
        
        # История цен (последние 5)
        context['price_history'] = ProductPrice.objects.filter(
            product=product
        ).select_related('supplier').order_by('-valid_from')[:5]
        
        # Все поставщики для выбора
        context['all_suppliers'] = Supplier.objects.filter(is_approved=True).order_by('name')
        
        return context
    
    def form_valid(self, form):
        response = super().form_valid(form)
        
        # Обработка новой цены
        new_price = self.request.POST.get('new_price')
        if new_price:
            try:
                price_decimal = Decimal(new_price)
                supplier_id = self.request.POST.get('price_supplier')
                is_preferred = self.request.POST.get('is_preferred_price') == '1'
                
                # Определяем поставщика
                if supplier_id:
                    supplier = Supplier.objects.get(pk=supplier_id)
                elif self.object.supplier:
                    supplier = self.object.supplier
                else:
                    messages.warning(self.request, "Цена не сохранена: укажите поставщика")
                    return response
                
                # Если нужно сделать предпочтительной — сбрасываем другие
                if is_preferred:
                    ProductPrice.objects.filter(
                        product=self.object, 
                        is_preferred=True
                    ).update(is_preferred=False)
                
                # Создаём новую цену
                ProductPrice.objects.create(
                    product=self.object,
                    supplier=supplier,
                    price=price_decimal,
                    currency='RUB',
                    is_preferred=is_preferred,
                    valid_from=timezone.now().date(),
                    notes=f'Обновлено через редактирование товара ({self.request.user.username})'
                )
                
                messages.success(
                    self.request, 
                    f"Цена обновлена: {price_decimal} ₽"
                )
                
            except Supplier.DoesNotExist:
                messages.warning(self.request, "Указанный поставщик не найден")
            except Exception as e:
                messages.error(self.request, f"Ошибка сохранения цены: {str(e)}")
        
        return response

class ProductDelete(StaffRequiredMixin, DeleteView):
    model = Product
    success_url = reverse_lazy("product_list")
    template_name = "warehouse/confirm_delete.html"


# ==================== LOCATIONS (ТОЛЬКО ДЛЯ STAFF) ====================

class LocationList(LoginRequiredMixin, ListView):
    model = Location
    paginate_by = 20
    template_name = "warehouse/location_list.html"
    context_object_name = "locations"

    def get_queryset(self):
        queryset = Location.objects.annotate(
            total_quantity=Coalesce(
                Sum('stock_levels__quantity', filter=Q(stock_levels__quantity__gt=0)),
                models.Value(Decimal('0'), output_field=models.DecimalField(max_digits=12, decimal_places=2)),
            )
        )

        search_query = (self.request.GET.get('q') or '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(code__icontains=search_query)
                | Q(description__icontains=search_query)
                | Q(storage_conditions__icontains=search_query)
            )

        area_filter = (self.request.GET.get('area') or '').strip()
        if area_filter:
            queryset = queryset.filter(area=area_filter)

        if self.request.GET.get('has_stock'):
            queryset = queryset.filter(total_quantity__gt=0)

        return queryset.order_by('code')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = LocationFilterForm(self.request.GET or None)
        context['query_params'] = build_query_params_without_page(self.request)
        return context

class LocationCreate(StaffRequiredMixin, CreateView):
    model = Location
    form_class = LocationForm
    success_url = reverse_lazy("location_list")
    template_name = "warehouse/location_form.html"

class LocationUpdate(StaffRequiredMixin, UpdateView):
    model = Location
    form_class = LocationForm
    success_url = reverse_lazy("location_list")
    template_name = "warehouse/location_form.html"

class LocationDelete(StaffRequiredMixin, DeleteView):
    model = Location
    success_url = reverse_lazy("location_list")
    template_name = "warehouse/confirm_delete.html"


# ==================== STOCK (ТОЛЬКО ДЛЯ STAFF) ====================

class StockList(StaffRequiredMixin, ListView):
    model = Stock
    paginate_by = 50
    template_name = "warehouse/stock_list.html"
    context_object_name = "stock_items"

    def get_queryset(self):
        total_stock_subquery = Stock.objects.filter(
            product=OuterRef('product')
        ).values('product').annotate(
            total=Sum('quantity')
        ).values('total')[:1]

        queryset = Stock.objects.select_related(
            "product", "location", "batch"
        ).annotate(
            total_stock=Subquery(total_stock_subquery)
        ).order_by("product__sku", "location__code")

        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(product__sku__icontains=search)
                | Q(product__name__icontains=search)
                | Q(location__code__icontains=search)
                | Q(batch__lot_number__icontains=search)
            )

        status_filter = self.request.GET.get('status_filter')
        if status_filter == 'critical':
            queryset = queryset.filter(
                total_stock__lt=F('product__min_stock'),
                product__min_stock__gt=0
            )
        elif status_filter == 'low_location':
            queryset = queryset.filter(
                quantity__lt=F('product__min_stock'),
                product__min_stock__gt=0
            ).exclude(
                total_stock__lt=F('product__min_stock')
            )
        elif status_filter == 'ok':
            queryset = queryset.filter(quantity__gt=0).exclude(
                total_stock__lt=F('product__min_stock')
            ).exclude(
                quantity__lt=F('product__min_stock'),
                product__min_stock__gt=0,
            )

        return queryset

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get('export') == 'csv':
            return self.export_csv(context['stock_items'])
        return super().render_to_response(context, **response_kwargs)

    def export_csv(self, queryset):
        """Экспорт остатков в CSV с учётом фильтров"""
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="stock_export.csv"'
        response.write('\ufeff')
        
        writer = csv.writer(response, delimiter=';', lineterminator='\r\n')
        
        writer.writerow([
            'Артикул', 'Наименование', 'Ед.изм.', 
            'Локация', 'Зона', 'Партия',
            'Количество', 'Всего на складе', 
            'Мин.запас', 'Статус'
        ])
        
        for item in queryset:
            if item.total_stock < item.product.min_stock and item.product.min_stock > 0:
                status = 'КРИТИЧЕСКИ'
            elif item.quantity < item.product.min_stock and item.total_stock >= item.product.min_stock:
                status = 'Мало в ячейке'
            elif item.quantity == 0:
                status = 'Пусто'
            else:
                status = 'В наличии'
            
            writer.writerow([
                item.product.sku,
                item.product.name,
                item.product.get_unit_display(),
                item.location.code,
                item.location.get_area_display(),
                item.batch.lot_number if item.batch else '-',
                item.quantity,
                item.total_stock,
                item.product.min_stock,
                status
            ])
        
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        area_field = Location._meta.get_field("area")
        context["areas"] = area_field.choices
        context["current_filters"] = {
            'search': self.request.GET.get('search', ''),
            'status': self.request.GET.get('status_filter', '')
        }
        return context


class StockMoveList(LoginRequiredMixin, ListView):
    model = StockMove
    paginate_by = 20
    template_name = "warehouse/stockmove_list.html"
    context_object_name = "moves"
    
    def get_queryset(self):
        queryset = StockMove.objects.select_related(
            "product", "from_location", "to_location", "created_by", "batch"
        )
        if not has_staff_access(self.request.user):
            queryset = queryset.filter(created_by=self.request.user)
        
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(
                Q(product__sku__icontains=q) | 
                Q(product__name__icontains=q) |
                Q(reference__icontains=q)
            )
        
        move_type = self.request.GET.get('move_type')
        if move_type:
            queryset = queryset.filter(move_type=move_type)
        
        from_loc = self.request.GET.get('from_location')
        if from_loc:
            queryset = queryset.filter(from_location_id=from_loc)
        
        to_loc = self.request.GET.get('to_location')
        if to_loc:
            queryset = queryset.filter(to_location_id=to_loc)
        
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .models import Location
        
        context['locations'] = Location.objects.all().order_by('code')
        
        params = self.request.GET.copy()
        if 'page' in params:
            del params['page']
        context['query_params'] = '&' + params.urlencode() if params else ''
        
        return context


@login_required
def stockmove_create(request):
    if not can_manage_warehouse(request.user):
        messages.error(request, "У вас нет прав для создания движений.")
        return redirect("dashboard")
    
    initial_data = {}
    if request.method == "GET":
        product_id = request.GET.get('product')
        from_loc_id = request.GET.get('from_location')
        to_loc_id = request.GET.get('to_location')
        
        if product_id:
            initial_data['product'] = product_id
        if from_loc_id:
            initial_data['from_location'] = from_loc_id
        if to_loc_id:
            initial_data['to_location'] = to_loc_id
        
        if from_loc_id and not to_loc_id:
            initial_data['move_type'] = 'SHIP'
        elif to_loc_id and not from_loc_id:
            initial_data['move_type'] = 'RECEIPT'
        elif from_loc_id and to_loc_id:
            initial_data['move_type'] = 'TRANSFER'
    
    if request.method == "POST":
        form = StockMoveForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    move = form.save(commit=False)
                    move.created_by = request.user
                    move.batch = None
                    move.save()
                    move.apply()
                messages.success(request, "Движение применено.")
                return redirect("stockmove_list")
            except ValidationError as e:
                messages.error(request, str(e))
                return render(request, "warehouse/stockmove_form.html", {"form": form})
    else:
        form = StockMoveForm(initial=initial_data)
    
    context = {"form": form}
    if initial_data.get('product'):
        try:
            product = Product.objects.get(pk=initial_data['product'])
            context['preselected_product'] = product
        except Product.DoesNotExist:
            pass
    if initial_data.get('from_location'):
        try:
            location = Location.objects.get(pk=initial_data['from_location'])
            context['preselected_location'] = location
        except Location.DoesNotExist:
            pass
            
    return render(request, "warehouse/stockmove_form.html", context)


# ==================== PURCHASE ORDERS (ТОЛЬКО ДЛЯ STAFF) ====================

PO_SORT_CHOICES = [
    ("status", "По статусу"),
    ("created_desc", "Сначала новые"),
    ("created_asc", "Сначала старые"),
    ("expected_date", "По ожидаемой дате"),
]


def get_purchase_orders_browser_context(request):
    status_filter = (request.GET.get("order_status") or "").strip()
    supplier_filter = (request.GET.get("order_supplier") or "").strip()
    search_query = (request.GET.get("order_q") or "").strip()
    sort_by = (request.GET.get("order_sort") or "status").strip()

    allowed_statuses = {code for code, _ in PurchaseOrder.STATUSES}
    if status_filter not in allowed_statuses:
        status_filter = ""

    supplier_queryset = Supplier.objects.filter(
        id__in=PurchaseOrder.objects.values_list("supplier_id", flat=True).distinct()
    ).order_by("name")
    supplier_ids = {str(supplier.id) for supplier in supplier_queryset}
    if supplier_filter not in supplier_ids:
        supplier_filter = ""

    allowed_sorts = {code for code, _ in PO_SORT_CHOICES}
    if sort_by not in allowed_sorts:
        sort_by = "status"

    queryset = PurchaseOrder.objects.select_related("supplier").annotate(
        status_rank=models.Case(
            models.When(status=PurchaseOrder.RECEIVED, then=models.Value(0)),
            models.When(status=PurchaseOrder.DRAFT, then=models.Value(1)),
            models.When(status=PurchaseOrder.PLACED, then=models.Value(2)),
            models.When(status=PurchaseOrder.CANCELLED, then=models.Value(3)),
            default=models.Value(99),
            output_field=models.IntegerField(),
        ),
        expected_date_rank=models.Case(
            models.When(expected_date__isnull=True, then=models.Value(1)),
            default=models.Value(0),
            output_field=models.IntegerField(),
        ),
    )

    if search_query:
        queryset = queryset.filter(
            Q(number__icontains=search_query)
            | Q(supplier__name__icontains=search_query)
            | Q(notes__icontains=search_query)
        )

    if status_filter:
        queryset = queryset.filter(status=status_filter)

    if supplier_filter:
        queryset = queryset.filter(supplier_id=supplier_filter)

    if sort_by == "created_asc":
        queryset = queryset.order_by("created_at", "id")
    elif sort_by == "created_desc":
        queryset = queryset.order_by("-created_at", "-id")
    elif sort_by == "expected_date":
        queryset = queryset.order_by("expected_date_rank", "expected_date", "status_rank", "-created_at", "-id")
    else:
        queryset = queryset.order_by("status_rank", "-created_at", "-id")
        sort_by = "status"

    return queryset, {
        "po_status_choices": PurchaseOrder.STATUSES,
        "po_supplier_choices": supplier_queryset,
        "po_sort_choices": PO_SORT_CHOICES,
        "po_status_filter": status_filter,
        "po_supplier_filter": supplier_filter,
        "po_search_query": search_query,
        "po_sort": sort_by,
    }


class POList(LoginRequiredMixin, ListView):
    model = PurchaseOrder
    paginate_by = 20
    template_name = "warehouse/po_list.html"
    context_object_name = "purchase_orders"

    def get_queryset(self):
        queryset, browser_context = get_purchase_orders_browser_context(self.request)
        self.browser_context = browser_context
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(getattr(self, "browser_context", {}))
        context["query_params"] = build_query_params_without_page(self.request)
        return context

@login_required
def po_create(request):
    if not can_manage_procurement(request.user):
        messages.error(request, "У вас нет прав для создания заказов.")
        return redirect("dashboard")
    
    preselected_product = None
    initial_data = {}
    auto_quantity = 1
    auto_price = None
    suggested_items = []
    default_supplier = None  # Для группового режима
    
    if request.method == "GET":
        product_id = request.GET.get('product')
        
        if product_id:
            try:
                preselected_product = Product.objects.select_related('supplier').get(pk=product_id)
                
                # Поставщик
                if preselected_product.supplier:
                    initial_data['supplier'] = preselected_product.supplier.pk
                    auto_price = get_product_price(preselected_product, preselected_product.supplier)
                else:
                    cheapest_sup, cheapest_price = get_cheapest_supplier(preselected_product)
                    if cheapest_sup:
                        initial_data['supplier'] = cheapest_sup.pk
                        auto_price = cheapest_price
                        messages.info(request, f"Поставщик автоподобран: {cheapest_sup.name}")
                
                if auto_price:
                    initial_data['auto_price'] = auto_price
                
                # ДАТА — сохраняем в initial_data в ISO формате
                lead_days = preselected_product.lead_time_days or 7
                expected_date = timezone.now().date() + timedelta(days=lead_days)
                initial_data['expected_date'] = expected_date.strftime('%Y-%m-%d')  # ISO формат
                
                # Номер
                current_year = timezone.now().year
                prefix = f"ЗС-{current_year}"
                last_po = PurchaseOrder.objects.filter(
                    number__startswith=f"{prefix}-"
                ).order_by('-number').first()
                
                new_num = 1
                if last_po:
                    try:
                        new_num = int(last_po.number.split('-')[-1]) + 1
                    except:
                        pass
                initial_data['number'] = f"{prefix}-{new_num:03d}"
                
                # Количество
                current_stock = preselected_product.stock_levels.aggregate(
                    total=Sum('quantity')
                )['total'] or 0
                reserved = preselected_product.reservations.filter(
                    status='ACTIVE'
                ).aggregate(total=Sum('quantity'))['total'] or 0
                available = current_stock - reserved
                
                max_stock = preselected_product.max_stock or 0
                reorder_point = preselected_product.reorder_point or 0
                
                if max_stock > 0:
                    deficit = max_stock - available
                    auto_quantity = max(deficit, reorder_point * 2)
                else:
                    auto_quantity = reorder_point * 2 if reorder_point > 0 else 10
                
                if auto_quantity <= 0:
                    auto_quantity = 1
                
                suggested_items.append({
                    'product': preselected_product,
                    'quantity': auto_quantity,
                    'price': auto_price,
                    'sum': (auto_price * auto_quantity) if auto_price else None,
                    'reason': f'До макс. запаса' if max_stock > 0 else 'Точка заказа x2'
                })
                    
            except Product.DoesNotExist:
                pass
        
        # Групповой режим — ИСПРАВЛЕННЫЙ
        elif request.GET.get('mode') == 'reorder_all':
            suggestions = optimize_reorder_suggestions()[:20]
            
            if suggestions:
                current_year = timezone.now().year
                prefix = f"ЗС-{current_year}"
                last_po = PurchaseOrder.objects.filter(
                    number__startswith=f"{prefix}-"
                ).order_by('-number').first()
                new_num = 1
                if last_po:
                    try:
                        new_num = int(last_po.number.split('-')[-1]) + 1
                    except:
                        pass
                initial_data['number'] = f"{prefix}-{new_num:03d}"
                
                # ДАТА — максимальный срок поставки в ISO формате
                max_lead_time = max(s['product'].lead_time_days or 7 for s in suggestions)
                expected_date = timezone.now().date() + timedelta(days=max_lead_time)
                initial_data['expected_date'] = expected_date.strftime('%Y-%m-%d')  # ISO формат
                
                # НОВОЕ: Определяем основного поставщика (у кого больше товаров)
                supplier_counter = {}
                for s in suggestions:
                    prod = s['product']
                    if prod.supplier:
                        supplier_counter[prod.supplier.id] = supplier_counter.get(prod.supplier.id, 0) + 1
                    else:
                        # Ищем поставщика с мин. ценой
                        cheapest_sup, _ = get_cheapest_supplier(prod)
                        if cheapest_sup:
                            supplier_counter[cheapest_sup.id] = supplier_counter.get(cheapest_sup.id, 0) + 1
                
                if supplier_counter:
                    # Выбираем поставщика с наибольшим количеством товаров
                    main_supplier_id = max(supplier_counter, key=supplier_counter.get)
                    try:
                        default_supplier = Supplier.objects.get(pk=main_supplier_id)
                        initial_data['supplier'] = main_supplier_id
                        messages.info(request, f"Основной поставщик для группового заказа: {default_supplier.name}")
                    except Supplier.DoesNotExist:
                        pass
                
                # Формируем список товаров с ценами
                for s in suggestions:
                    prod = s['product']
                    # Ищем цену от выбранного поставщика или любую актуальную
                    price = None
                    if default_supplier:
                        price = get_product_price(prod, default_supplier)
                    if not price:
                        price = get_product_price(prod)  # Любая предпочтительная цена
                    
                    qty = s['suggested_qty']
                    
                    suggested_items.append({
                        'product': prod,
                        'quantity': qty,
                        'price': price,
                        'sum': (price * qty) if price else None,
                        'reason': 'Критично' if s['urgency'] == 'HIGH' else 'До точки заказа',
                        'supplier': prod.supplier or get_cheapest_supplier(prod)[0]  # Для отображения
                    })
                
                messages.info(request, f"Автоподбор: {len(suggested_items)} товаров")
                if not default_supplier:
                    messages.warning(request, "Внимание: товары без поставщиков, цены не подтянуты!")
                messages.warning(request, "Проверьте цены вручную — товары могут быть от разных поставщиков!")
    
    if request.method == "POST":
        form = PurchaseOrderForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    po = form.save()
                    
                    added_count = 0
                    total_sum = Decimal('0')
                    
                    # Один товар
                    product_id = request.POST.get('auto_product_id')
                    auto_price_post = request.POST.get('auto_price')
                    
                    if product_id:
                        try:
                            product = Product.objects.get(pk=product_id)
                            quantity = float(request.POST.get('auto_quantity', 1))
                            
                            price = None
                            if auto_price_post:
                                try:
                                    price = Decimal(auto_price_post)
                                except:
                                    pass
                            
                            if not price:
                                price = get_product_price(product, po.supplier)
                            
                            POItem.objects.create(
                                po=po, 
                                product=product, 
                                quantity=max(1, quantity), 
                                price=price
                            )
                            added_count += 1
                            if price:
                                total_sum += price * Decimal(quantity)
                                
                        except (Product.DoesNotExist, ValueError):
                            pass
                    
                    # Множественные товары
                    multiple_products = request.POST.getlist('auto_product_ids')
                    multiple_quantities = request.POST.getlist('auto_quantities')
                    multiple_prices = request.POST.getlist('auto_prices')
                    
                    for pid, qty, prc in zip(multiple_products, multiple_quantities, multiple_prices):
                        try:
                            product = Product.objects.get(pk=pid)
                            quantity = float(qty)
                            
                            price = None
                            if prc:
                                try:
                                    price = Decimal(prc)
                                except:
                                    price = get_product_price(product, po.supplier)
                            else:
                                price = get_product_price(product, po.supplier)
                            
                            POItem.objects.create(
                                po=po,
                                product=product,
                                quantity=max(1, quantity),
                                price=price
                            )
                            added_count += 1
                            if price:
                                total_sum += price * Decimal(quantity)
                                
                        except (Product.DoesNotExist, ValueError, InvalidOperation):
                            continue

                    receipt_created = False
                    if po.status == PurchaseOrder.RECEIVED:
                        receipt_created = receive_purchase_order(po, request.user)
            except ValidationError as exc:
                error_text = '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)
                messages.error(request, error_text)
            else:
                if added_count > 0:
                    msg = f"✅ Заказ {po.number} создан. Позиций: {added_count}"
                    if total_sum > 0:
                        msg += f". Сумма: {total_sum:,.2f} ₽"
                    if receipt_created:
                        msg += ". Товар автоматически оприходован на склад."
                    messages.success(request, msg)
                else:
                    messages.success(request, f"Заказ {po.number} создан. Добавьте позиции.")
                    
                return redirect("po_edit", pk=po.pk)
    else:
        form = PurchaseOrderForm(initial=initial_data)
    
    context = {
        "form": form,
        "preselected_product": preselected_product,
        "auto_quantity": auto_quantity,
        "auto_price": auto_price,
        "suggested_items": suggested_items,
        "is_reorder_mode": len(suggested_items) > 1,
        "default_supplier": default_supplier,  # Для отображения в шаблоне
    }
    return render(request, "warehouse/po_form.html", context)


def receive_purchase_order(po, user):
    """Проводит автоприход товаров по заказу поставщику в зону хранения STOR."""
    if po.receipt_applied_at:
        return False

    if po.status != PurchaseOrder.RECEIVED:
        raise ValidationError("Автоприход доступен только для заказа в статусе 'Получен'.")

    items = list(po.items.select_related('product').all())
    if not items:
        raise ValidationError("Нельзя принять пустой заказ без позиций.")

    target_location = Location.objects.filter(area=Area.STORAGE).order_by('code').first()
    if not target_location:
        raise ValidationError(
            "Не найдена складская локация зоны 'Хранение' (STOR) для автоприхода."
        )

    receipt_reference = f"Приход по заказу {po.number}"
    now = timezone.now()
    today = now.date()

    for item in items:
        if item.quantity is None or item.quantity <= 0:
            raise ValidationError(
                f"Позиция {item.product.sku} имеет некорректное количество: {item.quantity}."
            )

        move = StockMove.objects.create(
            product=item.product,
            from_location=None,
            to_location=target_location,
            batch=None,
            quantity=item.quantity,
            move_type=MoveType.RECEIPT,
            reference=receipt_reference,
            created_by=user,
        )
        move.apply()

        if item.price and item.price > 0:
            price_obj, _ = ProductPrice.objects.update_or_create(
                product=item.product,
                supplier=po.supplier,
                price=item.price,
                defaults={
                    'valid_from': today,
                    'is_preferred': False,
                    'notes': f'Авто из заказа {po.number}',
                    'created_by': user,
                }
            )
            if not ProductPrice.objects.filter(
                product=item.product,
                is_preferred=True
            ).exists():
                price_obj.is_preferred = True
                price_obj.save(update_fields=['is_preferred'])

    po.received_at = now
    po.received_by = user
    po.receipt_applied_at = now
    po.save(update_fields=['received_at', 'received_by', 'receipt_applied_at'])
    return True


@login_required
def po_delete(request, pk):
    """Удаление заказа поставщику из карточки редактирования"""
    po = get_object_or_404(PurchaseOrder.objects.select_related('supplier'), pk=pk)

    if not can_manage_procurement(request.user):
        messages.error(request, "У вас нет прав для удаления заказов.")
        return redirect("po_list")

    if request.method != "POST":
        return redirect("po_edit", pk=po.pk)

    if po.status == PurchaseOrder.RECEIVED:
        messages.error(
            request,
            f"Заказ {po.number} уже получен. Для сохранности истории его нельзя удалить."
        )
        return redirect("po_edit", pk=po.pk)

    po_number = po.number
    items_count = po.items.count()
    po.delete()

    messages.success(
        request,
        f"Заказ {po_number} удалён. Удалено позиций: {items_count}."
    )
    return redirect("po_list")


@login_required
def po_export_docx(request, pk):
    po = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier").prefetch_related("items__product"),
        pk=pk,
    )

    if not can_manage_procurement(request.user):
        messages.error(request, "У вас нет прав для выгрузки заказов.")
        return redirect("po_list")

    try:
        content = build_purchase_order_docx(po, generated_by=request.user)
    except Exception as exc:
        messages.error(request, f"Не удалось сформировать Word-документ: {exc}")
        return redirect("po_edit", pk=po.pk)

    response = HttpResponse(
        content,
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{build_purchase_order_filename(po, "docx")}"'
    )
    return response


@login_required
def po_export_pdf(request, pk):
    po = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier").prefetch_related("items__product"),
        pk=pk,
    )

    if not can_manage_procurement(request.user):
        messages.error(request, "У вас нет прав для выгрузки заказов.")
        return redirect("po_list")

    try:
        content = build_purchase_order_pdf(po, generated_by=request.user)
    except Exception as exc:
        messages.error(request, f"Не удалось сформировать PDF: {exc}")
        return redirect("po_edit", pk=po.pk)

    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{build_purchase_order_filename(po, "pdf")}"'
    )
    return response



@login_required
def po_edit(request, pk):
    """Редактирование заказа поставщику с проверкой прав и автоподстановкой товара"""
    po = get_object_or_404(PurchaseOrder, pk=pk)
    
    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: проверка прав
    if not can_manage_procurement(request.user):
        messages.error(request, "У вас нет прав для редактирования заказов.")
        return redirect("po_list")
    
    # === НОВОЕ: Автоподстановка товара из GET-параметра ===
    preselected_product = None
    auto_quantity = 1
    auto_price = None
    
    if request.method == "GET":
        product_id = request.GET.get('product')
        if product_id:
            try:
                preselected_product = Product.objects.select_related('supplier').get(pk=product_id)
                
                # Рассчитываем рекомендуемое количество (как в po_create)
                current_stock = preselected_product.stock_levels.aggregate(
                    total=Sum('quantity')
                )['total'] or 0
                reserved = preselected_product.reservations.filter(
                    status='ACTIVE'
                ).aggregate(total=Sum('quantity'))['total'] or 0
                available = current_stock - reserved
                
                max_stock = preselected_product.max_stock or 0
                reorder_point = preselected_product.reorder_point or 0
                
                if max_stock > 0:
                    deficit = max_stock - available
                    auto_quantity = max(deficit, reorder_point * 2)
                else:
                    auto_quantity = reorder_point * 2 if reorder_point > 0 else 10
                
                if auto_quantity <= 0:
                    auto_quantity = 1
                
                # Получаем цену
                if preselected_product.supplier and po.supplier == preselected_product.supplier:
                    auto_price = get_product_price(preselected_product, preselected_product.supplier)
                else:
                    # Ищем цену от поставщика заказа или любую актуальную
                    auto_price = get_product_price(preselected_product, po.supplier)
                    if not auto_price:
                        auto_price = get_product_price(preselected_product)
                
                messages.info(
                    request, 
                    f"Автоподбор: {preselected_product.sku} — {auto_quantity} шт. "
                    f"(остаток: {available}, цена: {auto_price or 'не найдена'})"
                )
                
            except Product.DoesNotExist:
                messages.warning(request, "Указанный товар не найден")
    
    if request.method == "POST":
        form = PurchaseOrderForm(request.POST, instance=po)
        item_form = POItemForm(request.POST)

        if "save_po" in request.POST and form.is_valid():
            old_status = po.status
            po_obj = form.save(commit=False)

            if po.receipt_applied_at and po_obj.status != PurchaseOrder.RECEIVED:
                messages.error(
                    request,
                    f"Заказ {po.number} уже оприходован. Нельзя менять статус с 'Получен' на другой."
                )
                return redirect("po_edit", pk=po.pk)

            try:
                with transaction.atomic():
                    po_obj.save()
                    receipt_created = False
                    if (
                        old_status != PurchaseOrder.RECEIVED
                        and po_obj.status == PurchaseOrder.RECEIVED
                    ):
                        receipt_created = receive_purchase_order(po_obj, request.user)
            except ValidationError as exc:
                error_text = '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)
                messages.error(request, error_text)
            else:
                if receipt_created:
                    messages.success(
                        request,
                        f"Заказ обновлён. Товар автоматически оприходован на локацию хранения."
                    )
                else:
                    messages.success(request, "Заказ обновлён.")
                return redirect("po_list")
        elif "add_item" in request.POST and item_form.is_valid():
            item = item_form.save(commit=False)
            item.po = po
            item.save()
            messages.success(request, "Позиция добавлена.")
            return redirect("po_edit", pk=po.pk)
    else:
        form = PurchaseOrderForm(instance=po)
        # === НОВОЕ: Инициализация формы позиции с автоподстановкой ===
        if preselected_product:
            initial_data = {
                'product': preselected_product.pk,
                'quantity': auto_quantity,
            }
            if auto_price:
                initial_data['price'] = auto_price
            item_form = POItemForm(initial=initial_data)
        else:
            item_form = POItemForm()

    items = po.items.select_related("product").all()
    order_browser_queryset, order_browser_context = get_purchase_orders_browser_context(request)
    return render(
    request,
    "warehouse/po_edit.html",
    {
        "form": form,
        "item_form": item_form,
        "po": po,
        "items": items,
        "preselected_product": preselected_product,  # ← ДОЛЖНО БЫТЬ
        "auto_quantity": auto_quantity,              # ← ДОЛЖНО БЫТЬ
        "auto_price": auto_price,                    # ← ДОЛЖНО БЫТЬ
        "order_browser_orders": order_browser_queryset,
        **order_browser_context,
    },
)


# ==================== SUPPLY REQUESTS ====================

class SupplyRequestList(LoginRequiredMixin, ListView):
    model = SupplyRequest
    paginate_by = 20
    template_name = "warehouse/supplyrequest_list.html"
    context_object_name = "supply_requests"

    def get_queryset(self):
        queryset = SupplyRequest.objects.select_related(
            'object', 'created_by'
        ).prefetch_related('items__product')

        if not has_staff_access(self.request.user):
            queryset = queryset.filter(created_by=self.request.user)

        search_query = (self.request.GET.get('q') or '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(number__icontains=search_query)
                | Q(object__code__icontains=search_query)
                | Q(object__name__icontains=search_query)
                | Q(delivery_address__icontains=search_query)
                | Q(contact_person__icontains=search_query)
                | Q(contact_phone__icontains=search_query)
                | Q(notes__icontains=search_query)
                | Q(created_by__username__icontains=search_query)
                | Q(created_by__first_name__icontains=search_query)
                | Q(created_by__last_name__icontains=search_query)
            )

        object_filter = (self.request.GET.get('object') or '').strip()
        if object_filter:
            queryset = queryset.filter(object_id=object_filter)

        priority_filter = (self.request.GET.get('priority') or '').strip()
        if priority_filter:
            queryset = queryset.filter(priority=priority_filter)

        status_filter = (self.request.GET.get('status') or '').strip()
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by('-created_at', '-id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = SupplyRequestFilterForm(self.request.GET or None)
        context['query_params'] = build_query_params_without_page(self.request)
        return context


@login_required
def supply_request_create(request):
    if request.method == "POST":
        form = SupplyRequestForm(request.POST)
        if form.is_valid():
            # Дополнительная проверка перед сохранением
            req = form.save(commit=False)
            try:
                req.clean()  # Явно вызываем валидацию модели
            except ValidationError as e:
                # Переносим ошибки модели в форму
                for field, errors in e.message_dict.items():
                    for error in errors:
                        form.add_error(field, error)
                return render(request, "warehouse/supplyrequest_form.html", {"form": form})
            
            req.created_by = request.user
            req.status = 'DRAFT'
            req.save()
            messages.success(request, f"Заявка {req.number} создана. Добавьте товары.")
            return redirect("supplyrequest_detail", pk=req.pk)
    else:
        form = SupplyRequestForm()
    return render(request, "warehouse/supplyrequest_form.html", {"form": form})


class SupplyRequestDetail(LoginRequiredMixin, DetailView):
    model = SupplyRequest
    template_name = "warehouse/supplyrequest_detail.html"
    context_object_name = "supply_request"
    
    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        
        queryset = queryset.select_related('object', 'created_by').prefetch_related(
            'items__product',
            'pick_tasks__product',
            'pick_tasks__from_location',
            'pick_tasks__to_location',
            'pick_tasks__batch'
        )
        
        obj = super().get_object(queryset)
        if not has_staff_access(self.request.user) and obj.created_by != self.request.user:
            raise PermissionDenied("У вас нет доступа к этой заявке.")
        return obj
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['item_form'] = SupplyRequestItemForm()

        products = annotate_product_availability(
            Product.objects.filter(is_active=True).select_related('supplier', 'material_group')
        ).order_by('sku')

        context['available_products'] = products
        context['all_suppliers'] = Supplier.objects.filter(
            is_approved=True
        ).order_by('name')
        context['can_print'] = can_user_print_supply_request(self.request.user, self.object)

        items_qs = SupplyRequestItem.objects.filter(
            request=self.object
        ).select_related('product').prefetch_related(
            Prefetch(
                'product__stock_levels',
                queryset=Stock.objects.select_related('location', 'batch').filter(quantity__gt=0),
                to_attr='available_stock',
            )
        )
        context['items'] = items_qs

        items = list(items_qs)
        context['pick_tasks'] = self.object.pick_tasks.all()

        product_ids = [item.product_id for item in items]
        if product_ids:
            context['stock_by_location'] = Stock.objects.filter(
                product_id__in=product_ids,
                quantity__gt=0
            ).select_related('product', 'location', 'batch').order_by(
                'product__sku', 'location__code'
            )

            context['active_reservations'] = Reservation.objects.filter(
                supply_request=self.object,
                status='ACTIVE',
                product_id__in=product_ids
            ).select_related('product', 'batch')
        else:
            context['stock_by_location'] = Stock.objects.none()
            context['active_reservations'] = Reservation.objects.none()

        return context


@login_required
def supply_request_add_item(request, pk):
    supply_request = get_object_or_404(SupplyRequest, pk=pk)
    
    if request.user != supply_request.created_by and not has_staff_access(request.user):
        messages.error(request, "Нет доступа к этой заявке.")
        return redirect("supplyrequest_list")
    
    if supply_request.status not in ['DRAFT', 'APPROVED']:
        messages.error(request, "Нельзя добавлять позиции в заявку со статусом %s" % supply_request.get_status_display())
        return redirect("supplyrequest_detail", pk=pk)
    
    if request.method == "POST":
        form = SupplyRequestItemForm(request.POST)
        if form.is_valid():
            product = form.cleaned_data['product']
            quantity_requested = form.cleaned_data['quantity_requested']
            
            # === ИСПРАВЛЕНИЕ: проверяем, есть ли уже такой товар в заявке ===
            existing_item = SupplyRequestItem.objects.filter(
                request=supply_request,
                product=product
            ).first()
            
            if existing_item:
                # Увеличиваем количество в существующей позиции
                existing_item.quantity_requested += quantity_requested
                existing_item.save()
                messages.success(
                    request, 
                    f"Обновлено: {product.name} — теперь {existing_item.quantity_requested} {product.get_unit_display()} (добавлено +{quantity_requested})"
                )
            else:
                # Создаём новую позицию
                item = form.save(commit=False)
                item.request = supply_request
                item.save()
                messages.success(
                    request, 
                    f"Добавлено: {product.name} — {quantity_requested} {product.get_unit_display()}"
                )
            
            if supply_request.status == 'DRAFT':
                supply_request.status = 'APPROVED'
                supply_request.save(update_fields=['status'])
                messages.info(request, "Заявка отправлена на рассмотрение снабженцу.")
                
    return redirect("supplyrequest_detail", pk=pk)


def _auto_create_pick_tasks(request, supply_request, user):
    """Автосоздание задач на отбор с FEFO без дублей и перепланирования."""
    created_count = 0
    ship_location = Location.objects.filter(area='SHIP').first()

    for item in supply_request.items.select_related('product').all():
        product = item.product

        already_done = PickTask.objects.filter(
            supply_request=supply_request,
            product=product,
            is_done=True
        ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

        already_planned = PickTask.objects.filter(
            supply_request=supply_request,
            product=product,
            is_done=False
        ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

        remaining = (item.quantity_requested or Decimal('0')) - already_done - already_planned
        if remaining <= 0:
            continue

        # Резерв в модели Reservation считается только по зоне хранения (STOR),
        # поэтому и задачи на отбор для авторезерва строим только по этим остаткам.
        # Иначе можно выбрать остаток, например, из SHIP/PICK/RECV и получить ValidationError
        # при создании резерва: "на складе 0, запрошено N".
        stocks = Stock.objects.filter(
            product=product,
            location__area='STOR',
            quantity__gt=0
        ).select_related('location', 'batch').order_by('batch__expiry_date', '-quantity')

        for stock in stocks:
            if remaining <= 0:
                break

            qty = min(remaining, stock.quantity)
            if qty <= 0:
                continue

            exact_duplicate = PickTask.objects.filter(
                supply_request=supply_request,
                product=product,
                from_location=stock.location,
                batch=stock.batch,
                is_done=False
            ).exists()
            if exact_duplicate:
                continue

            PickTask.objects.create(
                supply_request=supply_request,
                product=product,
                from_location=stock.location,
                batch=stock.batch,
                quantity=qty,
                to_location=ship_location or stock.location,
                assigned_to=user,
            )
            created_count += 1

            if supply_request.object:
                reservation, created = Reservation.objects.get_or_create(
                    supply_request=supply_request,
                    product=product,
                    batch=stock.batch,
                    status='ACTIVE',
                    defaults={
                        'object': supply_request.object,
                        'quantity': qty,
                        'planned_date': supply_request.required_date,
                        'reserved_by': user,
                        'notes': (
                            f'Авторезерв по заявке {supply_request.number} '
                            f'(партия: {stock.batch.lot_number if stock.batch else "без партии"})'
                        ),
                    }
                )
                if not created and reservation.quantity != qty:
                    reservation.quantity = qty
                    reservation.object = supply_request.object
                    reservation.planned_date = supply_request.required_date
                    reservation.reserved_by = user
                    reservation.notes = (
                        f'Авторезерв по заявке {supply_request.number} '
                        f'(партия: {stock.batch.lot_number if stock.batch else "без партии"})'
                    )
                    reservation.save(update_fields=['quantity', 'object', 'planned_date', 'reserved_by', 'notes'])

            remaining -= qty

    if created_count > 0:
        messages.info(request, f"Автоматически создано {created_count} задач на отбор")
    else:
        messages.warning(
            request,
            "Новых задач на отбор не создано: товар уже распределен по задачам или отсутствует на складе"
        )


@login_required
@transaction.atomic
def supply_request_update_status(request, pk):
    """Обновление статуса с проверкой на пустую заявку"""
    if not can_manage_procurement(request.user):
        messages.error(request, "Только снабженец может менять статус.")
        return redirect("supplyrequest_detail", pk=pk)
    
    supply_request = get_object_or_404(SupplyRequest, pk=pk)
    
    if request.method == "POST":
        new_status = request.POST.get('status')
        
        # Проверка: нельзя утвердить пустую заявку
        if new_status in ['APPROVED', 'IN_WORK'] and not supply_request.items.exists():
            messages.error(request, "Нельзя утвердить заявку без позиций! Добавьте товары.")
            return redirect("supplyrequest_detail", pk=pk)
        
        if new_status in ['APPROVED', 'IN_WORK', 'PARTIAL', 'COMPLETED', 'CANCELLED']:
            old_status = supply_request.status
            
            if new_status == 'IN_WORK' and old_status != 'IN_WORK':
                try:
                    _auto_create_pick_tasks(request, supply_request, request.user)
                except ValidationError as e:
                    error_text = '; '.join(e.messages) if hasattr(e, 'messages') else str(e)
                    messages.error(request, f"Не удалось перевести заявку в работу: {error_text}")
                    return redirect("supplyrequest_detail", pk=pk)
            
            if new_status == 'COMPLETED':
                Reservation.objects.filter(
                    supply_request=supply_request,
                    status='ACTIVE'
                ).update(status='SHIPPED')
            elif new_status == 'CANCELLED':
                Reservation.objects.filter(
                    supply_request=supply_request,
                    status='ACTIVE'
                ).update(status='CANCELLED')

            supply_request.status = new_status
            supply_request.save(update_fields=['status'])
            messages.success(request, f"Статус изменен: {supply_request.get_status_display()}")
                
    return redirect("supplyrequest_detail", pk=pk)


# ==================== RESERVATIONS (ТОЛЬКО ДЛЯ STAFF) ====================

class ReservationList(StaffRequiredMixin, ListView):
    model = Reservation
    paginate_by = 20
    template_name = "warehouse/reservation_list.html"
    context_object_name = "reservations"
    
    def get_queryset(self):
        return Reservation.objects.select_related(
            'product', 'object', 'batch', 'reserved_by'
        ).order_by('-reserved_at')

class ReservationCreate(StaffRequiredMixin, CreateView):
    model = Reservation
    form_class = ReservationForm
    template_name = "warehouse/reservation_form.html"
    success_url = reverse_lazy("reservation_list")
    
    def form_valid(self, form):
        form.instance.reserved_by = self.request.user
        messages.success(self.request, "Резерв создан.")
        return super().form_valid(form)


# ==================== PICK TASKS (ТОЛЬКО ДЛЯ STAFF) ====================

class PickTaskList(StaffRequiredMixin, ListView):
    model = PickTask
    paginate_by = 20
    template_name = "warehouse/picktask_list.html"
    context_object_name = "task_groups"

    def _get_filter_values(self):
        return {
            'q': (self.request.GET.get('q') or '').strip(),
            'priority': (self.request.GET.get('priority') or '').strip(),
            'request_status': (self.request.GET.get('request_status') or '').strip(),
            'group_type': (self.request.GET.get('group_type') or '').strip(),
        }

    def get_queryset(self):
        filters = self._get_filter_values()
        search_query = filters['q']
        priority_filter = filters['priority']
        request_status_filter = filters['request_status']
        group_type_filter = filters['group_type']

        tasks = PickTask.objects.filter(
            is_done=False,
            supply_request__isnull=False
        ).select_related(
            'product', 'from_location', 'to_location',
            'supply_request', 'supply_request__object', 'supply_request__created_by',
            'assigned_to', 'batch'
        )

        pending_requests = SupplyRequest.objects.filter(
            status__in=['APPROVED', 'IN_WORK'],
            pick_tasks__isnull=True
        ).select_related('object', 'created_by').prefetch_related('items__product')

        if search_query:
            tasks = tasks.filter(
                Q(supply_request__number__icontains=search_query)
                | Q(supply_request__object__code__icontains=search_query)
                | Q(supply_request__object__name__icontains=search_query)
                | Q(supply_request__delivery_address__icontains=search_query)
                | Q(supply_request__contact_person__icontains=search_query)
                | Q(supply_request__created_by__username__icontains=search_query)
                | Q(supply_request__created_by__first_name__icontains=search_query)
                | Q(supply_request__created_by__last_name__icontains=search_query)
                | Q(product__sku__icontains=search_query)
                | Q(product__name__icontains=search_query)
            )
            pending_requests = pending_requests.filter(
                Q(number__icontains=search_query)
                | Q(object__code__icontains=search_query)
                | Q(object__name__icontains=search_query)
                | Q(delivery_address__icontains=search_query)
                | Q(contact_person__icontains=search_query)
                | Q(created_by__username__icontains=search_query)
                | Q(created_by__first_name__icontains=search_query)
                | Q(created_by__last_name__icontains=search_query)
                | Q(items__product__sku__icontains=search_query)
                | Q(items__product__name__icontains=search_query)
            ).distinct()

        if priority_filter:
            tasks = tasks.filter(supply_request__priority=priority_filter)
            pending_requests = pending_requests.filter(priority=priority_filter)

        if request_status_filter:
            tasks = tasks.filter(supply_request__status=request_status_filter)
            pending_requests = pending_requests.filter(status=request_status_filter)

        tasks = tasks.order_by('supply_request__id', 'created_at')

        from collections import defaultdict
        groups = defaultdict(list)
        for task in tasks:
            groups[task.supply_request].append(task)

        result = []
        if group_type_filter != 'without_tasks':
            for supply_request, task_list in groups.items():
                result.append({
                    'type': 'group',
                    'supply_request': supply_request,
                    'tasks': task_list,
                    'total_tasks': len(task_list),
                    'completed_tasks': 0,
                    'priority': supply_request.priority,
                    'created_at': supply_request.created_at,
                    'created_by': supply_request.created_by,
                })

        if group_type_filter != 'with_tasks':
            for req in pending_requests.order_by('created_at', 'id'):
                result.append({
                    'type': 'empty',
                    'supply_request': req,
                    'tasks': [],
                    'total_tasks': 0,
                    'completed_tasks': 0,
                    'priority': req.priority,
                    'created_at': req.created_at,
                    'created_by': req.created_by,
                })

        priority_order = {'CRITICAL': 0, 'HIGH': 1, 'NORMAL': 2, 'LOW': 3}
        result.sort(key=lambda x: (priority_order.get(x['priority'], 4), x['created_at']))
        return result

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = self._get_filter_values()
        search_query = filters['q']
        priority_filter = filters['priority']
        request_status_filter = filters['request_status']

        completed_tasks = PickTask.objects.filter(
            is_done=True,
            supply_request__isnull=False
        ).select_related(
            'product', 'supply_request', 'supply_request__created_by'
        )

        if search_query:
            completed_tasks = completed_tasks.filter(
                Q(supply_request__number__icontains=search_query)
                | Q(supply_request__object__code__icontains=search_query)
                | Q(supply_request__object__name__icontains=search_query)
                | Q(supply_request__delivery_address__icontains=search_query)
                | Q(supply_request__contact_person__icontains=search_query)
                | Q(supply_request__created_by__username__icontains=search_query)
                | Q(supply_request__created_by__first_name__icontains=search_query)
                | Q(supply_request__created_by__last_name__icontains=search_query)
                | Q(product__sku__icontains=search_query)
                | Q(product__name__icontains=search_query)
            )

        if priority_filter:
            completed_tasks = completed_tasks.filter(supply_request__priority=priority_filter)

        if request_status_filter:
            completed_tasks = completed_tasks.filter(supply_request__status=request_status_filter)

        context['filter_form'] = PickTaskFilterForm(self.request.GET or None)
        context['query_params'] = build_query_params_without_page(self.request)
        context['completed_tasks'] = completed_tasks.order_by('-completed_at')[:10]
        return context


class PickTaskDetail(LoginRequiredMixin, DetailView):
    model = PickTask
    template_name = "warehouse/picktask_detail.html"
    context_object_name = "task"
    
    def get_queryset(self):
        return PickTask.objects.select_related(
            'product', 'from_location', 'to_location', 
            'supply_request', 'assigned_to', 'batch'
        )
    
    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user
        
        # Суперпользователь и staff имеют полный доступ
        if has_staff_access(user) or user.is_superuser:
            return obj
            
        # Обычный пользователь — только свои назначенные задачи
        if obj.assigned_to != user:
            raise PermissionDenied(
                "У вас нет доступа к этой задаче. "
                "Вы можете просматривать только назначенные вам задачи."
            )
            
        # Нельзя смотреть чужие задачи по чужим заявкам (доп. защита)
        if obj.supply_request and not has_staff_access(user):
            if obj.supply_request.created_by != user and obj.assigned_to != user:
                raise PermissionDenied("Доступ запрещен")
                
        return obj


@login_required
def picktask_create(request):
    """Создание новой задачи на отбор с автоподстановкой из заявки"""
    if not can_manage_warehouse(request.user):
        messages.error(request, "Доступ запрещен. Только для персонала склада.")
        return redirect("dashboard")
    
    supply_request_id = request.GET.get('supply_request')
    supply_request = None
    initial_data = {}
    preselected_item = None
    
    if supply_request_id:
        try:
            supply_request = SupplyRequest.objects.select_related().prefetch_related('items__product').get(pk=supply_request_id)
            initial_data['supply_request'] = supply_request
            
            # Получаем позицию заявки для предзаполнения (если указана)
            item_id = request.GET.get('item')
            if item_id:
                try:
                    preselected_item = supply_request.items.select_related('product').get(pk=item_id)
                except SupplyRequestItem.DoesNotExist:
                    pass
            
            # Если не указана конкретная позиция — берём первую НЕВЫПОЛНЕННУЮ
            if not preselected_item:
                for item in supply_request.items.all():
                    # Проверяем, сколько уже отобрано по этому товару
                    picked_qty = PickTask.objects.filter(
                        supply_request=supply_request,
                        product=item.product,
                        is_done=True
                    ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
                    planned_qty = PickTask.objects.filter(
                        supply_request=supply_request,
                        product=item.product,
                        is_done=False
                    ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

                    remaining = item.quantity_requested - picked_qty - planned_qty
                    if remaining > 0:
                        preselected_item = item
                        break
            
            # === КРИТИЧЕСКАЯ ПРОВЕРКА: если нет невыполненных позиций ===
            if not preselected_item:
                messages.error(request, "Все позиции заявки уже выполнены!")
                return redirect("supplyrequest_detail", pk=supply_request.pk)
            
            # Предзаполняем форму если есть позиция
            if preselected_item:
                initial_data['product'] = preselected_item.product_id
                # Сколько ещё нужно отобрать
                picked_qty = PickTask.objects.filter(
                    supply_request=supply_request,
                    product=preselected_item.product,
                    is_done=True
                ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
                planned_qty = PickTask.objects.filter(
                    supply_request=supply_request,
                    product=preselected_item.product,
                    is_done=False
                ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
                remaining = preselected_item.quantity_requested - picked_qty - planned_qty
                
                # === ЗАЩИТА: не даём создать задачу на 0 или меньше ===
                if remaining <= 0:
                    messages.error(request, 
                        f"Товар {preselected_item.product.sku} уже полностью отобран!")
                    return redirect("supplyrequest_detail", pk=supply_request.pk)
                
                initial_data['quantity'] = remaining
                
                # Ищем локацию с остатком для автоподстановки
                stock = Stock.objects.filter(
                    product=preselected_item.product,
                    quantity__gt=0
                ).select_related('location').order_by('-quantity').first()
                
                if stock:
                    initial_data['from_location'] = stock.location
                    
        except SupplyRequest.DoesNotExist:
            pass
    
    if request.method == "POST":
        form = PickTaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.assigned_to = request.user

            # === ФИНАЛЬНАЯ ПРОВЕРКА ПЕРЕД СОХРАНЕНИЕМ ===
            if task.supply_request and task.product:
                picked_qty = PickTask.objects.filter(
                    supply_request=task.supply_request,
                    product=task.product,
                    is_done=True
                ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
                planned_qty = PickTask.objects.filter(
                    supply_request=task.supply_request,
                    product=task.product,
                    is_done=False
                ).exclude(pk=task.pk).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

                requested = SupplyRequestItem.objects.filter(
                    request=task.supply_request,
                    product=task.product
                ).first()

                if requested:
                    remaining = requested.quantity_requested - picked_qty - planned_qty
                    
                    if remaining <= 0:
                        messages.error(request, 
                            f"Нельзя создать задачу: {task.product.sku} уже полностью выполнен")
                        return redirect("picktask_list")
                    
                    # Корректируем количество если превышает остаток
                    if task.quantity > remaining:
                        task.quantity = remaining
                        messages.warning(request, 
                            f"Количество скорректировано до {remaining}")
            
            task.save()
            messages.success(
                request, 
                f"Задача создана: {task.product.name} — {task.quantity} {task.product.get_unit_display()} "
                f"из {task.from_location} в {task.to_location}"
            )
            
            if task.supply_request and task.supply_request.status == 'APPROVED':
                task.supply_request.status = 'IN_WORK'
                task.supply_request.save(update_fields=['status'])
            
            # Редирект на создание следующей задачи по этой же заявке
            if task.supply_request:
                # Проверяем, остались ли невыполненные позиции
                has_remaining = False
                for item in task.supply_request.items.all():
                    picked = PickTask.objects.filter(
                        supply_request=task.supply_request,
                        product=item.product,
                        is_done=True
                    ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
                    planned = PickTask.objects.filter(
                        supply_request=task.supply_request,
                        product=item.product,
                        is_done=False
                    ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
                    if item.quantity_requested > picked + planned:
                        has_remaining = True
                        break
                
                if has_remaining:
                    return redirect(f"{reverse('picktask_create')}?supply_request={task.supply_request.pk}")
            
            return redirect("picktask_list")
    else:
        form = PickTaskForm(initial=initial_data)
    
    # Получаем остатки для справки
    stock_info = Stock.objects.filter(
        quantity__gt=0
    ).select_related('product', 'location').order_by(
        'product__sku', 'location__code'
    )
    
    # Формируем данные о позициях заявки для JavaScript
    request_items_data = []
    if supply_request:
        for item in supply_request.items.all():
            picked_qty = PickTask.objects.filter(
                supply_request=supply_request,
                product=item.product,
                is_done=True
            ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
            planned_qty = PickTask.objects.filter(
                supply_request=supply_request,
                product=item.product,
                is_done=False
            ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
            remaining = item.quantity_requested - picked_qty - planned_qty
            
            # Находим лучшую локацию для этого товара
            best_stock = Stock.objects.filter(
                product=item.product,
                quantity__gt=0
            ).select_related('location').order_by('-quantity').first()
            
            request_items_data.append({
                'item_id': item.pk,
                'product_id': item.product.pk,
                'product_sku': item.product.sku,
                'product_name': item.product.name,
                'unit': item.product.get_unit_display(),
                'requested': float(item.quantity_requested),
                'picked': float(picked_qty),
                'remaining': float(remaining),
                'best_location_id': best_stock.location.pk if best_stock else None,
                'best_location_code': best_stock.location.code if best_stock else None,
                'best_location_qty': float(best_stock.quantity) if best_stock else 0,
                'has_stock': best_stock is not None,
            })
    
    context = {
        "form": form,
        "supply_request": supply_request,
        "stock_info": stock_info,
        "request_items": supply_request.items.all() if supply_request else [],
        "request_items_json": request_items_data,
        "preselected_item": preselected_item,
        "preselected_best_location_id": initial_data.get('from_location').pk if initial_data.get('from_location') else '',
    }
    return render(request, "warehouse/picktask_form.html", context)


@login_required
@transaction.atomic
def picktask_complete(request, pk):
    """Выполнение задачи с атомарными блокировками в модели"""
    if not can_manage_warehouse(request.user):
        messages.error(request, "Только кладовщик может выполнять задачи.")
        return redirect("dashboard")
    
    task = get_object_or_404(PickTask.objects.select_related('supply_request', 'product'), pk=pk)
    
    # Проверка: задача уже выполнена?
    if task.is_done:
        messages.warning(request, "Задача уже выполнена ранее!")
        if task.supply_request:
            return redirect("supplyrequest_detail", pk=task.supply_request.pk)
        return redirect("picktask_list")
    
    # Проверяем ещё раз в БД
    if PickTask.objects.filter(pk=task.pk, is_done=True).exists():
        messages.warning(request, "Задача уже выполнена другим процессом.")
        if task.supply_request:
            return redirect("supplyrequest_detail", pk=task.supply_request.pk)
        return redirect("picktask_list")
    
    # Проверка назначения
    if task.assigned_to and task.assigned_to != request.user and not request.user.is_superuser:
        messages.warning(request, f"Задача назначена пользователю {task.assigned_to.username}")
    
    try:
        task.complete(user=request.user)
        
        batch_info = f" (партия: {task.batch.lot_number})" if task.batch else ""
        messages.success(
            request, 
            f"✅ Задача выполнена! Отобрано {task.quantity} {task.product.get_unit_display()}{batch_info} "
            f"из {task.from_location} в {task.to_location}"
        )
        
        if task.supply_request:
            return redirect("supplyrequest_detail", pk=task.supply_request.pk)
            
    except ValidationError as e:
        messages.error(request, str(e))
    except Exception as e:
        messages.error(request, f"Ошибка при выполнении: {str(e)}")
    
    return redirect("picktask_list")


# ==================== PRINT ====================

@login_required
def supply_request_print(request, pk):
    supply_request = get_object_or_404(
        SupplyRequest.objects.select_related('object', 'created_by'), pk=pk
    )
    
    user = request.user
    
    if not can_user_print_supply_request(user, supply_request):
        if supply_request.created_by == user and supply_request.status not in ['DRAFT', 'APPROVED']:
            raise PermissionDenied(
                "Заявка уже в работе. Печать доступна только персоналу снабжения."
            )
        raise PermissionDenied("У вас нет доступа к печати этой заявки.")
    
    items = supply_request.items.all()
    
    context = {
        'req': supply_request,
        'items': items,
        'total_items': items.count(),
        'total_quantity': sum(item.quantity_requested for item in items),
        'print_date': timezone.now(),
        'printed_by': user,
    }
    
    return render(request, 'warehouse/supplyrequest_print.html', context)


@login_required
def product_price_api(request, product_id):
    """API для получения текущей цены товара"""
    try:
        product = Product.objects.get(pk=product_id)
        
        # Получаем текущую предпочтительную цену или последнюю
        price = ProductPrice.objects.filter(
            product=product,
            valid_from__lte=timezone.now().date()
        ).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.now().date())
        ).order_by('-is_preferred', '-valid_from').first()
        
        return JsonResponse({
            'price': str(price.price) if price else None,
            'currency': price.currency if price else 'RUB',
            'supplier': price.supplier.name if price and price.supplier else None
        })
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    # ==================== SUPPLY REQUEST ITEM EDIT/DELETE ====================

@login_required
def supply_request_edit_item(request, pk, item_pk):
    """Редактирование позиции заявки"""
    supply_request = get_object_or_404(SupplyRequest, pk=pk)
    item = get_object_or_404(SupplyRequestItem, pk=item_pk, request=supply_request)
    
    # Проверка прав
    if request.user != supply_request.created_by and not can_manage_procurement(request.user):
        messages.error(request, "Нет доступа к редактированию этой заявки.")
        return redirect("supplyrequest_detail", pk=pk)
    
    if supply_request.status not in ['DRAFT', 'APPROVED']:
        messages.error(request, "Нельзя редактировать позиции в заявке со статусом %s" % supply_request.get_status_display())
        return redirect("supplyrequest_detail", pk=pk)
    
    if request.method == "POST":
        # Получаем новое количество напрямую из POST
        try:
            new_qty_str = request.POST.get('quantity_requested', '').strip().replace(',', '.')
            new_qty = Decimal(new_qty_str) if new_qty_str else Decimal('0')
        except (InvalidOperation, ValueError):
            messages.error(request, "Некорректное количество")
            return redirect("supplyrequest_detail", pk=pk)
        
        # Если количество 0 или меньше — удаляем
        if new_qty <= 0:
            product_name = item.product.name
            sku = item.product.sku
            item.delete()
            messages.success(request, f"Позиция {sku} — {product_name} удалена (количество было 0 или меньше).")
        else:
            old_qty = item.quantity_requested
            item.quantity_requested = new_qty
            item.save()
            messages.success(
                request, 
                f"Обновлено: {item.product.name} — {new_qty} {item.product.get_unit_display()} (было: {old_qty})"
            )
        
        # ⭐ ВАЖНО: редирект на страницу деталей заявки
        return redirect("supplyrequest_detail", pk=pk)
    
    # GET — рендерим шаблон
    return render(request, "warehouse/supplyrequest_edit_item.html", {
        "supply_request": supply_request,
        "item": item,
    })


@login_required
@transaction.atomic
def supply_request_delete_item(request, pk, item_pk):
    """Удаление позиции заявки"""
    supply_request = get_object_or_404(
        SupplyRequest.objects.select_for_update(),
        pk=pk
    )
    item = get_object_or_404(
        SupplyRequestItem.objects.select_related('product'),
        pk=item_pk,
        request=supply_request
    )

    # Проверка прав
    if request.user != supply_request.created_by and not can_manage_procurement(request.user):
        messages.error(request, "Нет доступа к удалению позиций этой заявки.")
        return redirect("supplyrequest_detail", pk=pk)

    if supply_request.status not in ['DRAFT', 'APPROVED']:
        messages.error(request, "Нельзя удалять позиции в заявке со статусом %s" % supply_request.get_status_display())
        return redirect("supplyrequest_detail", pk=pk)

    if request.method == "POST":
        product = item.product
        product_name = product.name
        sku = product.sku

        # Удаляем незавершённые задачи по этой заявке и товару
        deleted_tasks_count, _ = PickTask.objects.filter(
            supply_request=supply_request,
            product=product,
            is_done=False
        ).delete()

        # Отменяем активные резервы по этой заявке и товару
        Reservation.objects.filter(
            supply_request=supply_request,
            product=product,
            status='ACTIVE'
        ).update(status='CANCELLED')

        item.delete()

        if deleted_tasks_count > 0:
            messages.success(
                request,
                f'Позиция {sku} — {product_name} удалена из заявки. '
                f'Связанных задач на отбор удалено: {deleted_tasks_count}.'
            )
        else:
            messages.success(request, f"Позиция {sku} — {product_name} удалена из заявки.")
        return redirect("supplyrequest_detail", pk=pk)

    # GET — показываем подтверждение удаления
    return render(request, "warehouse/supplyrequest_delete_item.html", {
        "supply_request": supply_request,
        "item": item,
    })

@login_required
@transaction.atomic
def supply_request_delete(request, pk):
    """Удаление заявки только создателем. Каскадное удаление позиций и задач."""
    supply_request = get_object_or_404(SupplyRequest, pk=pk)
    
    # Только создатель может удалить свою заявку
    if request.user != supply_request.created_by:
        messages.error(request, "Нет доступа к удалению этой заявки.")
        return redirect("supplyrequest_detail", pk=pk)
    
    # Нельзя удалить выполненные или отменённые (архив)
    if supply_request.status in ['COMPLETED', 'CANCELLED']:
        messages.error(request, "Нельзя удалить архивную заявку.")
        return redirect("supplyrequest_detail", pk=pk)
    
    if request.method == "POST":
        number = supply_request.number
        status = supply_request.get_status_display()
        
        # Отменяем активные резервы по этой заявке
        Reservation.objects.filter(
            supply_request=supply_request,
            status='ACTIVE'
        ).update(status='CANCELLED')
        
        # PickTask и SupplyRequestItem удалятся автоматически (CASCADE)
        supply_request.delete()
        
        messages.success(
            request, 
            f"Заявка {number} ({status}) удалена."
        )
        return redirect("supplyrequest_list")
    
    # GET — подтверждение
    return render(request, "warehouse/supplyrequest_delete.html", {
        "supply_request": supply_request,
    })

@login_required
def check_reservation_api(request):
    """Проверка наличия резерва на товар по заявке"""
    product_id = request.GET.get('product')
    supply_request_id = request.GET.get('supply_request')
    
    if not product_id or not supply_request_id:
        return JsonResponse({'has_reservation': False})
    
    try:
        supply_request = SupplyRequest.objects.get(pk=supply_request_id)
        product = Product.objects.get(pk=product_id)

        reservations = Reservation.objects.filter(
            supply_request=supply_request,
            product=product,
            status='ACTIVE'
        ).select_related('batch').order_by('reserved_at')

        if reservations.exists():
            total_reserved = reservations.aggregate(total=Sum('quantity'))['total'] or Decimal('0')
            first_reservation = reservations.first()
            return JsonResponse({
                'has_reservation': True,
                'reserved_qty': float(total_reserved),
                'batch_id': first_reservation.batch_id if reservations.count() == 1 else None,
                'unit': product.get_unit_display()
            })

        return JsonResponse({'has_reservation': False})

    except (SupplyRequest.DoesNotExist, Product.DoesNotExist):
        return JsonResponse({'has_reservation': False})

@login_required
def product_batches_api(request):
    """Получение партий товара на конкретной локации"""
    product_id = request.GET.get('product')
    location_id = request.GET.get('location')
    
    if not product_id:
        return JsonResponse([], safe=False)
    
    stocks = Stock.objects.filter(
        product_id=product_id,
        quantity__gt=0
    ).select_related('batch', 'location')
    
    if location_id:
        stocks = stocks.filter(location_id=location_id)
    
    result = []
    for stock in stocks:
        if stock.batch:
            # Проверяем, есть ли резерв на эту партию
            is_reserved = Reservation.objects.filter(
                batch=stock.batch,
                status='ACTIVE'
            ).exists()
            
            result.append({
                'id': stock.batch.id,
                'lot_number': stock.batch.lot_number,
                'expiry_date': stock.batch.expiry_date.strftime('%d.%m.%Y') if stock.batch.expiry_date else None,
                'quantity': float(stock.quantity),
                'location': stock.location.code,
                'is_reserved': is_reserved
            })
    
    # Сортируем: сначала зарезервированные, потом по сроку годности (FEFO)
    result.sort(key=lambda x: (not x['is_reserved'], x['expiry_date'] or '9999'))
    
    return JsonResponse(result, safe=False)