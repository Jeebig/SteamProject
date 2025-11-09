import os, sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'steam_clone.settings')

import django
from django.utils import translation
from django.template.loader import render_to_string

django.setup()

class Game(SimpleNamespace):
    pass

def make_game(title, slug, price):
    from django.utils import timezone
    return Game(
        title=title,
        slug=slug,
        price=price,
        currency='USD',
        appid='999',
        cover_image=None,
        developer=SimpleNamespace(name='Dev'),
        genres=[],
        release_date=None,
        created_at=timezone.now(),
    )

free_game = make_game('Free test', 'free-test', 0)
ctx = {
    'user': SimpleNamespace(username='tester'),
    'games': [free_game],
    'MEDIA_URL': '/media/',
}

expected = {
    'ru': 'Бесплатно',
    'uk': 'Безкоштовно',
    'en': 'Free',
}

results = {}
for lang, label in expected.items():
    translation.activate(lang)
    out = render_to_string('store/wishlist.html', ctx)
    results[lang] = label in out

print('FREE_LABEL_RESULTS:', results)
