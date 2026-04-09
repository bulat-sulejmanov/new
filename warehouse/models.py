from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

User = get_user_model()


class Supplier(models.Model):
    name = models.CharField("Название", max_length=200)
    inn = models.CharField("ИНН", max_length=12, blank=True)
    kpp = models.CharField("КПП", max_length=9, blank=True)
    ogrn = models.CharField("ОГРН", max_length=15, blank=True)
    address = models.CharField("Адрес", max_length=255, blank=True)
    email = models.EmailField("Email", blank=True)
    phone = models.CharField("Телефон", max_length=50, blank=True)
    contact_person = models.CharField("Контактное лицо", max_length=120, blank=True)
    notes = models.TextField("Заметки", blank=True)
    is_approved = models.BooleanField("Аккредитован", default=True, help_text="Поставщик прошел аккредитацию Татнефти")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Поставщик"
        verbose_name_plural = "Поставщики"


class Object(models.Model):
    """Объекты потребления: скважины, цеха, месторождения (опционально)"""
    OBJECT_TYPES = [
        ('OILFIELD', 'Месторождение'),
        ('WORKSHOP', 'Цех переработки'),
        ('WELL', 'Скважина'),
        ('DRILL', 'Буровая установка'),
        ('WAREHOUSE', 'Промежуточный склад'),
    ]
    
    code = models.CharField("Код объекта", max_length=20, unique=True)
    name = models.CharField("Наименование", max_length=200)
    object_type = models.CharField("Тип объекта", max_length=20, choices=OBJECT_TYPES)
    location = models.CharField("Участок/Месторождение", max_length=100, blank=True)
    is_active = models.BooleanField("Активен", default=True)
    
    def __str__(self):
        return f"{self.code} ({self.get_object_type_display()})"

    class Meta:
        verbose_name = "Объект потребления"
        verbose_name_plural = "Объекты потребления"
        ordering = ['code']


class MaterialGroup(models.Model):
    """Группы материалов для классификации"""
    CATEGORIES = [
        ('KIP', 'КИПиА'),
        ('CHEM', 'Химреагенты'),
        ('PIPE', 'Трубопродукция'),
        ('ZIP', 'ЗИП'),
        ('PPE', 'СИЗ'),
        ('FUEL', 'ГСМ'),
        ('EQUIP', 'Оборудование'),
    ]
    
    code = models.CharField("Код группы", max_length=10, unique=True)
    name = models.CharField("Наименование", max_length=100)
    category = models.CharField("Категория", max_length=20, choices=CATEGORIES)
    description = models.TextField("Описание", blank=True)
    
    def __str__(self):
        return f"{self.code} - {self.name}"

    class Meta:
        verbose_name = "Группа материалов"
        verbose_name_plural = "Группы материалов"


class Unit(models.TextChoices):
    EA = "EA", "шт"
    KG = "KG", "кг"
    L = "L", "л"
    M = "M", "м"
    TON = "TON", "т"
    M3 = "M3", "м³"


class Product(models.Model):
    sku = models.CharField("Артикул", max_length=50, unique=True, db_index=True)
    name = models.CharField("Наименование", max_length=200)
    barcode = models.CharField("Штрихкод", max_length=64, blank=True)
    unit = models.CharField("Ед.изм.", max_length=3, choices=Unit.choices, default=Unit.EA)
    
    material_group = models.ForeignKey(
        MaterialGroup, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Группа материалов"
    )
    
    ABC_CLASSES = [
        ('A', 'A - Критически важные (80% стоимости)'),
        ('B', 'B - Средней важности (15% стоимости)'),
        ('C', 'C - Малоценные (5% стоимости)'),
    ]
    abc_class = models.CharField("ABC-класс", max_length=1, choices=ABC_CLASSES, default='C')
    
    is_oilfield_specific = models.BooleanField(
        "Спец. для добычи", default=False,
        help_text="Требует сертификации для применения на объектах добычи"
    )
    critical_level = models.PositiveSmallIntegerField(
        "Уровень критичности", default=1,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1-5, где 5 - критически важно для бурения/добычи (остановка)"
    )
    tnvd_code = models.CharField("Код ТНВЭД", max_length=20, blank=True)
    
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Основной поставщик"
    )
    
    min_stock = models.DecimalField(
        "Мин. запас (критический)", max_digits=12, decimal_places=2, default=0
    )
    max_stock = models.DecimalField(
        "Макс. запас", max_digits=12, decimal_places=2, default=0
    )
    reorder_point = models.DecimalField(
        "Точка заказа", max_digits=12, decimal_places=2, default=0,
        help_text="При достижении этого остатка формируется заявка на закупку"
    )
    safety_stock = models.DecimalField(
        "Страховой запас", max_digits=12, decimal_places=2, default=0
    )
    
    lead_time_days = models.PositiveIntegerField("Срок поставки (дней)", default=7)
    is_active = models.BooleanField("Активен", default=True)

    def __str__(self):
        return f"{self.sku} — {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.pk and not self.sku:
            prefix = "ТСН"
            if self.material_group and self.material_group.code:
                prefix = self.material_group.code
            
            max_number = 0
            
            existing_skus = Product.objects.filter(
                sku__startswith=f"{prefix}-"
            ).values_list('sku', flat=True)
            
            for sku in existing_skus:
                try:
                    if not sku.startswith(f"{prefix}-"):
                        continue
                    
                    num_part = sku[len(prefix)+1:]
                    
                    if num_part.isdigit():
                        num = int(num_part)
                        if num > max_number:
                            max_number = num
                except (ValueError, IndexError):
                    continue
            
            new_number = max_number + 1
            self.sku = f"{prefix}-{new_number:05d}"
        
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ['sku']


class Area(models.TextChoices):
    RECEIVING = "RECV", "Приёмка"
    STORAGE = "STOR", "Хранение"
    PICKING = "PICK", "Отбор"
    SHIPPING = "SHIP", "Отгрузка"


class Location(models.Model):
    code = models.CharField("Локация", max_length=30, unique=True)
    description = models.CharField("Описание", max_length=200, blank=True)
    area = models.CharField(
        "Зона", max_length=4, choices=Area.choices, default=Area.STORAGE
    )
    capacity = models.PositiveIntegerField("Ёмкость (условн.)", default=0)
    storage_conditions = models.CharField("Условия хранения", max_length=100, blank=True)

    def __str__(self):
        return self.code

    class Meta:
        verbose_name = "Локация"
        verbose_name_plural = "Локации"


class Batch(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Товар")
    lot_number = models.CharField("Номер партии", max_length=50)
    supplier_lot = models.CharField("Номер партии поставщика", max_length=50, blank=True)
    manufacture_date = models.DateField("Дата производства", null=True, blank=True)
    expiry_date = models.DateField("Срок годности", null=True, blank=True)
    serial_number = models.CharField("Серийный номер", max_length=100, blank=True)
    cert_number = models.CharField("Номер сертификата соответствия", max_length=100, blank=True)
    cert_valid_until = models.DateField("Сертификат действителен до", null=True, blank=True)
    created_at = models.DateTimeField("Дата создания", default=timezone.now)

    def __str__(self):
        return f"{self.lot_number} ({self.product.sku})"

    class Meta:
        verbose_name = "Партия"
        verbose_name_plural = "Партии"
        unique_together = ['product', 'lot_number']
        
    @property
    def is_expired(self):
        if self.expiry_date:
            return timezone.now().date() > self.expiry_date
        return False
    
    @property
    def is_cert_valid(self):
        if self.cert_valid_until:
            return timezone.now().date() <= self.cert_valid_until
        return True


class Stock(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Товар", related_name="stock_levels")
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="stock_levels"  # ИСПРАВЛЕНО: CASCADE -> PROTECT
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Партия"
    )
    quantity = models.DecimalField(
        "Количество", max_digits=12, decimal_places=2, default=0
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "location", "batch"],
                name="unique_stock_per_product_location_batch"
            ),
            models.CheckConstraint(
                check=models.Q(quantity__gte=0), 
                name="stock_quantity_non_negative"
            ),
        ]
        indexes = [
            models.Index(fields=['product', 'location']),
            models.Index(fields=['location', 'product']),
            models.Index(fields=['batch', 'product']),
            models.Index(fields=['quantity']),  # Добавлено: частый фильтр по остаткам
        ]
        verbose_name = "Остаток"
        verbose_name_plural = "Остатки"

    def __str__(self):
        return f"{self.product.sku}@{self.location.code} = {self.quantity}"


class MoveType(models.TextChoices):
    RECEIPT = "RECEIPT", "Приход"
    PUTAWAY = "PUTAWAY", "Размещение"
    PICK = "PICK", "Отбор"
    SHIP = "SHIP", "Отгрузка"
    ADJUSTMENT = "ADJ", "Корректировка"
    TRANSFER = "TRANSFER", "Перемещение"

class StockMove(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Товар")
    from_location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moves_from",
    )
    to_location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moves_to",
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Партия"
    )
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=2)
    move_type = models.CharField(
        "Тип", max_length=10, choices=MoveType.choices, default=MoveType.TRANSFER
    )
    reference = models.CharField("Основание", max_length=120, blank=True)
    created_at = models.DateTimeField("Дата", default=timezone.now, db_index=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        verbose_name = "Движение"
        verbose_name_plural = "Движения"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.move_type}: {self.product.sku} {self.quantity}"

    @transaction.atomic
    def apply(self):
        """
        Apply movement to stock levels with locking and atomic updates.
        """
        if self.from_location and self.to_location and self.from_location == self.to_location:
            raise ValidationError("Локация источника и назначения должны различаться")
        
        def process_location(loc, delta):
            if not loc:
                return None
            
            if delta < 0:
                try:
                    stock = Stock.objects.select_for_update(nowait=False).get(
                        product=self.product,
                        location=loc,
                        batch=self.batch
                    )
                except Stock.DoesNotExist:
                    raise ValidationError(
                        f"Недостаточно товара {self.product.sku} на локации {loc.code}. "
                        f"Доступно: 0, требуется: {abs(delta)}"
                    )
                
                if stock.quantity < abs(delta):
                    raise ValidationError(
                        f"Недостаточно товара {self.product.sku} на локации {loc.code}. "
                        f"Доступно: {stock.quantity}, требуется: {abs(delta)}"
                    )
                
                stock.quantity = F('quantity') + delta
                stock.save()
                stock.refresh_from_db()
                return stock
            
            else:
                try:
                    with transaction.atomic():
                        stock = Stock.objects.select_for_update().get(
                            product=self.product,
                            location=loc,
                            batch=self.batch
                        )
                        stock.quantity = F('quantity') + delta
                        stock.save()
                        stock.refresh_from_db()
                        return stock
                        
                except Stock.DoesNotExist:
                    try:
                        return Stock.objects.create(
                            product=self.product,
                            location=loc,
                            batch=self.batch,
                            quantity=delta
                        )
                    except IntegrityError:
                        transaction.set_rollback(True)
                        return process_location(loc, delta)

        result_from = None
        result_to = None
        
        if self.from_location:
            result_from = process_location(self.from_location, -self.quantity)
        
        if self.to_location:
            result_to = process_location(self.to_location, self.quantity)
            
        return result_to or result_from


class ProductPrice(models.Model):
    """История цен товаров от поставщиков"""
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, 
        related_name='price_history',
        verbose_name="Товар"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.CASCADE,
        related_name='product_prices',
        verbose_name="Поставщик"
    )
    price = models.DecimalField(
        "Цена", max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    currency = models.CharField("Валюта", max_length=3, default='RUB')
    is_preferred = models.BooleanField(
        "Предпочтительная цена", default=False,
        help_text="Использовать эту цену по умолчанию при заказе"
    )
    valid_from = models.DateField("Действует с", default=timezone.now)
    valid_until = models.DateField("Действует до", null=True, blank=True)
    notes = models.TextField("Примечание", blank=True)
    created_at = models.DateTimeField("Дата добавления", auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        verbose_name = "Цена товара"
        verbose_name_plural = "История цен товаров"
        ordering = ['-valid_from', 'price']
        indexes = [
            models.Index(fields=['product', 'supplier', '-valid_from']),
            models.Index(fields=['product', 'is_preferred']),
        ]

    def __str__(self):
        return f"{self.product.sku}: {self.price} от {self.supplier.name}"

    def clean(self):
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError("Дата окончания должна быть позже даты начала")
        
        # Только одна предпочтительная цена на товар
        if self.is_preferred:
            ProductPrice.objects.filter(
                product=self.product, 
                is_preferred=True
            ).exclude(pk=self.pk).update(is_preferred=False)

    def is_current(self):
        """Актуальна ли цена"""
        today = timezone.now().date()
        if self.valid_until and self.valid_until < today:
            return False
        return self.valid_from <= today


class PurchaseOrder(models.Model):
    DRAFT, PLACED, RECEIVED, CANCELLED = "DRAFT", "PLACED", "RECEIVED", "CANCELLED"
    STATUSES = [
        (DRAFT, "Черновик"),
        (PLACED, "Размещён"),
        (RECEIVED, "Получен"),
        (CANCELLED, "Отменён"),
    ]

    number = models.CharField("Номер", max_length=30, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    status = models.CharField("Статус", max_length=10, choices=STATUSES, default=DRAFT)
    expected_date = models.DateField("Ожидаемая дата", null=True, blank=True)
    created_at = models.DateTimeField("Создан", default=timezone.now)
    notes = models.TextField("Примечания", blank=True)
    received_at = models.DateTimeField("Получен в системе", null=True, blank=True)
    received_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_purchase_orders',
        verbose_name="Принял",
    )
    receipt_applied_at = models.DateTimeField(
        "Приход проведён", null=True, blank=True
    )

    def __str__(self):
        return self.number

    @property
    def total_sum(self):
        """Общая сумма заказа"""
        result = self.items.filter(price__isnull=False).aggregate(
            total=Sum(F('price') * F('quantity'))
        )['total']
        return result or Decimal('0')
    
    @property
    def items_with_prices_count(self):
        """Количество позиций с ценами"""
        return self.items.filter(price__isnull=False).count()
    
    def get_missing_prices_items(self):
        """Позиции без цен"""
        return self.items.filter(price__isnull=True)

    class Meta:
        verbose_name = "Заказ поставщику"
        verbose_name_plural = "Заказы поставщикам"


class POItem(models.Model):
    po = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=2)
    price = models.DecimalField("Цена", max_digits=12, decimal_places=2, null=True, blank=True)

    def get_sum(self):
        """Сумма позиции"""
        if self.price:
            return self.price * self.quantity
        return None

    class Meta:
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказа"

    def __str__(self):
        price_str = f" @ {self.price}₽" if self.price else ""
        return f"{self.po.number} — {self.product.sku} {self.quantity}{price_str}"


class SupplyRequest(models.Model):
    """Заявки от объектов добычи (скважин, цехов) в отдел снабжения"""
    PRIORITIES = [
        ('LOW', 'Низкий'),
        ('NORMAL', 'Нормальный'),
        ('HIGH', 'Высокий'),
        ('CRITICAL', 'Критический (остановка)'),
    ]
    
    STATUSES = [
        ('DRAFT', 'Черновик'),
        ('APPROVED', 'Утверждено'),
        ('IN_WORK', 'В работе'),
        ('PARTIAL', 'Частично выполнено'),
        ('COMPLETED', 'Выполнено'),
        ('CANCELLED', 'Отменено'),
    ]
    
    number = models.CharField("Номер заявки", max_length=20, unique=True)
    
    object = models.ForeignKey(
        Object, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Объект (из справочника)", 
        help_text="Выберите из списка или заполните адрес вручную ниже"
    )
    
    delivery_address = models.TextField(
        "Адрес доставки", 
        blank=True, 
        help_text="Например: скв. №45, куст 12, НГДУ Азнакаево, въезд с трассы М7"
    )
    contact_person = models.CharField(
        "Контактное лицо", 
        max_length=200, 
        blank=True,
        help_text="ФИО получателя на объекте"
    )
    contact_phone = models.CharField(
        "Телефон контакта", 
        max_length=50, 
        blank=True,
        help_text="Мобильный телефон для связи"
    )
    delivery_notes = models.TextField(
        "Примечание по доставке", 
        blank=True,
        help_text="Время доставки, ориентиры, проезд, координаты"
    )
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="Заявитель")
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    required_date = models.DateField("Требуемая дата поставки")
    priority = models.CharField("Приоритет", max_length=10, choices=PRIORITIES, default='NORMAL')
    status = models.CharField("Статус", max_length=10, choices=STATUSES, default='DRAFT', db_index=True)
    notes = models.TextField("Основание/Примечание", blank=True)

    def clean(self):
        """Валидация модели перед сохранением"""
        super().clean()
        
        # Хотя бы один из способов идентификации места доставки
        if not self.object and not self.delivery_address:
            raise ValidationError({
                'delivery_address': 'Укажите адрес доставки или выберите объект из справочника'
            })
        
        # Дата не в прошлом при создании
        if self.pk is None and self.required_date < timezone.now().date():
            raise ValidationError({
                'required_date': 'Требуемая дата не может быть в прошлом'
            })

    def save(self, *args, **kwargs):
        if not self.number:
            prefix = "ТСН"
            if self.object and self.object.code:
                prefix = self.object.code
            
            max_number = 0
            
            existing_numbers = SupplyRequest.objects.filter(
                number__startswith=f"{prefix}-"
            ).values_list('number', flat=True)
            
            for num in existing_numbers:
                try:
                    if not num.startswith(f"{prefix}-"):
                        continue
                    
                    num_part = num[len(prefix)+1:]
                    
                    if num_part.isdigit():
                        n = int(num_part)
                        if n > max_number:
                            max_number = n
                except (ValueError, IndexError):
                    continue
            
            new_number = max_number + 1
            self.number = f"{prefix}-{new_number:05d}"
        
        super().save(*args, **kwargs)

    @transaction.atomic
    def check_completion(self):
        """
        Проверка полного выполнения заявки.
        Вызывать только внутри транзакции!
        """
        # Считаем по ВСЕМ позициям заявки
        items = SupplyRequestItem.objects.filter(request=self)
        
        all_completed = True
        any_issued = False
        
        for item in items:
            # Сколько отобрано по ВСЕМ задачам (не только quantity_issued)
            picked = PickTask.objects.filter(
                supply_request=self,
                product=item.product,
                is_done=True
            ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
            
            # Синхронизируем quantity_issued если расходится
            if picked != item.quantity_issued:
                SupplyRequestItem.objects.filter(pk=item.pk).update(quantity_issued=picked)
            
            if picked > 0:
                any_issued = True
            if picked < item.quantity_requested:
                all_completed = False
        
        old_status = self.status
        if all_completed and any_issued:
            self.status = 'COMPLETED'
        elif any_issued:
            self.status = 'PARTIAL'
        
        if self.status != old_status:
            self.save(update_fields=['status'])

    def __str__(self):
        if self.object:
            return f"Заявка {self.number} от {self.object.code}"
        return f"Заявка {self.number} ({self.delivery_address[:30]}...)"

    class Meta:
         verbose_name = "Заявка на снабжение"
         verbose_name_plural = "Заявки на снабжение"
         ordering = ['-created_at']
         indexes = [
    models.Index(fields=['status', '-created_at']),
    models.Index(fields=['required_date']),  # Добавлено: сортировка по дате
    models.Index(fields=['priority', 'status']),  # Добавлено: фильтр по приоритету

       ]


class SupplyRequestItem(models.Model):
    """Позиции заявки от объектов"""
    request = models.ForeignKey(SupplyRequest, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Товар")
    quantity_requested = models.DecimalField("Запрошено", max_digits=12, decimal_places=2)
    quantity_issued = models.DecimalField("Отпущено", max_digits=12, decimal_places=2, default=0)
    
    class Meta:
        verbose_name = "Позиция заявки"
        verbose_name_plural = "Позиции заявок"
        indexes = [
            models.Index(fields=['request', 'product']),
        ]
        unique_together = ['request', 'product']

    def __str__(self):
        return f"{self.request.number}: {self.product.sku}"


class Reservation(models.Model):
    """Резервирование ТМЦ под конкретные объекты (скважины, бурение)"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reservations', verbose_name="Товар")
    supply_request = models.ForeignKey(
        SupplyRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations',
        verbose_name="По заявке",
    )
    object = models.ForeignKey(Object, on_delete=models.CASCADE, verbose_name="Объект назначения")
    batch = models.ForeignKey(Batch, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Партия")
    quantity = models.DecimalField("Зарезервировано", max_digits=12, decimal_places=2)
    reserved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="Кем зарезервировано")
    reserved_at = models.DateTimeField("Дата резерва", auto_now_add=True)
    planned_date = models.DateField("Плановая дата отгрузки")
    status = models.CharField("Статус", max_length=10, choices=[
        ('ACTIVE', 'Активно'),
        ('SHIPPED', 'Отгружено'),
        ('CANCELLED', 'Отменено'),
    ], default='ACTIVE')
    notes = models.TextField("Примечание", blank=True)

    def clean(self):
        """Валидация модели перед сохранением (без проверки остатков — она в save)"""
        super().clean()

        today = timezone.now().date()

        if self.supply_request_id and self.supply_request and self.supply_request.object_id:
            if self.object_id and self.object_id != self.supply_request.object_id:
                raise ValidationError({
                    'object': 'Объект резерва должен совпадать с объектом заявки.'
                })
            self.object = self.supply_request.object

        if self.planned_date and self.planned_date < today:
            raise ValidationError({
                'planned_date': 'Плановая дата отгрузки не может быть в прошлом'
            })

        max_future = today + timezone.timedelta(days=365)
        if self.planned_date and self.planned_date > max_future:
            raise ValidationError({
                'planned_date': 'Плановая дата не может быть более чем через год'
            })

    @transaction.atomic
    def save(self, *args, **kwargs):
        """Атомарное сохранение с проверкой остатков через select_for_update."""
        self.full_clean()

        if self.status == 'ACTIVE':
            stock_entries = Stock.objects.select_for_update().filter(
                product=self.product,
                location__area='STOR'
            )
            available = stock_entries.aggregate(total=Sum('quantity'))['total'] or Decimal('0')

            existing_reserves = Reservation.objects.select_for_update().filter(
                product=self.product,
                status='ACTIVE'
            ).exclude(pk=self.pk).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

            free_qty = available - existing_reserves
            if free_qty < self.quantity:
                raise ValidationError(
                    f'Недостаточно товара для резерва. '
                    f'Доступно: {free_qty}, '
                    f'запрошено: {self.quantity}. '
                    f'Всего на складе: {available}, '
                    f'уже зарезервировано: {existing_reserves}'
                )

        super().save(*args, **kwargs)

    def __str__(self):
        if self.supply_request_id:
            return f"Резерв {self.product.sku} по заявке {self.supply_request.number}"
        return f"Резерв {self.product.sku} для {self.object.code}"

    class Meta:
        verbose_name = "Резерв под объект"
        verbose_name_plural = "Резервы под объекты"
        indexes = [
            models.Index(fields=['product', 'status']),
            models.Index(fields=['object', 'status']),
            models.Index(fields=['planned_date']),
            models.Index(fields=['supply_request', 'status']),
            models.Index(fields=['supply_request', 'product', 'status']),
        ]


class PickTask(models.Model):
    """Задачи на отбор (picking) для комплектации заявок"""
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    batch = models.ForeignKey(Batch, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Партия")
    quantity = models.DecimalField("Количество", max_digits=12, decimal_places=2)
    from_location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="picks_from",
    )
    to_location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="picks_to",
    )
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    supply_request = models.ForeignKey(
        SupplyRequest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pick_tasks', verbose_name="По заявке"
    )
    is_done = models.BooleanField("Выполнено", default=False)
    created_at = models.DateTimeField("Создано", default=timezone.now)
    completed_at = models.DateTimeField("Завершено", null=True, blank=True)

    @transaction.atomic
    def complete(self, user=None):
        """
        Выполнение задачи в транзакции.
        Защищает от повторного отбора по уже закрытой потребности
        и автоматически убирает лишние/неактуальные незавершенные задачи.
        """
        if self.is_done:
            return self

        task_db = PickTask.objects.select_for_update().get(pk=self.pk)
        if task_db.is_done:
            return task_db

        if not self.supply_request_id:
            raise ValidationError("Задача не привязана к заявке")

        item = SupplyRequestItem.objects.select_for_update().filter(
            request=self.supply_request,
            product=self.product
        ).first()

        # Позицию из заявки уже удалили — закрываем задачу тихо
        if not item:
            self.is_done = True
            self.completed_at = timezone.now()
            if user:
                self.assigned_to = user
            self.save(update_fields=['is_done', 'completed_at', 'assigned_to'])

            PickTask.objects.filter(
                supply_request=self.supply_request,
                product=self.product,
                is_done=False
            ).exclude(pk=self.pk).delete()

            return self

        already_picked = PickTask.objects.filter(
            supply_request=self.supply_request,
            product=self.product,
            is_done=True
        ).exclude(pk=self.pk).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

        requested = item.quantity_requested or Decimal('0')
        remaining = requested - already_picked

        # Потребность уже закрыта — задача больше не актуальна
        if remaining <= 0:
            self.is_done = True
            self.completed_at = timezone.now()
            if user:
                self.assigned_to = user
            self.save(update_fields=['is_done', 'completed_at', 'assigned_to'])

            PickTask.objects.filter(
                supply_request=self.supply_request,
                product=self.product,
                is_done=False
            ).exclude(pk=self.pk).delete()

            return self

        qty_to_pick = self.quantity
        if qty_to_pick > remaining:
            qty_to_pick = remaining

        if qty_to_pick <= 0:
            self.is_done = True
            self.completed_at = timezone.now()
            if user:
                self.assigned_to = user
            self.save(update_fields=['is_done', 'completed_at', 'assigned_to'])
            return self

        batch_to_use = self.batch
        if not batch_to_use and self.from_location:
            stock_with_batch = Stock.objects.filter(
                product=self.product,
                location=self.from_location,
                quantity__gt=0,
                batch__isnull=False
            ).select_related('batch').order_by('batch__expiry_date').first()

            if stock_with_batch:
                batch_to_use = stock_with_batch.batch

        if self.from_location:
            try:
                stock = Stock.objects.get(
                    product=self.product,
                    location=self.from_location,
                    batch=batch_to_use
                )
            except Stock.DoesNotExist:
                batch_info = f" (партия: {batch_to_use.lot_number})" if batch_to_use else ""
                raise ValidationError(
                    f"Товар {self.product.sku}{batch_info} отсутствует на локации {self.from_location.code}"
                )

            if stock.quantity < qty_to_pick:
                raise ValidationError(
                    f"Недостаточно товара на локации {self.from_location.code}. "
                    f"Доступно: {stock.quantity}, требуется: {qty_to_pick}"
                )

        move = StockMove.objects.create(
            product=self.product,
            batch=batch_to_use,
            from_location=self.from_location,
            to_location=self.to_location,
            quantity=qty_to_pick,
            move_type='PICK',
            reference=f"Отбор по заявке {self.supply_request.number}",
            created_by=user,
        )
        move.apply()

        self.quantity = qty_to_pick
        self.is_done = True
        self.completed_at = timezone.now()
        if user:
            self.assigned_to = user
        self.batch = batch_to_use
        self.save(update_fields=['quantity', 'is_done', 'completed_at', 'assigned_to', 'batch'])

        new_issued = already_picked + qty_to_pick
        SupplyRequestItem.objects.filter(pk=item.pk).update(quantity_issued=new_issued)

        if new_issued >= requested:
            PickTask.objects.filter(
                supply_request=self.supply_request,
                product=self.product,
                is_done=False
            ).exclude(pk=self.pk).delete()

        if self.supply_request:
            Reservation.objects.filter(
                supply_request=self.supply_request,
                product=self.product,
                status='ACTIVE'
            ).filter(
                Q(batch=batch_to_use) | Q(batch__isnull=True)
            ).update(status='SHIPPED')

        self.supply_request.check_completion()
        return move

    class Meta:
        verbose_name = "Задача на отбор"
        verbose_name_plural = "Задачи на отбор"
        indexes = [
            models.Index(fields=['is_done', 'created_at']),
            models.Index(fields=['supply_request', 'is_done']),
            models.Index(fields=['from_location', 'is_done']),
            models.Index(fields=['product', 'batch']),
        ]

    def __str__(self):
        batch_info = f" (партия: {self.batch.lot_number})" if self.batch else ""
        return f"Отбор {self.product.sku}{batch_info} {self.quantity}"