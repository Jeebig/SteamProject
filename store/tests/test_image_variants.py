from __future__ import annotations
import os
import shutil
from django.test import TestCase
from django.conf import settings
from PIL import Image

from store.templatetags.store_extras import img_url_w, srcset_webp


class ImageVariantsTest(TestCase):
    def setUp(self):
        self.media_root = str(settings.MEDIA_ROOT)
        self.test_dir = os.path.join(self.media_root, 'test_src')
        os.makedirs(self.test_dir, exist_ok=True)
        # Create a sample image 800x450 (16:9)
        self.src_abs = os.path.join(self.test_dir, 'sample.jpg')
        if not os.path.exists(self.src_abs):
            img = Image.new('RGB', (800, 450), color=(10, 40, 90))
            img.save(self.src_abs, 'JPEG', quality=92)
        self.src_url = f"{settings.MEDIA_URL}test_src/sample.jpg"

    def tearDown(self):
        # Clean up test directory to avoid residue between runs
        if os.path.isdir(self.test_dir):
            try:
                shutil.rmtree(self.test_dir)
            except Exception:
                pass

    def _url_to_abs(self, url: str) -> str:
        media_url = str(settings.MEDIA_URL)
        if url.startswith(media_url):
            rel = url[len(media_url):]
        elif url.startswith('/media/'):
            rel = url[len('/media/'):]
        else:
            rel = url
        return os.path.join(self.media_root, rel)

    def test_img_url_w_generates_variant(self):
        out_url = img_url_w(self.src_url, 320)
        self.assertTrue(out_url.endswith('.webp'))
        self.assertIn('/media/test_src/variants/sample_w320.webp', out_url.replace('\\', '/'))
        out_abs = self._url_to_abs(out_url)
        self.assertTrue(os.path.isfile(out_abs))
        # ensure variant is not larger than requested width
        with Image.open(out_abs) as im:
            self.assertLessEqual(im.size[0], 320)

    def test_srcset_webp_returns_expected_pairs(self):
        ss = srcset_webp(self.src_url, '320,640')
        self.assertIn('320w', ss)
        self.assertIn('640w', ss)
        # and files exist for both widths
        parts = [p.strip().split(' ')[0] for p in ss.split(',') if p.strip()]
        for url in parts:
            self.assertTrue(os.path.isfile(self._url_to_abs(url)))
