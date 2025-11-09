import os
import sys
from types import SimpleNamespace

# Ensure project root is on path
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'steam_clone.settings')

import django
from django.template.loader import render_to_string
from django.utils import translation


def make_wishlist_ctx():
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

    games = [
        G('With cover','with-cover', appid='123', cover_url='/media/covers/1.jpg', developer_name='Dev A', price=0),
        G('Only appid','only-appid', appid='264710', cover_url=None, developer_name='Dev B', price=29.99),
        G('No image','no-image', appid=None, cover_url=None, developer_name='Dev C', price=19.99),
    ]
    user = SimpleNamespace(username='tester')
    return {'user': user, 'games': games, 'MEDIA_URL': '/media/'}


def make_index_ctx():
    return {
        'MEDIA_URL': '/media/',
        'featured': [],
        'promos': [],
        'catalog': [],
    }


def main():
    django.setup()
    # args: lang template
    lang = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get('LANG', 'uk')).strip()
    tpl = (sys.argv[2] if len(sys.argv) > 2 else 'wishlist').strip()
    translation.activate(lang)
    try:
        if tpl == 'wishlist':
            ctx = make_wishlist_ctx()
            tpl_name = 'store/wishlist.html'
        elif tpl == 'index':
            ctx = make_index_ctx()
            tpl_name = 'store/index.html'
        else:
            print('UNKNOWN_TEMPLATE')
            sys.exit(2)
        out = render_to_string(tpl_name, ctx)
        print('RENDER_OK', lang, tpl)
        print('len=', len(out))
        # Print a couple of known tokens for quick grep
        if tpl == 'wishlist':
            # Expect localized header and button
            for token in [
                'Список желаемого', # ru base msgid
                'Список бажаного',  # uk
                'Бесплатно',        # ru FREE
                'Безкоштовно',      # uk FREE
            ]:
                if token in out:
                    print('HAS:', token)
        elif tpl == 'index':
            for token in ['Популярное и рекомендуемое', 'Популярне та рекомендоване']:
                if token in out:
                    print('HAS:', token)
    except Exception:
        print('RENDER_FAIL', lang, tpl)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
