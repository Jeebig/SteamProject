from django.core.management.base import BaseCommand
from django.conf import settings
import json
from pathlib import Path
from store.utils.currency import _fetch_rates, _FALLBACK_USD

class Command(BaseCommand):
    help = "Fetch and cache current currency rates into a JSON file for warm start."

    def add_arguments(self, parser):
        parser.add_argument('--base', default='USD', help='Base currency (default USD)')

    def handle(self, *args, **options):
        base = options.get('base', 'USD').upper()
        self.stdout.write(f'Fetching rates for base {base}...')
        try:
            rates = _fetch_rates(base)
            if not rates:
                self.stdout.write(self.style.WARNING('API returned empty or failed; using fallback.'))
                rates = _FALLBACK_USD if base == 'USD' else {}
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error fetching: {e}; using fallback.'))
            rates = _FALLBACK_USD if base == 'USD' else {}
        data = {
            'base': base,
            'rates': rates,
        }
        out_dir = Path(settings.BASE_DIR) / 'data'
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f'currency_{base.lower()}.json'
        with out_file.open('w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS(f'Saved {len(rates)} rates to {out_file}'))
