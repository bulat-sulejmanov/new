import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model

from warehouse.models import (
    Supplier, Object, MaterialGroup, Location, Product, 
    Batch, Stock, StockMove, PurchaseOrder, POItem,
    SupplyRequest, SupplyRequestItem, Reservation, PickTask
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Заполнение базы демонстрационными данными Техснаб'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Удаляем старые данные...'))
        
        PickTask.objects.all().delete()
        StockMove.objects.all().delete()
        Reservation.objects.all().delete()
        SupplyRequestItem.objects.all().delete()
        SupplyRequest.objects.all().delete()
        POItem.objects.all().delete()
        PurchaseOrder.objects.all().delete()
        Stock.objects.all().delete()
        Batch.objects.all().delete()
        Product.objects.all().delete()
        Location.objects.all().delete()
        MaterialGroup.objects.all().delete()
        Object.objects.all().delete()
        Supplier.objects.all().delete()
        User.objects.all().delete()

        self.stdout.write(self.style.SUCCESS('Создаем демо-данные...'))

        self.create_users()
        self.create_suppliers()
        self.create_objects()
        self.create_material_groups()
        self.create_locations()
        self.create_products()
        self.create_batches()
        self.create_stock()
        self.create_stock_moves()
        self.create_purchase_orders()
        self.create_supply_requests()
        self.create_reservations()
        self.create_pick_tasks()

        self.stdout.write(self.style.SUCCESS('✅ Готово! База наполнена демо-данными.'))
        self.stdout.write(self.style.HTTP_INFO('''
Данные для входа:
- Админ: admin / admin123
- Снабженец: snab / snab123  
- Кладовщик: skidder / skidder123
        '''))

    def create_users(self):
        self.admin = User.objects.create_superuser('admin', 'admin@tatneft.tn', 'admin123', first_name='Админ')
        self.snab = User.objects.create_user('snab', 'snab@tatneft.tn', 'snab123', first_name='Иванов А.П.', is_staff=True)
        self.skidder = User.objects.create_user('skidder', 'sklad@tatneft.tn', 'skidder123', first_name='Петров В.С.', is_staff=True)
        self.user = User.objects.create_user('user', 'user@mail.ru', 'user123', first_name='Сидоров М.И.')
        self.stdout.write(f'  Создано пользователей: 4')

    def create_suppliers(self):
        suppliers_data = [
            ('ООО "Буровые технологии"', '1649051234', '164901001', '1021601234567', 'г. Альметьевск, ул. Ленина, 45'),
            ('АО "Татнефть-Снаб"', '1644001234', '164401001', '1021609876543', 'г. Альметьевск, ул. Рабочая, 12'),
            ('ООО "КИП-Сервис"', '1655012345', '165501001', '1151698765432', 'г. Казань, ул. Кремлевская, 15'),
            ('ООО "Промхим"', '1648034567', '164801001', '1021612345678', 'г. Набережные Челны, пр. Мира, 78'),
            ('ЗАО "Трубопроводные системы"', '1651023456', '165101001', '1021654321098', 'г. Альметьевск, ул. Нефтяников, 92'),
        ]
        
        self.suppliers = []
        for name, inn, kpp, ogrn, address in suppliers_data:
            s = Supplier.objects.create(
                name=name, inn=inn, kpp=kpp, ogrn=ogrn, address=address,
                email=f"info@{name.lower().replace(' ', '').replace(chr(34), '')}.ru",
                phone=f"+7({random.randint(900,999)}){random.randint(10,99)}-{random.randint(10,99)}-{random.randint(10,99)}",
                contact_person=f"Менеджер {random.randint(1,5)}",
                is_approved=True
            )
            self.suppliers.append(s)
        self.stdout.write(f'  Создано поставщиков: {len(self.suppliers)}')

    def create_objects(self):
        objects_data = [
            ('СКВ-145', 'WELL', 'Скважина №145 (добывающая)', 'НГДУ Азнакаево, куст 12'),
            ('СКВ-89', 'WELL', 'Скважина №89 (нагнетательная)', 'НГДУ Азнакаево, куст 8'),
            ('ЦЕХ-4', 'WORKSHOP', 'Цех подготовки нефти', 'НГДУ Альметьевск'),
            ('БУ-23', 'DRILL', 'Буровая установка №23', 'Площадь Ромашкино'),
            ('СКВ-210', 'WELL', 'Скважина №210 (добывающая)', 'НГДУ Южный, куст 45'),
        ]
        
        self.objects = []
        for code, obj_type, name, location in objects_data:
            obj = Object.objects.create(code=code, object_type=obj_type, name=name, location=location)
            self.objects.append(obj)
        self.stdout.write(f'  Создано объектов: {len(self.objects)}')

    def create_material_groups(self):
        groups = [
            ('KIP', 'КИП', 'КИПиА контрольно-измерительные приборы'),
            ('CHEM', 'ХИМ', 'Химические реагенты для добычи'),
            ('PIPE', 'ТРБ', 'Трубопродукция и запорная арматура'),
            ('ZIP', 'ЗИП', 'Запасные части'),
            ('PPE', 'СИЗ', 'Средства индивидуальной защиты'),
        ]
        
        self.groups = {}
        for code, cat, name in groups:
            mg = MaterialGroup.objects.create(code=code, name=name, category=cat)
            self.groups[code] = mg

    def create_locations(self):
        self.loc_recv = Location.objects.create(code='RECV-01', area='RECV', description='Зона разгрузки', capacity=1000)
        self.loc_stor1 = Location.objects.create(code='STOR-A1', area='STOR', description='Стеллаж A, ярус 1', capacity=500)
        self.loc_stor2 = Location.objects.create(code='STOR-A2', area='STOR', description='Стеллаж A, ярус 2', capacity=500)
        self.loc_stor3 = Location.objects.create(code='STOR-B1', area='STOR', description='Стеллаж B, зона химии', storage_conditions='Температура +5..+25')
        self.loc_stor4 = Location.objects.create(code='STOR-C1', area='STOR', description='Стеллаж C, КИП', capacity=300)
        self.loc_pick = Location.objects.create(code='PICK-01', area='PICK', description='Зона комплектации')
        self.loc_ship = Location.objects.create(code='SHIP-01', area='SHIP', description='Погрузочная площадка')
        
        self.locations_stor = [self.loc_stor1, self.loc_stor2, self.loc_stor3, self.loc_stor4]
        self.stdout.write(f'  Создано локаций: 6')

    def create_products(self):
        products_data = [
            ('KIP', 'Датчик давления МИДА-ДИ-13', 0, (10, 50, 20), 'EA', 5),
            ('KIP', 'Преобразователь расхода ПР-2М', 2, (5, 30, 15), 'EA', 4),
            ('KIP', 'Термометр сопротивления ТСП-108', 2, (15, 60, 25), 'EA', 3),
            ('CHEM', 'Реагент Праэсол-650 (канистра)', 3, (100, 500, 200), 'L', 4),
            ('CHEM', 'Метанол технический (бочка)', 3, (50, 200, 100), 'L', 5),
            ('CHEM', 'Ингибитор коррозии ИК-1', 1, (20, 100, 40), 'KG', 4),
            ('PIPE', 'Труба НКТ 73х5.5 (одна штанга)', 4, (30, 150, 50), 'M', 5),
            ('PIPE', 'Кран шаровый Ду50 Ру16', 4, (10, 40, 15), 'EA', 3),
            ('ZIP', 'Подшипник 305 (6315)', 1, (20, 80, 30), 'EA', 2),
            ('ZIP', 'Сальник 45х65', 1, (50, 200, 80), 'EA', 2),
            ('PPE', 'Комбинезон рабочий', 3, (20, 100, 40), 'EA', 2),
        ]
        
        self.products = []
        sku_counter = 1
        
        for idx, (group_code, name, sup_idx, (min_s, max_s, reorder), unit, critical) in enumerate(products_data):
            prefix = self.groups[group_code].code
            sku = f"{prefix}-{sku_counter:05d}"
            sku_counter += 1
            
            p = Product(
                sku=sku,
                name=name,
                unit=unit,
                material_group=self.groups[group_code],
                supplier=self.suppliers[sup_idx],
                min_stock=min_s,
                max_stock=max_s,
                reorder_point=reorder,
                critical_level=critical,
                lead_time_days=random.randint(5, 14),
                is_active=True
            )
            self.products.append(p)
        
        Product.objects.bulk_create(self.products)
        self.products = list(Product.objects.all())
        self.stdout.write(f'  Создано товаров: {len(self.products)}')

    def create_batches(self):
        now = timezone.now().date()
        
        for prod in self.products:
            if prod.material_group.code == 'CHEM':
                for i in range(2):
                    Batch.objects.create(
                        product=prod,
                        lot_number=f"{prod.sku}-2024-{i+1}",
                        manufacture_date=now - timedelta(days=random.randint(30, 180)),
                        expiry_date=now + timedelta(days=random.randint(180, 730)),
                        cert_number=f"СЕРТ-{random.randint(1000,9999)}",
                        cert_valid_until=now + timedelta(days=365)
                    )
            else:
                Batch.objects.create(
                    product=prod,
                    lot_number=f"{prod.sku}-2024-1",
                    manufacture_date=now - timedelta(days=random.randint(1, 60))
                )
        
        self.batches = list(Batch.objects.all())
        self.stdout.write(f'  Создано партий: {len(self.batches)}')

    def create_stock(self):
        for prod in self.products:
            total = int(prod.max_stock) if prod.max_stock > 0 else 100
            current = total
            
            prod_batches = [b for b in self.batches if b.product == prod]
            batch = prod_batches[0] if prod_batches else None
            
            loc = random.choice(self.locations_stor)
            qty = int(total * 0.7)
            if qty > 0:
                Stock.objects.create(product=prod, location=loc, batch=batch, quantity=qty)
                current -= qty
            
            if current > 0:
                loc2 = random.choice([l for l in self.locations_stor if l != loc])
                Stock.objects.create(product=prod, location=loc2, batch=batch, quantity=current)
        
        self.stdout.write(f'  Создано остатков: {Stock.objects.count()}')

    def create_stock_moves(self):
        for _ in range(20):
            prod = random.choice(self.products)
            move = StockMove(
                product=prod,
                from_location=random.choice(self.locations_stor),
                to_location=random.choice([self.loc_pick, self.loc_ship]),
                quantity=random.randint(1, 10),
                move_type='TRANSFER',
                reference='Пополнение зоны отбора',
                created_by=random.choice([self.admin, self.skidder]),
                created_at=timezone.now() - timedelta(days=random.randint(1, 30))
            )
            move.save()
        self.stdout.write(f'  Создано движений: 20')

    def create_purchase_orders(self):
        for i in range(3):
            po = PurchaseOrder.objects.create(
                number=f"ЗС-2024-{101+i}",
                supplier=random.choice(self.suppliers),
                status=random.choice(['DRAFT', 'PLACED', 'RECEIVED']),
                expected_date=timezone.now().date() + timedelta(days=random.randint(7, 30)),
                notes='Срочная поставка для текущего ремонта'
            )
            for _ in range(random.randint(2, 5)):
                POItem.objects.create(
                    po=po,
                    product=random.choice(self.products),
                    quantity=random.randint(10, 100),
                    price=Decimal(str(random.uniform(1000, 50000))).quantize(Decimal('0.01'))
                )
        self.stdout.write(f'  Создано заказов: 3')

    def create_supply_requests(self):
        statuses = ['DRAFT', 'APPROVED', 'IN_WORK', 'COMPLETED']
        
        for i, obj in enumerate(self.objects):
            sr = SupplyRequest.objects.create(
                number=f"ЗС-2024-{201+i}",
                object=obj,
                delivery_address=f"{obj.location}, {obj.code}",
                contact_person=f"Мастер {obj.code}",
                contact_phone=f"+7(917)123-45-{10+i}",
                required_date=timezone.now().date() + timedelta(days=random.randint(3, 14)),
                priority=random.choice(['NORMAL', 'HIGH', 'CRITICAL']),
                status=statuses[i % len(statuses)],
                notes=f'Плановое ТО для {obj.name}',
                created_by=random.choice([self.user, self.snab])
            )
            
            for _ in range(random.randint(1, 4)):
                SupplyRequestItem.objects.create(
                    request=sr,
                    product=random.choice(self.products),
                    quantity_requested=random.randint(5, 50)
                )
        self.stdout.write(f'  Создано заявок: {len(self.objects)}')

    def create_reservations(self):
        active_requests = SupplyRequest.objects.filter(status__in=['APPROVED', 'IN_WORK'])
        for sr in active_requests:
            for item in sr.items.all():
                Reservation.objects.create(
                    product=item.product,
                    object=sr.object,
                    quantity=item.quantity_requested,
                    planned_date=sr.required_date,
                    reserved_by=self.snab,
                    status='ACTIVE',
                    notes=f'Резерв по заявке {sr.number}'
                )
        self.stdout.write(f'  Создано резервов: {Reservation.objects.count()}')

    def create_pick_tasks(self):
        active_requests = SupplyRequest.objects.filter(status='IN_WORK')
        for sr in active_requests:
            for item in sr.items.all():
                stocks = Stock.objects.filter(product=item.product, quantity__gt=0)
                if stocks.exists():
                    stock = stocks.first()
                    PickTask.objects.create(
                        product=item.product,
                        batch=stock.batch,
                        quantity=item.quantity_requested,
                        from_location=stock.location,
                        to_location=self.loc_ship,
                        supply_request=sr,
                        assigned_to=self.skidder,
                        is_done=False
                    )
        self.stdout.write(f'  Создано задач на отбор: {PickTask.objects.count()}')