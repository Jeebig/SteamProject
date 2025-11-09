import os
from typing import Any, Iterable, Optional, Union, List, Dict, cast

from decimal import Decimal
from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.utils.text import slugify

from store.models import Game, OrderItem
from store.utils.currency import convert_amount

register = template.Library()


@register.filter
def file_exists(rel_path: str) -> bool:
    """Check if file exists in MEDIA_ROOT/rel_path."""
    abs_path = os.path.join(str(settings.MEDIA_ROOT), rel_path)
    return os.path.isfile(abs_path)


@register.filter
def nonheader(screenshots: Iterable[Any], count: int = 2) -> List[Any]:
    """Return first `count` screenshot objects whose file name does not contain 'header'.

    Usage in template: {% for s in g.screenshots.all|nonheader:2 %}
    """
    try:
        n = int(count)
    except (ValueError, TypeError):
        n = 2
    out: List[Any] = []
    for s in (screenshots or []):
        # try to access file name; support both FileField and simple dict-like
        fname = getattr(getattr(s, 'file', None), 'name', '') or str(getattr(s, 'file', ''))
        if 'header' in fname.lower():
            continue
        out.append(s)
        if len(out) >= n:
            break
    return out


@register.simple_tag
def local_screenshots(appid: Union[int, str], count: int = 2) -> List[str]:
    """Return list of MEDIA_URL paths for screenshots found in MEDIA_ROOT/steam_imports/<appid>/

    Excludes files with 'header' in the filename. Usage in template:
        {% local_screenshots g.appid 2 as local_shots %}
    """
    try:
        n = int(count)
    except (ValueError, TypeError):
        n = 2
    rel_dir = os.path.join('steam_imports', str(appid))
    abs_dir = os.path.join(str(settings.MEDIA_ROOT), rel_dir)
    if not os.path.isdir(abs_dir):
        return []
    try:
        files = sorted([f for f in os.listdir(abs_dir)
                        if os.path.isfile(os.path.join(abs_dir, f))
                        and 'header' not in f.lower()])
    except Exception:
        return []
    out: List[str] = []
    for f in files[:n]:
        # Build URL using MEDIA_URL and POSIX-style path
        rel_path = os.path.join(rel_dir, f).replace('\\', '/')
        out.append(str(settings.MEDIA_URL) + rel_path)
    return out


@register.simple_tag
def catalog_categories(catalog: Optional[Iterable[Any]], max_categories: int = 24) -> List[Dict[str, str]]:
    """Return a list of unique category dicts extracted from a catalog of games.

    - Tries game.tags (objects or strings) first
    - Falls back to game.genres (ManyToMany of Genre) when tags are absent

    Each item is a dict: {'name': <name>, 'slug': <slug>}.
    If an object has a "slug" attribute it will be used; otherwise it is generated
    from the name via slugify.

    Usage in template:
        {% catalog_categories catalog 24 as categories %}
    """
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    try:
        max_n = int(max_categories)
    except Exception:
        max_n = 24

    if not catalog:
        return out

    for g in catalog:
        # Prefer explicit tags if present; else use genres
        items = getattr(g, 'tags', None) or getattr(g, 'genres', None)
        if not items:
            continue

        # handle Django related manager (.all()) or plain iterable
        try:
            iterable = items.all() if hasattr(items, 'all') else items
        except Exception:
            iterable = items

        for t in iterable:
            name = str(getattr(t, 'name', t))
            if not name:
                continue
            slug = str(getattr(t, 'slug', '')) or slugify(name)
            if name in seen:
                continue
            seen.add(name)
            out.append({'name': name, 'slug': slug})
            if len(out) >= max_n:
                return out

    return out


@register.simple_tag
def paid_games(games: Optional[Iterable[Any]], min_count: int = 0, fallback: Optional[Iterable[Any]] = None) -> List[Any]:
    """Return a list of games from `games` that appear to be paid (price > 0 and not marked is_free).

    Optional parameters:
      min_count -- try to return at least this many items (default 0)
      fallback -- optional iterable (e.g. `catalog`) to draw additional paid items from if `games`
                  doesn't provide enough.

    Usage in template:
        {% paid_games promos as paid_promos %}
        {% paid_games promos 4 catalog as paid_promos %}
    """
    out: List[Any] = []
    if not games:
        games = []

    def _is_paid(item: Any) -> bool:
        try:
            price = getattr(item, 'price', None)
            is_free = getattr(item, 'is_free', False)
            if price is None:
                return False
            try:
                p = float(price)
            except Exception:
                return False
            return (p > 0) and (not is_free)
        except Exception:
            return False

    # First pass: take paid items from the primary iterable
    for g in games:
        if _is_paid(g):
            out.append(g)

    # If we need more and a fallback iterable is provided, draw from it
    try:
        min_n = int(min_count)
    except Exception:
        min_n = 0

    if min_n > 0 and len(out) < min_n and fallback:
        try:
            # If fallback is a queryset-like with .all(), prefer that
            if hasattr(fallback, 'all'):
                fb_iter: Iterable[Any] = cast(Iterable[Any], fallback.all())  # type: ignore[attr-defined]
            else:
                fb_iter: Iterable[Any] = fallback  # type: ignore[assignment]
        except Exception:
            fb_iter = cast(Iterable[Any], fallback or [])

        for g in fb_iter:
            if _is_paid(g) and g not in out:
                out.append(g)
                if len(out) >= min_n:
                    break

    return out


@register.simple_tag
def category_cover(category_slug: str, catalog: Optional[Iterable[Any]] = None) -> str:
    """Return a background image URL for a category/genre slug.

    Priority:
    1) Static curated image at static/store/categories/<slug>.(webp|jpg|png)
    2) A game from provided `catalog` iterable with this genre
    3) Any game from DB with this genre

    Image URL priority for a game:
    - game.cover_image.url
    - MEDIA_URL + steam_imports/<appid>/header.jpg (when file exists)
    - Steam CDN header by appid
    Returns empty string if nothing found.
    """
    # 1) curated static image, like Steam categories artwork
    rel_candidates = [
        f"store/categories/{category_slug}.webp",
        f"store/categories/{category_slug}.jpg",
        f"store/categories/{category_slug}.png",
        f"store/categories/{category_slug}.svg",
    ]
    for rel in rel_candidates:
        try:
            if finders.find(rel):
                return str(settings.STATIC_URL) + rel
        except Exception:
            pass
    # 1b) Mapping from settings for curated remote images (e.g., Steam-like category art)
    try:
        mapping = getattr(settings, 'STORE_CATEGORY_IMAGES', {}) or {}
        url = mapping.get(category_slug)
        if url:
            return url
    except Exception:
        pass
    # 1c) Generic curated default poster, if present — prefer it to game-based fallback for consistent look
    try:
        default_rel = "store/categories/default.svg"
        if finders.find(default_rel):
            return str(settings.STATIC_URL) + default_rel
    except Exception:
        pass
    # try to find a game in provided catalog first
    def iter_games(iterable: Optional[Iterable[Any]]) -> Iterable[Any]:
        if not iterable:
            return []
        try:
            if hasattr(iterable, 'all'):
                return cast(Iterable[Any], iterable.all())  # type: ignore[attr-defined]
            return iterable
        except Exception:
            return iterable or []

    candidate = None
    for g in iter_games(catalog):
        try:
            genres = getattr(g, 'genres', None)
            if genres and (hasattr(genres, 'filter') and genres.filter(slug=category_slug).exists() or any(getattr(x, 'slug', None) == category_slug for x in (genres.all() if hasattr(genres, 'all') else genres))):
                candidate = g
                break
        except Exception:
            continue

    if candidate is None:
        try:
            candidate = Game.objects.filter(genres__slug=category_slug).first()
        except Exception:
            candidate = None

    if not candidate:
        return ''

    # Build URL following priority
    try:
        if getattr(candidate, 'cover_image', None):
            url = candidate.cover_image.url
            if url:
                return url
    except Exception:
        pass

    appid = getattr(candidate, 'appid', None)
    if appid:
        rel = os.path.join('steam_imports', str(appid), 'header.jpg').replace('\\', '/')
        abs_path = os.path.join(str(settings.MEDIA_ROOT), rel)
        if os.path.isfile(abs_path):
            return str(settings.MEDIA_URL) + rel
        # fallback to cdn
        return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"

    return ''


@register.simple_tag
def convert_price(amount: Union[int, float, Decimal], from_currency: str, to_currency: str) -> Decimal:
    """Convert amount to another currency using convert_amount utility.

    Usage in template:
      {% convert_price game.price game.currency preferred_currency as price %}
    """
    try:
        return convert_amount(amount, from_currency, to_currency)
    except Exception:
        try:
            return Decimal(str(amount))
        except Exception:
            return Decimal('0.00')


@register.simple_tag
def is_owned(user: Any, game: Any) -> bool:
    """Return True if the user owns the given game (has a PAID order with this game).

    Usage in template:
      {% is_owned user game as owned %}
    """
    try:
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        return OrderItem.objects.filter(order__user=user, order__status='paid', game=game).exists()
    except Exception:
        return False


@register.simple_tag
def stars() -> list[int]:
    """Return a constant 1..5 list for star widgets in templates.

    Usage:
      {% stars as five %}
      {% for i in five %} ... {% endfor %}
    """
    return [1, 2, 3, 4, 5]


@register.simple_tag
def price_display(price: Union[int, float, Decimal, None], currency: str | None,
                  preferred_currency: str | None = None,
                  original_price: Union[int, float, Decimal, None] = None,
                  discount_percent: int | None = None) -> str:
    """Вернуть HTML блок цены с учётом скидки и конвертации.

    Логика:
    - Если итоговая цена 0 -> выводим перевод 'Бесплатно'.
    - Если есть скидка (discount_percent > 0 и original_price > price) выводим:
        - Значок процента
        - Зачёркнутую исходную цену (и её конвертированный эквивалент при смене валюты)
        - Итоговую цену + (≈ сконвертированная) если валюта отличается
    - Иначе обычная цена (+ ≈конвертированная при отличии валют)
    Все значения форматируются до 2 знаков.
    """
    from django.utils.html import format_html
    from django.utils.translation import gettext as _
    try:
        if price is None:
            return ''
        p = Decimal(str(price))
    except Exception:
        return ''
    cur = currency or ''
    # free case
    if p == 0:
        return format_html('<span class="text-green-300 font-semibold">{}</span>', _('Бесплатно'))

    # detect discount
    show_discount = False
    orig_dec = None
    if discount_percent and discount_percent > 0 and original_price is not None:
        try:
            orig_dec = Decimal(str(original_price))
            if orig_dec > p:
                show_discount = True
        except Exception:
            orig_dec = None

    # conversion
    conv_price = None
    conv_orig = None
    if preferred_currency and preferred_currency != cur:
        try:
            conv_price = convert_amount(p, cur, preferred_currency)
            if show_discount and orig_dec is not None:
                conv_orig = convert_amount(orig_dec, cur, preferred_currency)
        except Exception:
            conv_price = None

    parts: list[str] = []
    if show_discount and discount_percent:
        parts.append(f'<span class="px-1.5 py-0.5 rounded bg-green-700/40 border border-green-600 text-green-100 text-[11px] align-middle">-{discount_percent}%</span>')
        parts.append('<span class="line-through opacity-70 text-sm ml-1 align-middle">{orig} {cur}</span>'.format(
            orig=f"{orig_dec:.2f}" if orig_dec is not None else '', cur=cur))
        if conv_orig and preferred_currency and preferred_currency != cur:
            parts.append('<span class="line-through opacity-40 text-xs ml-1 align-middle">≈ {orig} {pc}</span>'.format(
                orig=f"{conv_orig:.2f}", pc=preferred_currency))
    # final price
    parts.append('<span class="ml-1 font-semibold align-middle">{price} {cur}</span>'.format(price=f"{p:.2f}", cur=cur))
    if conv_price and preferred_currency and preferred_currency != cur:
        parts.append('<span class="text-gray-400 text-xs ml-2 align-middle">≈ {cv:.2f} {pc}</span>'.format(cv=conv_price, pc=preferred_currency))
    return format_html(' '.join(parts))


# -----------------------------
# Pluralization helpers (ngettext wrappers)
# -----------------------------
from django.utils.translation import ngettext


@register.simple_tag
def n_reviews(count: Union[int, float, Decimal]) -> str:
    """Return a localized '<count> review(s)' string using ngettext.

    Example:
      {% n_reviews reviews_count %} -> '1 review' / '2 reviews' (localized)
    """
    try:
        c = int(count)
    except Exception:
        c = 0
    return ngettext("%(count)d review", "%(count)d reviews", c) % {"count": c}


@register.simple_tag
def n_games(count: Union[int, float, Decimal]) -> str:
    """Return a localized '<count> game(s)' string using ngettext."""
    try:
        c = int(count)
    except Exception:
        c = 0
    return ngettext("%(count)d game", "%(count)d games", c) % {"count": c}


@register.simple_tag
def n_minutes(count: Union[int, float, Decimal]) -> str:
    """Return a localized '<count> minute(s)' string using ngettext."""
    try:
        c = int(count)
    except Exception:
        c = 0
    return ngettext("%(count)d minute", "%(count)d minutes", c) % {"count": c}


# -----------------------------
# Markdown sanitize for profile bio
# -----------------------------
@register.filter(name='markdown_sanitize')
def markdown_sanitize(text: Any) -> str:
    """Render Markdown to HTML and sanitize using Bleach.

    Allowed tags/attrs are conservative: headings, emphasis, code, lists, links, paragraphs.
    Disallows images/iframes/scripts.
    """
    from django.utils.safestring import mark_safe
    try:
        s = str(text or '')
    except Exception:
        return ''
    if not s:
        return ''
    try:
        import markdown as _md  # type: ignore
        import bleach  # type: ignore
        # Render basic Markdown
        html = _md.markdown(s, extensions=['extra', 'sane_lists'])
        # Remove dangerous blocks entirely (strip tag + its content) before sanitizing
        try:
            import re as _re
            html = _re.sub(r'(?is)<script[^>]*>.*?</script>', '', html)
            html = _re.sub(r'(?is)<style[^>]*>.*?</style>', '', html)
        except Exception:
            pass
        # Normalize legacy HTML tags to semantic equivalents before sanitizing
        # e.g., <b> -> <strong>, <i> -> <em>
        try:
            import re as _re
            # open tags with optional attributes
            html = _re.sub(r"<\s*b(\s+[^>]*)?>", "<strong>", html, flags=_re.IGNORECASE)
            html = _re.sub(r"<\s*/\s*b\s*>", "</strong>", html, flags=_re.IGNORECASE)
            html = _re.sub(r"<\s*i(\s+[^>]*)?>", "<em>", html, flags=_re.IGNORECASE)
            html = _re.sub(r"<\s*/\s*i\s*>", "</em>", html, flags=_re.IGNORECASE)
        except Exception:
            pass
        allowed_tags = [
            'p', 'br', 'em', 'strong', 'code', 'pre', 'blockquote',
            'ul', 'ol', 'li', 'a', 'h1', 'h2', 'h3', 'h4'
        ]
        allowed_attrs = {
            'a': ['href', 'title', 'rel', 'target'],
        }
        clean = bleach.clean(
            html,
            tags=allowed_tags,
            attributes=allowed_attrs,
            protocols=['http', 'https', 'mailto'],
            strip=True,
        )
        # Ensure links get rel and target for safety/UX
        # Apply linkify with safe rel/target; bleach 6+ exposes default callbacks via bleach.linkifier
        try:
            from bleach.linkifier import Linker
            # Provide empty iterable for callbacks to satisfy type checkers
            linker = Linker(callbacks=())
            clean = linker.linkify(clean)
        except Exception:
            # Fallback: leave links as-is if linkifier not available
            pass
        return mark_safe(clean)
    except Exception:
        # If markdown/bleach not available, fall back to escaped text with simple breaks
        from django.utils.html import escape
        esc = escape(s).replace('\n', '<br>')
        return mark_safe(f"<p>{esc}</p>")


@register.filter
def get_item(d: Any, key: Any) -> Any:
    """Dictionary .get() helper for templates: {{ dict|get_item:key }}"""
    try:
        return d.get(key)
    except Exception:
        return None


@register.simple_tag
def star_fill(avg: Any, index: int) -> str:
    """Return 'full' | 'half' | 'empty' for a star index given an average rating.

    avg: numeric average (float/Decimal), e.g., 3.6
    index: 1-based star index
    Logic: full if avg >= index; half if avg >= index - 0.5; else empty.
    """
    try:
        from decimal import Decimal
        a = Decimal(str(avg))
        i = int(index)
    except Exception:
        return 'empty'
    if a >= i:
        return 'full'
    half_threshold = Decimal(i) - Decimal('0.5')
    if a >= half_threshold:
        return 'half'
    return 'empty'


@register.simple_tag
def star_steps() -> list[str]:
    """Return rating steps from 1.0 to 5.0 with 0.5 step as strings.

    Example: ['1.0','1.5',...,'5.0']
    """
    steps: list[str] = []
    for i in range(10):  # 0..9
        val = 1.0 + i * 0.5
        steps.append(f"{val:.1f}")
    return steps


# -----------------------------
# Image helpers (WebP variants)
# -----------------------------
from PIL import Image, ImageFile  # type: ignore
ImageFile.LOAD_TRUNCATED_IMAGES = True


def _posix_path(p: str) -> str:
    return p.replace('\\', '/')


def _url_to_local_path(src: str) -> Optional[str]:
    """Map a URL under MEDIA_URL to an absolute path under MEDIA_ROOT.

    Returns None for non-media or remote URLs.
    """
    if not src:
        return None
    # Normalize MEDIA_URL (may be '/media/' or absolute)
    media_url = str(settings.MEDIA_URL)
    if not media_url.endswith('/'):
        media_url += '/'

    s = str(src)
    if s.startswith('http://') or s.startswith('https://'):
        return None
    # Handle '/media/...'
    if s.startswith(media_url):
        rel = s[len(media_url):]
    elif s.startswith('/media/'):
        rel = s[len('/media/'):]
    else:
        # allow passing a relative media path like 'covers/x.jpg' or 'steam_imports/...'
        rel = s
    abs_path = os.path.join(str(settings.MEDIA_ROOT), rel)
    return abs_path


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _variant_path(orig_abs: str, target_width: int, fmt: str = 'webp') -> tuple[str, str]:
    """Return (variant_abs, variant_rel) paths for a given original file.

    Variants are stored alongside original in a 'variants/' subfolder:
      <dir>/variants/<name>_w<width>.<fmt>
    rel path is POSIX relative to MEDIA_ROOT.
    """
    base_dir, fname = os.path.split(orig_abs)
    name, _ext = os.path.splitext(fname)
    variants_dir = os.path.join(base_dir, 'variants')
    _ensure_dir(variants_dir)
    variant_fname = f"{name}_w{int(target_width)}.{fmt.lower()}"
    variant_abs = os.path.join(variants_dir, variant_fname)
    media_root = str(settings.MEDIA_ROOT)
    variant_rel = _posix_path(os.path.relpath(variant_abs, media_root))
    return variant_abs, variant_rel


def _needs_regen(src_abs: str, dst_abs: str) -> bool:
    try:
        src_m = os.path.getmtime(src_abs)
        dst_m = os.path.getmtime(dst_abs)
        return dst_m < src_m
    except FileNotFoundError:
        return True
    except Exception:
        return True


@register.simple_tag
def img_url_w(src: str, width: Union[int, str], fmt: str = 'webp', quality: int = 85) -> str:
    """Return URL for a resized WebP variant of a media image at given width.

    - If src is not under MEDIA_URL or file missing, returns src unchanged.
    - Variants are cached under '<orig_dir>/variants/<name>_w<width>.<fmt>'.
    - No upscaling: if original width < requested width, original width is used.
    """
    try:
        w = int(width)
        if w <= 0:
            return src
    except Exception:
        return src

    abs_path = _url_to_local_path(src)
    if not abs_path or not os.path.isfile(abs_path):
        return src

    try:
        variant_abs, variant_rel = _variant_path(abs_path, w, fmt)
        if _needs_regen(abs_path, variant_abs):
            from PIL import Image as _Image  # local import for static analyzers
            with _Image.open(abs_path) as im:  # type: ignore[assignment]
                # keep aspect ratio, don't upscale
                orig_w, orig_h = im.size
                target_w = min(w, orig_w)
                if im.mode in ('P', 'LA'):
                    im = im.convert('RGBA')
                elif im.mode in ('CMYK',):
                    im = im.convert('RGB')
                ratio = target_w / float(orig_w)
                target_h = max(1, int(round(orig_h * ratio)))
                try:
                    resample = getattr(_Image, 'LANCZOS', getattr(_Image, 'Resampling', None).LANCZOS if hasattr(getattr(_Image, 'Resampling', None), 'LANCZOS') else getattr(_Image, 'BICUBIC', 1))  # type: ignore[attr-defined]
                except Exception:  # fallback
                    resample = 1  # BILINEAR
                im = im.resize((int(target_w), int(target_h)), resample)
                save_kwargs: Dict[str, Any] = {}
                if fmt.lower() == 'webp':
                    save_kwargs = {'quality': int(quality), 'method': 6}
                im.save(variant_abs, fmt.upper(), optimize=True, **save_kwargs)
        return _posix_path(str(settings.MEDIA_URL) + variant_rel)
    except Exception:
        # On any error, fail soft and return original src
        return src


@register.simple_tag
def srcset_webp(src: str, widths: str = '320,480,640,800', quality: int = 85) -> str:
    """Build a WebP srcset string for a media image.

    Example output: '/media/.../variants/x_w320.webp 320w, /media/.../x_w640.webp 640w'
    For non-media/remote sources returns empty string.
    """
    try:
        abs_path = _url_to_local_path(src)
        if not abs_path or not os.path.isfile(abs_path):
            return ''
        pairs: List[str] = []
        for token in str(widths).split(','):
            token = token.strip()
            if not token:
                continue
            try:
                w = int(token)
            except Exception:
                continue
            url = img_url_w(src, w, 'webp', quality)
            if url:
                pairs.append(f"{url} {w}w")
        return ', '.join(pairs)
    except Exception:
        return ''

# -----------------------------
# Dimension helper for CLS
# -----------------------------
_DIM_CACHE: dict[str, tuple[int, int]] = {}

def _local_media_abs(src: str) -> Optional[str]:
    """Map MEDIA_URL or relative media path to absolute path under MEDIA_ROOT."""
    if not src:
        return None
    media_url = str(settings.MEDIA_URL)
    if not media_url.endswith('/'):
        media_url += '/'
    s = str(src)
    if s.startswith('http://') or s.startswith('https://'):
        return None
    if s.startswith(media_url):
        rel = s[len(media_url):]
    elif s.startswith('/media/'):
        rel = s[len('/media/'):]
    else:
        rel = s
    abs_path = os.path.join(str(settings.MEDIA_ROOT), rel)
    return abs_path

@register.simple_tag
def img_dims(src: str) -> str:
    """Return width/height attributes for an image to reduce layout shift.

    Priority:
      1. Local media file -> probe via Pillow (cached in-process)
      2. Steam CDN header heuristic (460x215) if URL matches header pattern
      3. Empty string if unknown.

    Usage: <img src="..." {% img_dims some_url %} alt="...">
    """
    try:
        if not src:
            return ''
        # Heuristic for Steam headers
        if ('steamstatic.com/steam/apps/' in src) and ('header' in src):
            return 'width="460" height="215"'
        abs_path = _local_media_abs(src)
        if abs_path and os.path.isfile(abs_path):
            cached = _DIM_CACHE.get(abs_path)
            if not cached:
                try:
                    with Image.open(abs_path) as im:  # type: ignore[assignment]
                        w, h = im.size
                    _DIM_CACHE[abs_path] = (int(w), int(h))
                except Exception:
                    _DIM_CACHE[abs_path] = (0, 0)
            w, h = _DIM_CACHE.get(abs_path, (0, 0))
            if w > 0 and h > 0:
                return f'width="{w}" height="{h}"'
        return ''
    except Exception:
        return ''
