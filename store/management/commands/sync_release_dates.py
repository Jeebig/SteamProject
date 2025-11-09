from django.core.management.base import BaseCommand
from django.db import models, transaction
from datetime import datetime
from typing import Optional

from store.models import Game
from store.steam_api import fetch_appdetails


COMMON_FORMATS = (
    "%b %d, %Y",   # Nov 10, 2023
    "%d %b, %Y",   # 27 Oct, 2015
    "%B %d, %Y",   # November 10, 2023
    "%d %B, %Y",   # 27 October, 2015
    "%Y-%m-%d",    # 2023-11-10 (rare)
)


def parse_release_date(text: str) -> Optional[datetime.date]:
    if not text:
        return None
    t = text.strip()
    # Ignore generic or non-specific strings
    lowers = t.lower()
    if any(k in lowers for k in ("coming soon", "to be announced", "tba", "q1", "q2", "q3", "q4")):
        return None
    for fmt in COMMON_FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except Exception:
            continue
    # Try removing trailing markers like " (Early Access)"
    if "(" in t:
        base = t.split("(", 1)[0].strip()
        for fmt in COMMON_FORMATS:
            try:
                return datetime.strptime(base, fmt).date()
            except Exception:
                continue
    return None


class Command(BaseCommand):
    help = "Синхронизировать даты выхода игр из Steam (поле release_date)."

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None, help='Ограничить количество игр')
        parser.add_argument('--only-missing', action='store_true', help='Только игры без даты выхода')
        parser.add_argument('--dry-run', action='store_true', help='Только показать изменения, без сохранения')
        parser.add_argument('--language', type=str, default='en', help='Язык Steam; для парсинга надёжнее en')

    def handle(self, *args, **opts):
        qs = Game.objects.exclude(appid__isnull=True).order_by('id')
        if opts.get('only_missing'):
            qs = qs.filter(release_date__isnull=True)
        limit = opts.get('limit')
        if limit:
            qs = qs[:limit]
        dry = opts.get('dry_run')
        lang = opts.get('language') or 'en'

        total = 0
        updated = 0
        for g in qs:
            total += 1
            app = None
            try:
                app = fetch_appdetails(int(g.appid), language=lang)
            except Exception:
                app = None
            if not app:
                self.stdout.write(f"- {g.title}: нет данных от Steam")
                continue

            rd = (app.get('release_date') or {}) if isinstance(app, dict) else {}
            date_text = (rd.get('date') or '').strip()
            coming = bool(rd.get('coming_soon')) if isinstance(rd, dict) else False

            parsed = parse_release_date(date_text)
            if not parsed and not coming:
                self.stdout.write(f"- {g.title}: не удалось распарсить дату '{date_text}'")
                continue

            old = g.release_date
            new = parsed if parsed else old
            if old == new:
                self.stdout.write(f"= {g.title}: без изменений ({old})")
                continue

            self.stdout.write(self.style.WARNING(f"~ {g.title}: {old} → {new}"))
            if not dry:
                with transaction.atomic():
                    g.release_date = new
                    g.save(update_fields=['release_date'])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Готово: обработано {total}, обновлено {updated}"))
