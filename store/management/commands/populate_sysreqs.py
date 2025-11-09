from django.core.management.base import BaseCommand
from django.db import transaction, models
from typing import Optional, Tuple
import re
import html

from store.models import Game
from store.steam_api import fetch_appdetails


BR_RE = re.compile(r"<\s*br\s*/?>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(s: str) -> str:
    if not s:
        return ""
    # Normalize <br> to newlines, strip tags, unescape entities, collapse extra blank lines
    s = BR_RE.sub("\n", s)
    s = TAG_RE.sub("", s)
    s = html.unescape(s)
    # Normalize Windows/Mac newlines
    lines = [ln.strip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    # drop consecutive empties
    out = []
    for ln in lines:
        if not ln and (not out or not out[-1]):
            continue
        out.append(ln)
    return "\n".join(out).strip()


def choose_platform(game: Game, prefer: Optional[str] = None) -> str:
    if prefer in {"win", "mac", "linux"}:
        return prefer
    # Auto by flags; default to win
    if getattr(game, "supports_windows", False):
        return "win"
    if getattr(game, "supports_mac", False):
        return "mac"
    if getattr(game, "supports_linux", False):
        return "linux"
    return "win"


def extract_requirements(app: dict, platform: str) -> Tuple[Optional[str], Optional[str]]:
    # Steam returns fields like pc_requirements / mac_requirements / linux_requirements
    key = {
        "win": "pc_requirements",
        "mac": "mac_requirements",
        "linux": "linux_requirements",
    }[platform]
    data = app.get(key) or {}
    # Some apps return list or string; normalize to dict
    if isinstance(data, list):
        # pick first element heuristically
        data = data[0] if data else {}
    if isinstance(data, str):
        # only one block provided
        return html_to_text(data), None
    if not isinstance(data, dict):
        return None, None
    minimum = data.get("minimum")
    recommended = data.get("recommended")
    return html_to_text(minimum) if minimum else None, html_to_text(recommended) if recommended else None


# Heuristic fallback when Steam doesn't provide reqs
from decimal import Decimal

def classify_tier(game: Game) -> str:
    price = game.price or Decimal("0")
    gnames = {g.name.lower() for g in game.genres.all()}
    if price >= Decimal("29.99") or {"экшен", "action", "rpg", "shooter", "open world"} & gnames:
        return "aaa"
    if price >= Decimal("14.99") or {"adventure", "симулятор", "strategy", "platformer"} & gnames:
        return "mid"
    return "indie"


def build_sysreq_text(platform: str, level: str = "min", tier: str = "mid") -> str:
    if platform == "win":
        os_line = "Windows 10/11 (64-bit)"
    elif platform == "mac":
        os_line = "macOS 12 Monterey"
    else:
        os_line = "Ubuntu 20.04 / SteamOS 3.0"

    presets = {
        "indie": {
            "min": dict(cpu="Intel Core i3-4130", ram="4 GB ОЗУ", gpu="Intel HD 4600 / GT 730", storage="2 GB свободного места"),
            "rec": dict(cpu="Intel Core i5-6400", ram="8 GB ОЗУ", gpu="GTX 750 Ti / RX 460", storage="2 GB SSD пространства"),
        },
        "mid": {
            "min": dict(cpu="Intel Core i5-4570 / FX-8350", ram="8 GB ОЗУ", gpu="GTX 960 / R9 280 (2 GB)", storage="20 GB свободного места"),
            "rec": dict(cpu="Intel Core i7-6700 / Ryzen 5 2600", ram="16 GB ОЗУ", gpu="GTX 1060 / RX 580 (6 GB)", storage="20 GB SSD пространства"),
        },
        "aaa": {
            "min": dict(cpu="Intel Core i5-9600K / Ryzen 5 3600", ram="16 GB ОЗУ", gpu="GTX 1660 / RX 5600 (6 GB)", storage="60 GB свободного места"),
            "rec": dict(cpu="Intel Core i7-10700K / Ryzen 7 3700X", ram="16-24 GB ОЗУ", gpu="RTX 2060 / RX 6600 (8 GB)", storage="60 GB SSD пространства"),
        },
    }

    tier = tier if tier in presets else "mid"
    comp = presets[tier]["min" if level == "min" else "rec"]
    return (
        f"ОС: {os_line}\n"
        f"Процессор: {comp['cpu']}\n"
        f"Оперативная память: {comp['ram']}\n"
        f"Видеокарта: {comp['gpu']}\n"
        f"Место на диске: {comp['storage']}\n"
    )


class Command(BaseCommand):
    help = "Заполнить системные требования игр из Steam (по appid) с умным запасным вариантом."

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None, help='Ограничить количество игр')
        parser.add_argument('--only-missing', action='store_true', help='Только для игр без требований')
        parser.add_argument('--language', type=str, default='ru', help='Язык данных Steam (ru/en/...)')
        parser.add_argument('--prefer', type=str, default='auto', help='Предпочесть платформу: auto|win|mac|linux')
        parser.add_argument('--dry-run', action='store_true', help='Показать план без сохранения')

    def handle(self, *args, **opts):
        qs = Game.objects.all().order_by('id')
        if opts.get('only_missing'):
            qs = qs.filter(models.Q(sysreq_min__isnull=True) | models.Q(sysreq_min='') | models.Q(sysreq_rec__isnull=True) | models.Q(sysreq_rec=''))
        limit = opts.get('limit')
        if limit:
            qs = qs[:limit]
        lang = opts.get('language') or 'ru'
        prefer_opt = opts.get('prefer')
        dry = opts.get('dry_run')

        updated = 0
        total = 0
        for game in qs:
            total += 1
            plat = choose_platform(game, prefer=None if prefer_opt == 'auto' else prefer_opt)
            min_txt = None
            rec_txt = None
            if game.appid:
                # Try primary language, then fallback to English
                app = None
                try:
                    app = fetch_appdetails(int(game.appid), language=lang)
                    if not app and lang != 'en':
                        app = fetch_appdetails(int(game.appid), language='en')
                except Exception:
                    app = None
                if app:
                    min_txt, rec_txt = extract_requirements(app, plat)
                    # If chosen platform empty, try Windows as a common fallback from Steam
                    if not (min_txt or rec_txt):
                        alt_min, alt_rec = extract_requirements(app, 'win')
                        min_txt = min_txt or alt_min
                        rec_txt = rec_txt or alt_rec

            # Heuristic fallback
            if not (min_txt or rec_txt):
                tier = classify_tier(game)
                min_txt = build_sysreq_text(plat, 'min', tier)
                rec_txt = build_sysreq_text(plat, 'rec', tier)

            old_min = (game.sysreq_min or '').strip()
            old_rec = (game.sysreq_rec or '').strip()
            new_min = (min_txt or '').strip()
            new_rec = (rec_txt or '').strip()

            if not new_min and old_min:
                new_min = old_min
            if not new_rec and old_rec:
                new_rec = old_rec

            if old_min == new_min and old_rec == new_rec:
                self.stdout.write(f"= {game.title}: без изменений")
                continue

            self.stdout.write(self.style.WARNING(f"~ {game.title}: обновление требований"))
            self.stdout.write("  - MIN:\n" + (new_min or '(пусто)'))
            self.stdout.write("  - REC:\n" + (new_rec or '(пусто)'))

            if not dry:
                with transaction.atomic():
                    game.sysreq_min = new_min
                    game.sysreq_rec = new_rec
                    game.save(update_fields=['sysreq_min', 'sysreq_rec'])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Готово: обработано {total}, обновлено {updated}"))
