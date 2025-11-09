"""Currency conversion utilities with caching and graceful fallback.

We attempt to fetch live rates from exchangerate.host but cache them in-memory
for a short TTL to avoid hammering the API. If network fails, we use a static
fallback table relative to USD.
"""
from decimal import Decimal, ROUND_HALF_UP
import requests
from django.conf import settings
import time
from typing import Dict, Any
from django.db import transaction

try:
    from store.models import CurrencyRate
except Exception:  # pragma: no cover - модель может быть недоступна при раннем импортировании
    CurrencyRate = None  # type: ignore

_CACHE: Dict[str, Dict[str, float]] = {}
_CACHE_TS: Dict[str, float] = {}
_TTL_SECONDS = 60 * 60  # 1 hour

_FALLBACK_USD = {
    'USD': 1.0,
    'EUR': 0.92,
    'GBP': 0.78,
    'UAH': 41.0,
    'RUB': 92.0,
    'JPY': 150.0,
    'CAD': 1.37,
    'AUD': 1.55,
    'CNY': 7.30,
    'PLN': 3.98,
}

def _fetch_rates(base: str) -> Dict[str, float]:
    now = time.time()
    if base in _CACHE and (now - _CACHE_TS.get(base, 0)) < _TTL_SECONDS:
        return _CACHE[base]
    # Fast path: disable live fetching entirely if feature flag off
    if not getattr(settings, 'CURRENCY_FETCH_ENABLED', True):
        # Try DB cache first
        if CurrencyRate:
            try:
                recs = CurrencyRate.objects.filter(base=base).order_by('-fetched_at')[:len(_FALLBACK_USD)]
                if recs:
                    db_rates = {r.target: float(r.rate) for r in recs if r.target in _FALLBACK_USD}
                    if db_rates:
                        _CACHE[base] = db_rates; _CACHE_TS[base] = now
                        return db_rates
            except Exception:
                pass
        # Fallback generation
        if base == 'USD':
            return _FALLBACK_USD
        if base in _FALLBACK_USD:
            rate_base = _FALLBACK_USD[base]
            derived = {cur: (val / rate_base) for cur, val in _FALLBACK_USD.items()}
            return derived
        return _FALLBACK_USD
    try:
        # Use a much shorter timeout to avoid blocking page renders.
        # Allow override via settings.CURRENCY_FETCH_TIMEOUT (seconds).
        timeout = getattr(settings, 'CURRENCY_FETCH_TIMEOUT', 1.2)
        url = f'https://api.exchangerate.host/latest?base={base}'
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        raw = resp.json() or {}
        data: Dict[str, Any] = raw if isinstance(raw, dict) else {}
        raw_rates = data.get('rates', {}) or {}
        rates: Dict[str, Any] = raw_rates if isinstance(raw_rates, dict) else {}
        # keep only currencies we care about
        filtered: Dict[str, float] = {str(k): float(v) for k, v in rates.items() if str(k) in _FALLBACK_USD.keys()}
        if filtered:
            _CACHE[base] = filtered
            _CACHE_TS[base] = now
            # Persist to DB (best-effort)
            if CurrencyRate:
                # timestamp recorded implicitly via model default; explicit variable removed
                try:
                    with transaction.atomic():
                        objects = []
                        for tgt, val in filtered.items():
                            objects.append(CurrencyRate(base=base, target=str(tgt), rate=Decimal(str(val))))
                        CurrencyRate.objects.bulk_create(objects)
                except Exception:
                    pass
            return filtered
    except Exception:
        pass
    # Try DB fallback (latest rates for base)
    if CurrencyRate:
        try:
            recs = CurrencyRate.objects.filter(base=base).order_by('-fetched_at')[:len(_FALLBACK_USD)]
            if recs:
                db_rates = {r.target: float(r.rate) for r in recs if r.target in _FALLBACK_USD}
                if db_rates:
                    _CACHE[base] = db_rates
                    _CACHE_TS[base] = now
                    return db_rates
        except Exception:
            pass
    # build fallback relative to requested base via USD pivot
    try:
        if base == 'USD':
            return _FALLBACK_USD
        # pivot: amount_in_base = amount_in_usd / rate_base
        if base in _FALLBACK_USD:
            rate_base = _FALLBACK_USD[base]
            derived = {cur: (val / rate_base) for cur, val in _FALLBACK_USD.items()}
            return derived
    except Exception:
        pass
    return _FALLBACK_USD  # last resort

def convert_amount(amount: Decimal | float, from_currency: str, to_currency: str) -> Decimal:
    amount_dec = Decimal(str(amount))
    if from_currency == to_currency:
        return amount_dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    rates_from = _fetch_rates(from_currency)
    rate_to = rates_from.get(to_currency)
    if rate_to is None:
        # Fallback via USD pivot if possible
        try:
            usd_rates = _fetch_rates('USD')
            r_from = usd_rates.get(from_currency)
            r_to = usd_rates.get(to_currency)
            if r_from and r_to:
                # amount in USD = amount / r_from ; then * r_to
                converted = (amount_dec / Decimal(str(r_from))) * Decimal(str(r_to))
                return converted.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            pass
        return amount_dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    converted = amount_dec * Decimal(str(rate_to))
    return converted.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
