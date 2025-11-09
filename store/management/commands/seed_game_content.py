import os
import io
import math
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import shutil

from django.core.files import File
from django.core.management.base import BaseCommand
from django.conf import settings

from PIL import Image, ImageDraw, ImageFont
import requests

from store.models import Game, Screenshot


def ensure_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def quantize_money(x: Decimal) -> Decimal:
    return x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def create_placeholder_image(size=(1200, 500), title: str = "Game") -> Image.Image:
    w, h = size
    # Background gradient
    img = Image.new('RGB', (w, h), '#0b1f26')
    draw = ImageDraw.Draw(img)
    for y in range(h):
        # subtle teal gradient
        r, g, b = (11, 31 + int(20 * y / h), 38 + int(25 * y / h))
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # Frame
    draw.rectangle([(0, 0), (w - 1, h - 1)], outline=(10, 30, 36))

    # Title text centered
    try:
        font = ImageFont.truetype("arial.ttf", size=36)
    except Exception:
        font = ImageFont.load_default()

    text = title[:60]
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        # Fallback for older Pillow
        tw, th = font.getsize(text)
    draw.text(((w - tw) / 2, (h - th) / 2), text, font=font, fill=(220, 240, 245))
    return img


def copy_image_to_field(src_path: Path, dest_rel: str) -> File:
    """Copy a file from src_path into MEDIA_ROOT/dest_rel and return a Django File ready to save."""
    dest_path = Path(settings.MEDIA_ROOT) / dest_rel
    ensure_dir(dest_path)
    shutil.copyfile(src_path, dest_path)
    return File(open(dest_path, 'rb'))


def save_pil_to_field(img: Image.Image, dest_rel: str, format_: str = 'JPEG', quality: int = 88) -> File:
    dest_path = Path(settings.MEDIA_ROOT) / dest_rel
    ensure_dir(dest_path)
    buf = io.BytesIO()
    img.save(buf, format=format_, quality=quality)
    with open(dest_path, 'wb') as f:
        f.write(buf.getvalue())
    return File(open(dest_path, 'rb'))


def ensure_cover(game: Game) -> bool:
    """Ensure game has a cover_image. Returns True if modified."""
    if game.cover_image:
        return False
    cover_rel = f"covers/{game.slug}_cover.jpg"
    # Prefer local steam_imports header if available (or try to fetch)
    if game.appid:
        header = Path(settings.MEDIA_ROOT) / f"steam_imports/{game.appid}/header.jpg"
        if not header.exists():
            # try fetch from Steam CDN
            try:
                header.parent.mkdir(parents=True, exist_ok=True)
                url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{game.appid}/header.jpg"
                r = requests.get(url, timeout=10)
                if r.ok and r.content:
                    with open(header, 'wb') as f:
                        f.write(r.content)
            except Exception:
                pass
        if header.exists():
            game.cover_image.save(Path(cover_rel).name, copy_image_to_field(header, cover_rel), save=False)
            return True

    # Fallback: generate placeholder cover
    img = create_placeholder_image((1200, 500), game.title)
    game.cover_image.save(Path(cover_rel).name, save_pil_to_field(img, cover_rel), save=False)
    return True


def ensure_screenshots(game: Game, min_count: int = 3) -> int:
    """Ensure game has at least min_count screenshots. Returns number created."""
    created = 0
    existing = list(game.screenshots.all())
    if len(existing) >= min_count:
        return 0

    # Determine a source image (header or cover)
    src_path = None
    if game.appid:
        header = Path(settings.MEDIA_ROOT) / f"steam_imports/{game.appid}/header.jpg"
        if not header.exists():
            # attempt fetch so we can at least use header as source
            try:
                header.parent.mkdir(parents=True, exist_ok=True)
                url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{game.appid}/header.jpg"
                r = requests.get(url, timeout=10)
                if r.ok and r.content:
                    with open(header, 'wb') as f:
                        f.write(r.content)
            except Exception:
                pass
        if header.exists():
            src_path = header
    if not src_path and game.cover_image:
        try:
            src_path = Path(game.cover_image.path)
        except Exception:
            src_path = None

    needed = min_count - len(existing)
    base_index = len(existing)

    for i in range(needed):
        index = base_index + i + 1
        ss_rel = f"screenshots/{game.slug}_{index}.jpg"
        if src_path and src_path.exists():
            django_file = copy_image_to_field(src_path, ss_rel)
        else:
            # generate placeholder 960x540
            img = create_placeholder_image((960, 540), f"{game.title} — скриншот {index}")
            django_file = save_pil_to_field(img, ss_rel)

        Screenshot.objects.create(
            game=game,
            image=django_file,
            caption=f"Скриншот {index}",
            order=index,
        )
        created += 1
    return created


def ensure_description(game: Game) -> bool:
    if game.description and game.description.strip():
        return False
    genre_names = ", ".join(g.name for g in game.genres.all()[:3]) or "Экшн"
    dev = game.developer.name if game.developer else "Независимая студия"
    game.description = (
        f"<p><strong>{game.title}</strong> — {genre_names.lower()} от студии {dev}. "
        "Погрузитесь в атмосферный мир, где вас ждут яркие сражения, исследование локаций и продуманный прогресс.</p>"
        "<ul>"
        "<li>Насыщенная кампания и дополнительный свободный режим</li>"
        "<li>Глубокая настройка персонажа и экипировки</li>"
        "<li>Разнообразные испытания и достижения</li>"
        "</ul>"
        "<p>Игра оптимизирована для стабильной работы и поддерживает облачные сохранения."
        " Новые режимы и контент будут добавляться в будущих обновлениях.</p>"
    )
    return True


def classify_tier(game: Game) -> str:
    """Classify game into 'indie', 'mid', 'aaa' by price/genres."""
    price = game.price or Decimal('0')
    gnames = {g.name.lower() for g in game.genres.all()}
    # heuristics
    if price >= Decimal('29.99') or {'экшен', 'action', 'rpg', 'shooter', 'open world'} & gnames:
        return 'aaa'
    if price >= Decimal('14.99') or {'adventure', 'симулятор', 'strategy', 'platformer'} & gnames:
        return 'mid'
    return 'indie'


def build_sysreq_text(platform: str, level: str = 'min', tier: str = 'mid') -> str:
    if platform == 'win':
        os_line = 'Windows 10/11 (64-bit)'
    elif platform == 'mac':
        os_line = 'macOS 12 Monterey'
    else:
        os_line = 'Ubuntu 20.04 / SteamOS 3.0'

    # component presets by tier
    presets = {
        'indie': {
            'min': dict(cpu='Intel Core i3-4130', ram='4 GB ОЗУ', gpu='Intel HD 4600 / GT 730', storage='2 GB свободного места'),
            'rec': dict(cpu='Intel Core i5-6400', ram='8 GB ОЗУ', gpu='GTX 750 Ti / RX 460', storage='2 GB SSD пространства'),
        },
        'mid': {
            'min': dict(cpu='Intel Core i5-4570 / FX-8350', ram='8 GB ОЗУ', gpu='GTX 960 / R9 280 (2 GB)', storage='20 GB свободного места'),
            'rec': dict(cpu='Intel Core i7-6700 / Ryzen 5 2600', ram='16 GB ОЗУ', gpu='GTX 1060 / RX 580 (6 GB)', storage='20 GB SSD пространства'),
        },
        'aaa': {
            'min': dict(cpu='Intel Core i5-9600K / Ryzen 5 3600', ram='16 GB ОЗУ', gpu='GTX 1660 / RX 5600 (6 GB)', storage='60 GB свободного места'),
            'rec': dict(cpu='Intel Core i7-10700K / Ryzen 7 3700X', ram='16-24 GB ОЗУ', gpu='RTX 2060 / RX 6600 (8 GB)', storage='60 GB SSD пространства'),
        },
    }

    tier = tier if tier in presets else 'mid'
    comp = presets[tier][level]

    return (
        f"ОС: {os_line}\n"
        f"Процессор: {comp['cpu']}\n"
        f"Оперативная память: {comp['ram']}\n"
        f"Видеокарта: {comp['gpu']}\n"
        f"Место на диске: {comp['storage']}\n"
    )


def ensure_sysreqs(game: Game) -> bool:
    changed = False
    prefer = 'win' if game.supports_windows or not (game.supports_mac or game.supports_linux) else (
        'mac' if game.supports_mac else 'linux'
    )
    tier = classify_tier(game)
    if not game.sysreq_min or not game.sysreq_min.strip():
        game.sysreq_min = build_sysreq_text(prefer, 'min', tier)
        changed = True
    if not game.sysreq_rec or not game.sysreq_rec.strip():
        game.sysreq_rec = build_sysreq_text(prefer, 'rec', tier)
        changed = True
    return changed


def ensure_prices(game: Game) -> bool:
    """Fill original_price when discount_percent is set but original is missing; keep current price as discounted."""
    changed = False
    if game.price and game.discount_percent and (game.original_price is None or game.original_price <= Decimal('0.00')):
        # derive original_price from current price and discount
        # price = original * (1 - d/100) => original = price / (1 - d/100)
        d = Decimal(game.discount_percent) / Decimal(100)
        try:
            original = (Decimal(game.price) / (Decimal(1) - d)) if d < 1 else Decimal(game.price)
        except Exception:
            original = Decimal(game.price)
        game.original_price = quantize_money(original)
        changed = True
    return changed


class Command(BaseCommand):
    help = "Автозаполнение контента для вкладки игры: обложка, скриншоты, описание, системные требования, прайсы."

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None, help='Ограничить количество обработанных игр')
        parser.add_argument('--dry-run', action='store_true', help='Только показать план, без сохранения')
        parser.add_argument('--fetch', action='store_true', help='Пытаться скачать header.jpg из Steam CDN для appid')

    def handle(self, *args, **options):
        qs = Game.objects.all().order_by('id')
        limit = options.get('limit')
        dry = options.get('dry_run')
        if limit:
            qs = qs[:limit]

        total = 0
        updated = 0
        created_ss = 0

        for game in qs:
            total += 1
            changed = False

            # cover
            changed |= ensure_cover(game)
            # screenshots
            created_ss += ensure_screenshots(game, min_count=3)
            # description
            changed |= ensure_description(game)
            # sysreqs
            changed |= ensure_sysreqs(game)
            # prices (derive original if discount set)
            changed |= ensure_prices(game)

            if changed and not dry:
                game.save()
                updated += 1

            self.stdout.write(self.style.SUCCESS(
                f"✔ {game.title}: cover={'ok' if game.cover_image else 'gen'}; ss={game.screenshots.count()}; desc={'yes' if game.description else 'no'}; sysreq={'ok' if (game.sysreq_min and game.sysreq_rec) else 'no'}"
            ))

        self.stdout.write(self.style.WARNING(
            f"Обработано игр: {total}; обновлено: {updated}; создано скриншотов: {created_ss}"
        ))
