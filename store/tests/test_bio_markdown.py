from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from store.models import UserProfile

User = get_user_model()

class BioMarkdownTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='mduser', password='pass123')
        UserProfile.objects.get_or_create(user=self.user)
        self.client.login(username='mduser', password='pass123')

    def _post(self, bio):
        url = reverse('store:profile_edit')
        data = {
            'steam_persona': '',
            'bg_appid': '',
            'bio': bio,
            'theme_color': '',
            'new_username': '',
        }
        return self.client.post(url, data=data)

    def test_markdown_render_basic(self):
        resp = self._post('# Заголовок\n\n**bold** _italic_')
        self.assertEqual(resp.status_code, 302)
        self.user.profile.refresh_from_db()
        # Visit profile page
        prof_url = reverse('store:profile', args=[self.user.username])
        page = self.client.get(prof_url)
        self.assertContains(page, '<h1>Заголовок</h1>', html=True)
        self.assertContains(page, '<strong>bold</strong>', html=True)
        self.assertContains(page, '<em>italic</em>', html=True)

    def test_script_tag_stripped(self):
        malicious = "Hello <script>alert('x')</script> world"
        resp = self._post(malicious)
        self.assertEqual(resp.status_code, 302)
        prof_url = reverse('store:profile', args=[self.user.username])
        page = self.client.get(prof_url)
        # Ensure inline script injection from bio removed (don't assert absence of global layout scripts)
        self.assertNotContains(page, "<script>alert('x')")
        self.assertContains(page, 'Hello  world')  # script removed

    def test_disallowed_html_removed(self):
        html = "<iframe src='http://evil'></iframe><b>ok</b>"
        resp = self._post(html)
        self.assertEqual(resp.status_code, 302)
        prof_url = reverse('store:profile', args=[self.user.username])
        page = self.client.get(prof_url)
        self.assertNotContains(page, '<iframe')
        self.assertContains(page, '<strong>ok</strong>', html=True)

    def test_links_and_lists(self):
        md = "- item1\n- item2\n\n[site](https://example.com)"
        resp = self._post(md)
        self.assertEqual(resp.status_code, 302)
        prof_url = reverse('store:profile', args=[self.user.username])
        page = self.client.get(prof_url)
        self.assertContains(page, '<ul>')
        self.assertContains(page, '<a href="https://example.com"')

    def test_length_limit(self):
        long_md = ('A' * 5000)
        resp = self._post(long_md)
        # Should still save (form limits via maxlength attr, but server should truncate)
        self.assertEqual(resp.status_code, 302)
        self.user.profile.refresh_from_db()
        self.assertTrue(len(self.user.profile.bio) <= 2000)
