from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.db import models
from .models import (
    Supplier, Product, Location, StockMove, PurchaseOrder, POItem, 
    PickTask, Batch, Object, MaterialGroup, SupplyRequest, SupplyRequestItem, 
    Reservation, Stock, Area 
)
from .utils import annotate_product_availability

User = get_user_model()


class SignUpForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'password1', 'password2')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Придумайте логин'}),
            'password1': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Придумайте пароль'}),
            'password2': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Повторите пароль'}),
        }
        help_texts = {
            'username': '',
        }


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'ООО "Название компании"'
            }),
            'inn': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '1645001234'
            }),
            'kpp': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '164501001'
            }),
            'ogrn': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '1021602840123'
            }),
            'address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '423450, г. Альметьевск, ул. Ленина, д. 1'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'info@company.ru'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '8 (8553) 12-34-56'
            }),
            'contact_person': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Иванов Иван Иванович'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Условия поставки, особые требования...'
            }),
            'is_approved': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }


class ObjectForm(forms.ModelForm):
    """Форма для объектов потребления (скважины, цеха)"""
    class Meta:
        model = Object
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
        }


class MaterialGroupForm(forms.ModelForm):
    """Форма для групп материалов"""
    class Meta:
        model = MaterialGroup
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'sku', 'name', 'barcode', 'unit', 'material_group', 'supplier',
            'abc_class', 'is_oilfield_specific', 'critical_level', 'tnvd_code',
            'min_stock', 'max_stock', 'reorder_point', 'safety_stock',
            'lead_time_days', 'is_active'
        ]
        widgets = {
            'sku': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Оставьте пустым для автогенерации (KIP-00001)'
            }),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'barcode': forms.TextInput(attrs={'class': 'form-control'}),
            'tnvd_code': forms.TextInput(attrs={'class': 'form-control'}),
            'min_stock': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
            'max_stock': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
            'reorder_point': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
            'safety_stock': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
            'critical_level': forms.NumberInput(attrs={'min': 1, 'max': 5, 'class': 'form-control'}),
            'lead_time_days': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sku'].required = False
        self.fields['sku'].help_text = "Если не указан, будет сгенерирован автоматически на основе группы материалов (например: KIP-00001)"

        select_fields = ('unit', 'material_group', 'supplier', 'abc_class')
        checkbox_fields = ('is_oilfield_specific', 'is_active')

        for field_name in select_fields:
            self.fields[field_name].widget.attrs.update({'class': 'form-select'})

        for field_name in checkbox_fields:
            self.fields[field_name].widget.attrs.update({'class': 'form-check-input'})

        self.fields['material_group'].empty_label = '— Выберите группу материалов —'
        self.fields['supplier'].empty_label = '— Выберите поставщика —'


class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = '__all__'
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'area': forms.Select(attrs={'class': 'form-select'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control'}),
            'storage_conditions': forms.TextInput(attrs={'class': 'form-control'}),
        }


class StockMoveForm(forms.ModelForm):
    class Meta:
        model = StockMove
        fields = [
            'product', 'quantity', 'move_type', 
            'from_location', 'to_location', 'reference'
        ]
        widgets = {
            'quantity': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
            'reference': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].widget.attrs.update({'class': 'form-control'})
        self.fields['from_location'].widget.attrs.update({'class': 'form-control'})
        self.fields['to_location'].widget.attrs.update({'class': 'form-control'})
        self.fields['move_type'].widget.attrs.update({'class': 'form-control'})



class PurchaseOrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ['number', 'supplier', 'status', 'expected_date', 'notes']
        widgets = {
            'number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'ЗС-2024-001'
            }),
            'supplier': forms.Select(attrs={
                'class': 'form-control',
                'placeholder': 'Выберите поставщика из списка'
            }),
            'status': forms.Select(attrs={
                'class': 'form-control'
            }),
            'expected_date': forms.DateInput(attrs={
                'type': 'date', 
                'class': 'form-control'
            }, format='%Y-%m-%d'),  # ISO формат для HTML5 date input
            'notes': forms.Textarea(attrs={
                'rows': 3, 
                'class': 'form-control',
                'placeholder': 'Условия поставки, особые требования...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supplier'].empty_label = "— Выберите поставщика —"
        self.fields['status'].empty_label = None
        # Устанавливаем формат отображения даты для HTML5 date input
        if self.instance and self.instance.expected_date:
            self.initial['expected_date'] = self.instance.expected_date.strftime('%Y-%m-%d')


class POItemForm(forms.ModelForm):
    class Meta:
        model = POItem
        fields = ['product', 'quantity', 'price']
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-control'
            }),
            'quantity': forms.NumberInput(attrs={
                'step': '1', 
                'min': '1',
                'class': 'form-control',
                'value': '1'
            }),
            'price': forms.NumberInput(attrs={
                'step': '0.01', 
                'min': '0',
                'class': 'form-control',
                'placeholder': '0.00'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get('quantity'):
            self.initial['quantity'] = 1


class SupplyRequestForm(forms.ModelForm):
    """Заявка на снабжение от объекта с адресом доставки"""
    class Meta:
        model = SupplyRequest
        fields = [
            'number', 'object', 'delivery_address', 'contact_person', 
            'contact_phone', 'delivery_notes', 'required_date', 'priority', 'notes'
        ]
        widgets = {
            'number': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Оставьте пустым для автогенерации (ЗС-2024-001)'
            }),
            'object': forms.Select(attrs={
                'class': 'form-control',
                'placeholder': 'Выберите из списка (необязательно)'
            }),
            'delivery_address': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Например: скв. №45, куст 12, НГДУ Азнакаево'
            }),
            'contact_person': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Иванов А.П.'
            }),
            'contact_phone': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': '8-917-123-45-67'
            }),
            'delivery_notes': forms.Textarea(attrs={
                'rows': 2, 
                'class': 'form-control', 
                'placeholder': 'Время доставки: 09:00-18:00, ориентир: красный ангар'
            }),
            'required_date': forms.DateInput(attrs={
                'type': 'date', 
                'class': 'form-control'
            }),
            'priority': forms.Select(attrs={
                'class': 'form-control'
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3, 
                'class': 'form-control', 
                'placeholder': 'Основание заявки (остановка, плановое ТО и т.д.)'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['number'].required = False
        self.fields['number'].help_text = "Если не указан, сгенерируется автоматически (ЗС-ГГГГ-ННН)"
        
        self.fields['object'].required = False
        self.fields['object'].empty_label = "— Выберите из списка (необязательно) —"

class SupplyRequestItemForm(forms.ModelForm):
    """Позиция заявки с отображением актуальных остатков за минусом резервов."""

    class Meta:
        model = SupplyRequestItem
        fields = ['product', 'quantity_requested']
        widgets = {
            'quantity_requested': forms.NumberInput(attrs={
                'step': '0.01',
                'class': 'form-control',
                'placeholder': 'Количество'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        queryset = annotate_product_availability(
            Product.objects.filter(is_active=True).select_related('material_group', 'supplier')
        ).order_by('sku')

        self.fields['product'] = forms.ModelChoiceField(
            queryset=queryset,
            widget=forms.Select(attrs={'class': 'form-control'}),
            label="Товар (доступно с учётом резервов)",
            empty_label="--- Выберите товар ---"
        )

        self.fields['product'].label_from_instance = lambda obj: (
            f"{obj.sku} | {obj.name} | Доступно: {obj.available or 0} {obj.get_unit_display()} "
            f"(всего: {obj.total_stock or 0}, резерв: {obj.total_reserved or 0})"
        )

class ReservationForm(forms.ModelForm):
    """Резервирование ТМЦ под объект"""
    class Meta:
        model = Reservation
        fields = ['product', 'object', 'batch', 'quantity', 'planned_date', 'notes']
        widgets = {
            'quantity': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
            'planned_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].widget.attrs.update({'class': 'form-control'})
        self.fields['object'].widget.attrs.update({'class': 'form-control'})
        self.fields['batch'].widget.attrs.update({'class': 'form-control'})
        self.fields['batch'].required = False


class PickTaskForm(forms.ModelForm):
    """Задача на отбор с отображением остатков"""
    
    # Переопределяем поле batch для настройки виджета
    batch = forms.ModelChoiceField(
        queryset=Batch.objects.none(),  # Пустой queryset по умолчанию, заполняется динамически
        required=False,
        label="Партия",
        widget=forms.Select(attrs={
            'class': 'form-control form-control-lg',
        }),
        empty_label="--- Без указания партии ---"
    )
    
    class Meta:
        model = PickTask
        fields = ['product', 'batch', 'quantity', 'from_location', 'to_location', 'supply_request']
        
        widgets = {
            'quantity': forms.NumberInput(attrs={
                'step': '0.01', 
                'class': 'form-control form-control-lg',
                'placeholder': 'Количество для отбора'
            }),
            'from_location': forms.Select(attrs={
                'class': 'form-control form-control-lg'
            }),
            'to_location': forms.Select(attrs={
                'class': 'form-control form-control-lg'
            }),
            'supply_request': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.db.models import Sum, OuterRef, Subquery
        
        # ВСЕ активные товары (не только с остатками, т.к. может быть заказ поставщику)
        self.fields['product'] = forms.ModelChoiceField(
            queryset=Product.objects.filter(
                is_active=True
            ).annotate(
                total_qty=Sum('stock_levels__quantity')
            ).distinct().order_by('sku'),
            widget=forms.Select(attrs={'class': 'form-control form-control-lg'}),
            label="Товар",
            empty_label="--- Выберите товар ---"
        )
        
        # Локации только с остатками для выбора "Откуда"
        self.fields['from_location'].queryset = Location.objects.filter(
            stock_levels__quantity__gt=0
        ).annotate(
            has_stock=Sum('stock_levels__quantity')
        ).distinct().order_by('code')

        # Локации только зоны хранения и отгрузки для "Куда"
        self.fields['to_location'].queryset = Location.objects.filter(
            area__in=['STOR', 'PICK', 'SHIP']
        ).order_by('code')
        
        # Подписи для удобства
        self.fields['from_location'].label = "Откуда взять (локация хранения)"
        self.fields['to_location'].label = "Куда доставить (зона отгрузки/комплектации)"
        self.fields['product'].label_from_instance = lambda obj: \
            f"{obj.sku} | {obj.name} (всего на складах: {obj.total_qty or 0} {obj.get_unit_display()})"
        
        # Если указан товар — фильтруем партии
        if self.data.get('product') or self.initial.get('product'):
            product_id = self.data.get('product') or self.initial.get('product')
            try:
                product = Product.objects.get(pk=product_id)
                self.fields['batch'].queryset = Batch.objects.filter(
                    product=product,
                    stock__quantity__gt=0
                ).distinct().order_by('expiry_date')
                
                # Добавляем отображение срока годности и остатка
                self.fields['batch'].label_from_instance = lambda obj: \
                    f"{obj.lot_number} | Срок: {obj.expiry_date or '—'} | Остаток: {obj.stock_set.filter(quantity__gt=0).first().quantity if obj.stock_set.filter(quantity__gt=0).exists() else 0}"
                    
            except Product.DoesNotExist:
                pass
        
class ProductFilterForm(forms.Form):
    q = forms.CharField(
        required=False, 
        label="Поиск",
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Артикул, название или штрихкод...'
        })
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.all(),
        required=False,
        label="Поставщик",
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label="— Все —"
    )
    abc_class = forms.ChoiceField(
        choices=[('', '— Все —'), ('A', 'A'), ('B', 'B'), ('C', 'C')],
        required=False,
        label="ABC",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    is_active = forms.ChoiceField(
        choices=[('', '— Все —'), ('1', 'Активные'), ('0', 'Неактивные')],
        required=False,
        label="Статус",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    has_stock = forms.BooleanField(
        required=False,
        label="В наличии",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )


class SupplierFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Поиск",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Название, ИНН, КПП, ОГРН, контакт...'
        })
    )
    is_approved = forms.ChoiceField(
        choices=[('', '— Все —'), ('1', 'Аккредитованные'), ('0', 'Неаккредитованные')],
        required=False,
        label="Аккредитация",
        widget=forms.Select(attrs={'class': 'form-control'})
    )


class LocationFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Поиск",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Код, описание или условия хранения...'
        })
    )
    area = forms.ChoiceField(
        choices=[('', '— Все —'), *Area.choices],
        required=False,
        label="Зона",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    has_stock = forms.BooleanField(
        required=False,
        label="Есть остатки",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )


class SupplyRequestFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Поиск",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Номер, объект, адрес, контакт, заявитель...'
        })
    )
    object = forms.ModelChoiceField(
        queryset=Object.objects.none(),
        required=False,
        label="Объект",
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label='— Все —'
    )
    priority = forms.ChoiceField(
        choices=[('', '— Все —'), *SupplyRequest.PRIORITIES],
        required=False,
        label="Приоритет",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    status = forms.ChoiceField(
        choices=[('', '— Все —'), *SupplyRequest.STATUSES],
        required=False,
        label="Статус",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['object'].queryset = Object.objects.order_by('code')


class PickTaskFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="Поиск",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Заявка, объект, адрес, товар, заявитель...'
        })
    )
    priority = forms.ChoiceField(
        choices=[('', '— Все —'), *SupplyRequest.PRIORITIES],
        required=False,
        label="Приоритет",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    request_status = forms.ChoiceField(
        choices=[('', '— Все —'), *SupplyRequest.STATUSES],
        required=False,
        label="Статус заявки",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    group_type = forms.ChoiceField(
        choices=[
            ('', '— Все —'),
            ('with_tasks', 'Только с задачами'),
            ('without_tasks', 'Только без задач'),
        ],
        required=False,
        label="Показать",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
