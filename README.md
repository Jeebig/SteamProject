# Steam-like store (Django)

This is a starter skeleton for a Steam-like store built with Django.

Goals for the scaffold in this repo:

- Basic Django project with `store` app
- Tailwind via CDN for quick styling
- i18n ready (English/Українська)
- Simple `Game` model, admin registration and a list view

Quick start (Windows PowerShell / local development):

```powershell
python -m venv .venv
\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
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

## Deployment (PythonAnywhere / Generic Linux hosting)

1. Clone the repository on the server:

	```bash
	git clone https://github.com/your-user/SteamProject.git
	cd SteamProject
	```

2. Create and activate a virtual environment, install deps:

	```bash
	python -m venv venv
	source venv/bin/activate
	pip install -r requirements.txt
	```

3. Create a production `.env` file based on `.env.example` (PythonAnywhere can use its web UI env vars instead):

	```bash
	cp .env.example .env
	```

4. Run migrations and collect static files:

	```bash
	python manage.py migrate
	python manage.py collectstatic --noinput
	```

5. (PythonAnywhere) Configure WSGI: point to `steam_clone.wsgi` module and set working directory to the project root.
6. Ensure `ALLOWED_HOSTS` (and `CSRF_TRUSTED_ORIGINS` if HTTPS) match your domain.
7. Switch `EMAIL_BACKEND` in environment to SMTP for real email.
8. Create the support admin user (matching SUPPORT_ADMIN_USERNAME):

	```bash
	python manage.py createsuperuser
	```

To run with Gunicorn locally:

```bash
gunicorn steam_clone.wsgi:application --bind 0.0.0.0:8000
```

## Translations (i18n)

We added starter Ukrainian translations in `locale/uk/LC_MESSAGES/django.po`.
To extract messages and compile translations locally run:

```powershell
# extract messages (run after changing templates/source strings)
django-admin makemessages -l uk
# edit the resulting .po file(s)
django-admin compilemessages
```

If you run into issues on Windows, ensure GNU gettext tools are installed (for compilemessages).

## Environment Variables

Production configuration is driven by environment variables (see `.env.example`):

- `SECRET_KEY` – Django secret key
- `DEBUG` – set False in production
- `ALLOWED_HOSTS` – comma separated hostnames
- `CSRF_TRUSTED_ORIGINS` – comma separated origins with scheme
- `STEAM_API_KEY` – Steam Web API key
- `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `SUPPORT_EMAIL` – email settings
- `SUPPORT_ADMIN_USERNAME` – username allowed to manage support tickets

## Static Files

`collectstatic` outputs into `staticfiles/` (configured as `STATIC_ROOT`). Point your web server (or PythonAnywhere static files mapping) to serve that directory at `/static/`.

## Security Quick Checklist

- Replace default `SECRET_KEY`.
- Set `DEBUG=False`.
- Restrict `ALLOWED_HOSTS`.
- Use HTTPS (configure `CSRF_TRUSTED_ORIGINS`).
- Switch to SMTP email backend.
- Create an admin user and set a strong password.
- Consider upgrading to Postgres for production workloads.


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
