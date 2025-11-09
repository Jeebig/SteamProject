from __future__ import annotations
from typing import Any
import os
import requests
from django.conf import settings
from django.db import transaction
from django.contrib.auth import get_user_model
from .models import UserProfile, Game, OwnedGame

API_KEY = getattr(settings, 'SOCIAL_AUTH_STEAM_API_KEY', '') or os.getenv('STEAM_API_KEY', '')


def _steam_api(url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.ok:
            return resp.json() or {}
    except Exception:
        pass
    return {}


def sync_steam(strategy, details, response, user=None, uid=None, *args, **kwargs):
    """Pipeline: after user is created/associated, sync Steam profile and library.

    - uid is the SteamID64 from SteamOpenId backend
    - requires STEAM_API_KEY
    - imports owned games that exist in our DB by appid into OwnedGame
    - stores basic persona and avatar fields into UserProfile
    """
    if not user:
        return
    if not uid:
        uid = kwargs.get('uid') or getattr(strategy, 'uid', None)
    if not uid:
        return

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.steam_id = str(uid)

    if not API_KEY:
        profile.save(update_fields=['steam_id'])
        return

    # Player summaries
    summ = _steam_api('https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/', {
        'key': API_KEY,
        'steamids': uid,
    })
    try:
        players = (summ.get('response', {}) or {}).get('players', [])
        if players:
            p = players[0]
            profile.steam_persona = p.get('personaname', '') or ''
            profile.steam_avatar = p.get('avatarfull', '') or p.get('avatarmedium', '') or p.get('avatar', '') or ''
            profile.save(update_fields=['steam_id', 'steam_persona', 'steam_avatar'])
    except Exception:
        profile.save(update_fields=['steam_id'])

    # Owned games (only when game details are public)
    data = _steam_api('https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/', {
        'key': API_KEY,
        'steamid': uid,
        'include_appinfo': 0,
        'include_played_free_games': 1,
        'format': 'json',
    })
    try:
        games = (data.get('response', {}) or {}).get('games', [])
        if not games:
            return
        appids = [g.get('appid') for g in games if g.get('appid')]
        if not appids:
            return
        existing_games = {g.appid: g for g in Game.objects.filter(appid__in=appids)}

        # load existing OwnedGame for the user keyed by game_id
        existing_owned = {og.game_id: og for og in OwnedGame.objects.filter(user=user, game__appid__in=appids)}

        to_create = []
        to_update = []

        from datetime import datetime, timezone as py_tz

        for item in games:
            aid = item.get('appid')
            game = existing_games.get(aid)
            if not game:
                continue
            play_forever = int(item.get('playtime_forever') or 0)
            play_2w = item.get('playtime_2weeks')
            play_2w = int(play_2w) if play_2w is not None else None
            rtime = item.get('rtime_last_played')
            last_dt = None
            try:
                if rtime:
                    last_dt = datetime.fromtimestamp(int(rtime), tz=py_tz.utc)
            except Exception:
                last_dt = None

            og = existing_owned.get(game.id)
            if og:
                changed = False
                if og.playtime_forever != play_forever:
                    og.playtime_forever = play_forever; changed = True
                if og.playtime_2weeks != play_2w:
                    og.playtime_2weeks = play_2w; changed = True
                if og.last_played != last_dt:
                    og.last_played = last_dt; changed = True
                if changed:
                    to_update.append(og)
            else:
                to_create.append(OwnedGame(user=user, game=game, source='steam',
                                           playtime_forever=play_forever, playtime_2weeks=play_2w, last_played=last_dt))

        if to_create or to_update:
            with transaction.atomic():
                if to_create:
                    OwnedGame.objects.bulk_create(to_create, ignore_conflicts=True)
                if to_update:
                    OwnedGame.objects.bulk_update(to_update, ['playtime_forever', 'playtime_2weeks', 'last_played'])
    except Exception:
        return

    # Recently played for more accurate 2-weeks stats (best-effort)
    recent = _steam_api('https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/', {
        'key': API_KEY,
        'steamid': uid,
        'count': 100,
        'format': 'json',
    })
    try:
        items = (recent.get('response', {}) or {}).get('games', [])
        if not items:
            return
        appids = [it.get('appid') for it in items if it.get('appid')]
        if not appids:
            return
        # Map game/app
        games = {g.appid: g for g in Game.objects.filter(appid__in=appids)}
        # Pull existing OwnedGame
        existing = {og.game_id: og for og in OwnedGame.objects.filter(user=user, game__appid__in=appids)}
        from datetime import datetime, timezone as py_tz
        to_update = []
        for it in items:
            g = games.get(it.get('appid'))
            if not g:
                continue
            og = existing.get(g.id)
            if not og:
                # create minimal record if not present
                og = OwnedGame(user=user, game=g, source='steam')
            changed = False
            p2 = it.get('playtime_2weeks')
            if p2 is not None:
                p2 = int(p2)
                if og.playtime_2weeks != p2:
                    og.playtime_2weeks = p2; changed = True
            rtime = it.get('rtime_last_played')
            if rtime:
                try:
                    dt = datetime.fromtimestamp(int(rtime), tz=py_tz.utc)
                    if og.last_played != dt:
                        og.last_played = dt; changed = True
                except Exception:
                    pass
            if changed:
                to_update.append(og)
        if to_update:
            with transaction.atomic():
                OwnedGame.objects.bulk_update(to_update, ['playtime_2weeks', 'last_played'])
    except Exception:
        return
