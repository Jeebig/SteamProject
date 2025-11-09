from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

class ProfileEditTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='alice', password='testpass123')
        self.client.login(username='alice', password='testpass123')

    def test_get_profile_edit(self):
        url = reverse('store:profile_edit')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Редактирование профиля')

    def test_update_persona_and_avatar(self):
        url = reverse('store:profile_edit')
        # minimal 1x1 PNG
        # Generate a valid in-memory PNG via Pillow to satisfy ImageField validation
        from io import BytesIO
        try:
            from PIL import Image
            bio = BytesIO()
            img = Image.new('RGBA', (2, 2), (255, 0, 0, 255))
            img.save(bio, format='PNG')
            png_bytes = bio.getvalue()
        except Exception:
            # Fallback raw tiny PNG if Pillow not available
            png_bytes = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' +
                         b'\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00' +
                         b'\x90wS\xDE\x00\x00\x00\x0bIDAT\x08\xD7c````\x00\x00\x00\x05\x00\x01' +
                         b'\r\n-\xB4\x00\x00\x00\x00IEND\xAE\x42\x60\x82')
        avatar = SimpleUploadedFile('avatar.png', png_bytes, content_type='image/png')
        resp = self.client.post(url, data={
            'steam_persona': 'Alice Persona',
            'preferred_language': 'en',
            'preferred_currency': 'USD',
            'privacy': 'public',
            'comment_privacy': 'public',
            'friend_request_privacy': 'public',
            'bg_appid': '',
            'notify_profile_comment': 'on',
            'notify_friend_request': 'on',
            'notify_friend_accept': 'on',
            'email_profile_comment': 'on',
            # omit email_friend_events (False)
            'notify_price_drop': 'on',
            # omit email_price_drop (False)
            'avatar': avatar,
        })
        if resp.status_code != 302:
            # Debug output to understand form errors in CI
            try:
                print(resp.content.decode('utf-8')[:2000])
            except Exception:
                pass
        self.assertEqual(resp.status_code, 302)  # redirect after success
        prof = self.user.profile
        self.assertEqual(prof.steam_persona, 'Alice Persona')
        self.assertTrue(prof.avatar)
