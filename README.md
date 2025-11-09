# Steam-like store (Django)

This is a starter skeleton for a Steam-like store built with Django.

Goals for the scaffold in this repo:

- Basic Django project with `store` app
- Tailwind via CDN for quick styling
- i18n ready (English/Українська)
- Simple `Game` model, admin registration and a list view

Quick start (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd SteamProject
python manage.py migrate
python manage.py runserver
```

Notes:

- Images will be loaded via external APIs (Steam Store API / RAWG / IGDB). See docs below.
- We'll use exchangerate.host (free) for currency conversion in MVP.

Environment and API keys

- Store your Steam Web API key in an environment variable named `STEAM_API_KEY`.
 In PowerShell for the current session:

```powershell
$env:STEAM_API_KEY = 'YOUR_KEY_HERE'
```

 To set it persistently for your user (PowerShell), run:

```powershell
setx STEAM_API_KEY "YOUR_KEY_HERE"
```

Usage example (manage.py shell):

```python
from store.steam_api import fetch_app_and_images
# fetch and save up to 3 images for appid 570 (Dota 2)
data = fetch_app_and_images(570)
print(data)
```

Translations (i18n)

We added starter Ukrainian translations in `locale/uk/LC_MESSAGES/django.po`.
To extract messages and compile translations locally run:

```powershell
# extract messages (run after changing templates/source strings)
django-admin makemessages -l uk
# edit the resulting .po file(s)
django-admin compilemessages
```

If you run into issues on Windows, ensure GNU gettext tools are installed (for compilemessages).

## Management commands

The project includes a few helpers to import games and keep prices fresh:

- import_steam_apps: Import games by specific AppIDs, download a few images, and fill price/discount/platforms.
- sync_steam_collections: Import multiple categories from Steam Featuredcategories (specials, top sellers, new releases, coming soon, new on Steam) and download images.
- sync_steam_featured: Import a curated set of popular/featured apps from Steam Featured API and download images.
- update_steam_prices: Refresh prices/discounts and platform flags for existing games (no image downloads).

Example usage (PowerShell):

```powershell
# Import specific appids
python manage.py import_steam_apps --appids 570 730 271590

# Sync featured (popular) apps with images
python manage.py sync_steam_featured --cc us --lang en --max 30

# Sync collections (specials/top sellers/new releases/etc.) with images
python manage.py sync_steam_collections --cc us --lang en --max 80 --max-images 2

# Update prices/discounts for existing games only
python manage.py update_steam_prices --cc us --lang en
```
