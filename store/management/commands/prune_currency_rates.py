from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from store.models import CurrencyRate


class Command(BaseCommand):
    help = "Удаляет записи CurrencyRate старше N дней (по умолчанию 7). Поддерживает --dry-run."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7, help='Сколько дней хранить курсы (по умолчанию 7)')
        parser.add_argument('--dry-run', action='store_true', help='Показать количество к удалению, но не удалять')
        parser.add_argument('--batch', type=int, default=2000, help='Размер пачки удаления (по умолчанию 2000)')

    def handle(self, *args, **options):
        days = max(options['days'], 1)
        cutoff = timezone.now() - timedelta(days=days)
        qs = CurrencyRate.objects.filter(fetched_at__lt=cutoff)
        total = qs.count()
        if options['dry_run']:
            self.stdout.write(self.style.WARNING(f"Будет удалено записей: {total} (старше {days} дн.)"))
            return
        batch = options['batch']
        deleted = 0
        while True:
            ids = list(qs.values_list('id', flat=True)[:batch])
            if not ids:
                break
            CurrencyRate.objects.filter(id__in=ids).delete()
            deleted += len(ids)
        self.stdout.write(self.style.SUCCESS(f"Удалено записей CurrencyRate: {deleted}"))
