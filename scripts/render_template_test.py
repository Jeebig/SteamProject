import os
import sys

# Ensure project root is on path
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'steam_clone.settings')

import django
from django.template.loader import render_to_string

django.setup()

context = {
    'MEDIA_URL': '/media/',
    'featured': [],
    'promos': [],
    'catalog': [],
}

try:
    out = render_to_string('store/index.html', context)
    print('RENDER_OK')
    print('Output length:', len(out))
except Exception as e:
    print('RENDER_FAIL')
    import traceback
    traceback.print_exc()
