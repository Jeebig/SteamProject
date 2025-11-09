from django.test import TestCase
from django.contrib.auth import get_user_model
from store.forms import ProfileAppearanceForm
from store.models import UserProfile

User = get_user_model()

class ThemeColorValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pass123')
        # Ensure profile exists
        UserProfile.objects.create(user=self.user)

    def get_form(self, color_value):
        profile = self.user.profile
        data = {
            'steam_persona': profile.steam_persona,
            'bg_appid': profile.bg_appid or '',
            'bio': profile.bio,
            'theme_color': color_value,
            'remove_avatar': False,
            'new_username': '',
        }
        return ProfileAppearanceForm(data=data, instance=profile, user=self.user)

    def test_empty_theme_color_ok(self):
        form = self.get_form('')
        self.assertTrue(form.is_valid(), form.errors)
        inst = form.save()
        self.assertEqual(inst.theme_color, '')

    def test_valid_lowercase_hex(self):
        form = self.get_form('#1b6b80')
        self.assertTrue(form.is_valid(), form.errors)
        inst = form.save()
        self.assertEqual(inst.theme_color, '#1b6b80')

    def test_valid_uppercase_normalized(self):
        form = self.get_form('#A0B1C2')
        self.assertTrue(form.is_valid(), form.errors)
        inst = form.save()
        self.assertEqual(inst.theme_color, '#a0b1c2')

    def test_invalid_short_hex(self):
        form = self.get_form('#123')
        self.assertFalse(form.is_valid())
        self.assertIn('theme_color', form.errors)

    def test_invalid_missing_hash(self):
        form = self.get_form('1b6b80')
        self.assertFalse(form.is_valid())
        self.assertIn('theme_color', form.errors)

    def test_invalid_bad_chars(self):
        form = self.get_form('#ZZZZZZ')
        self.assertFalse(form.is_valid())
        self.assertIn('theme_color', form.errors)

    def test_invalid_length(self):
        form = self.get_form('#1234567')  # 7 hex digits + '#'
        self.assertFalse(form.is_valid())
        self.assertIn('theme_color', form.errors)
