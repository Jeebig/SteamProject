from django.core.management.base import BaseCommand
from django.db import models, transaction

from store.models import Game
from store.steam_api import fetch_appdetails


class Command(BaseCommand):
    help = "Синхронизировать платформенные флаги игр (Windows/macOS/Linux) по данным Steam appdetails."

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None, help='Ограничить количество игр')
        parser.add_argument('--only-missing', action='store_true', help='Только игры без явных флагов (все False)')
        parser.add_argument('--reset', action='store_true', help='Принудительно выставлять False, если в Steam платформа не поддерживается')
        parser.add_argument('--dry-run', action='store_true', help='Только показать изменения, без сохранения')
        parser.add_argument('--language', type=str, default='en', help='Язык запроса (необязателен для платформ)')

    def handle(self, *args, **opts):
        qs = Game.objects.exclude(appid__isnull=True).order_by('id')
        if opts.get('only_missing'):
            qs = qs.filter(supports_windows=False, supports_mac=False, supports_linux=False)
        limit = opts.get('limit')
        if limit:
            qs = qs[:limit]
        dry = opts.get('dry_run')
        reset = opts.get('reset')
        lang = opts.get('language') or 'en'

        total = 0
        updated = 0
        for g in qs:
            total += 1
            try:
                app = fetch_appdetails(int(g.appid), language=lang)
            except Exception:
                app = None
            if not app:
                self.stdout.write(f"- {g.title}: нет данных от Steam")
                continue

            plats = (app.get('platforms') or {}) if isinstance(app, dict) else {}
            win = bool(plats.get('windows'))
            mac = bool(plats.get('mac'))
            lin = bool(plats.get('linux'))

            new_win = win or (g.supports_windows if not reset else False)
            new_mac = mac or (g.supports_mac if not reset else False)
            new_lin = lin or (g.supports_linux if not reset else False)

            # If reset=True, set exactly to Steam values
            if reset:
                new_win, new_mac, new_lin = win, mac, lin

            if (g.supports_windows, g.supports_mac, g.supports_linux) == (new_win, new_mac, new_lin):
                self.stdout.write(f"= {g.title}: без изменений (W:{g.supports_windows} M:{g.supports_mac} L:{g.supports_linux})")
                continue

            self.stdout.write(self.style.WARNING(
                f"~ {g.title}: W {g.supports_windows}→{new_win}, M {g.supports_mac}→{new_mac}, L {g.supports_linux}→{new_lin}"
            ))

            if not dry:
                with transaction.atomic():
                    g.supports_windows = new_win
                    g.supports_mac = new_mac
                    g.supports_linux = new_lin
                    g.save(update_fields=['supports_windows', 'supports_mac', 'supports_linux'])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Готово: обработано {total}, обновлено {updated}"))
