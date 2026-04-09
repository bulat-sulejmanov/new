from django.db.models import DecimalField, Sum, F, Count, Q, Avg, OuterRef, Subquery, Value
from django.db.models.functions import TruncMonth, Coalesce
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import logging

from .models import Product, StockMove, Batch, POItem, Stock, ProductPrice, Reservation

logger = logging.getLogger(__name__)


def annotate_product_availability(queryset):
    """Аннотирует queryset товара суммарным остатком, активными резервами и доступным количеством."""
    stock_sq = Stock.objects.filter(
        product=OuterRef('pk')
    ).values('product').annotate(
        total=Coalesce(Sum('quantity'), Value(Decimal('0')))
    ).values('total')[:1]

    reserve_sq = Reservation.objects.filter(
        product=OuterRef('pk'),
        status='ACTIVE'
    ).values('product').annotate(
        total=Coalesce(Sum('quantity'), Value(Decimal('0')))
    ).values('total')[:1]

    return queryset.annotate(
        total_stock=Coalesce(
            Subquery(stock_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
            Value(Decimal('0'))
        ),
        total_reserved=Coalesce(
            Subquery(reserve_sq, output_field=DecimalField(max_digits=12, decimal_places=2)),
            Value(Decimal('0'))
        ),
    ).annotate(
        available=F('total_stock') - F('total_reserved')
    )


def calculate_abc_classification():
    """
    Расчет ABC классификации на основе стоимости движения за последние 6 месяцев.
    """
    six_months_ago = timezone.now() - timedelta(days=180)
    
    movements = StockMove.objects.filter(
        created_at__gte=six_months_ago,
        move_type__in=['SHIP', 'TRANSFER']
    ).select_related('product')
    
    if not movements.exists():
        logger.info("ABC-анализ: нет движений за последние 6 месяцев")
        return 0
    
    product_ids = list(set(m.product_id for m in movements))
    
    avg_prices = {
        item['product']: item['avg_price'] or Decimal('0')
        for item in POItem.objects.filter(
            product_id__in=product_ids,
            po__status='RECEIVED',
            price__isnull=False,
            price__gt=0
        ).values('product').annotate(avg_price=Avg('price'))
    }
    
    product_values = {}
    for move in movements:
        price = avg_prices.get(move.product_id, Decimal('0'))
        value = float(move.quantity) * float(price)
        product_values[move.product_id] = product_values.get(move.product_id, 0) + value
    
    if not product_values:
        logger.info("ABC-анализ: нет данных о стоимости движений")
        return 0
    
    sorted_products = sorted(product_values.items(), key=lambda x: x[1], reverse=True)
    total_value = sum(v for _, v in sorted_products)
    
    if total_value == 0:
        return 0
    
    products_map = Product.objects.in_bulk([p[0] for p in sorted_products])
    
    cumulative = 0
    products_to_update = []
    
    for product_id, value in sorted_products:
        cumulative += value
        percentage = cumulative / total_value
        
        product = products_map.get(product_id)
        if not product:
            continue
            
        new_class = 'C'
        if percentage <= 0.8:
            new_class = 'A'
        elif percentage <= 0.95:
            new_class = 'B'
        
        if product.abc_class != new_class:
            product.abc_class = new_class
            products_to_update.append(product)
    
    if products_to_update:
        Product.objects.bulk_update(products_to_update, ['abc_class'])
        logger.info(f"ABC-анализ обновлен для {len(products_to_update)} товаров")
    
    return len(products_to_update)


def get_critical_stock_alerts(limit=10):
    """
    Получение критических уведомлений для дашборда.
    """
    alerts = []
    
    # 1. Критические остатки (ABC=A и остаток < min)
    critical_products = Product.objects.filter(
        abc_class='A',
        is_active=True,
        min_stock__gt=0
    ).annotate(
        current_qty=Coalesce(Sum('stock_levels__quantity'), Decimal('0'))
    ).filter(
        current_qty__lt=F('min_stock')
    )[:limit]
    
    for prod in critical_products:
        alerts.append({
            'type': 'CRITICAL_STOCK',
            'priority': 'HIGH',
            'product': prod,
            'current_qty': prod.current_qty,
            'message': f'Критический остаток {prod.sku}: {prod.current_qty} {prod.get_unit_display()} (мин: {prod.min_stock})'
        })
    
    # 2. Просроченные партии
    expired_batches = Batch.objects.filter(
        expiry_date__lt=timezone.now().date(),
        stock__quantity__gt=0
    ).select_related('product').distinct()[:limit]

    for batch in expired_batches:
        qty = batch.stock_set.aggregate(total=Sum('quantity'))['total'] or 0
        if qty > 0:
            alerts.append({
                'type': 'EXPIRED',
                'priority': 'MEDIUM',
                'batch': batch,
                'message': f'Просрочена партия {batch.lot_number} товара {batch.product.sku} (остаток: {qty})'
            })
    
    # 3. Требуется заказ (точка заказа)
    reorder_products = Product.objects.filter(
        is_active=True,
        reorder_point__gt=0,
        min_stock__gte=0
    ).annotate(
        total_qty=Coalesce(Sum('stock_levels__quantity', filter=Q(stock_levels__quantity__gt=0)), Decimal('0'))
    ).filter(
        total_qty__lte=F('reorder_point'),
        total_qty__gt=F('min_stock')
    )[:limit]
    
    for prod in reorder_products:
        alerts.append({
            'type': 'REORDER',
            'priority': 'NORMAL',
            'product': prod,
            'current_qty': prod.total_qty,
            'message': f'Требуется заказ {prod.sku} (остаток: {prod.total_qty}, точка заказа: {prod.reorder_point})'
        })
    
    priority_order = {'HIGH': 0, 'MEDIUM': 1, 'NORMAL': 2}
    alerts.sort(key=lambda x: priority_order.get(x['priority'], 3))
    
    return alerts[:limit]


def calculate_inventory_turnover():
    """
    Расчет оборачиваемости запасов.
    """
    six_months_ago = timezone.now() - timedelta(days=180)
    
    avg_stock = Product.objects.annotate(
        avg_qty=Coalesce(Avg('stock_levels__quantity'), Decimal('0'))
    ).values('id', 'avg_qty')
    
    sales = StockMove.objects.filter(
        created_at__gte=six_months_ago,
        move_type__in=['SHIP', 'TRANSFER']
    ).values('product').annotate(
        total_qty=Sum('quantity'),
        total_value=Sum(F('quantity') * F('product__stock_levels__quantity'))
    )
    
    turnover_data = {}
    for sale in sales:
        product_id = sale['product']
        avg = next((x['avg_qty'] for x in avg_stock if x['id'] == product_id), 0)
        if avg and avg > 0:
            turnover_data[product_id] = float(sale['total_qty']) / float(avg) * 2
    
    return turnover_data


def check_and_notify_critical_stock():
    """
    Проверка критических остатков для фоновых задач (cron).
    """
    from django.contrib.auth import get_user_model
    
    User = get_user_model()
    staff_emails = list(User.objects.filter(is_staff=True, email__isnull=False).exclude(email='').values_list('email', flat=True))
    
    critical_items = Stock.objects.select_related('product', 'location').filter(
        product__min_stock__gt=0,
        quantity__lt=F('product__min_stock')
    ).order_by('product__sku', '-quantity')
    
    grouped_by_product = {}
    for item in critical_items:
        sku = item.product.sku
        if sku not in grouped_by_product:
            grouped_by_product[sku] = {
                'product': item.product,
                'total_qty': 0,
                'locations': []
            }
        grouped_by_product[sku]['total_qty'] += item.quantity
        grouped_by_product[sku]['locations'].append({
            'location': item.location.code,
            'qty': item.quantity
        })
    
    notifications = []
    for sku, data in grouped_by_product.items():
        if data['total_qty'] < data['product'].min_stock:
            notifications.append({
                'sku': sku,
                'name': data['product'].name,
                'current': data['total_qty'],
                'min': data['product'].min_stock,
                'locations': data['locations']
            })
    
    logger.info(f"Найдено {len(notifications)} критических позиций")
    
    return {
        'count': len(notifications),
        'items': notifications,
        'staff_emails': staff_emails
    }


def optimize_reorder_suggestions():
    """
    Рекомендации по заказу с учетом сроков поставки (lead_time) 
    и уже существующих заказов поставщикам.
    """
    today = timezone.now().date()
    
    # Получаем товары, у которых остаток ниже точки заказа
    products = annotate_product_availability(
        Product.objects.filter(
            is_active=True,
            reorder_point__gt=0,
            lead_time_days__gt=0
        ).select_related('supplier')
    ).annotate(
        current_stock=F('total_stock'),
        available_stock=F('available')
    ).filter(
        available_stock__lte=F('reorder_point')
    )
    
    suggestions = []
    for prod in products:
        # === НОВОЕ: Проверяем, есть ли уже открытые заказы на этот товар ===
        open_order_qty = POItem.objects.filter(
            product=prod,
            po__status__in=['DRAFT', 'PLACED']  # Заказы в работе
        ).aggregate(
            total=Coalesce(Sum('quantity'), Decimal('0'))
        )['total'] or Decimal('0')
        
        # Если товар уже заказан в достаточном количестве — пропускаем
        if open_order_qty > 0:
            # Проверяем, покрывает ли заказ дефицит
            projected_stock = prod.available_stock + open_order_qty
            if projected_stock > prod.reorder_point:
                continue  # Уже заказано достаточно, не показываем в рекомендациях
        
        # === КОНЕЦ НОВОГО ===
        
        required_order_date = today + timedelta(days=prod.lead_time_days)
        
        deficit = prod.max_stock - prod.available_stock
        min_order = prod.reorder_point * 2
        suggested_qty = max(deficit, min_order) if prod.max_stock > 0 else min_order
        
        # Вычитаем уже заказанное количество
        suggested_qty = max(Decimal('0'), suggested_qty - open_order_qty)
        
        if suggested_qty <= 0:
            continue  # Не предлагаем заказать 0 или отрицательное
        
        suggestions.append({
            'product': prod,
            'current_available': prod.available_stock,
            'open_order_qty': open_order_qty,  # Показываем сколько уже заказано
            'suggested_qty': suggested_qty,
            'required_by_date': required_order_date,
            'urgency': 'HIGH' if prod.available_stock <= prod.safety_stock else 'NORMAL',
            'supplier': prod.supplier
        })
    
    return sorted(suggestions, key=lambda x: x['current_available'] / x['product'].reorder_point)

def get_product_price(product, supplier=None, prefer_preferred=True):
    """
    Получить актуальную цену товара.
    
    Args:
        product: Product instance
        supplier: Supplier instance (опционально)
        prefer_preferred: если True, сначала ищем предпочтительную цену
    
    Returns:
        Decimal или None
    """
    today = timezone.now().date()
    
    qs = ProductPrice.objects.filter(
        product=product,
        valid_from__lte=today
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    )
    
    if supplier:
        qs = qs.filter(supplier=supplier)
    
    if prefer_preferred:
        preferred = qs.filter(is_preferred=True).first()
        if preferred:
            return preferred.price
    
    # Последняя актуальная цена
    latest = qs.order_by('-valid_from').first()
    return latest.price if latest else None


def get_cheapest_supplier(product):
    """
    Найти поставщика с минимальной актуальной ценой.
    
    Returns:
        tuple (supplier, price) или (None, None)
    """
    today = timezone.now().date()
    
    price = ProductPrice.objects.filter(
        product=product,
        valid_from__lte=today
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    ).order_by('price').first()
    
    return (price.supplier, price.price) if price else (None, None)


def calculate_po_totals(po):
    """
    Рассчитать итоги заказа.
    
    Returns:
        dict с суммами
    """
    items = po.items.select_related('product')
    
    total_sum = Decimal('0')
    items_with_prices = 0
    items_without_prices = 0
    
    for item in items:
        if item.price:
            total_sum += item.price * item.quantity
            items_with_prices += 1
        else:
            items_without_prices += 1
    
    return {
        'total_sum': total_sum,
        'items_count': items.count(),
        'items_with_prices': items_with_prices,
        'items_without_prices': items_without_prices,
        'currency': 'RUB'
    }