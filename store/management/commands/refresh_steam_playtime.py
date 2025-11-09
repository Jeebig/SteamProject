from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.auth import get_user_model
from store.models import UserProfile, Game, OwnedGame
import os
import requests
from datetime import datetime, timezone


API_KEY = getattr(settings, 'SOCIAL_AUTH_STEAM_API_KEY', '') or os.getenv('STEAM_API_KEY', '')


class Command(BaseCommand):
    help = "Обновить недавнее время игры (2 недели) и дату последнего запуска из Steam для пользователей."

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Обновить только для указанного пользователя')

    def handle(self, *args, **options):
        if not API_KEY:
            self.stderr.write('STEAM_API_KEY не задан. Пропуск.')
            return
        User = get_user_model()
        qs = User.objects.all()
        if options.get('username'):
            qs = qs.filter(username=options['username'])
        count = 0
        for user in qs:
            prof = getattr(user, 'profile', None)
            if not prof or not prof.steam_id:
                continue
            try:
                self._refresh_user(prof)
                count += 1
            except Exception as e:
                self.stderr.write(f"Ошибка {user.username}: {e}")
        self.stdout.write(self.style.SUCCESS(f'Обновлено пользователей: {count}'))

    def _refresh_user(self, profile: UserProfile):
        uid = profile.steam_id
        r = requests.get('https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/',
                         params={'key': API_KEY, 'steamid': uid, 'count': 100, 'format': 'json'}, timeout=10)
        if not r.ok:
            return
        data = (r.json() or {}).get('response', {})
        items = data.get('games') or []
        if not items:
            return
        appids = [it.get('appid') for it in items if it.get('appid')]
        if not appids:
            return
        games = {g.appid: g for g in Game.objects.filter(appid__in=appids)}
        existing = {og.game_id: og for og in OwnedGame.objects.filter(user=profile.user, game__appid__in=appids)}
        to_update = []
        for it in items:
            g = games.get(it.get('appid'))
            if not g:
                continue
            og = existing.get(g.id)
            if not og:
                og = OwnedGame(user=profile.user, game=g, source='steam')
            changed = False
            p2 = it.get('playtime_2weeks')
            if p2 is not None:
                p2 = int(p2)
                if og.playtime_2weeks != p2:
                    og.playtime_2weeks = p2; changed = True
            rtime = it.get('rtime_last_played')
            if rtime:
                try:
                    dt = datetime.fromtimestamp(int(rtime), tz=timezone.utc)
                    if og.last_played != dt:
                        og.last_played = dt; changed = True
                except Exception:
                    pass
            if changed:
                to_update.append(og)
        if to_update:
            OwnedGame.objects.bulk_update(to_update, ['playtime_2weeks', 'last_played'])
