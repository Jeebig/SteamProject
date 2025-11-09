from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from store.models import UserProfile

User = get_user_model()

class UsernameChangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='userA', password='pass123')
        UserProfile.objects.get_or_create(user=self.user)  # ensure profile
        self.client.login(username='userA', password='pass123')
        # second user to test uniqueness
        self.other = User.objects.create_user(username='takenName', password='pass123')
        UserProfile.objects.get_or_create(user=self.other)

    def _post(self, new_username, extra=None):
        url = reverse('store:profile_edit')
        data = {
            'steam_persona': '',
            'bg_appid': '',
            'bio': '',
            'theme_color': '',
            'new_username': new_username,
        }
        if extra:
            data.update(extra)
        return self.client.post(url, data=data)

    def test_success_change_non_steam(self):
        resp = self._post('newnick')
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'newnick')

    def test_no_change_on_empty(self):
        resp = self._post('   ')
        self.assertEqual(resp.status_code, 302)  # form valid, redirect
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'userA')

    def test_conflict_existing_username(self):
        resp = self._post('takenName')
        # Expect form re-render with error (status 200)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Такой ник уже занят.')
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'userA')

    def test_steam_linked_cannot_change(self):
        # Simulate Steam-linked profile: assign steam_id
        prof = self.user.profile
        prof.steam_id = '12345678901234567'
        prof.save(update_fields=['steam_id'])
        resp = self._post('anotherNick')
        # Form should show error and not redirect
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Никнейм меняется в аккаунте Steam')
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'userA')

    def test_whitespace_trim(self):
        resp = self._post('  trimmedNick  ')
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'trimmedNick')
