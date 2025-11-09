from decimal import Decimal
from typing import Any, Dict, cast
import argparse

from django.core.management.base import BaseCommand

from store.models import Game
from store.steam_api import fetch_appdetails


class Command(BaseCommand):
    help = "Обновить цены, скидки и платформы у существующих игр по их Steam AppID (без загрузки изображений)."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument('--cc', default='us', help='Country code for pricing (default: us)')
        parser.add_argument('--lang', default='en', help='Language (default: en)')
        parser.add_argument('--only-discounted', action='store_true', help='Обновлять только если есть скидка')

    def handle(self, *args: Any, **options: Any) -> None:
        cc = options['cc']
        lang = options['lang']
        only_discounted = bool(options.get('only_discounted'))
        qs = Game.objects.filter(appid__isnull=False)
        total = qs.count()
        updated = 0
        price_changes = 0
        discount_changes = 0

        for game in qs.iterator():
            if game.appid is None:
                continue
            appid = int(game.appid)
            try:
                data = fetch_appdetails(appid, language=lang, cc=cc)
            except Exception as e:
                self.stderr.write(f"{game.title} (appid={appid}): fetch failed: {e}")
                continue
            if not data:
                self.stderr.write(f"{game.title} (appid={appid}): no data")
                continue

            pv: Dict[str, Any] = cast(Dict[str, Any], data.get('price_overview') or {})
            if only_discounted and not pv.get('discount_percent'):
                continue

            old_price = game.price
            old_disc = game.discount_percent

            # price and discount
            if pv:
                try:
                    final_cents = int(pv.get('final') or 0)
                    init_cents = int(pv.get('initial') or 0)
                    discount_percent = int(pv.get('discount_percent') or 0)
                    currency = str(pv.get('currency') or game.currency)

                    game.price = (Decimal(str(final_cents)) / Decimal('100'))
                    game.currency = currency
                    game.discount_percent = discount_percent
                    if discount_percent > 0 and init_cents:
                        game.original_price = (Decimal(str(init_cents)) / Decimal('100'))
                    else:
                        game.original_price = None
                except Exception:
                    pass

            # platforms
            plats: Dict[str, Any] = cast(Dict[str, Any], data.get('platforms') or {})
            game.supports_windows = bool(plats.get('windows'))
            game.supports_mac = bool(plats.get('mac'))
            game.supports_linux = bool(plats.get('linux'))

            game.save()
            updated += 1
            if game.price != old_price:
                price_changes += 1
            if game.discount_percent != old_disc:
                discount_changes += 1

            self.stdout.write(self.style.SUCCESS(f"✓ {game.title}: {old_price} → {game.price}, discount {old_disc}% → {game.discount_percent}%"))

        self.stdout.write(self.style.WARNING(
            f"Готово: обновлено {updated}/{total}, изменили цену {price_changes}, изменили скидку {discount_changes}"
        ))
