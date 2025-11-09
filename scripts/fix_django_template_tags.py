#!/usr/bin/env python3
"""
Небольшой скрипт для исправления проблем с автоформатированием VSCode, когда
он разбивает Django-теги на несколько строк, из-за чего шаблоны падают с
TemplateSyntaxError.

Что делает:
- Идёт по всем .html файлам в каталоге templates (рекурсивно).
- Для каждого вхождения тега вида {% ... %}, если внутри тега есть перевод строки,
  склеивает содержимое тега в одну строку, удаляя лишние пробелы/переносы.
- Создаёт резервную копию файла с расширением .bak перед изменением.

Запуск:
  python scripts/fix_django_template_tags.py templates

ВНИМАНИЕ: скрипт меняет файлы на месте (с .bak резервной копией). Рекомендую
закоммитить текущие изменения перед выполнением.
"""
import sys
import re
from pathlib import Path
def fix_content(text: str) -> str:
    # Обработаем все шаблонные теги {% ... %} и если внутри тега есть переносы,
    # заменим последовательности пробелов/переносов на один пробел.
    def repl(m):
        inner = m.group(1)
        if "\n" in inner or "\r" in inner:
            # Склеиваем внутренности тега в одну строку
            new_inner = " ".join(inner.split())
            return "{% " + new_inner + " %}"
        return m.group(0)

    # Обрабатываем и {% ... %} и {{ ... }} теги.
    def repl_any(m):
        open_delim = m.group(1)
        inner = m.group(2)
        close_delim = m.group(3)
        if "\n" in inner or "\r" in inner:
            new_inner = " ".join(inner.split())
            return f"{open_delim} {new_inner} {close_delim}"
        return m.group(0)

    pattern_any = re.compile(r"(\{[%{])\s*(.*?)\s*(%\}|}})", re.S)
    return pattern_any.sub(repl_any, text)


def process_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    new = fix_content(text)
    if new != text:
        bak = path.with_suffix(path.suffix + ".bak")
        bak.write_text(text, encoding="utf-8")
        path.write_text(new, encoding="utf-8")
        print(f"Fixed: {path} (backup: {bak.name})")
        return True
    return False


def main(argv):
    if len(argv) < 2:
        print("Usage: fix_django_template_tags.py <templates_dir>")
        return 2
    root = Path(argv[1])
    if not root.exists():
        print("Path not found:", root)
        return 2
    changed = 0
    for p in root.rglob("*.html"):
        try:
            if process_file(p):
                changed += 1
        except Exception as e:
            print(f"Error processing {p}: {e}")
    print(f"Done. Files changed: {changed}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
