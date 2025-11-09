import json
import urllib.request
import urllib.error

from django import template
from django.core.cache import cache
from django.conf import settings

register = template.Library()


@register.simple_tag
def steam_tags(appid, max_tags=5):
    """Return a list of tag/genre names for the given Steam appid.

    Uses store API: https://store.steampowered.com/api/appdetails?appids=<id>
    Caches results in Django cache (if available) under key 'steam_tags_<appid>'.
    If requests isn't available or network fails, returns an empty list.
    """
    if not appid:
        return []
    cache_key = f"steam_tags_{appid}"
    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached[:int(max_tags)]
    except Exception:
        # Cache not configured or other issue — continue without cache
        cached = None

    # Feature flag: disable remote fetch by default to avoid slowing down page renders.
    # To enable fetching, set in settings.py: STORE_FETCH_STEAM_TAGS = True
    fetch_enabled = bool(getattr(settings, 'STORE_FETCH_STEAM_TAGS', False))
    if not fetch_enabled:
        return cached[: int(max_tags)] if cached is not None else []

    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=en"
        # Keep a very short timeout; if Steam is slow, don't block our page render
        with urllib.request.urlopen(url, timeout=0.8) as resp:
            raw = resp.read()
        data = json.loads(raw)
        app_data = data.get(str(appid), {})
        if not app_data.get('success'):
            return []
        info = app_data.get('data', {})
        tags = []
        # genres
        for g in info.get('genres', [])[:max_tags]:
            name = g.get('description') or g.get('id')
            if name:
                tags.append(name)
        # categories (append if still space)
        if len(tags) < int(max_tags):
            for c in info.get('categories', [])[: max(0, int(max_tags) - len(tags))]:
                name = c.get('description')
                if name:
                    tags.append(name)

        # persist to cache (best-effort)
        try:
            cache.set(cache_key, tags, 60 * 60 * 24)
        except Exception:
            pass

        return tags[: int(max_tags)]
    except Exception:
        return []
