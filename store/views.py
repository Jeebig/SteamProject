from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login as auth_login
from django.shortcuts import render
from django.views.generic import ListView, DetailView, UpdateView, TemplateView
from typing import Any, Dict
from django.views import View
from django.shortcuts import get_object_or_404, redirect
from django.http import JsonResponse
import os
from django.conf import settings
from django.urls import reverse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.contrib.auth import logout as auth_logout
from django.urls import reverse_lazy
from django.db.models import F, Q, Avg, Count, Sum, Case, When, IntegerField, Value
from django.core.cache import cache
from django.db.models.functions import Coalesce
from django.db import transaction
from django.contrib import messages
from .models import (
    Game, UserProfile, CartItem, SupportTicket, Order, OrderItem, Review, ReviewVote, Genre,
    ProfileComment, Friendship, ProfileCommentSubscription, ProfileCommentBan, Notification, FriendshipRequest
)
from .forms import (
    ProfileSettingsForm,  # legacy (single form)
    ProfileAppearanceForm,
    SupportTicketForm,
    ReviewForm,
    GeneralSettingsForm,
    PrivacySettingsForm,
    NotificationSettingsForm,
)
from .utils.currency import convert_amount
import requests
from django.utils import translation
from django.utils.translation import gettext as _
class RegisterView(View):
    def get(self, request):
        form = UserCreationForm()
        return render(request, 'registration/register.html', {'form': form})

    def post(self, request):
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect('store:home')
        return render(request, 'registration/register.html', {'form': form})

class GameListView(ListView):
    model = Game
    template_name = 'store/game_list.html'
    context_object_name = 'games'

    def get(self, request, *args, **kwargs):
        """On visiting the catalog, delete games that don't have a Steam AppID.

        Example: keep /game/dota-2-570/ and delete /game/dota-2/ (no appid).
        """
        try:
            # Remove placeholder entries with missing/invalid appid
            Game.objects.filter(appid__isnull=True).delete()
        except Exception:
            # Don't block the page if cleanup fails
            pass
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        preferred_currency = 'USD'
        if user.is_authenticated:
            profile = getattr(user, 'profile', None)
            if profile:
                preferred_currency = profile.preferred_currency
        ctx['preferred_currency'] = preferred_currency
        # expose current GET filters to template for prefilling form values
        # Parse platform filters safely from either repeated params or comma-separated single param
        platforms_list = self.request.GET.getlist('platform')
        if not platforms_list:
            single_platforms = self.request.GET.get('platform', '')
            if single_platforms:
                platforms_list = [p.strip() for p in single_platforms.split(',') if p.strip()]
        ctx['filters'] = {
            'q': self.request.GET.get('q', ''),
            'category': self.request.GET.get('category', ''),
            'min_price': self.request.GET.get('min_price', ''),
            'max_price': self.request.GET.get('max_price', ''),
            'platforms': platforms_list,
            'sort': self.request.GET.get('sort', ''),
        }
        return ctx

    def get_queryset(self):
        """Support simple querystring filters:

        - q: text search against title (icontains)
        - category: genre slug
        - developer: developer slug or name
        - min_price, max_price: numeric price bounds
        """
        # Show only games that have a valid AppID; eager-load developer & genres for card rendering
        qs = (
            super().get_queryset()
            .filter(appid__isnull=False)
            .select_related('developer')
            .prefetch_related('genres')
        )
        request = self.request
        q = request.GET.get('q')
        category = request.GET.get('category')
        developer = request.GET.get('developer')
        min_price = request.GET.get('min_price')
        max_price = request.GET.get('max_price')
        # platform: can be provided as repeated ?platform=windows&platform=linux or as single comma-separated
        platforms = request.GET.getlist('platform')
        if not platforms:
            sp = request.GET.get('platform', '')
            if sp:
                platforms = [p.strip() for p in sp.split(',') if p.strip()]

        if q:
            q = q.strip()
            # broaden search to title/description/developer/genres
            qs = qs.filter(
                Q(title__icontains=q) |
                Q(description__icontains=q) |
                Q(developer__name__icontains=q) |
                Q(genres__name__icontains=q)
            ).distinct()
            # add simple ranking: exact title match > startswith > contains > others
            from django.db.models.functions import Lower
            from django.db.models import Case, When, IntegerField, Value
            qs = qs.annotate(title_lower=Lower('title'))
            q_lower = q.lower()
            qs = qs.annotate(
                search_rank=Case(
                    When(title_lower=q_lower, then=Value(300)),
                    When(title_lower__startswith=q_lower, then=Value(200)),
                    When(title_lower__contains=q_lower, then=Value(120)),
                    default=Value(0),
                    output_field=IntegerField()
                )
            )

        if category:
            # try slug first, then name
            qs = qs.filter(genres__slug=category) | qs.filter(genres__name__iexact=category)
            qs = qs.distinct()

        if developer:
            qs = qs.filter(Q(developer__slug=developer) | Q(developer__name__iexact=developer)).distinct()

        # numeric price bounds
        from decimal import Decimal, InvalidOperation
        try:
            if min_price:
                mp = Decimal(min_price)
                qs = qs.filter(price__gte=mp)
        except (InvalidOperation, ValueError):
            pass
        try:
            if max_price:
                Mp = Decimal(max_price)
                qs = qs.filter(price__lte=Mp)
        except (InvalidOperation, ValueError):
            pass

        # platform filtering
        if platforms:
            platform_q = Q()
            for p in platforms:
                key = p.lower()
                if key in ('win', 'windows', 'windows10', 'windows7'):
                    platform_q |= Q(supports_windows=True)
                elif key in ('mac', 'macos', 'osx'):
                    platform_q |= Q(supports_mac=True)
                elif key in ('linux',):
                    platform_q |= Q(supports_linux=True)
            if platform_q:
                qs = qs.filter(platform_q)

        # annotate average rating and count
        qs = qs.annotate(rating_avg=Avg('reviews__rating'), rating_count=Count('reviews'))
        # sorting by rating
        sort = request.GET.get('sort')
        if sort in ('rating', '-rating'):
            if sort == 'rating':
                qs = qs.order_by(F('rating_avg').asc(nulls_last=True), F('rating_count').asc(nulls_last=True), F('created_at').desc())
            else:
                qs = qs.order_by(F('rating_avg').desc(nulls_last=True), F('rating_count').desc(nulls_last=True), F('created_at').desc())
        else:
            # default search ordering: search_rank desc (if present), then rating and recency
            if q:
                qs = qs.order_by(F('search_rank').desc(nulls_last=True), F('rating_avg').desc(nulls_last=True), F('rating_count').desc(nulls_last=True), F('updated_at').desc(nulls_last=True))
        return qs

    # Кешируем только для гостей (нет персонализации wishlist/owned)
    def dispatch(self, request, *args, **kwargs):
        if request.method == 'GET' and not request.user.is_authenticated:
            key = f"catalog_page:{request.get_full_path()}"
            cached = cache.get(key)
            if cached is not None:
                return cached
            response = super().dispatch(request, *args, **kwargs)
            # Безопасно принудительно рендерим TemplateResponse перед кешированием,
            # иначе locmem backend пытается его pickle'ить и падает с ContentNotRenderedError.
            if hasattr(response, 'render'):
                try:
                    if not getattr(response, 'is_rendered', False):
                        response.render()  # TemplateResponse.render() возвращает self
                except Exception:
                    # Если рендер почему-то упал — не кешируем этот ответ, вернём как есть.
                    return response
            # малый TTL (60s) чтобы не мешать свежести скидок
            cache.set(key, response, 60)
            return response
        return super().dispatch(request, *args, **kwargs)


class GameDetailView(DetailView):
    model = Game
    template_name = 'store/game_detail.html'
    context_object_name = 'game'

    def get_queryset(self):
        # Жадно подтягиваем связанные объекты для страницы игры
        return (
            Game.objects.select_related('developer')
            .prefetch_related('genres', 'screenshots', 'reviews__user')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        preferred_currency = 'USD'
        if user.is_authenticated:
            profile = getattr(user, 'profile', None)
            if profile:
                preferred_currency = profile.preferred_currency
        # converted price for display
        ctx['preferred_currency'] = preferred_currency
        try:
            ctx['converted_price'] = convert_amount(self.object.price, self.object.currency, preferred_currency)
        except Exception:
            ctx['converted_price'] = self.object.price
        # UI state flags for buttons
        in_wishlist = False
        in_cart = False
        is_owned = False
        is_free = False
        try:
            from decimal import Decimal
            is_free = (self.object.price or Decimal('0')) == 0
        except Exception:
            is_free = False
        if user.is_authenticated:
            try:
                prof = getattr(user, 'profile', None)
                if prof:
                    in_wishlist = prof.wishlist.filter(id=self.object.id).exists()
            except Exception:
                in_wishlist = False
            try:
                in_cart = CartItem.objects.filter(user=user, game=self.object).exists()
            except Exception:
                in_cart = False
            try:
                from .models import OrderItem
                is_owned = OrderItem.objects.filter(order__user=user, order__status='paid', game=self.object).exists()
            except Exception:
                is_owned = False
        ctx.update({
            'in_wishlist': in_wishlist,
            'in_cart': in_cart,
            'is_owned_flag': is_owned,
            'is_free': is_free,
        })

        # platform badges helper
        platform_badges = []
        if self.object.supports_windows:
            platform_badges.append('windows')
        if self.object.supports_mac:
            platform_badges.append('macos')
        if self.object.supports_linux:
            platform_badges.append('linux')
        ctx['platform_badges'] = platform_badges

        # related games (same developer and by genres)
        by_dev = Game.objects.none()
        if self.object.developer:
            # Используем select_related для developer (уже) + prefetch жанров
            by_dev = (
                Game.objects.filter(developer=self.object.developer)
                .exclude(id=self.object.id)
                .select_related('developer')
                .prefetch_related('genres')
                .annotate(rating_avg=Avg('reviews__rating'), rating_count=Count('reviews'))[:10]
            )
        by_genres = (
            Game.objects.filter(genres__in=self.object.genres.all())
            .exclude(id=self.object.id)
            .distinct()
            .select_related('developer')
            .prefetch_related('genres')
            .annotate(rating_avg=Avg('reviews__rating'), rating_count=Count('reviews'))[:12]
        )
        ctx['more_from_developer'] = by_dev
        ctx['similar_games'] = by_genres

        # reviews aggregate + sorting
        try:
            # reviews.prefetched выше (reviews__user) – используем .all() без дополнительных запросов
            reviews_qs = self.object.reviews.all()
            count = reviews_qs.count()
            avg = 0
            if count:
                avg = reviews_qs.aggregate(Avg('rating'))['rating__avg'] or 0
            ctx['reviews_count'] = count
            ctx['reviews_avg'] = avg

            # annotate helpful yes/no counts
            reviews_qs = reviews_qs.annotate(
                helpful_yes=Sum(Case(When(votes__helpful=True, then=1), default=0, output_field=IntegerField())),
                helpful_no=Sum(Case(When(votes__helpful=False, then=1), default=0, output_field=IntegerField())),
            )

            # sorting param: rsort = 'date' | '-date' | 'help' (default: help)
            rsort = self.request.GET.get('rsort', 'help')
            ctx['rsort'] = rsort
            if rsort == 'date':
                reviews_qs = reviews_qs.order_by('created_at')
            elif rsort == '-date':
                reviews_qs = reviews_qs.order_by('-created_at')
            else:  # help
                reviews_qs = reviews_qs.order_by(
                    F('helpful_yes').desc(nulls_last=True),
                    F('helpful_no').asc(nulls_last=True),
                    F('created_at').desc(),
                )
            from django.core.paginator import Paginator, EmptyPage
            page = self.request.GET.get('rpage', '1')
            try:
                page_num = int(page)
            except Exception:
                page_num = 1
            paginator = Paginator(reviews_qs, 10)
            try:
                page_obj = paginator.page(page_num)
            except EmptyPage:
                page_obj = paginator.page(paginator.num_pages or 1)
            ctx['reviews_qs'] = reviews_qs
            ctx['reviews_page'] = page_obj
        except Exception:
            ctx['reviews_count'] = 0
            ctx['reviews_avg'] = 0
            ctx['reviews_qs'] = self.object.reviews.all()
            ctx['reviews_page'] = None

        # Review form visibility: only for owners (paid order contains this game)
        can_review = False
        existing_review = None
        if user.is_authenticated:
            try:
                can_review = OrderItem.objects.filter(order__user=user, order__status='paid', game=self.object).exists()
                if can_review:
                    existing_review = Review.objects.filter(user=user, game=self.object).first()
            except Exception:
                can_review = False
        ctx['can_review'] = can_review
        ctx['user_review'] = existing_review
        if can_review:
            ctx['review_form'] = ReviewForm(instance=existing_review)
            try:
                # keep one decimal for half-star UI
                val = getattr(existing_review, 'rating', None)
                if val is None:
                    ctx['initial_rating'] = 5.0
                else:
                    try:
                        ctx['initial_rating'] = float(val)
                    except Exception:
                        ctx['initial_rating'] = 5.0
            except Exception:
                ctx['initial_rating'] = 5.0
            ctx['initial_text'] = getattr(existing_review, 'text', '') if existing_review else ''
            # user's existing votes per review (id -> 'up' | 'down')
            try:
                votes = ReviewVote.objects.filter(review__game=self.object, user=user)
                ctx['user_review_votes'] = {v.review_id: ('up' if v.helpful else 'down') for v in votes}
            except Exception:
                ctx['user_review_votes'] = {}
        return ctx

    def post(self, request, *args, **kwargs):
        # Handle review submit on the game detail page
        self.object = self.get_object()
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(next=self.request.get_full_path())
        # permission: must own the game
        owns = OrderItem.objects.filter(order__user=request.user, order__status='paid', game=self.object).exists()
        if not owns:
            messages.error(request, "Оставлять отзыв могут только купившие игру.")
            return redirect('store:game_detail', slug=self.object.slug)
        # Simple rate-limit: one submit per 30 seconds per game (session based)
        try:
            import time
            key = f"last_review_ts_{self.object.id}"
            last_ts = request.session.get(key)
            now_ts = time.time()
            if last_ts and (now_ts - float(last_ts) < 30):
                messages.error(request, "Слишком часто. Попробуйте через несколько секунд.")
                return redirect('store:game_detail', slug=self.object.slug)
        except Exception:
            pass
        form = ReviewForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            review, created = Review.objects.get_or_create(user=request.user, game=self.object,
                                                           defaults={'rating': data['rating'], 'text': data.get('text', '')})
            if not created:
                review.rating = data['rating']
                review.text = data.get('text', '')
                review.save(update_fields=['rating', 'text'])
            messages.success(request, "Спасибо! Ваш отзыв сохранён.")
            try:
                request.session[key] = time.time()
            except Exception:
                pass
        else:
            messages.error(request, "Проверьте поля формы отзыва.")
        return redirect('store:game_detail', slug=self.object.slug)
        return ctx


class ReviewVoteView(LoginRequiredMixin, View):
    """Handle helpful/unhelpful votes for a review (one per user)."""

    def post(self, request, pk):
        review = get_object_or_404(Review, id=pk)
        vote = request.POST.get('vote')  # 'up' or 'down'
        helpful = True if vote == 'up' else False
        # disallow voting on own review
        if review.user_id == request.user.id:
            msg = "Нельзя голосовать за собственный отзыв."
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"ok": False, "message": msg}, status=400)
            messages.info(request, msg)
            return redirect(request.META.get('HTTP_REFERER') or reverse('store:game_detail', args=[review.game.slug]))
        # simple vote throttle: 10s per review per session
        try:
            import time
            vkey = f"last_vote_ts_{review.id}"
            last = request.session.get(vkey)
            now = time.time()
            if last and (now - float(last) < 10):
                msg = "Слишком часто голосуете. Подождите пару секунд."
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"ok": False, "message": msg}, status=429)
                messages.info(request, msg)
                return redirect(request.META.get('HTTP_REFERER') or reverse('store:game_detail', args=[review.game.slug]))
        except Exception:
            pass
        obj, created = ReviewVote.objects.get_or_create(review=review, user=request.user, defaults={'helpful': helpful})
        if not created and obj.helpful != helpful:
            obj.helpful = helpful
            obj.save(update_fields=['helpful'])
        try:
            request.session[vkey] = time.time()
        except Exception:
            pass
        # recompute counts for response
        agg = ReviewVote.objects.filter(review=review).aggregate(
            yes=Sum(Case(When(helpful=True, then=1), default=0)),
            no=Sum(Case(When(helpful=False, then=1), default=0)),
        )
        user_vote = 'up' if helpful else 'down'
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                "ok": True,
                "review_id": review.id,
                "helpful_yes": agg.get('yes') or 0,
                "helpful_no": agg.get('no') or 0,
                "user_vote": user_vote,
            })
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('store:game_detail', args=[review.game.slug])
        return redirect(next_url)


class MyReviewsView(LoginRequiredMixin, ListView):
    template_name = 'store/my_reviews.html'
    context_object_name = 'reviews'
    paginate_by = 10

    def get_queryset(self):
        return Review.objects.select_related('game').filter(user=self.request.user).order_by('-created_at')


class ReviewDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        review = get_object_or_404(Review, id=pk, user=request.user)
        slug = review.game.slug
        review.delete()
        messages.success(request, "Отзыв удалён.")
        next_url = request.POST.get('next') or reverse('store:game_detail', args=[slug])
        return redirect(next_url)


class ProfileSettingsView(LoginRequiredMixin, UpdateView):
    model = UserProfile
    form_class = ProfileSettingsForm
    template_name = 'store/profile_settings.html'
    success_url = reverse_lazy('store:profile_settings')

    def get_object(self, queryset=None):
        # ensure a profile exists
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return profile

    def form_valid(self, form):
        # При смене preferred_currency конвертируем существующий баланс в новую валюту
        try:
            obj = self.get_object()
            old_cur = obj.preferred_currency
            new_cur = form.cleaned_data.get('preferred_currency') or old_cur
            if new_cur != old_cur:
                # пересчитаем баланс без немедленного сохранения (сохранит UpdateView)
                obj.convert_balance(new_cur, save=False)
                # sync instance with updated balance for saving
                form.instance.balance = obj.balance
        except Exception:
            pass
        return super().form_valid(form)


class ProfileEditView(LoginRequiredMixin, UpdateView):
    """Steam-like multi-section profile

    Uses extended ProfileForm with avatar + persona + price drop prefs.
    URL: /profile/edit/
    """
    model = UserProfile
    form_class = ProfileAppearanceForm
    template_name = 'store/profile_edit.html'
    success_url = reverse_lazy('store:profile_edit')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Передаём текущего пользователя в форму, чтобы управлять сменой ника
        kwargs['user'] = self.request.user
        return kwargs

    def get_object(self, queryset=None):
        """Return the current user's profile instance.

        The edit URL does not include a pk/slug, so we override get_object
        to fetch (or create) the profile for the logged-in user.
        """
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return profile

    def form_valid(self, form):
        messages.success(self.request, "Внешний вид профиля обновлён.")
        return super().form_valid(form)

    def form_invalid(self, form):
        # Simplify: rely on default handling, avoid noisy debug prints
        return super().form_invalid(form)


class SettingsView(LoginRequiredMixin, View):
    """Unified Steam-like settings hub with sectional forms.

    URL patterns:
        /settings/ -> general section
        /settings/<section>/ where <section> in {general, privacy, notifications}

    Each section uses a dedicated ModelForm subset for clarity and reduced cognitive load.
    """
    template_name = 'store/settings.html'
    SECTIONS: dict[str, dict[str, Any]] = {
        'general': {
            'title': _('Общие'),
            'form_class': GeneralSettingsForm,
        },
        'privacy': {
            'title': _('Приватность'),
            'form_class': PrivacySettingsForm,
        },
        'notifications': {
            'title': _('Уведомления'),
            'form_class': NotificationSettingsForm,
        },
    }

    def get_profile(self):
        prof, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return prof

    def normalize_section(self, raw: str | None) -> str:
        if not raw:
            return 'general'
        raw = str(raw).lower().strip()
        return raw if raw in self.SECTIONS else 'general'

    def get(self, request, section: str = 'general'):
        section = self.normalize_section(section)
        meta = self.SECTIONS[section]
        prof = self.get_profile()
        form = meta['form_class'](instance=prof)
        return render(request, self.template_name, self._ctx(section, form))

    def post(self, request, section: str = 'general'):
        section = self.normalize_section(section)
        meta = self.SECTIONS[section]
        prof = self.get_profile()
        form = meta['form_class'](request.POST, instance=prof)
        if form.is_valid():
            # Special case: currency change requires balance conversion
            try:
                if section == 'general':
                    old_cur = prof.preferred_currency
                    new_cur = form.cleaned_data.get('preferred_currency') or old_cur
                    if new_cur != old_cur:
                        prof.convert_balance(new_cur, save=False)
                        form.instance.balance = prof.balance
            except Exception:
                pass
            form.save()
            messages.success(request, _('Настройки сохранены.'))
            return redirect('store:settings', section=section)
        messages.error(request, _('Исправьте ошибки формы.'))
        return render(request, self.template_name, self._ctx(section, form))

    def _ctx(self, section: str, form):
        nav_items = [
            {'key': key, 'title': data['title'], 'url': reverse('store:settings', args=[key])}
            for key, data in self.SECTIONS.items()
        ]
        prof = self.get_profile()
        return {
            'active_section': section,
            'sections_meta': self.SECTIONS,
            'nav_items': nav_items,
            'form': form,
            'profile': prof,
            'friend_code': prof.friend_code,
        }


class HomeView(TemplateView):
    template_name = 'store/index.html'

    # Гостевой кеш на короткий срок (120 сек), т.к. блоки без персонализации
    def dispatch(self, request, *args, **kwargs):
        if request.method == 'GET' and not request.user.is_authenticated:
            key = f"home_page:{request.get_full_path()}"
            cached = cache.get(key)
            if cached is not None:
                return cached
            resp = super().dispatch(request, *args, **kwargs)
            try:
                if hasattr(resp, 'render'):
                    resp.render()
            except Exception:
                pass
            cache.set(key, resp, 120)
            return resp
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Вставляем предпочитаемую валюту пользователя, чтобы цены на главной странице
        # корректно конвертировались единым шаблонным тегом price_display
        preferred_currency = 'USD'
        try:
            user = self.request.user
            if getattr(user, 'is_authenticated', False):
                prof = getattr(user, 'profile', None)
                if prof and getattr(prof, 'preferred_currency', None):
                    preferred_currency = prof.preferred_currency
        except Exception:
            preferred_currency = 'USD'
        ctx['preferred_currency'] = preferred_currency
        # показываем только игры с фото (обложка или скриншоты)
        with_images = (
            Game.objects.filter(Q(cover_image__isnull=False) | Q(screenshots__isnull=False))
            .distinct()
            .select_related('developer')
            .prefetch_related('screenshots', 'genres')
        )
        # featured: свежие/со скидкой для хиро и слайдов
        featured_qs = with_images.order_by(F('discount_percent').desc(nulls_last=True), F('updated_at').desc())
        featured = list(featured_qs[:6])
        if len(featured) == 0:
            featured = list(with_images.order_by('-created_at')[:6])
        ctx['featured'] = featured
        # промо: максимальная скидка с фото
        promos_qs = with_images.filter(Q(discount_percent__gt=0) | Q(original_price__isnull=False, original_price__gt=F('price')))
        promos = list(promos_qs.order_by(F('discount_percent').desc(nulls_last=True), F('updated_at').desc())[:4])
        if len(promos) == 0:
            promos = featured[:4]
        ctx['promos'] = promos
        # категории (жадно из каталога ниже)
        # компактный каталог: последние с фото
        catalog = with_images.order_by('-created_at')[:12]
        ctx['catalog'] = catalog
        # топы продаж и новые релизы (на основе флагов из импорта)
        desired = 8
        top_qs = with_images.filter(is_top_seller=True).order_by('-updated_at')
        top_list = list(top_qs[:desired])
        if len(top_list) < desired:
            # backfill with biggest discounts excluding already selected
            exclude_ids = [g.id for g in top_list]
            backfill = list(
                with_images.exclude(id__in=exclude_ids)
                .order_by(F('discount_percent').desc(nulls_last=True), '-updated_at')[: desired - len(top_list)]
            )
            top_list.extend(backfill)
        ctx['top_sellers'] = top_list

        new_qs = with_images.filter(is_new_release=True).order_by(F('release_date').desc(nulls_last=True), '-created_at')
        new_list = list(new_qs[:desired])
        if len(new_list) < desired:
            exclude_ids = [g.id for g in new_list]
            backfill_new = list(
                with_images.exclude(id__in=exclude_ids)
                .order_by(F('release_date').desc(nulls_last=True), '-created_at')[: desired - len(new_list)]
            )
            new_list.extend(backfill_new)
        ctx['new_releases'] = new_list
        return ctx


class RecommendationsView(ListView):
    template_name = 'store/recommendations.html'
    context_object_name = 'games'
    paginate_by = 24

    def get_queryset(self):
        # Base set: only games with images so cards look good
        with_images = Game.objects.filter(Q(cover_image__isnull=False) | Q(screenshots__isnull=False)).distinct()

        request = self.request
        user = request.user
        if not user.is_authenticated:
            # Fallback для гостей: популярные и со скидками/оценками
            return (
                with_images
                .annotate(rating_avg=Avg('reviews__rating'), rating_count=Count('reviews'))
                .order_by(
                    F('discount_percent').desc(nulls_last=True),
                    F('rating_avg').desc(nulls_last=True),
                    '-updated_at'
                )[:60]
            )

        # Собираем библиотеку пользователя (купленное)
        owned = (
            Game.objects.filter(orderitem__order__user=user, orderitem__order__status='paid')
            .distinct()
        )
        owned_ids = list(owned.values_list('id', flat=True))

        # Подмешиваем интересы из вишлиста
        wishlist_ids = []
        try:
            profile = getattr(user, 'profile', None)
            if profile:
                wishlist_ids = list(profile.wishlist.values_list('id', flat=True))
        except Exception:
            wishlist_ids = []

        # Частоты жанров по библиотеке и вишлисту (вес вишлиста чуть выше)
        from collections import Counter
        genre_counter = Counter()
        if owned_ids:
            owned_genre_ids = list(
                Game.objects.filter(id__in=owned_ids).values_list('genres', flat=True)
            )
            genre_counter.update([gid for gid in owned_genre_ids if gid])
        if wishlist_ids:
            wl_genre_ids = list(
                Game.objects.filter(id__in=wishlist_ids).values_list('genres', flat=True)
            )
            # вес 1.5 для вишлиста: умножим на 3 и потом поделим (приблизительно)
            genre_counter.update([gid for gid in wl_genre_ids if gid])
            genre_counter.update([gid for gid in wl_genre_ids if gid])
            genre_counter.update([gid for gid in wl_genre_ids if gid])
        # список жанров по убыванию веса
        genre_ids = [gid for gid, _ in genre_counter.most_common(30) if gid]

        if not genre_ids:
            # если жанры не найдены, отдадим «новые и со скидкой»
            return (
                with_images
                .exclude(id__in=owned_ids)
                .annotate(rating_avg=Avg('reviews__rating'), rating_count=Count('reviews'))
                .order_by(F('discount_percent').desc(nulls_last=True), '-updated_at')[:60]
            )

        # Исключить выбранные пользователем жанры
        ex = request.GET.getlist('exclude') or []
        if not ex:
            single = request.GET.get('exclude', '')
            if single:
                ex = [x.strip() for x in single.split(',') if x.strip()]
        exclude_genre_ids = []
        if ex:
            exclude_genre_ids = list(Genre.objects.filter(slug__in=ex).values_list('id', flat=True))

        # скрытые игры из сессии
        hidden_ids = set()
        try:
            hidden_ids = set(request.session.get('hidden_rec_ids', []) or [])
        except Exception:
            hidden_ids = set()

        # Параметр A/B: g — жанры важнее, r — рейтинг важнее
        ab = (request.GET.get('ab') or 'g').lower()
        wg, wr, wd, wf = (2.5, 1.0, 0.2, 0.6) if ab == 'g' else (1.2, 2.2, 0.2, 0.6)

        # Буст свежести релизов (за последние 60 дней)
        from datetime import date, timedelta
        fresh_cut = date.today() - timedelta(days=60)

        wishlist_genre_ids = []
        if wishlist_ids:
            wishlist_genre_ids = list(
                Game.objects.filter(id__in=wishlist_ids).values_list('genres', flat=True)
            )

        qs = (
            with_images
            .exclude(id__in=owned_ids)
            .exclude(id__in=list(hidden_ids))
            .filter(genres__in=[gid for gid in genre_ids if gid not in exclude_genre_ids])
            .distinct()
            .annotate(
                genre_match=Count('genres', filter=Q(genres__in=genre_ids), distinct=True),
                wishlist_match=Count('genres', filter=Q(genres__in=wishlist_genre_ids), distinct=True),
                rating_avg=Avg('reviews__rating'),
                rating_count=Count('reviews'),
                is_fresh=Case(When(release_date__gte=fresh_cut, then=1), default=0, output_field=IntegerField()),
            )
        )

        # Итоговый скор для сортировки
        score = (
            F('genre_match') * wg + Coalesce(F('rating_avg'), Value(0.0)) * wr + Coalesce(F('discount_percent'), Value(0)) * wd + F('is_fresh') * wf + Coalesce(F('wishlist_match'), Value(0)) * 0.5
        )
        qs = qs.order_by(score.desc(nulls_last=True), F('rating_count').desc(nulls_last=True), '-updated_at')
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['recommendation_source'] = 'library_genres'
        # Топ жанры для UI исключения
        user = self.request.user
        top_genres = []
        try:
            owned_ids = list(
                Game.objects.filter(orderitem__order__user=user, orderitem__order__status='paid').values_list('id', flat=True)
            )
            wishlist_ids = []
            profile = getattr(user, 'profile', None)
            if profile:
                wishlist_ids = list(profile.wishlist.values_list('id', flat=True))
            from collections import Counter
            cnt = Counter()
            if owned_ids:
                cnt.update(list(Game.objects.filter(id__in=owned_ids).values_list('genres', flat=True)))
            if wishlist_ids:
                wl = list(Game.objects.filter(id__in=wishlist_ids).values_list('genres', flat=True))
                cnt.update(wl); cnt.update(wl)  # усиление
            ids = [gid for gid, _ in cnt.most_common(12) if gid]
            top_genres = list(Genre.objects.filter(id__in=ids))
        except Exception:
            top_genres = []
        ctx['top_genres'] = top_genres
        ctx['ab'] = (self.request.GET.get('ab') or 'g').lower()
        ctx['exclude'] = self.request.GET.getlist('exclude') or []
        return ctx


class RecommendationsHideView(View):
    def post(self, request, pk):
        hidden = set(request.session.get('hidden_rec_ids', []) or [])
        hidden.add(int(pk))
        request.session['hidden_rec_ids'] = list(hidden)
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('store:recommendations')
        return redirect(next_url)


class LogoutView(View):
    """Log the user out and show a short spinner page before redirecting home."""

    def post(self, request):
        auth_logout(request)
        return render(request, 'registration/logging_out.html', {"redirect_to": reverse('store:home'), "delay_ms": 1000})

    def get(self, request):
        # Allow GET for convenience
        auth_logout(request)
        return render(request, 'registration/logging_out.html', {"redirect_to": reverse('store:home'), "delay_ms": 1000})


class AboutView(TemplateView):
    template_name = 'store/about.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Simple metrics to make the page feel alive
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            ctx['metrics'] = {
                'games': Game.objects.count(),
                'genres': getattr(Game, 'genres').rel.model.objects.count() if hasattr(Game, 'genres') else 0,
                'users': User.objects.count(),
                'reviews': Review.objects.count(),
            }
        except Exception:
            ctx['metrics'] = {'games': 0, 'genres': 0, 'users': 0, 'reviews': 0}
        return ctx


class ChartsView(TemplateView):
    template_name = 'store/charts.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        request = self.request
        # Only show games with some imagery
        with_images = Game.objects.filter(Q(cover_image__isnull=False) | Q(screenshots__isnull=False)).distinct()

        # 1) Top sellers from Steam featuredcategories to approximate charts ordering
        top_ids: list[int] = []
        try:
            lang = (translation.get_language() or 'en').split('-')[0]
            # country code best-effort: map by preferred currency or default to US
            cc = 'US'
            try:
                user = request.user
                if getattr(user, 'is_authenticated', False):
                    prof = getattr(user, 'profile', None)
                    cur = getattr(prof, 'preferred_currency', '') if prof else ''
                    # simple mapping currency -> CC
                    currency_cc = {
                        'USD': 'US', 'EUR': 'DE', 'GBP': 'GB', 'UAH': 'UA', 'RUB': 'RU', 'JPY': 'JP',
                        'CAD': 'CA', 'AUD': 'AU', 'CNY': 'CN', 'PLN': 'PL'
                    }
                    cc = currency_cc.get(cur, cc)
            except Exception:
                pass
            url = f'https://store.steampowered.com/api/featuredcategories?cc={cc}&l={lang}'
            r = requests.get(url, timeout=5)
            if r.ok:
                j = r.json() or {}
                items = (j.get('top_sellers') or {}).get('items') or []
                top_ids = [it.get('id') for it in items if it.get('id')]
        except Exception:
            top_ids = []

        # Keep order as in API
        top_sellers = []
        if top_ids:
            whens = [When(appid=aid, then=pos) for pos, aid in enumerate(top_ids, start=1)]
            rank_expr = Case(*whens, default=9999, output_field=IntegerField())
            qs = (
                with_images.filter(appid__in=top_ids)
                .annotate(chart_rank=rank_expr)
                .order_by('chart_rank')
            )
            top_sellers = list(qs[:100])
        else:
            # Fallback: use internal flag + discount as proxy
            top_sellers = list(
                with_images.filter(is_top_seller=True).order_by(F('discount_percent').desc(nulls_last=True), '-updated_at')[:100]
            )

        # 2) Most wishlisted (our community)
        wishlisted = list(
            with_images.annotate(wish_count=Count('wishlisted_by', distinct=True))
            .filter(wish_count__gt=0)
            .order_by(F('wish_count').desc(nulls_last=True), '-updated_at')[:100]
        )

        # 3) Top rated (avg rating with count as tiebreaker)
        top_rated = list(
            with_images.annotate(rating_avg=Avg('reviews__rating'), rating_count=Count('reviews'))
            .filter(rating_count__gt=0)
            .order_by(F('rating_avg').desc(nulls_last=True), F('rating_count').desc(nulls_last=True))[:100]
        )

        # 4) Most reviewed
        most_reviewed = list(
            with_images.annotate(rating_count=Count('reviews'))
            .filter(rating_count__gt=0)
            .order_by(F('rating_count').desc(nulls_last=True), '-updated_at')[:100]
        )

        # 5) Biggest discounts
        biggest_discounts = list(
            with_images.filter(Q(discount_percent__gt=0) | Q(original_price__isnull=False, original_price__gt=F('price')))
            .order_by(F('discount_percent').desc(nulls_last=True), '-updated_at')[:100]
        )

        # 6) New releases (recent first)
        new_releases = list(with_images.order_by(F('release_date').desc(nulls_last=True), '-created_at')[:100])

        # 7) Best sellers in our store (paid order items quantity)
        best_sellers_local = list(
            with_images.annotate(total_sold=Coalesce(Sum('orderitem__quantity', filter=Q(orderitem__order__status='paid')), Value(0)))
            .filter(total_sold__gt=0)
            .order_by(F('total_sold').desc(nulls_last=True), '-updated_at')[:100]
        )

        ctx.update({
            'top_sellers': top_sellers,
            'wishlisted': wishlisted,
            'top_rated': top_rated,
            'most_reviewed': most_reviewed,
            'biggest_discounts': biggest_discounts,
            'new_releases': new_releases,
            'best_sellers_local': best_sellers_local,
        })

        # Extra charts: Free popular and Coming soon + top-level metrics
        try:
            free_popular = list(
                with_images.filter(Q(price__lte=0))
                .annotate(wish_count=Count('wishlisted_by', distinct=True), rating_avg=Avg('reviews__rating'))
                .order_by(F('wish_count').desc(nulls_last=True), F('rating_avg').desc(nulls_last=True), '-updated_at')[:100]
            )
        except Exception:
            free_popular = []

        from datetime import date
        today = date.today()
        try:
            coming_soon = list(
                with_images.filter(release_date__gt=today)
                .order_by('release_date')[:100]
            )
        except Exception:
            coming_soon = []

        # Small metrics strip
        try:
            total_games = with_images.count()
            discounted_qs = with_images.filter(Q(discount_percent__gt=0) | Q(original_price__isnull=False, original_price__gt=F('price')))
            discounted_count = discounted_qs.count()
            avg_discount = discounted_qs.aggregate(val=Avg('discount_percent'))['val'] or 0
            free_count = with_images.filter(price__lte=0).count()
            upcoming_count = with_images.filter(release_date__gt=today).count()
            ctx['chart_metrics'] = {
                'total': total_games,
                'discounted': discounted_count,
                'avg_discount': round(float(avg_discount or 0), 1),
                'free_count': free_count,
                'upcoming': upcoming_count,
            }
        except Exception:
            ctx['chart_metrics'] = {'total': 0, 'discounted': 0, 'avg_discount': 0, 'free_count': 0, 'upcoming': 0}

        ctx['free_popular'] = free_popular
        ctx['coming_soon'] = coming_soon
        return ctx

class WishlistListView(LoginRequiredMixin, ListView):
    template_name = 'store/wishlist.html'
    context_object_name = 'games'

    def get_queryset(self):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        qs = profile.wishlist.all()

        # Filters
        request = self.request
        q = request.GET.get('q')
        platform = request.GET.get('platform')  # 'win' | 'mac' | 'linux'
        sort = request.GET.get('sort')  # 'title', '-title', 'price', '-price', 'created', '-created'

        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q)).distinct()

        if platform:
            p = platform.lower()
            if p in ('win', 'windows'):
                qs = qs.filter(supports_windows=True)
            elif p in ('mac', 'macos', 'osx'):
                qs = qs.filter(supports_mac=True)
            elif p in ('linux',):
                qs = qs.filter(supports_linux=True)

        # Sorting
        if sort in ('title', '-title', 'price', '-price', 'created', '-created'):
            if sort == 'created':
                qs = qs.order_by('created_at')
            elif sort == '-created':
                qs = qs.order_by('-created_at')
            else:
                qs = qs.order_by(sort)
        else:
            # default: newest first
            qs = qs.order_by('-created_at')

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        preferred_currency = 'USD'
        if user.is_authenticated:
            profile = getattr(user, 'profile', None)
            if profile:
                preferred_currency = profile.preferred_currency
        ctx['preferred_currency'] = preferred_currency
        ctx['filters'] = {
            'q': self.request.GET.get('q', ''),
            'platform': self.request.GET.get('platform', ''),
            'sort': self.request.GET.get('sort', ''),
        }
        return ctx


class CartAddView(LoginRequiredMixin, View):
    """Add a game to the user's cart (quantity +1 if already present)."""

    def post(self, request, slug):
        game = get_object_or_404(Game, slug=slug)
        # If the game is free, add directly to library as a paid order with zero price
        try:
            from decimal import Decimal
            is_free = (game.price or Decimal('0')) == 0
        except Exception:
            is_free = False

        if is_free:
            # Already owned?
            owns = OrderItem.objects.filter(order__user=request.user, order__status='paid', game=game).exists()
            if owns:
                messages.info(request, "Эта игра уже в вашей библиотеке.")
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    # For AJAX, signal that the game is owned already
                    return JsonResponse({
                        "ok": True,
                        "owned": True,
                        "already_owned": True,
                        "game": game.slug,
                        "cart_items": CartItem.objects.filter(user=request.user).count(),
                    })
            else:
                from decimal import Decimal
                with transaction.atomic():
                    order = Order.objects.create(
                        user=request.user,
                        total_price=Decimal('0.00'),
                        currency=game.currency,
                        status='paid',
                    )
                    OrderItem.objects.create(
                        order=order,
                        game=game,
                        quantity=1,
                        price=Decimal('0.00'),
                        currency=game.currency,
                    )
                messages.success(request, f"‘{game.title}’ добавлена в библиотеку (бесплатно)")
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        "ok": True,
                        "owned": True,
                        "already_owned": False,
                        "game": game.slug,
                        "cart_items": CartItem.objects.filter(user=request.user).count(),
                    })
            next_url = request.POST.get('next') or reverse('store:library')
            return redirect(next_url)

        # Non-free: proceed with regular cart flow
        item, created = CartItem.objects.get_or_create(user=request.user, game=game, defaults={'quantity': 1})
        if not created:
            item.quantity += 1
            item.save(update_fields=['quantity'])
        try:
            messages.success(request, f"‘{game.title}’ добавлена в корзину")
        except Exception:
            pass
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                "ok": True,
                "in_cart": True,
                "game": game.slug,
                # distinct cart items count for header badge
                "cart_items": CartItem.objects.filter(user=request.user).count(),
            })
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('store:wishlist')
        return redirect(next_url)


class CartView(LoginRequiredMixin, TemplateView):
    template_name = 'store/cart.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        items = CartItem.objects.select_related('game').filter(user=self.request.user).order_by('-added_at')
        preferred_currency = 'USD'
        profile = getattr(self.request.user, 'profile', None)
        if profile:
            preferred_currency = profile.preferred_currency

        # Build cart summary
        subtotal = 0
        detailed_items: list[dict[str, Any]] = []
        for it in items:
            price = it.game.price or 0
            qty = it.quantity or 1
            line_total = price * qty
            subtotal += line_total
            # Try conversion for line total
            try:
                converted_line_total = convert_amount(line_total, it.game.currency, preferred_currency)
            except Exception:
                converted_line_total = line_total
            detailed_items.append({
                'item': it,
                'game': it.game,
                'qty': qty,
                'price': price,
                'currency': it.game.currency,
                'line_total': line_total,
                'converted_line_total': converted_line_total,
            })

        try:
            from_currency = detailed_items[0]['currency'] if detailed_items else preferred_currency
            converted_subtotal = convert_amount(subtotal, from_currency, preferred_currency)
        except Exception:
            converted_subtotal = subtotal

        # simple recommendations: recent games not in cart
        try:
            in_cart_ids = [it.game.id for it in items]
            recommendations = Game.objects.exclude(id__in=in_cart_ids).order_by('-created_at')[:6]
        except Exception:
            recommendations = Game.objects.all().order_by('-created_at')[:6]

        ctx.update({
            'items': items,
            'detailed_items': detailed_items,
            'subtotal': subtotal,
            'currency': detailed_items[0]['currency'] if detailed_items else preferred_currency,
            'preferred_currency': preferred_currency,
            'converted_subtotal': converted_subtotal,
            'recommendations': recommendations,
        })
        return ctx


class CartUpdateView(LoginRequiredMixin, View):
    def post(self, request, item_id):
        item = get_object_or_404(CartItem, id=item_id, user=request.user)
        try:
            qty = int(request.POST.get('quantity', '1'))
        except ValueError:
            qty = 1
        if qty <= 0:
            item.delete()
        else:
            item.quantity = qty
            item.save(update_fields=['quantity'])
        return redirect('store:cart')


class CartRemoveView(LoginRequiredMixin, View):
    def post(self, request, item_id):
        item = get_object_or_404(CartItem, id=item_id, user=request.user)
        item.delete()
        return redirect('store:cart')


class CartClearView(LoginRequiredMixin, View):
    def post(self, request):
        CartItem.objects.filter(user=request.user).delete()
        return redirect('store:cart')


class CheckoutView(LoginRequiredMixin, TemplateView):
    template_name = 'store/checkout.html'

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        items = CartItem.objects.select_related('game').filter(user=self.request.user)
        subtotal = sum([(it.game.price or 0) * (it.quantity or 1) for it in items])
        preferred_currency = getattr(getattr(self.request.user, 'profile', None), 'preferred_currency', 'USD')
        first_item = items.first()
        currency = first_item.game.currency if first_item else preferred_currency
        try:
            converted = convert_amount(subtotal, currency, preferred_currency)
        except Exception:
            converted = subtotal
        ctx.update({
            'items': items,
            'subtotal': subtotal,
            'currency': currency,
            'preferred_currency': preferred_currency,
            'converted_subtotal': converted,
        })
        return ctx

    def post(self, request, *args, **kwargs):
        """Создаём заказ (pending) и перенаправляем на фейковую оплату. Без реального провайдера."""
        user = request.user
        items = list(CartItem.objects.select_related('game').filter(user=user))
        if not items:
            messages.info(request, "Корзина пуста.")
            return redirect('store:cart')

        preferred_currency = getattr(getattr(user, 'profile', None), 'preferred_currency', 'USD')
        first = items[0]
        order_currency = getattr(getattr(first, 'game', None), 'currency', None) or preferred_currency

        from decimal import Decimal
        # Пересчитываем сумму в валюту заказа при необходимости
        total = Decimal('0.00')
        for it in items:
            price = it.game.price or Decimal('0.00')
            qty = it.quantity or 1
            line = price * qty
            try:
                if it.game.currency != order_currency:
                    line = convert_amount(line, it.game.currency, order_currency)
            except Exception:
                # в случае ошибки конвертации — берём как есть
                pass
            total += line

        with transaction.atomic():
            # Если есть уже незавершённый заказ в сессии — переиспользуем
            pending_id = request.session.get('pending_order_id')
            order = None
            if pending_id:
                order = Order.objects.filter(id=pending_id, user=user, status='pending').first()

            if order is None:
                order = Order.objects.create(
                    user=user,
                    total_price=total,
                    currency=order_currency,
                    status='pending',
                )
                # Снимок позиций (фиксируем, что именно покупает пользователь)
                order_items = []
                for it in items:
                    oi = OrderItem(
                        order=order,
                        game=it.game,
                        quantity=it.quantity or 1,
                        price=it.game.price or Decimal('0.00'),
                        currency=it.game.currency or order_currency,
                    )
                    order_items.append(oi)
                OrderItem.objects.bulk_create(order_items)
                # Сохраняем id в сессии — защита от дабл-сабмита
                request.session['pending_order_id'] = order.id
            else:
                # Обновим тотал на всякий случай (например, если курс поменялся)
                order.total_price = total
                order.currency = order_currency
                order.save(update_fields=['total_price', 'currency'])

        messages.success(request, "Черновик заказа создан. Перейдите к оплате.")
        return redirect('store:pay', pk=order.id)


class OrderDetailView(LoginRequiredMixin, DetailView):
    model = Order
    template_name = 'store/order_detail.html'
    context_object_name = 'order'

    def get_queryset(self):
        # Limit visibility to the current user's orders
        return Order.objects.filter(user=self.request.user).prefetch_related('items_snapshot__game')


class OrdersListView(LoginRequiredMixin, ListView):
    model = Order
    template_name = 'store/orders_list.html'
    context_object_name = 'orders'
    paginate_by = 20

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).order_by('-created_at')


class PaymentView(LoginRequiredMixin, TemplateView):
    template_name = 'store/pay.html'

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        order = get_object_or_404(Order, id=kwargs.get('pk'), user=self.request.user)
        ctx['order'] = order
        # Показать приблизительную конвертацию в предпочитаемую валюту
        preferred_currency = getattr(getattr(self.request.user, 'profile', None), 'preferred_currency', 'USD')
        try:
            ctx['converted_total'] = convert_amount(order.total_price, order.currency, preferred_currency)
        except Exception:
            ctx['converted_total'] = order.total_price
        ctx['preferred_currency'] = preferred_currency
        return ctx

    def post(self, request, *args, **kwargs):
        order = get_object_or_404(Order, id=kwargs.get('pk'), user=request.user)
        # Опционально списать средства с баланса (форма содержит hidden использование баланса или чекбокс)
        use_wallet = request.POST.get('use_wallet') == '1'
        prof = getattr(request.user, 'profile', None)
        if order.status != 'paid':
            with transaction.atomic():
                order.status = 'paid'
                order.save(update_fields=['status'])
                # Обновим траты пользователя
                if prof:
                    try:
                        # Если используем баланс – сначала конвертируем order.total_price в preferred_currency
                        if use_wallet and prof.balance > 0:
                            from decimal import Decimal
                            to_charge = order.total_price
                            if order.currency != prof.preferred_currency:
                                try:
                                    to_charge = convert_amount(order.total_price, order.currency, prof.preferred_currency)
                                except Exception:
                                    pass
                            # Пытаемся списать, если хватает средств
                            if prof.balance >= to_charge:
                                before = prof.balance
                                ok = prof.deduct_balance(to_charge, prof.preferred_currency, allow_negative=False)
                                if ok:
                                    # Запишем транзакцию кошелька
                                    try:
                                        from .models import WalletTransaction
                                        WalletTransaction.objects.create(
                                            user=request.user,
                                            amount=(before - prof.balance) * Decimal('-1'),  # negative value
                                            currency=prof.preferred_currency,
                                            source_amount=order.total_price,
                                            source_currency=order.currency,
                                            kind='purchase_deduct',
                                            balance_after=prof.balance,
                                            description=f"Оплата заказа #{order.id}"
                                        )
                                    except Exception:
                                        pass
                                messages.info(request, _("Списано %(amount).2f %(cur)s с баланса.") % { 'amount': to_charge, 'cur': prof.preferred_currency })
                            else:
                                messages.info(request, _("Недостаточно средств на балансе. Списание пропущено."))
                        prof.add_spending(order.total_price)
                    except Exception:
                        pass
        # Очистим корзину после успешной оплаты
        CartItem.objects.filter(user=request.user).delete()
        # Снимем флаг сессии
        request.session.pop('pending_order_id', None)
        messages.success(request, _("Оплата прошла успешно. Спасибо за покупку!"))
        return redirect('store:order_detail', pk=order.id)


class LibraryView(LoginRequiredMixin, ListView):
    template_name = 'store/library.html'
    context_object_name = 'games'
    paginate_by = 24

    def get_queryset(self):
        user = self.request.user
        # Базовый набор: купленные (paid orders) + внешние владения (OwnedGame)
        qs = Game.objects.filter(
            Q(orderitem__order__user=user, orderitem__order__status='paid') |
            Q(owned_by__user=user)
        ).distinct()
        # Аннотации: последняя дата покупки и playtime (берём максимум playtime_forever из OwnedGame)
        from django.db.models import Subquery, OuterRef, Max, IntegerField
        from .models import OwnedGame, OrderItem
        last_purchase_sub = OrderItem.objects.filter(
            order__user=user, order__status='paid', game=OuterRef('pk')
        ).order_by('-order__created_at').values('order__created_at')[:1]
        qs = qs.annotate(
            last_purchase_at=Subquery(last_purchase_sub),
            playtime_forever=Max('owned_by__playtime_forever', filter=Q(owned_by__user=user), output_field=IntegerField()),
        )
        # Фильтры
        request = self.request
        min_play = request.GET.get('min_play')  # часы
        max_play = request.GET.get('max_play')
        try:
            if min_play:
                mp = int(float(min_play) * 60)  # convert hours -> minutes
                qs = qs.filter(owned_by__playtime_forever__gte=mp)
            if max_play:
                xp = int(float(max_play) * 60)
                qs = qs.filter(owned_by__playtime_forever__lte=xp)
        except Exception:
            pass
        # Сортировка
        sort = request.GET.get('sort', '')
        if sort == 'playtime':
            qs = qs.order_by(F('playtime_forever').desc(nulls_last=True), '-updated_at')
        elif sort == 'playtime_asc':
            qs = qs.order_by(F('playtime_forever').asc(nulls_last=True), '-updated_at')
        elif sort == 'recent':
            qs = qs.order_by(F('last_purchase_at').desc(nulls_last=True), '-updated_at')
        elif sort == 'oldest':
            qs = qs.order_by(F('last_purchase_at').asc(nulls_last=True), '-updated_at')
        elif sort == 'title':
            qs = qs.order_by('title')
        elif sort == 'title_desc':
            qs = qs.order_by('-title')
        else:
            qs = qs.order_by('-updated_at')
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['filters'] = {
            'sort': self.request.GET.get('sort', ''),
            'min_play': self.request.GET.get('min_play', ''),
            'max_play': self.request.GET.get('max_play', ''),
        }
        return ctx


class DiscountsListView(ListView):
    template_name = 'store/discounts.html'
    context_object_name = 'games'
    paginate_by = 24

    def get_queryset(self):
        qs = Game.objects.all()
        # отбираем со скидкой: либо discount_percent > 0, либо old > current
        qs = qs.filter(Q(discount_percent__gt=0) | Q(original_price__isnull=False, original_price__gt=F('price')))

        # поиск и платформы (как в каталоге, сокращённо)
        request = self.request
        q = request.GET.get('q')
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

        platform = request.GET.get('platform', '')
        if platform:
            p = platform.lower()
            if p in ('win', 'windows'):
                qs = qs.filter(supports_windows=True)
            elif p in ('mac', 'macos', 'osx'):
                qs = qs.filter(supports_mac=True)
            elif p in ('linux',):
                qs = qs.filter(supports_linux=True)

        sort = request.GET.get('sort', '-discount')
        if sort == '-discount':
            qs = qs.order_by(F('discount_percent').desc(nulls_last=True), F('updated_at').desc())
        elif sort == 'price':
            qs = qs.order_by('price')
        elif sort == '-price':
            qs = qs.order_by('-price')
        elif sort == 'title':
            qs = qs.order_by('title')
        elif sort == '-title':
            qs = qs.order_by('-title')
        else:
            qs = qs.order_by(F('discount_percent').desc(nulls_last=True))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        preferred_currency = 'USD'
        if user.is_authenticated:
            profile = getattr(user, 'profile', None)
            if profile:
                preferred_currency = profile.preferred_currency
        ctx['preferred_currency'] = preferred_currency
        ctx['filters'] = {
            'q': self.request.GET.get('q', ''),
            'platform': self.request.GET.get('platform', ''),
            'sort': self.request.GET.get('sort', '-discount'),
        }
        return ctx


class WishlistToggleView(LoginRequiredMixin, View):
    """Toggle a game in the user's wishlist. Expects POST."""

    def post(self, request, slug):
        game = get_object_or_404(Game, slug=slug)
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        in_list = profile.wishlist.filter(id=game.id).exists()
        if in_list:
            profile.wishlist.remove(game)
            in_list = False
        else:
            profile.wishlist.add(game)
            in_list = True
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                "ok": True,
                "in_wishlist": in_list,
                "game": game.slug,
                "wishlist_count": profile.wishlist.count(),
            })
        # redirect back to 'next' or game detail
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('store:game_detail', args=[game.slug])
        return redirect(next_url)


from django.contrib.auth.mixins import LoginRequiredMixin


class SupportView(LoginRequiredMixin, View):
    template_name = 'store/support.html'

    def get(self, request):
        form = SupportTicketForm()
        faqs = [
            {"q": "Как добавить игру в список желаемого?", "a": "Откройте страницу игры и нажмите кнопку \"В список желаемого\"."},
            {"q": "Почему не загружаются обложки?", "a": "Проверьте наличие header.jpg в MEDIA/steam_imports/<appid> или подключение к Steam CDN."},
            {"q": "Как изменить валюту?", "a": "В настройках профиля выберите предпочитаемую валюту."},
        ]
        return render(request, self.template_name, {"form": form, "faqs": faqs})


class SearchSuggestView(View):
    """Return lightweight JSON suggestions for the header search field.

    GET /api/search_suggest/?q=te
    Response: { items: [ {title, slug, price, currency, image} ] }
    """
    def get(self, request):
        q = (request.GET.get('q') or '').strip()
        if len(q) < 2:
            return JsonResponse({"items": []})
        # Ranking heuristic:
        # 1. Exact case-insensitive title match startswith(q) -> highest weight
        # 2. Title icontains(q) prefix (position == 0) -> high
        # 3. Title icontains(q) later in string -> medium
        # 4. Genre name startswith(q) -> medium
        # 5. Developer name startswith(q) -> medium-low
        # 6. Genre/Developer contains -> low
        # We build a queryset and annotate a numeric score, then order by score desc, updated_at desc.
        base = Game.objects.filter(appid__isnull=False).filter(Q(cover_image__isnull=False) | Q(screenshots__isnull=False)).distinct()
        q_lower = q.lower()
        # Annotate matches; since SQLite lacks sophisticated functions, we compute booleans and map to weights.
        from django.db.models import Case, When, IntegerField, Value
        from django.db.models.functions import Lower
        qs = (
            base.annotate(
                title_lower=Lower('title'),
                dev_lower=Lower('developer__name'),
            )
            .annotate(
                score=Coalesce(
                    Case(
                        # exact startswith
                        When(title_lower__startswith=q_lower, then=Value(160)),
                        default=Value(0), output_field=IntegerField()
                    ), Value(0)
                )
            )
        )
        # Additional layering in Python for clarity (since chained Case for contains position is clumsy):
        candidates = list(qs[:160])  # limit pre-scan
        # Pre-fetch genres to reduce queries (simple dict of id->names)
        # We'll compute a final composite score in Python then slice top 10.
        scored = []
        for g in candidates:
            s = getattr(g, 'score', 0)
            tl = getattr(g, 'title', '')
            tl_low = tl.lower()
            if q_lower == tl_low:
                s += 200  # perfect match
            elif tl_low.startswith(q_lower):
                s += 120
            elif q_lower in tl_low:
                # position factor: earlier is better
                try:
                    pos = tl_low.index(q_lower)
                    if pos < 8:
                        s += 70 - pos * 4
                    else:
                        s += 40
                except ValueError:
                    pass
            # Genres
            try:
                genre_names = list(g.genres.values_list('name', flat=True))
            except Exception:
                genre_names = []
            for name in genre_names:
                nl = name.lower()
                if nl.startswith(q_lower):
                    s += 55
                elif q_lower in nl:
                    s += 25
            # Developer
            try:
                dev_name = getattr(getattr(g, 'developer', None), 'name', '')
            except Exception:
                dev_name = ''
            dl = dev_name.lower()
            if dl:
                if dl.startswith(q_lower):
                    s += 45
                elif q_lower in dl:
                    s += 20
            # Small boost for higher discount (user interest) and recent update
            try:
                disc = int(getattr(g, 'discount_percent', 0) or 0)
                if disc > 0:
                    s += min(30, disc)  # cap boost
            except Exception:
                pass
            scored.append((s, g))
        scored.sort(key=lambda tup: (tup[0], getattr(tup[1], 'updated_at', None)), reverse=True)
        final_games = [g for _score, g in scored[:10]]

        def cover_url(g: Game) -> str:
            try:
                if getattr(g, 'cover_image', None):
                    u = g.cover_image.url
                    if u:
                        return u
            except Exception:
                pass
            appid = getattr(g, 'appid', None)
            if appid:
                rel = os.path.join('steam_imports', str(appid), 'header.jpg').replace('\\', '/')
                abs_path = os.path.join(str(settings.MEDIA_ROOT), rel)
                if os.path.isfile(abs_path):
                    return str(settings.MEDIA_URL) + rel
                return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
            return ''

        items = []
        for g in final_games:
            items.append({
                'title': g.title,
                'slug': g.slug,
                'price': float(g.price or 0),
                'currency': g.currency,
                'image': cover_url(g),
            })
        return JsonResponse({"items": items})

    def post(self, request):
        form = SupportTicketForm(request.POST)
        faqs = []
        if form.is_valid():
            ticket = SupportTicket(
                user=request.user,
                email=request.user.email or '',
                category=form.cleaned_data['category'],
                category_other=form.cleaned_data.get('category_other', ''),
                subject=form.cleaned_data['subject'],
                message=form.cleaned_data['message'],
            )
            ticket.save()
            return render(request, self.template_name, {
                "form": SupportTicketForm(),
                "success": True,
                "ticket": ticket,
                "faqs": faqs,
            })
        return render(request, self.template_name, {"form": form, "faqs": faqs})


class SteamAuthStartView(TemplateView):
    """Interstitial page to give immediate feedback before redirecting to Steam OpenID.

    Renders a spinner and then navigates to the social-auth URL /oauth/login/steam/.
    Also includes a manual link if auto-redirect is blocked.
    """
    template_name = 'store/steam_redirect.html'


class SafeLoginView(LoginView):
    """Login view that sanitizes 'next' to avoid redirecting into Steam OpenID flows.

    Prevents loops when the user previously landed on /auth/steam/ or /oauth/login/steam/.
    """
    def get_success_url(self):
        url = super().get_success_url()
        banned_prefixes = (
            '/auth/steam/',
            '/oauth/login/steam/',
            '/oauth/complete/steam/',
        )
        try:
            from urllib.parse import urlparse
            path = urlparse(url).path
        except Exception:
            path = url or '/'
        if any((path or '').startswith(p) for p in banned_prefixes):
            return '/'
        return url


class WalletTopUpView(LoginRequiredMixin, TemplateView):
    template_name = 'store/wallet_topup.html'

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        prof = getattr(self.request.user, 'profile', None)
        ctx['preferred_currency'] = getattr(prof, 'preferred_currency', 'USD')
        ctx['balance'] = getattr(prof, 'balance', 0)
        # Предлагаем выбор валюты пополнения (отдельно от preferred_currency)
        from .models import Game
        ctx['currency_choices'] = Game.CURRENCY_CHOICES
        # Предрасчёт минимального пополнения ~= $1 в каждой валюте
        from decimal import Decimal
        min_by_currency: dict[str, str] = {}
        for code, _label in Game.CURRENCY_CHOICES:
            try:
                v = convert_amount(Decimal('1.00'), 'USD', code)
            except Exception:
                v = Decimal('1.00') if code == 'USD' else Decimal('0.00')
            # строкой для удобной вставки в атрибуты
            min_by_currency[code] = f"{v:.2f}"
        ctx['min_topup_by_currency'] = min_by_currency
        ctx['min_topup_usd'] = '1.00'
        # История транзакций кошелька с фильтрами и пагинацией
        try:
            from .models import WalletTransaction
            qs = WalletTransaction.objects.filter(user=self.request.user).order_by('-created_at')
            # Фильтры: тип операции и диапазон дат
            kind = (self.request.GET.get('kind') or '').strip()
            if kind in { 'topup', 'purchase_deduct', 'manual_adjust', 'refund' }:
                qs = qs.filter(kind=kind)
            date_from = (self.request.GET.get('date_from') or '').strip()
            date_to = (self.request.GET.get('date_to') or '').strip()
            from django.utils.dateparse import parse_date
            df = parse_date(date_from) if date_from else None
            dt = parse_date(date_to) if date_to else None
            if df:
                from django.utils import timezone as dj_tz
                start = dj_tz.make_aware(dj_tz.datetime.combine(df, dj_tz.datetime.min.time())) if dj_tz.is_naive(dj_tz.datetime.now()) else dj_tz.datetime.combine(df, dj_tz.datetime.min.time()).replace(tzinfo=dj_tz.get_current_timezone())
                qs = qs.filter(created_at__gte=start)
            if dt:
                from django.utils import timezone as dj_tz
                end = dj_tz.make_aware(dj_tz.datetime.combine(dt, dj_tz.datetime.max.time())) if dj_tz.is_naive(dj_tz.datetime.now()) else dj_tz.datetime.combine(dt, dj_tz.datetime.max.time()).replace(tzinfo=dj_tz.get_current_timezone())
                qs = qs.filter(created_at__lte=end)

            # Пагинация
            from django.core.paginator import Paginator, EmptyPage
            page_str = self.request.GET.get('page', '1')
            try:
                page_num = int(page_str)
            except Exception:
                page_num = 1
            paginator = Paginator(qs, 25)
            try:
                page_obj = paginator.page(page_num)
            except EmptyPage:
                page_obj = paginator.page(paginator.num_pages or 1)
            ctx['wallet_transactions'] = page_obj  # page object
            ctx['tx_filters'] = { 'kind': kind, 'date_from': date_from, 'date_to': date_to }
        except Exception:
            ctx['wallet_transactions'] = []
        return ctx

    def post(self, request, *args, **kwargs):
        prof = getattr(request.user, 'profile', None)
        if not prof:
            messages.error(request, _('Профиль не найден.'))
            return redirect('store:home')
        amt_raw = (request.POST.get('amount') or '').strip()
        chosen_currency = (request.POST.get('currency') or '').strip() or prof.preferred_currency
        from decimal import Decimal, InvalidOperation
        try:
            amt = Decimal(amt_raw)
        except InvalidOperation:
            messages.error(request, _('Введите корректную сумму.'))
            return redirect('store:wallet_topup')
        if amt <= 0:
            messages.error(request, _('Сумма должна быть больше 0.'))
            return redirect('store:wallet_topup')
        # Минимальное пополнение: эквивалент $1 в выбранной валюте
        try:
            min_amt = convert_amount(Decimal('1.00'), 'USD', chosen_currency)
        except Exception:
            min_amt = Decimal('1.00') if chosen_currency == 'USD' else Decimal('0.00')
        if amt < min_amt:
            messages.error(request, _("Минимальная сумма пополнения для %(code)s: %(amount).2f (эквивалент $1).") % { 'code': chosen_currency, 'amount': min_amt })
            return redirect('store:wallet_topup')
        # Конвертируем в preferred_currency если выбрана другая.
        target_cur = prof.preferred_currency
        credited = amt
        if chosen_currency != target_cur:
            try:
                credited = convert_amount(amt, chosen_currency, target_cur)
            except Exception:
                credited = amt
        before = prof.balance
        prof.add_balance(credited, target_cur)
        delta = prof.balance - before
        # Записываем транзакцию
        try:
            from .models import WalletTransaction
            WalletTransaction.objects.create(
                user=request.user,
                amount=delta,  # already in preferred currency
                currency=target_cur,
                source_amount=amt if chosen_currency != target_cur else None,
                source_currency=chosen_currency if chosen_currency != target_cur else None,
                kind='topup',
                balance_after=prof.balance,
                description=f"Пополнение {amt:.2f} {chosen_currency}"
            )
        except Exception:
            pass
        # Сообщение: сколько ввели и сколько зачислено после конверсии
        if chosen_currency != target_cur:
            messages.success(request, _("Пополнение %(src_amount).2f %(src_cur)s → зачислено %(dst_amount).2f %(dst_cur)s.") % { 'src_amount': amt, 'src_cur': chosen_currency, 'dst_amount': delta, 'dst_cur': target_cur })
        else:
            messages.success(request, _("Баланс пополнен на %(amount).2f %(cur)s.") % { 'amount': delta, 'cur': target_cur })
        return redirect('store:wallet_topup')


class ProfileView(TemplateView):
    """Public profile page similar to Steam layout (simplified).

    Builds context: privacy checks, library stats, recent activity (Steam + local),
    wishlist preview, reviews, badges, header metrics and sidebar status.
    """

    template_name = 'store/profile.html'
    TARGET = 5
    CUTOFF_DAYS = 30

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        username = kwargs.get('username')
        user_obj = get_object_or_404(User, username=username)
        profile, _ = UserProfile.objects.get_or_create(user=user_obj)

        # --- Privacy enforcement ---
        is_owner = self.request.user.is_authenticated and self.request.user.id == user_obj.id
        is_friend = False
        if self.request.user.is_authenticated and not is_owner:
            uid = self.request.user.id; oid = user_obj.id
            a, b = (uid, oid) if uid < oid else (oid, uid)
            is_friend = Friendship.objects.filter(user_a_id=a, user_b_id=b).exists()
        if profile.privacy == 'private' and not is_owner:
            return {'profile_user': user_obj, 'profile': profile, 'is_private': True}
        if profile.privacy == 'friends' and not (is_owner or is_friend):
            return {'profile_user': user_obj, 'profile': profile, 'is_private': True}

        # --- Library & purchases ---
        purchased_qs = Game.objects.filter(orderitem__order__user=user_obj, orderitem__order__status='paid').distinct()
        external_qs = Game.objects.filter(owned_by__user=user_obj).distinct()
        lib_ids = list(set(list(purchased_qs.values_list('id', flat=True)) + list(external_qs.values_list('id', flat=True))))
        library_count = len(lib_ids)
        recent_purchases = list(purchased_qs.order_by('-orderitem__order__created_at', '-updated_at')[:8])

        # --- Recent activity (Steam + local OwnedGame) ---
        recent_activity: list[dict[str, Any]] = []
        try:
            api_key = getattr(settings, 'SOCIAL_AUTH_STEAM_API_KEY', '') or os.getenv('STEAM_API_KEY', '')
            if profile.steam_id and api_key:
                from django.core.cache import cache
                cache_key = f"steam_recent_{profile.steam_id}"
                cached = cache.get(cache_key)
                if cached is None:
                    try:
                        r = requests.get(
                            'https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/',
                            params={'key': api_key, 'steamid': profile.steam_id, 'count': 100, 'format': 'json'},
                            timeout=1.5
                        )
                        items = (r.json().get('response', {}).get('games') if r.ok else []) or []
                    except Exception:
                        items = []
                    cache.set(cache_key, items, 600)
                else:
                    items = cached or []
                # Map existing Game instances and OwnedGame records
                if items:
                    appids = [it.get('appid') for it in items if it.get('appid')]
                    games_map = {g.appid: g for g in Game.objects.filter(appid__in=appids)} if appids else {}
                    from .models import OwnedGame as _OG
                    existing = {og.game_id: og for og in _OG.objects.filter(user=user_obj, game__appid__in=appids)} if appids else {}
                    from datetime import datetime as _dt, timezone as _tz
                    to_update = []
                    fallback_items = []
                    for it in items:
                        g = games_map.get(it.get('appid'))
                        if not g:
                            fb = {
                                'steam_appid': it.get('appid'),
                                'steam_title': it.get('name') or '',
                                'hours_2weeks': (float(it.get('playtime_2weeks') or 0) / 60.0),
                                'last_dt': None,
                            }
                            rtime = it.get('rtime_last_played')
                            if rtime:
                                try: fb['last_dt'] = _dt.fromtimestamp(int(rtime), tz=_tz.utc)
                                except Exception: pass
                            fallback_items.append(fb); continue
                        og = existing.get(g.id) or _OG(user=user_obj, game=g, source='steam')
                        changed = False
                        p2 = it.get('playtime_2weeks')
                        if p2 is not None:
                            p2 = int(p2);
                            if og.playtime_2weeks != p2: og.playtime_2weeks = p2; changed = True
                        rtime = it.get('rtime_last_played')
                        if rtime:
                            try:
                                dt = _dt.fromtimestamp(int(rtime), tz=_tz.utc)
                                if og.last_played != dt: og.last_played = dt; changed = True
                            except Exception:
                                pass
                        if changed: to_update.append(og)
                    if to_update:
                        from django.db import transaction as dj_tx
                        with dj_tx.atomic():
                            create_list = [og for og in to_update if not getattr(og, 'id', None)]
                            update_list = [og for og in to_update if getattr(og, 'id', None)]
                            if create_list: _OG.objects.bulk_create(create_list, ignore_conflicts=True)
                            if update_list: _OG.objects.bulk_update(update_list, ['playtime_2weeks', 'last_played'])
                    ctx['_recent_fallback_items'] = fallback_items
            # Build from OwnedGame
            from .models import OwnedGame
            from django.utils import timezone as dj_tz
            from datetime import timedelta as _td
            cutoff_dt = dj_tz.now() - _td(days=self.CUTOFF_DAYS)
            og_qs = OwnedGame.objects.select_related('game').filter(user=user_obj).exclude(game__isnull=True)
            from django.db.models import Q as _Q
            og_qs = og_qs.filter(_Q(playtime_2weeks__gt=0) | _Q(last_played__gte=cutoff_dt))
            og_qs = og_qs.order_by(F('last_played').desc(nulls_last=True), F('playtime_2weeks').desc(nulls_last=True))[:self.TARGET]
            for rec in og_qs:
                recent_activity.append({'game': rec.game, 'last_dt': rec.last_played, 'hours_2weeks': (float(rec.playtime_2weeks) / 60.0) if rec.playtime_2weeks else 0.0})
            # Mix Steam fallbacks if short
            fb = ctx.pop('_recent_fallback_items', []) if len(recent_activity) < self.TARGET else []
            if fb and len(recent_activity) < self.TARGET:
                seen = {int(a['game'].appid) for a in recent_activity if a.get('game') and getattr(a['game'], 'appid', None)}
                filtered_fb = []
                for it in fb:
                    aid = it.get('steam_appid'); last_dt = it.get('last_dt'); hours = float(it.get('hours_2weeks') or 0.0)
                    if not aid or aid in seen: continue
                    if (last_dt and last_dt >= cutoff_dt) or hours > 0.0: filtered_fb.append(it)
                try:
                    filtered_fb.sort(key=lambda x: (x.get('last_dt') or dj_tz.now()-_td(days=365*30), float(x.get('hours_2weeks') or 0.0)), reverse=True)
                except Exception: pass
                for it in filtered_fb:
                    if len(recent_activity) >= self.TARGET: break
                    aid = it.get('steam_appid');
                    if aid in seen: continue
                    recent_activity.append(it); seen.add(aid)
            if not recent_activity:
                # fallback purchases
                for g in purchased_qs.order_by('-orderitem__order__created_at', '-updated_at')[:self.TARGET]:
                    last_dt = Order.objects.filter(user=user_obj, status='paid', items_snapshot__game=g).order_by('-created_at').values_list('created_at', flat=True).first()
                    recent_activity.append({'game': g, 'last_dt': last_dt, 'hours_2weeks': 0.0})
            if not recent_activity:
                for g in Game.objects.order_by('-updated_at')[:self.TARGET]:
                    recent_activity.append({'game': g, 'last_dt': None, 'hours_2weeks': 0.0})
        except Exception:
            recent_activity = [{'game': g, 'last_dt': None, 'hours_2weeks': 0.0} for g in Game.objects.order_by('-updated_at')[:3]]

        # --- Wishlist preview ---
        wishlist_qs = profile.wishlist.all().distinct()
        wishlist_count = wishlist_qs.count()
        wishlist_preview = list(wishlist_qs.order_by('-updated_at')[:8])

        # Reviews
        reviews_qs = (
            Review.objects.select_related('game')
            .filter(user=user_obj)
            .annotate(
                helpful_yes=Sum(Case(When(votes__helpful=True, then=1), default=0, output_field=IntegerField())),
                helpful_no=Sum(Case(When(votes__helpful=False, then=1), default=0, output_field=IntegerField())),
            )
            .order_by('-created_at')
        )
        reviews_count = reviews_qs.count()
        recent_reviews = list(reviews_qs[:5])

        # Badges: simple tiers for spend, reviews, wishlist, library size
        def tier(value: int | float, steps: list[int]) -> int:
            t = 0
            for i, s in enumerate(steps, start=1):
                if value >= s:
                    t = i
            return t

        from decimal import Decimal
        spent = profile.total_spent or Decimal('0')
        badges = [
            {
                'key': 'spender',
                'icon': 'store/profile/badges/coin.svg',
                'title': 'Покупатель',
                'desc': f"Потратил {spent:.2f} {profile.preferred_currency}",
                'tier': tier(int(spent), [10, 50, 100, 250]),
            },
            {
                'key': 'critic',
                'icon': 'store/profile/badges/star.svg',
                'title': 'Критик',
                'desc': f"Отзывов: {reviews_count}",
                'tier': tier(reviews_count, [1, 5, 20, 50]),
            },
            {
                'key': 'collector',
                'icon': 'store/profile/badges/crown.svg',
                'title': 'Коллекционер',
                'desc': f"Игры в библиотеке: {library_count}",
                'tier': tier(library_count, [5, 15, 40, 100]),
            },
            {
                'key': 'dreamer',
                'icon': 'store/profile/badges/heart.svg',
                'title': 'Мечтатель',
                'desc': f"Желания: {wishlist_count}",
                'tier': tier(wishlist_count, [5, 15, 40, 100]),
            },
        ]

        # simple cosmetic level derived from spending (no badges system yet)
        try:
            from decimal import Decimal
            level = int((profile.total_spent or Decimal('0')) // Decimal('10')) + 1
        except Exception:
            level = 1

        # Build profile banner background URL: prefer uploaded image, else bg_appid
        banner_url = ''
        try:
            if getattr(profile, 'profile_bg', None) and getattr(profile.profile_bg, 'url', None):
                banner_url = profile.profile_bg.url
            elif profile.bg_appid:
                rel = os.path.join('steam_imports', str(profile.bg_appid), 'header.jpg').replace('\\','/')
                abs_path = os.path.join(str(settings.MEDIA_ROOT), rel)
                if os.path.isfile(abs_path):
                    banner_url = str(settings.MEDIA_URL) + rel
                else:
                    banner_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{profile.bg_appid}/header.jpg"
        except Exception:
            banner_url = ''

        # Sidebar helpers
        # last seen/online label based on profile.last_seen (updated by middleware)
        online_status = 'Не в сети'
        try:
            from django.utils import timezone
            last_seen = getattr(profile, 'last_seen', None)
            if last_seen:
                delta = timezone.now() - last_seen
                secs = int(delta.total_seconds())
                if secs < 300:  # < 5 минут считаем «в сети сейчас»
                    online_status = 'Сейчас в сети'
                else:
                    mins = secs // 60
                    if mins < 60:
                        online_status = f"В сети: {mins} мин. назад"
                    elif mins < 60 * 24:
                        hrs = mins // 60
                        online_status = f"В сети: {hrs} ч. назад"
                    else:
                        days = mins // (60 * 24)
                        online_status = f"В сети: {days} дн. назад"
        except Exception:
            online_status = 'Не в сети'

        badges_count = sum(1 for b in badges if (b.get('tier') or 0) > 0)

        # friend/subscription flags for UI
        # relationship status for header button logic
        is_friend_flag = is_owner or is_friend
        pending_out = None
        pending_in = None
        if self.request.user.is_authenticated and not is_owner and not is_friend_flag:
            pending_out = FriendshipRequest.objects.filter(sender=self.request.user, receiver=user_obj, status='pending').first()
            pending_in = FriendshipRequest.objects.filter(sender=user_obj, receiver=self.request.user, status='pending').first()
        is_subscribed = False
        if self.request.user.is_authenticated and not is_owner:
            is_subscribed = ProfileCommentSubscription.objects.filter(subscriber=self.request.user, profile_owner=user_obj).exists()

        # Aggregate recent hours for header (sum of 2-weeks, minutes -> hours)
        try:
            rh = 0.0
            from .models import OwnedGame as _OG
            mins = _OG.objects.filter(user=user_obj, playtime_2weeks__isnull=False).aggregate(val=Sum('playtime_2weeks'))['val'] or 0
            rh = float(mins) / 60.0 if mins else 0.0
        except Exception:
            rh = 0.0

        ctx.update({
            'profile_user': user_obj,
            'profile': profile,
            'library_count': library_count,
            'recent_purchases': recent_purchases,
            'recent_activity': recent_activity,
            'recent_hours_2weeks': rh,
            'wishlist_count': wishlist_count,
            'wishlist_preview': wishlist_preview,
            'reviews_count': reviews_count,
            'recent_reviews': recent_reviews,
            'level': level,
            'banner_url': banner_url,
            'badges': badges,
            'badges_count': badges_count,
            'online_status': online_status,
            'is_own_profile': is_owner,
            'is_friend': is_friend_flag,
            'is_subscribed': is_subscribed,
            'pending_out': pending_out,
            'pending_in': pending_in,
            'comments': ProfileComment.objects.select_related('author').filter(profile_owner=user_obj).order_by('-created_at')[:20],
        })
        return ctx


class ProfileCommentCreateView(LoginRequiredMixin, View):
    """Создание комментария на странице профиля.

    Учитывает приватность профиля: писать может только владелец при режиме private/friends.
    Простейший антиспам: не чаще одного сообщения раз в 30 секунд.
    """

    def post(self, request, username):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        owner = get_object_or_404(User, username=username)
        profile, _ = UserProfile.objects.get_or_create(user=owner)

        # privacy: комментирование по отдельной настройке comment_privacy
        is_owner = request.user.id == owner.id
        is_friend = False
        if not is_owner:
            uid, oid = (request.user.id, owner.id)
            a, b = (uid, oid) if uid < oid else (oid, uid)
            is_friend = Friendship.objects.filter(user_a_id=a, user_b_id=b).exists()

        cpriv = getattr(profile, 'comment_privacy', 'public')
        if (cpriv == 'nobody' and not is_owner) or (cpriv == 'friends' and not (is_owner or is_friend)):
            messages.info(request, 'Профиль закрыт. Комментирование недоступно.')
            return redirect('store:profile', username=owner.username)

        text = (request.POST.get('text') or '').strip()
        if not text:
            messages.error(request, 'Введите текст комментария.')
            return redirect('store:profile', username=owner.username)

        # simple rate limit
        import time
        key = f"pc_last_{owner.id}"
        last = request.session.get(key)
        now = time.time()
        if last and now - float(last) < 30:
            messages.info(request, 'Слишком часто. Попробуйте через несколько секунд.')
            return redirect('store:profile', username=owner.username)

        comment = ProfileComment.objects.create(profile_owner=owner, author=request.user, text=text)
        request.session[key] = now
        messages.success(request, 'Комментарий добавлен.')

        # notify subscribers and owner (internal + email best-effort)
        try:
            subs = ProfileCommentSubscription.objects.filter(profile_owner=owner).select_related('subscriber')
            recipients = [s.subscriber for s in subs if s.subscriber_id != request.user.id]
            if owner.id != request.user.id:
                recipients.append(owner)
            # deduplicate list
            seen = set()
            recipients = [u for u in recipients if not (u.id in seen or seen.add(u.id))]
            # Internal notifications: respect notify_profile_comment flag
            notifs = []
            for u in recipients:
                prof = getattr(u, 'profile', None)
                if prof and prof.notify_profile_comment:
                    notifs.append(Notification(
                        user=u,
                        kind='profile_comment',
                        payload={'author': request.user.username, 'owner': owner.username, 'text': text[:140]},
                        link_url=f"/profile/{owner.username}/",
                    ))
            if notifs:
                Notification.objects.bulk_create(notifs)
            # Email notifications gated by email_profile_comment
            from django.core.mail import send_mail
            from django.conf import settings as djset
            subj = f"Новый комментарий на профиле {owner.username}"
            body = f"{request.user.username}: {text}\n\nСмотреть: /profile/{owner.username}/"
            for u in recipients:
                try:
                    prof = getattr(u, 'profile', None)
                    if prof and prof.email_profile_comment and u.email:
                        send_mail(subj, body, getattr(djset, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'), [u.email], fail_silently=True)
                except Exception:
                    pass
        except Exception:
            pass
        return redirect('store:profile', username=owner.username)


class FriendToggleView(LoginRequiredMixin, View):
    def post(self, request, username):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        other = get_object_or_404(User, username=username)
        if other.id == request.user.id:
            return redirect('store:profile', username=other.username)
        # privacy: если другие запретили заявки — отклоняем
        other_prof = getattr(other, 'profile', None)
        if other_prof and getattr(other_prof, 'friend_request_privacy', 'public') == 'nobody':
            messages.info(request, 'Этот пользователь не принимает заявки в друзья.')
            return redirect('store:profile', username=other.username)
        # Если уже друзья — разорвать. Если нет — создать заявку (двухшаговая).
        a, b = (request.user.id, other.id)
        if a > b:
            a, b = b, a
        rel = Friendship.objects.filter(user_a_id=a, user_b_id=b).first()
        if rel:
            rel.delete(); messages.info(request, 'Удалено из друзей.')
        else:
            # если есть встречная входящая заявка, принять сразу
            incoming = FriendshipRequest.objects.filter(sender=other, receiver=request.user, status='pending').first()
            if incoming:
                from django.utils import timezone
                incoming.status = 'accepted'; incoming.responded_at = timezone.now(); incoming.save(update_fields=['status','responded_at'])
                Friendship.objects.create(user_a_id=a, user_b_id=b)
                # Internal notification for accept (respect notify_friend_accept)
                other_prof = getattr(other, 'profile', None)
                if other_prof and other_prof.notify_friend_accept:
                    Notification.objects.create(user=other, kind='friend_accept', payload={'user': request.user.username}, link_url=f"/profile/{request.user.username}/")
                # Optional email
                if other_prof and other_prof.email_friend_events and other.email:
                    try:
                        from django.core.mail import send_mail
                        from django.conf import settings as djset
                        send_mail(
                            "Ваша заявка в друзья принята",
                            f"Пользователь {request.user.username} подтвердил дружбу. Смотрите профиль: /profile/{request.user.username}/",
                            getattr(djset, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                            [other.email],
                            fail_silently=True
                        )
                    except Exception:
                        pass
                messages.success(request, 'Заявка принята. Вы теперь друзья.')
            else:
                # создаём исходящую заявку (или ничего, если уже есть исходящая)
                fr, created = FriendshipRequest.objects.get_or_create(sender=request.user, receiver=other, defaults={'status': 'pending'})
                if created or fr.status != 'pending':
                    fr.status = 'pending'; fr.save(update_fields=['status'])
                # Internal notification for request (respect notify_friend_request)
                other_prof = getattr(other, 'profile', None)
                if other_prof and other_prof.notify_friend_request:
                    Notification.objects.create(user=other, kind='friend_request', payload={'user': request.user.username}, link_url=f"/profile/{request.user.username}/")
                if other_prof and other_prof.email_friend_events and other.email:
                    try:
                        from django.core.mail import send_mail
                        from django.conf import settings as djset
                        send_mail(
                            "Новая заявка в друзья",
                            f"Пользователь {request.user.username} отправил вам заявку. Перейдите: /profile/{request.user.username}/",
                            getattr(djset, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                            [other.email],
                            fail_silently=True
                        )
                    except Exception:
                        pass
                messages.success(request, 'Заявка в друзья отправлена.')
        return redirect('store:profile', username=other.username)


class ProfileCommentSubscriptionToggleView(LoginRequiredMixin, View):
    def post(self, request, username):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        owner = get_object_or_404(User, username=username)
        if owner.id == request.user.id:
            # подписка на самого себя не нужна
            return redirect('store:profile', username=owner.username)
        sub = ProfileCommentSubscription.objects.filter(subscriber=request.user, profile_owner=owner).first()
        if sub:
            sub.delete(); messages.info(request, 'Вы отписались от комментариев.')
        else:
            ProfileCommentSubscription.objects.create(subscriber=request.user, profile_owner=owner)
            messages.success(request, 'Вы подписались на комментарии.')
        return redirect('store:profile', username=owner.username)


class ProfileCommentDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        c = get_object_or_404(ProfileComment, id=pk)
        owner_id = c.profile_owner_id
        if c.author_id != request.user.id and owner_id != request.user.id:
            messages.error(request, 'Недостаточно прав для удаления комментария.')
            return redirect('store:profile', username=c.profile_owner.username)
        username = c.profile_owner.username
        c.delete()
        messages.success(request, 'Комментарий удалён.')
        return redirect('store:profile', username=username)


class FriendRequestRespondView(LoginRequiredMixin, View):
    def post(self, request, pk):
        action = request.POST.get('action')  # accept | reject | cancel
        fr = get_object_or_404(FriendshipRequest, id=pk)
        if fr.receiver_id != request.user.id and fr.sender_id != request.user.id:
            messages.error(request, 'Нет прав на действие.')
            return redirect('store:friends')
        from django.utils import timezone
        if action == 'accept' and fr.receiver_id == request.user.id and fr.status == 'pending':
            fr.status = 'accepted'; fr.responded_at = timezone.now(); fr.save(update_fields=['status','responded_at'])
            a, b = (fr.sender_id, fr.receiver_id)
            if a > b:
                a, b = b, a
            Friendship.objects.get_or_create(user_a_id=a, user_b_id=b)
            sender_prof = getattr(fr.sender, 'profile', None)
            if sender_prof and sender_prof.notify_friend_accept:
                Notification.objects.create(user=fr.sender, kind='friend_accept', payload={'user': request.user.username}, link_url=f"/profile/{request.user.username}/")
            if sender_prof and sender_prof.email_friend_events and fr.sender.email:
                try:
                    from django.core.mail import send_mail
                    from django.conf import settings as djset
                    send_mail(
                        "Заявка в друзья принята",
                        f"Пользователь {request.user.username} принял вашу заявку. Профиль: /profile/{request.user.username}/",
                        getattr(djset, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                        [fr.sender.email],
                        fail_silently=True
                    )
                except Exception:
                    pass
        elif action == 'reject' and fr.receiver_id == request.user.id and fr.status == 'pending':
            fr.status = 'rejected'; fr.responded_at = timezone.now(); fr.save(update_fields=['status','responded_at'])
        elif action == 'cancel' and fr.sender_id == request.user.id and fr.status == 'pending':
            fr.status = 'cancelled'; fr.responded_at = timezone.now(); fr.save(update_fields=['status','responded_at'])
        else:
            messages.info(request, 'Ничего не изменилось.')
        return redirect('store:friends')


class FriendsListView(LoginRequiredMixin, TemplateView):
    template_name = 'store/friends.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Добавляем предпочитаемую валюту (для будущих цен/виджетов и единообразия шаблонов)
        preferred_currency = 'USD'
        try:
            user = self.request.user
            if getattr(user, 'is_authenticated', False):
                prof = getattr(user, 'profile', None)
                if prof and getattr(prof, 'preferred_currency', None):
                    preferred_currency = prof.preferred_currency
        except Exception:
            preferred_currency = 'USD'
        ctx['preferred_currency'] = preferred_currency
        uid = self.request.user.id
        friends_ids = list(
            Friendship.objects.filter(user_a_id__in=[uid], user_b_id__gt=0).values_list('user_b_id', flat=True)
        ) + list(
            Friendship.objects.filter(user_b_id__in=[uid], user_a_id__gt=0).values_list('user_a_id', flat=True)
        )
        from django.contrib.auth import get_user_model
        User = get_user_model()
        friends = list(User.objects.filter(id__in=friends_ids))
        # Ensure profiles exist so template can safely access avatar
        for f in friends:
            try:
                _ = f.profile  # access to trigger DoesNotExist
            except Exception:
                UserProfile.objects.get_or_create(user=f)
        incoming = list(FriendshipRequest.objects.filter(receiver_id=uid, status='pending').select_related('sender'))
        for r in incoming:
            try:
                _ = r.sender.profile
            except Exception:
                UserProfile.objects.get_or_create(user=r.sender)
        outgoing = list(FriendshipRequest.objects.filter(sender_id=uid, status='pending').select_related('receiver'))
        for r in outgoing:
            try:
                _ = r.receiver.profile
            except Exception:
                UserProfile.objects.get_or_create(user=r.receiver)
        # Compute online status map (reuse logic from ProfileView: online if last_seen <5min)
        from django.utils import timezone
        now = timezone.now()
        online_map = {}
        for f in friends:
            last = getattr(getattr(f, 'profile', None), 'last_seen', None)
            online = False
            try:
                if last:
                    delta = now - last
                    if delta.total_seconds() < 300:  # 5 minutes
                        online = True
            except Exception:
                online = False
            online_map[f.id] = online
        # Attach is_online to user objects for template simplicity
        for f in friends:
            try:
                setattr(f, 'is_online', bool(online_map.get(f.id, False)))
            except Exception:
                setattr(f, 'is_online', False)
        for r in incoming:
            try:
                setattr(r.sender, 'is_online', bool(online_map.get(r.sender_id, False)))
            except Exception:
                setattr(r.sender, 'is_online', False)
        for r in outgoing:
            try:
                setattr(r.receiver, 'is_online', bool(online_map.get(r.receiver_id, False)))
            except Exception:
                setattr(r.receiver, 'is_online', False)
        ctx['friends'] = friends
        ctx['incoming'] = incoming
        ctx['outgoing'] = outgoing
        # Optional simple server-side search filter by ?q= substring
        q = (self.request.GET.get('q') or '').strip()
        if q:
            q_lower = q.lower()
            ctx['friends'] = [f for f in ctx['friends'] if q_lower in f.username.lower()]
        ctx['friends_query'] = q
        # expose own friend code for UI
        try:
            prof, _ = UserProfile.objects.get_or_create(user=self.request.user)
            ctx['my_friend_code'] = prof.ensure_friend_code() if hasattr(prof, 'ensure_friend_code') else getattr(prof, 'friend_code', '')
        except Exception:
            ctx['my_friend_code'] = ''
        return ctx


class FriendAddByCodeView(LoginRequiredMixin, View):
    """Handle friend request by friend_code input.

    POST: code
    Behavior:
    - lookup user by profile.friend_code (case-insensitive)
    - reject self, respect receiver privacy (friend_request_privacy)
    - if a reciprocal pending request exists from them to us -> accept immediately
    - else create/update outgoing FriendshipRequest
    """
    def post(self, request):
        from django.http import JsonResponse

        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

        def respond(status, message, status_code=200, extra_data=None):
            if is_ajax:
                data = {'status': status, 'message': message}
                if extra_data:
                    data.update(extra_data)
                return JsonResponse(data, status=status_code)
            else:
                if status == 'success':
                    messages.success(request, message)
                elif status == 'info':
                    messages.info(request, message)
                else:
                    messages.error(request, message)
                return redirect('store:friends')

        code = (request.POST.get('code') or '').strip().upper().replace(' ', '')
        if not code:
            return respond('error', 'Введите ID друга.', 400)

        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            target_profile = UserProfile.objects.filter(friend_code__iexact=code).select_related('user').first()
        except Exception:
            target_profile = None

        if not target_profile:
            return respond('error', 'Пользователь с таким ID не найден.', 404)

        other = target_profile.user
        if other.id == request.user.id:
            return respond('info', 'Нельзя добавить себя в друзья.', 400)

        # respect privacy of receiver
        other_prof = target_profile
        if getattr(other_prof, 'friend_request_privacy', 'public') == 'nobody':
            return respond('info', 'Этот пользователь не принимает заявки в друзья.', 403)

        # Already friends?
        a, b = (request.user.id, other.id)
        if a > b:
            a, b = b, a
        rel = Friendship.objects.filter(user_a_id=a, user_b_id=b).first()
        if rel:
            return respond('info', 'Вы уже друзья.', 200)

        # If there is an incoming pending request from other -> accept
        incoming = FriendshipRequest.objects.filter(sender=other, receiver=request.user, status='pending').first()
        if incoming:
            from django.utils import timezone
            incoming.status = 'accepted'; incoming.responded_at = timezone.now(); incoming.save(update_fields=['status','responded_at'])
            Friendship.objects.get_or_create(user_a_id=a, user_b_id=b)
            if other_prof.notify_friend_accept:
                Notification.objects.create(user=other, kind='friend_accept', payload={'user': request.user.username}, link_url=f"/profile/{request.user.username}/")
            return respond('success', 'Заявка принята. Вы теперь друзья.')

        # Else create our outgoing request (idempotent)
        fr, created = FriendshipRequest.objects.get_or_create(sender=request.user, receiver=other, defaults={'status': 'pending'})
        if not created and fr.status != 'pending':
            fr.status = 'pending'; fr.save(update_fields=['status'])

        # Notify receiver (respect notify_friend_request)
        if other_prof.notify_friend_request:
            Notification.objects.create(user=other, kind='friend_request', payload={'user': request.user.username}, link_url=f"/profile/{request.user.username}/")

        return respond('success', 'Заявка в друзья отправлена.')


class SubscriptionsView(LoginRequiredMixin, TemplateView):
    template_name = 'store/subscriptions.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        subs = ProfileCommentSubscription.objects.filter(subscriber=self.request.user).select_related('profile_owner')
        ctx['subs'] = subs
        return ctx


class NotificationsView(LoginRequiredMixin, TemplateView):
    template_name = 'store/notifications.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = Notification.objects.filter(user=self.request.user).order_by('-created_at')[:100]
        ctx['unread'] = [n for n in qs if not n.is_read]
        ctx['all'] = qs
        # mark all as read (simple behavior)
        Notification.objects.filter(user=self.request.user, is_read=False).update(is_read=True)
        return ctx


class ProfileCommentBanToggleView(LoginRequiredMixin, View):
    def post(self, request, username, user_id):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        owner = get_object_or_404(User, username=username)
        if owner.id != request.user.id:
            messages.error(request, 'Только владелец профиля может банить у себя.')
            return redirect('store:profile', username=username)
        target = get_object_or_404(User, id=user_id)
        ban = ProfileCommentBan.objects.filter(profile_owner=owner, banned_user=target).first()
        if ban:
            ban.delete(); messages.info(request, 'Пользователь разбанен для комментариев.')
        else:
            ProfileCommentBan.objects.create(profile_owner=owner, banned_user=target)
            messages.success(request, 'Пользователь забанен для комментариев.')
        return redirect('store:profile', username=username)


class ProfileBadgesView(TemplateView):
    template_name = 'store/profile_badges.html'

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        username = kwargs.get('username')
        user_obj = get_object_or_404(User, username=username)
        profile, _ = UserProfile.objects.get_or_create(user=user_obj)

        # Privacy enforcement (same as profile)
        if profile.privacy in ('private', 'friends') and (not self.request.user.is_authenticated or self.request.user.id != user_obj.id):
            return {'profile_user': user_obj, 'profile': profile, 'is_private': True}

        owned_qs = (
            Game.objects.filter(orderitem__order__user=user_obj, orderitem__order__status='paid')
            .distinct()
        )
        library_count = owned_qs.count()
        wishlist_qs = profile.wishlist.all().distinct()
        wishlist_count = wishlist_qs.count()

        # Reviews aggregates
        reviews_qs = (
            Review.objects.filter(user=user_obj)
        )
        reviews_count = reviews_qs.count()
        from django.utils import timezone
        from datetime import timedelta
        recent_window = timezone.now() - timedelta(days=30)
        reviews_month = reviews_qs.filter(created_at__gte=recent_window).count()

        votes_agg = ReviewVote.objects.filter(review__user=user_obj).aggregate(
            helpful_yes=Sum(Case(When(helpful=True, then=1), default=0, output_field=IntegerField()))
        )
        helpful_total = votes_agg.get('helpful_yes') or 0

        # Discount hunter: wishlist discounted now
        discounted_wishlist = wishlist_qs.filter(Q(discount_percent__gt=0) | Q(original_price__isnull=False, original_price__gt=F('price'))).count()

        def mk_badges():
            def tier(value: int | float, steps: list[int]):
                t = 0
                for i, s in enumerate(steps, start=1):
                    if value >= s:
                        t = i
                # next threshold for progress
                nxt = None
                for s in steps:
                    if value < s:
                        nxt = s
                        break
                return t, nxt

            from decimal import Decimal
            spent = profile.total_spent or Decimal('0')
            b = []
            for spec in [
                ('spender', 'store/profile/badges/coin.svg', 'Покупатель', f"Потратил {spent:.2f} {profile.preferred_currency}", int(spent), [10,50,100,250]),
                ('critic', 'store/profile/badges/star.svg', 'Критик', f"Отзывов: {reviews_count}", reviews_count, [1,5,20,50]),
                ('collector', 'store/profile/badges/crown.svg', 'Коллекционер', f"Игры в библиотеке: {library_count}", library_count, [5,15,40,100]),
                ('dreamer', 'store/profile/badges/heart.svg', 'Мечтатель', f"Желания: {wishlist_count}", wishlist_count, [5,15,40,100]),
                ('reviewer_month', 'store/profile/badges/star.svg', 'Рецензент месяца', f"Отзывов за 30 дней: {reviews_month}", reviews_month, [1,3,5,10]),
                ('discount_hunter', 'store/profile/badges/coin.svg', 'Скидочник', f"Желаний со скидкой: {discounted_wishlist}", discounted_wishlist, [3,8,15,25]),
                ('achiever', 'store/profile/badges/crown.svg', 'Достиженец', f"Полезных голосов: {helpful_total}", helpful_total, [5,20,50,100]),
            ]:
                key, icon, title, desc, value, steps = spec
                t, nxt = tier(value, steps)
                if nxt:
                    try:
                        progress = max(0, min(100, int((value / nxt) * 100)))
                    except Exception:
                        progress = 0
                else:
                    progress = 100
                b.append({'key': key, 'icon': icon, 'title': title, 'desc': desc, 'tier': t, 'value': value, 'next': nxt, 'steps': steps, 'progress': progress})
            return b

        badges = mk_badges()

        ctx.update({
            'profile_user': user_obj,
            'profile': profile,
            'badges': badges,
        })
        return ctx


class ProfilePrefToggleView(LoginRequiredMixin, View):
    """AJAX endpoint to toggle profile notification preferences (boolean fields).

    POST JSON: { field: 'notify_friend_request', value: true }
    Returns: { ok: true, field: 'notify_friend_request', value: true }
    Only allows specific whitelist fields.
    """
    ALLOWED_FIELDS = {
        'notify_profile_comment',
        'notify_friend_request',
        'notify_friend_accept',
        'email_profile_comment',
        'email_friend_events',
        'notify_price_drop',
        'email_price_drop',
    }

    def post(self, request):
        import json
        try:
            data = json.loads(request.body.decode('utf-8'))
        except Exception:
            return JsonResponse({'ok': False, 'error': 'INVALID_JSON'}, status=400)
        field = data.get('field')
        value = data.get('value')
        if field not in self.ALLOWED_FIELDS:
            return JsonResponse({'ok': False, 'error': 'FIELD_NOT_ALLOWED'}, status=400)
        if not isinstance(value, bool):
            return JsonResponse({'ok': False, 'error': 'VALUE_NOT_BOOL'}, status=400)
        prof, _ = UserProfile.objects.get_or_create(user=request.user)
        try:
            setattr(prof, field, value)
            prof.save(update_fields=[field])
        except Exception:
            return JsonResponse({'ok': False, 'error': 'SAVE_FAILED'}, status=500)
        return JsonResponse({'ok': True, 'field': field, 'value': value})


class LanguageSetView(LoginRequiredMixin, View):
    """AJAX endpoint to update preferred_language and immediately activate it.

    POST JSON: { lang: 'ru' }
    Response: { ok: true, lang: 'ru' }
    """
    def post(self, request):
        import json
        from django.conf import settings as djset
        try:
            data = json.loads(request.body.decode('utf-8'))
        except Exception:
            return JsonResponse({'ok': False, 'error': 'INVALID_JSON'}, status=400)
        lang = (data.get('lang') or '').strip()
        allowed = [code for code, _ in getattr(djset, 'LANGUAGES', [])]
        if lang not in allowed:
            return JsonResponse({'ok': False, 'error': 'LANG_NOT_ALLOWED'}, status=400)
        prof, _ = UserProfile.objects.get_or_create(user=request.user)
        prof.preferred_language = lang
        try:
            prof.save(update_fields=['preferred_language'])
        except Exception:
            return JsonResponse({'ok': False, 'error': 'SAVE_FAILED'}, status=500)
        # activate immediately for this response
        try:
            from django.utils import translation
            translation.activate(lang)
            request.LANGUAGE_CODE = lang
        except Exception:
            pass
        return JsonResponse({'ok': True, 'lang': lang})
