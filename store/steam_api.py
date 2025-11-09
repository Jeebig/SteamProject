"""
Minimal helper to fetch Steam app details and download up to N images to MEDIA_ROOT.

Usage:
  - Set environment variable STEAM_API_KEY (optional for store/appdetails)
  - Call `fetch_app_and_images(appid)` from manage.py shell or from a Django view/management command.

This file is intentionally simple for the MVP. For production, add error handling,
rate-limiting, caching, and storage via Django's Storage API (S3 etc.).
"""
from pathlib import Path
import os
import urllib.request
import urllib.error
import json
from urllib.parse import urlparse

# Minimal requests-like shim using urllib to avoid requiring the external 'requests' package.
# It provides the parts of the API used in this file: get(...), Response.content, Response.json(), Response.raise_for_status().
class _SimpleResponse:
    def __init__(self, content: bytes, status: int, url: str):
        self.content = content
        self.status_code = status
        self._url = url
        self._json = None

    def raise_for_status(self):
        if 400 <= self.status_code:
            raise urllib.error.HTTPError(self._url, self.status_code, "HTTP Error", hdrs=None, fp=None)

    def json(self):
        if self._json is None:
            # decode as utf-8 and parse JSON
            self._json = json.loads(self.content.decode('utf-8'))
        return self._json

def _requests_get(url, timeout=10):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        status = resp.getcode()
        return _SimpleResponse(data, status, url)

# compatibility shim: mimic `requests.get(...)`
class _RequestsShim:
    @staticmethod
    def get(url, timeout=10):
        return _requests_get(url, timeout=timeout)

# expose a `requests` object with a .get method so existing code remains unchanged
requests = _RequestsShim()

from django.conf import settings


STEAM_API_KEY = os.environ.get('STEAM_API_KEY')


def fetch_appdetails(appid: int, language: str = 'en', cc: str = 'us'):
    """Fetch app details from Steam Store API.

    Returns the JSON object for the app (data field) or None on failure.
    """
    url = f'https://store.steampowered.com/api/appdetails?appids={appid}&l={language}&cc={cc}'
    # appdetails does not require key, but keep key param if provided
    if STEAM_API_KEY:
        url += f'&key={STEAM_API_KEY}'
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    j = resp.json()
    # response is { "<appid>": { "success": True, "data": { ... } } }
    app_entry = j.get(str(appid)) or j.get(int(appid))
    if not app_entry:
        return None
    if not app_entry.get('success'):
        return None
    return app_entry.get('data')


def _save_bytes_to_media(subpath: Path, content: bytes):
    full_path = settings.MEDIA_ROOT / subpath
    full_path.parent.mkdir(parents=True, exist_ok=True)
    with open(full_path, 'wb') as f:
        f.write(content)
    # return path relative to MEDIA_ROOT
    return str(subpath)


def fetch_app_and_images(appid: int, max_images: int = 3, target_subdir: str = 'steam_imports'):
    """Fetch app details and download up to `max_images` to MEDIA_ROOT/target_subdir/<appid>/.

    Returns dict: { 'app': <app_data or None>, 'images': [relative_paths...] }
    """
    data = fetch_appdetails(appid)
    images = []
    if not data:
        return {'app': None, 'images': images}

    # collect candidate image URLs: header_image + screenshots
    candidates = []
    header = data.get('header_image')
    if header:
        candidates.append(header)
    screenshots = data.get('screenshots') or []
    for s in screenshots:
        # screenshot objects often have 'path_thumbnail' and 'path_full'
        url = s.get('path_full') or s.get('path_thumbnail')
        if url:
            candidates.append(url)

    # limit and download
    base_dir = Path(target_subdir) / str(appid)
    count = 0
    for url in candidates:
        if count >= max_images:
            break
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
        except Exception:
            continue
        parsed = urlparse(url)
        filename = Path(parsed.path).name
        # prepare relative subpath under MEDIA_ROOT
        rel_subpath = base_dir / filename
        rel_path_str = _save_bytes_to_media(rel_subpath, r.content)
        images.append(rel_path_str)
        count += 1

    return {'app': data, 'images': images}
