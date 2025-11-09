from typing import Any
from django.core.management.base import BaseCommand
from django.db.models import Count
from store.models import Game, Screenshot
from store.steam_api import fetch_app_and_images


class Command(BaseCommand):
    help = (
        "Скачать и привязать изображения для игр. По умолчанию пополняет игры без фото,\n"
        "а также может довести количество скриншотов до минимума (--min-images)."
    )

    def add_arguments(self, parser):
        parser.add_argument('--max-images', type=int, default=2, help='Сколько изображений скачивать на игру (верхний предел)')
        parser.add_argument('--min-images', type=int, default=2, help='Минимум скриншотов на игру; если меньше — дозакачать')
        parser.add_argument('--limit', type=int, default=100, help='Максимум игр для обработки за один запуск')

    def handle(self, *args: Any, **options: Any) -> None:
        max_images = int(options.get('max_images') or 2)
        min_images = int(options.get('min_images') or 2)
        limit = int(options.get('limit') or 100)

        # 1) Игры без каких‑либо фото
        qs_no_photo = (
            Game.objects.filter(appid__isnull=False)
            .filter(screenshots__isnull=True, cover_image__isnull=True)
            .annotate(scount=Count('screenshots'))
            .distinct()
            .order_by()
        )
        # 2) Игры с количеством скринов < min_images — нужно «дотянуть»
        qs_low_count = (
            Game.objects.filter(appid__isnull=False)
            .annotate(scount=Count('screenshots'))
            .filter(scount__lt=min_images)
            .order_by()
        )
        qs = qs_no_photo.union(qs_low_count).order_by('id')[:limit]
        processed = 0
        attached = 0
        for game in qs:
            if game.appid is None:
                continue
            try:
                # Запрашиваем до max(min_images, max_images) чтобы хватило для пополнения
                need_up_to = max(min_images, max_images)
                result = fetch_app_and_images(int(game.appid), max_images=need_up_to)
            except Exception as e:
                self.stderr.write(f"{game.title} (appid={game.appid}): fetch failed: {e}")
                continue
            imgs = result.get('images') or []
            if not imgs:
                continue
            existing = list(game.screenshots.values_list('image', flat=True))
            base_index = len(existing)
            for idx, img_rel in enumerate(imgs):
                try:
                    # не создаём дубликаты по пути картинки
                    if img_rel in existing:
                        continue
                    Screenshot.objects.get_or_create(game=game, image=img_rel, defaults={'order': base_index + idx})
                except Exception:
                    pass
            if not game.cover_image:
                try:
                    game.cover_image = imgs[0]
                    game.save(update_fields=['cover_image'])
                except Exception:
                    pass
            processed += 1
            attached += len(imgs)
            self.stdout.write(self.style.SUCCESS(f"✓ {game.title}: добавлено изображений {len(imgs)}"))

        self.stdout.write(self.style.WARNING(f"Готово: обработано {processed} игр, добавлено всего изображений {attached}"))
