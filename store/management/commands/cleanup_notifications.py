from django.core.management.base import BaseCommand
from django.utils import timezone

from store.models import Notification


class Command(BaseCommand):
    help = "Удаляет устаревшие уведомления (expires_at < now). Поддерживает --dry-run."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Показать, сколько записей будет удалено, но не удалять')
        parser.add_argument('--batch', type=int, default=1000, help='Размер пачки удаления (по умолчанию 1000)')

    def handle(self, *args, **options):
        now = timezone.now()
        qs = Notification.objects.filter(expires_at__isnull=False, expires_at__lt=now)
        total = qs.count()
        dry = options['dry_run']
        batch = options['batch']
        if dry:
            self.stdout.write(self.style.WARNING(f"Будет удалено: {total} уведомлений"))
            return
        deleted = 0
        while True:
            ids = list(qs.values_list('id', flat=True)[:batch])
            if not ids:
                break
            Notification.objects.filter(id__in=ids).delete()
            deleted += len(ids)
        self.stdout.write(self.style.SUCCESS(f"Удалено уведомлений: {deleted}"))
