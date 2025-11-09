from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple, cast

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from store.models import Developer, Genre, Game, Screenshot
from store.steam_api import requests, fetch_app_and_images, fetch_appdetails


def upsert_game_from_appdetails(appid: int, data: Dict[str, Any]) -> Tuple[Game, bool]:
    title = str(data.get('name') or data.get('title') or f'App {appid}')
    description = (
        data.get('short_description')
        or data.get('about_the_game')
        or data.get('detailed_description')
        or ''
    )

    # Developer
    developer = None
    devs = cast(List[str], data.get('developers') or [])
    if devs:
        developer, _ = Developer.objects.get_or_create(name=devs[0])

    # Genres
    genre_objs: List[Genre] = []
    for g in cast(List[Any], data.get('genres') or []):
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
                original_price = Decimal(str(init_cents)) / Decimal('100')
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

    # Update core fields
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
    rd = (data.get('release_date') or {}).get('date') if isinstance(data.get('release_date'), dict) else None
    if rd and isinstance(rd, str):
        for fmt in ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B %Y"):
            try:
                game.release_date = datetime.strptime(rd, fmt).date()
                break
            except Exception:
                continue

    # discounts
    game.discount_percent = discount_percent or 0
    game.original_price = original_price if discount_percent > 0 else None

    game.save()
    if genre_objs:
        game.genres.set(genre_objs)

    return game, created


def collect_appids_from_featuredcategories(cc: str, lang: str) -> tuple[List[int], dict[str, set[int]]]:
    url = f'https://store.steampowered.com/api/featuredcategories?cc={cc}&l={lang}'
    resp = requests.get(url, timeout=12)
    resp.raise_for_status()
    j = resp.json()

    appids: List[int] = []
    seen: Set[int] = set()
    bucket_ids: dict[str, set[int]] = {
        'top_sellers': set(),
        'new_releases': set(),
        'specials': set(),
        'coming_soon': set(),
        'new_on_steam': set(),
    }

    def pick(arr: Iterable[Dict[str, Any]]):
        for item in arr:
            if not item:
                continue
            appid = item.get('id') or item.get('appid') or item.get('id')
            if not appid:
                continue
            try:
                aid = int(appid)
            except Exception:
                continue
            if aid not in seen:
                seen.add(aid)
                appids.append(aid)

    # buckets include: specials, coming_soon, new_releases, top_sellers, new_on_steam
    specials = (j.get('specials') or {}).get('items') or []
    coming_soon = (j.get('coming_soon') or {}).get('items') or []
    new_releases = (j.get('new_releases') or {}).get('items') or []
    top_sellers = (j.get('top_sellers') or {}).get('items') or []
    new_on_steam = (j.get('new_on_steam') or {}).get('items') or []

    # fill per-bucket id sets and merged appids
    for item in specials:
        aid = item.get('id') or item.get('appid')
        try:
            aid = int(aid)
            bucket_ids['specials'].add(aid)
        except Exception:
            pass
    for item in top_sellers:
        aid = item.get('id') or item.get('appid')
        try:
            aid = int(aid)
            bucket_ids['top_sellers'].add(aid)
        except Exception:
            pass
    for item in new_releases:
        aid = item.get('id') or item.get('appid')
        try:
            aid = int(aid)
            bucket_ids['new_releases'].add(aid)
        except Exception:
            pass
    for item in coming_soon:
        aid = item.get('id') or item.get('appid')
        try:
            aid = int(aid)
            bucket_ids['coming_soon'].add(aid)
        except Exception:
            pass
    for item in new_on_steam:
        aid = item.get('id') or item.get('appid')
        try:
            aid = int(aid)
            bucket_ids['new_on_steam'].add(aid)
        except Exception:
            pass

    for bucket in (specials, top_sellers, new_releases, coming_soon, new_on_steam):
        pick(bucket)

    return appids, bucket_ids


class Command(BaseCommand):
    help = "Импорт коллекций игр из Steam (featuredcategories) + опционально из файла со списком AppID. Загружает изображения."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument('--cc', default='us', help='Country code (по умолчанию: us)')
        parser.add_argument('--lang', default='en', help='Language (по умолчанию: en)')
        parser.add_argument('--max', type=int, default=80, help='Максимум игр для импорта')
        parser.add_argument('--max-images', type=int, default=3, help='Максимум изображений на игру')
        parser.add_argument('--from-file', type=str, help='Путь к файлу со списком AppID (по одному в строке)')

    def handle(self, *args: Any, **opts: Any) -> None:
        cc = str(opts.get('cc') or 'us')
        lang = str(opts.get('lang') or 'en')
        limit = int(opts.get('max') or 80)
        max_images = int(opts.get('max_images') or opts.get('max-images') or 3)

        appids, bucket_ids = collect_appids_from_featuredcategories(cc, lang)

        # optional curated additions from file
        file_path = opts.get('from_file')
        if file_path:
            p = Path(file_path)
            if p.exists():
                for line in p.read_text(encoding='utf-8').splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        aid = int(line)
                    except Exception:
                        continue
                    if aid not in appids:
                        appids.append(aid)

        # trim
        appids = appids[:limit]

        created = 0
        updated = 0
        downloaded_images = 0

        for appid in appids:
            try:
                result = fetch_app_and_images(appid, max_images=max_images)
            except Exception as e:
                self.stderr.write(f"Fetch failed for {appid}: {e}")
                continue
            data = result.get('app')
            if not data:
                self.stderr.write(f"No data for {appid}")
                continue
            game, is_created = upsert_game_from_appdetails(appid, data)
            # mark homepage flags
            try:
                top_flag = appid in bucket_ids.get('top_sellers', set())
                new_flag = appid in bucket_ids.get('new_releases', set())
                changed = False
                if game.is_top_seller != top_flag:
                    game.is_top_seller = top_flag
                    changed = True
                if game.is_new_release != new_flag:
                    game.is_new_release = new_flag
                    changed = True
                if changed:
                    game.save(update_fields=['is_top_seller', 'is_new_release'])
            except Exception:
                pass
            # Create Screenshot objects and set cover from first
            imgs = result.get('images') or []
            if imgs:
                for idx, img_rel in enumerate(imgs):
                    try:
                        Screenshot.objects.get_or_create(game=game, image=img_rel, defaults={'order': idx})
                    except Exception:
                        pass
                if not game.cover_image:
                    try:
                        game.cover_image = imgs[0]
                        game.save(update_fields=['cover_image'])
                    except Exception:
                        pass
            if is_created:
                created += 1
            else:
                updated += 1
            downloaded_images += len(imgs)
            self.stdout.write(self.style.SUCCESS(f"✔ {game.title} (appid={appid}) — {'created' if is_created else 'updated'}"))

        self.stdout.write(self.style.WARNING(
            f"Готово: создано {created}, обновлено {updated}, скачано изображений {downloaded_images}"
        ))
