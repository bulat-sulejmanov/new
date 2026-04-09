# warehouse/management/commands/abc_analysis.py
from django.core.management.base import BaseCommand
from warehouse.utils import calculate_abc_classification

class Command(BaseCommand):
    help = 'Пересчет ABC-классификации товаров'

    def handle(self, *args, **kwargs):
        self.stdout.write("Начинаю ABC-анализ...")
        calculate_abc_classification()
        self.stdout.write(self.style.SUCCESS("ABC-анализ завершен"))