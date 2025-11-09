from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
from store.models import Game, PriceSnapshot, Notification, UserProfile
from django.conf import settings

class Command(BaseCommand):
    help = "Create daily price snapshots and generate price-drop notifications for wishlists"

    def add_arguments(self, parser):
        parser.add_argument('--threshold', type=int, default=getattr(settings, 'PRICE_DROP_THRESHOLD_PERCENT', 15), help='Percent drop threshold to notify (default from settings)')
        parser.add_argument('--dry-run', action='store_true', help='Only collect snapshots; do not create notifications')

    def handle(self, *args, **options):
        today = timezone.now().date()
        threshold = options['threshold']
        dry = options['dry_run']
        created = 0
        updated = 0
        notified = 0
        qs = Game.objects.filter(appid__isnull=False)
        for g in qs.iterator():
            current_price = g.price or Decimal('0')
            current_currency = g.currency
            # Find latest snapshot (<= today)
            latest = (
                PriceSnapshot.objects
                .filter(game=g, snapshot_date__lte=today)
                .order_by('-snapshot_date')
                .first()
            )
            old_price = None
            old_currency = None
            snap_today = None
            if latest and latest.snapshot_date == today:
                snap_today = latest
                old_price = latest.price
                old_currency = latest.currency
            else:
                # create today's snapshot with current price
                snap_today, _created = PriceSnapshot.objects.get_or_create(
                    game=g, snapshot_date=today,
                    defaults={'price': current_price, 'currency': current_currency}
                )
                if _created:
                    created += 1
                if latest:
                    old_price = latest.price
                    old_currency = latest.currency
            # Compare if we have an old price in same currency
            if old_price is not None and old_currency == current_currency:
                try:
                    drop_percent = Decimal('0')
                    if old_price > 0:
                        drop_percent = ((old_price - current_price) / old_price) * 100
                except Exception:
                    drop_percent = Decimal('0')
                if drop_percent >= threshold and current_price < old_price:
                    wishlisters = UserProfile.objects.filter(wishlist__id=g.id, notify_price_drop=True).select_related('user').distinct()
                    for prof in wishlisters:
                        if dry:
                            continue
                        try:
                            Notification.objects.create(
                                user=prof.user,
                                kind='price_drop',
                                payload={
                                    'game_title': g.title,
                                    'old_price': f"{old_price:.2f} {old_currency}",
                                    'new_price': f"{current_price:.2f} {current_currency}",
                                    'percent': int(drop_percent),
                                },
                                link_url=f"/game/{g.slug}/"
                            )
                            notified += 1
                        except Exception:
                            continue
            # Update today's snapshot to reflect current price if changed
            if snap_today and (snap_today.price != current_price or snap_today.currency != current_currency):
                snap_today.price = current_price
                snap_today.currency = current_currency
                try:
                    snap_today.save(update_fields=['price', 'currency'])
                    updated += 1
                except Exception:
                    pass
        self.stdout.write(self.style.SUCCESS(f"Snapshots: +{created} new, ~{updated} updated | Notifications: {notified} | Threshold: {threshold}% | Dry-run: {dry}"))
