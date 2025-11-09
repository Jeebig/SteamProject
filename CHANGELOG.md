# Changelog

## 2025-10-27

- Fixed Django template parsing issues in `templates/store/index.html` and `templates/store/wishlist.html`.
  - Removed duplicated nested template content that caused mis-nested tags.
  - Normalized multi-line `{% if %}` / `{% else %}` template constructs into single-line expressions where appropriate (e.g. `{% if game.price|floatformat:2 == "0.00" %}Бесплатно{% else %}{{ game.price }} {{ game.currency }}{% endif %}`) to avoid Django parser errors.
  - Fixed a broken line where `{{ game.currency }}` was split across lines in `wishlist.html`.
- Templates now prefer local preview images stored under `media/steam_imports/<appid>/header.jpg` when present (via `file_exists` template filter); otherwise they fall back to Steam CDN headers.

Notes for contributors:

- Avoid breaking up `{% if ... %}` / `{% endif %}` blocks across multiple lines in a way that nests other template tags incorrectly.
- Use the `file_exists` filter (from `store_extras`) to check for local media availability before falling back to external URLs.
