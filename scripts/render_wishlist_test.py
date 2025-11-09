import os, sys
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'steam_clone.settings')
import django
from types import SimpleNamespace
from django.template.loader import render_to_string

django.setup()

# Create fake game objects
class G:
    def __init__(self, title, slug, appid=None, cover_url=None, developer_name=None, price=0, currency='USD'):
        self.title = title
        self.slug = slug
        self.appid = appid
        self.price = price
        self.currency = currency
        self.developer = SimpleNamespace(name=developer_name) if developer_name else None
        if cover_url:
            self.cover_image = SimpleNamespace(url=cover_url)
        else:
            self.cover_image = None
        self.genres = []
        self.release_date = None
        from django.utils import timezone
        self.created_at = timezone.now()

# Examples
games = [
    G('With cover','with-cover', appid='123', cover_url='/media/covers/1.jpg', developer_name='Dev A', price=0),
    G('Only appid','only-appid', appid='264710', cover_url=None, developer_name='Dev B', price=29.99),
    G('No image','no-image', appid=None, cover_url=None, developer_name='Dev C', price=19.99),
]
user = SimpleNamespace(username='tester')

ctx = {'user': user, 'games': games, 'MEDIA_URL': '/media/'}
try:
    out = render_to_string('store/wishlist.html', ctx)
    print('RENDER_OK')
    print('len=', len(out))
except Exception as e:
    print('RENDER_FAIL')
    import traceback
    traceback.print_exc()
