from django.core.management.base import BaseCommand, CommandError
from store.steam_api import fetch_app_and_images
from store.models import Developer, Genre, Game, Screenshot
from django.utils import timezone
from django.utils.text import slugify
from datetime import datetime


class Command(BaseCommand):
    help = 'Import apps from Steam by appid(s), download up to 3 images and create Game/Developer/Genre/Screenshot records.'

    def add_arguments(self, parser):
        parser.add_argument('appids', nargs='+', type=int, help='One or more Steam appids to import')

    def handle(self, *args, **options):
        appids = options['appids']
        for appid in appids:
            self.stdout.write(f'Importing appid={appid}...')
            try:
                result = fetch_app_and_images(appid, max_images=3)
            except Exception as e:
                self.stderr.write(f'Failed to fetch app {appid}: {e}')
                continue

            data = result.get('app')
            images = result.get('images', [])
            if not data:
                self.stderr.write(f'No data for appid {appid}')
                continue

            # Title and description
            title = data.get('name') or data.get('title') or f'App {appid}'
            description = data.get('short_description') or data.get('about_the_game') or data.get('detailed_description') or ''

            # Developer
            dev_name = None
            devs = data.get('developers') or []
            if devs:
                dev_name = devs[0]
            developer = None
            if dev_name:
                developer, _ = Developer.objects.get_or_create(name=dev_name)

            # Genres
            genres_raw = data.get('genres') or []
            genre_objs = []
            for g in genres_raw:
                # g can be dict with 'description' key
                name = g.get('description') if isinstance(g, dict) else g
                if name:
                    obj, _ = Genre.objects.get_or_create(name=name)
                    genre_objs.append(obj)

            # Price and discounts (Steam returns price_overview dict)
            price = 0
            currency = 'USD'
            original_price = None
            discount_percent = 0
            pv = data.get('price_overview') or {}
            if pv:
                try:
                    price = (pv.get('final', 0) or 0) / 100.0
                    currency = pv.get('currency', 'USD')
                    discount_percent = int(pv.get('discount_percent') or 0)
                    init_cents = pv.get('initial', 0) or 0
                    if discount_percent > 0 and init_cents:
                        original_price = init_cents / 100.0
                except Exception:
                    price = 0

            # Create or update Game (store appid)
            # ensure slug uniqueness by appending appid to slug
            base_slug = slugify(title) or f'app-{appid}'
            unique_slug = f"{base_slug}-{appid}"
            game, created = Game.objects.get_or_create(appid=appid, defaults={
                'description': description,
                'price': price,
                'currency': currency,
                'release_date': None,
                'developer': developer,
                'title': title,
                'slug': unique_slug,
            })
            if not created:
                # update some fields
                game.description = description
                game.price = price
                game.currency = currency
                if developer:
                    game.developer = developer
                game.save()

            # discount fields
            if original_price is not None:
                game.original_price = original_price
            game.discount_percent = discount_percent or 0

            # platforms flags
            plats = data.get('platforms') or {}
            game.supports_windows = bool(plats.get('windows'))
            game.supports_mac = bool(plats.get('mac'))
            game.supports_linux = bool(plats.get('linux'))

            # release date (best-effort parse)
            rd = (data.get('release_date') or {}).get('date')
            if rd and isinstance(rd, str):
                parsed = None
                for fmt in ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B %Y"):
                    try:
                        parsed = datetime.strptime(rd, fmt).date()
                        break
                    except Exception:
                        continue
                if parsed:
                    game.release_date = parsed

            game.save()

            # attach genres
            if genre_objs:
                game.genres.set(genre_objs)

            # create screenshots records from downloaded images and set cover if empty
            for idx, img_rel in enumerate(images):
                ss, _ = Screenshot.objects.get_or_create(game=game, image=img_rel, defaults={'order': idx})
            if images and not game.cover_image:
                try:
                    game.cover_image = images[0]
                    game.save(update_fields=['cover_image'])
                except Exception:
                    pass

            self.stdout.write(self.style.SUCCESS(f'Imported {title} (appid={appid}) with {len(images)} images'))