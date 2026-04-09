# warehouse/signals.py
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import SupplyRequestItem, PickTask, PurchaseOrder

# Хранилище для отслеживания старых статусов
_status_tracker = {}


@receiver(post_save, sender=SupplyRequestItem)
def auto_approve_request(sender, instance, created, **kwargs):
    """Автоматическая смена статуса на УТВЕРЖДЕНО при добавлении первой позиции"""
    if created and instance.request.status == 'DRAFT':
        instance.request.status = 'APPROVED'
        instance.request.save(update_fields=['status'])


@receiver(post_save, sender=PickTask)
def auto_update_request_status(sender, instance, **kwargs):
    """Автоматический пересчет статуса заявки при выполнении задачи"""
    if instance.is_done and instance.supply_request:
        instance.supply_request.check_completion()


@receiver(pre_save, sender=PurchaseOrder)
def track_po_status(sender, instance, **kwargs):
    """Отслеживаем старый статус перед сохранением заказа поставщику."""
    if instance.pk:
        try:
            old_instance = PurchaseOrder.objects.get(pk=instance.pk)
            _status_tracker[instance.pk] = old_instance.status
        except PurchaseOrder.DoesNotExist:
            _status_tracker[instance.pk] = None
    else:
        _status_tracker[instance.pk] = None


@receiver(post_save, sender=PurchaseOrder)
def auto_fill_prices_on_receive(sender, instance, created, **kwargs):
    """
    Автоприход и обновление цен теперь выполняются в views.receive_purchase_order()
    внутри транзакции с нормальной обработкой ошибок для пользователя.
    Сигнал оставлен только для совместимости и очистки трекера статуса.
    """
    _status_tracker.pop(instance.pk, None)
    return
