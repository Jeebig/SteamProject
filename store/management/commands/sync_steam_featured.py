from django.core.management.base import BaseCommand
from store.steam_api import requests, fetch_app_and_images
from store.models import Developer, Genre, Game, Screenshot
from django.utils.text import slugify
from datetime import datetime
from typing import Any, Dict, Tuple, List, cast
from decimal import Decimal


def upsert_game_from_appdetails(appid: int, data: Dict[str, Any]) -> Tuple[Game, bool]:
    title = data.get('name') or data.get('title') or f'App {appid}'
    description = data.get('short_description') or data.get('about_the_game') or data.get('detailed_description') or ''

    # Developer
    developer = None
    devs = data.get('developers') or []
    if devs:
        developer, _ = Developer.objects.get_or_create(name=devs[0])

    # Genres
    genre_objs: List[Genre] = []
    genres_data: List[Any] = cast(List[Any], data.get('genres') or [])
    for g in genres_data:
        name = g.get('description') if isinstance(g, dict) else g
        if name:
            obj, _ = Genre.objects.get_or_create(name=name)
            genre_objs.append(obj)

    # Pricing / discounts
    price: Decimal = Decimal('0')
    currency: str = 'USD'
    original_price: Decimal | None = None
    discount_percent: int = 0
    pv: Dict[str, Any] = cast(Dict[str, Any], data.get('price_overview') or {})
    if pv:
        try:
            final_cents = int(pv.get('final') or 0)
            price = Decimal(str(final_cents)) / Decimal('100')
            currency = str(pv.get('currency') or 'USD')
            discount_percent = int(pv.get('discount_percent') or 0)
            init_cents = int(pv.get('initial') or 0)
            if discount_percent > 0 and init_cents:
                original_price = (Decimal(str(init_cents)) / Decimal('100'))
        except Exception:
            pass

    base_slug = slugify(title) or f'app-{appid}'
    unique_slug = f"{base_slug}-{appid}"
    game, created = Game.objects.get_or_create(appid=appid, defaults={
        'title': title,
        'slug': unique_slug,
        'description': description,
        'price': price,
        'currency': currency,
        'developer': developer,
    })
    # Update fields
    game.title = title
    game.description = description
    game.price = price
    game.currency = currency
    if developer:
        game.developer = developer

    # platforms
    plats: Dict[str, Any] = cast(Dict[str, Any], data.get('platforms') or {})
    game.supports_windows = bool(plats.get('windows'))
    game.supports_mac = bool(plats.get('mac'))
    game.supports_linux = bool(plats.get('linux'))

    # release date
    rd = (data.get('release_date') or {}).get('date')
    if rd and isinstance(rd, str):
        for fmt in ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B %Y"):
            try:
                game.release_date = datetime.strptime(rd, fmt).date()
                break
            except Exception:
                continue

    # discounts
    if original_price is not None:
        game.original_price = original_price
    game.discount_percent = discount_percent or 0

    game.save()
    if genre_objs:
        game.genres.set(genre_objs)

    return game, created


class Command(BaseCommand):
    help = "Импорт избранных/популярных игр из Steam Featured API и скачивание изображений."

    def add_arguments(self, parser):
        parser.add_argument('--cc', default='us', help='Country code for pricing (default: us)')
        parser.add_argument('--lang', default='en', help='Language (default: en)')
        parser.add_argument('--max', type=int, default=30, help='Максимум игр для импорта/обновления')

    def handle(self, *args, **opts):
        cc = opts['cc']
        lang = opts['lang']
        limit = int(opts['max'] or 30)
        url = f'https://store.steampowered.com/api/featured/?cc={cc}&l={lang}'
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        j = resp.json()

        buckets = []
        for key in ('large_capsules', 'featured_win', 'featured_mac', 'featured_linux'):
            arr = j.get(key) or []
            buckets.extend([x.get('id') for x in arr if x and x.get('id')])
        # unique appids, truncate
        appids = []
        seen = set()
        for a in buckets:
            if a not in seen:
                seen.add(a)
                appids.append(int(a))
            if len(appids) >= limit:
                break

        created_count = 0
        updated_count = 0
        downloaded_images = 0
        for appid in appids:
            try:
                res = fetch_app_and_images(appid, max_images=3)
            except Exception as e:
                self.stderr.write(f"Fetch failed for {appid}: {e}")
                continue
            data = res.get('app')
            if not data:
                self.stderr.write(f"No data for {appid}")
                continue
            game, created = upsert_game_from_appdetails(appid, data)
            # attach images as Screenshot records, set cover if empty
            imgs = res.get('images') or []
            if imgs:
                created_ss = 0
                for idx, img_rel in enumerate(imgs):
                    try:
                        Screenshot.objects.get_or_create(game=game, image=img_rel, defaults={'order': idx})
                        created_ss += 1
                    except Exception:
                        continue
                if not game.cover_image and imgs:
                    try:
                        game.cover_image = imgs[0]
                        game.save(update_fields=['cover_image'])
                    except Exception:
                        pass
            if created:
                created_count += 1
            else:
                updated_count += 1
            downloaded_images += len(imgs)
            self.stdout.write(self.style.SUCCESS(f"✔ {game.title} (appid={appid}) — {'created' if created else 'updated'}"))

        self.stdout.write(self.style.WARNING(f"Готово: создано {created_count}, обновлено {updated_count}, скачано изображений {downloaded_images}"))
