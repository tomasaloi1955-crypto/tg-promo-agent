# -*- coding: utf-8 -*-
"""
Агент-уборщик для телефона на Android (запускается в Termux).

Что считает мусором (всё настраивается в config.json):
  duplicates   — точные копии фото/видео/документов (по содержимому, не по имени).
                 Оставляет самый старый экземпляр, предпочитая DCIM/Camera.
  screenshots  — скриншоты старше N дней.
  messengers   — медиа из WhatsApp / Telegram / Viber старше N дней
                 (картинки, видео, голосовые, стикеры, присланные документы).
  downloads    — из «Загрузок»: .apk старше N дней, недокачанные файлы.
  thumbnails   — кэш миниатюр галереи (.thumbnails) — Android пересоздаст сам.
  empty_dirs   — пустые папки.
  big_files    — НЕ удаляет, только показывает самые большие файлы в отчёте.

Безопасность:
  * По умолчанию — только отчёт (ничего не трогает). Удаляет с ключом --apply.
  * Ничего не стирается сразу: файлы переносятся в корзину
    /storage/emulated/0/.PhoneCleanerTrash/<дата>/ (с .nomedia — галерея её
    не видит) и окончательно удаляются через trash_days дней.
  * Вернуть всё из последней уборки: python cleaner.py restore
  * Папки из "protect" не трогаются никогда.

Чего Android НЕ даёт сделать без root (ограничение системы, не агента):
  чистить кэш других приложений и Android/data/* — для этого
  «Настройки → Хранилище» или Files by Google.

Команды:
  python cleaner.py               отчёт: что было бы удалено и сколько места
  python cleaner.py --apply       уборка (в корзину)
  python cleaner.py restore [ID]  вернуть файлы из корзины (по умолчанию — последняя уборка)
  python cleaner.py purge         сразу очистить корзину полностью
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import notify

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config.json"
DAY = 86400

DEFAULT_CONFIG = {
    "root": "/storage/emulated/0",
    "trash_dir": ".PhoneCleanerTrash",
    "trash_days": 30,
    "protect": [
        "Documents/Важное",
        "DCIM/Camera/Избранное",
    ],
    "duplicates": {
        "enabled": True,
        "dirs": ["DCIM", "Pictures", "Download", "Documents", "Movies", "Music",
                 "WhatsApp", "Telegram", "Android/media"],
        "min_size_kb": 10,
    },
    "screenshots": {
        "enabled": True,
        "older_than_days": 30,
        "dirs": ["DCIM/Screenshots", "Pictures/Screenshots"],
    },
    "messengers": {
        "enabled": True,
        "older_than_days": 60,
        "dirs": [
            "Android/media/com.whatsapp/WhatsApp/Media",
            "WhatsApp/Media",
            "Android/media/org.telegram.messenger/Telegram",
            "Telegram",
            "Pictures/Telegram",
            "Movies/Telegram",
            "Android/media/com.viber.voip/Viber",
            "Viber",
        ],
    },
    "downloads": {
        "enabled": True,
        "dirs": ["Download"],
        "apk_older_than_days": 7,
        "partial_older_than_days": 1,
        "partial_ext": [".crdownload", ".part", ".partial", ".tmp", ".download"],
    },
    "thumbnails": {
        "enabled": True,
        "dirs": ["DCIM/.thumbnails", "Pictures/.thumbnails"],
    },
    "empty_dirs": {
        "enabled": True,
        "dirs": ["DCIM", "Pictures", "Download", "Documents", "Movies", "Music"],
    },
    "big_files": {
        "enabled": True,
        "min_size_mb": 100,
        "top": 15,
    },
}

MEDIA_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".bmp",
             ".mp4", ".mkv", ".mov", ".3gp", ".webm", ".avi",
             ".mp3", ".m4a", ".ogg", ".opus", ".aac", ".wav", ".amr",
             ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar"}

RULE_TITLES = {
    "duplicates": "Дубликаты",
    "screenshots": "Старые скриншоты",
    "messengers": "Старые медиа мессенджеров",
    "downloads": "Мусор в Загрузках",
    "thumbnails": "Кэш миниатюр",
    "empty_dirs": "Пустые папки",
}


def _merge(default: dict, user: dict) -> dict:
    out = dict(default)
    for k, v in user.items():
        out[k] = _merge(default[k], v) if isinstance(v, dict) and isinstance(default.get(k), dict) else v
    return out


def load_config(path: Path = CONFIG_FILE) -> dict:
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        return json.loads(json.dumps(DEFAULT_CONFIG))
    return _merge(DEFAULT_CONFIG, json.loads(path.read_text(encoding="utf-8")))


def human(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


class Cleaner:
    def __init__(self, cfg: dict, now: float = None):
        self.cfg = cfg
        self.root = Path(cfg["root"])
        self.trash = self.root / cfg["trash_dir"]
        self.now = now or time.time()
        self.protect = [(self.root / p).resolve() for p in cfg["protect"]]
        # путь -> (правило, размер); один файл попадает только под одно правило
        self.found: dict[Path, tuple[str, int]] = {}
        self.empty: list[Path] = []
        self.big: list[tuple[int, Path]] = []

    # ---------- обход ----------
    def _skip(self, p: Path) -> bool:
        rp = p.resolve()
        if rp == self.trash.resolve() or self.trash.resolve() in rp.parents:
            return True
        return any(rp == pr or pr in rp.parents for pr in self.protect)

    def _walk(self, rel_dirs, hidden=False):
        """Все файлы в папках из списка (рекурсивно), без защищённых и корзины."""
        seen = set()
        for rel in rel_dirs:
            top = self.root / rel
            if not top.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(top, onerror=lambda e: None):
                d = Path(dirpath)
                if self._skip(d):
                    dirnames[:] = []
                    continue
                if not hidden:
                    dirnames[:] = [n for n in dirnames if not n.startswith(".")]
                for name in filenames:
                    p = d / name
                    if name == ".nomedia" or p in seen or p.is_symlink():
                        continue
                    seen.add(p)
                    yield p

    def _age_days(self, st) -> float:
        return (self.now - st.st_mtime) / DAY

    def _add(self, p: Path, rule: str, size: int):
        self.found.setdefault(p, (rule, size))

    # ---------- правила ----------
    def rule_thumbnails(self, c):
        for p in self._walk(c["dirs"], hidden=True):
            try:
                self._add(p, "thumbnails", p.stat().st_size)
            except OSError:
                pass

    def rule_downloads(self, c):
        partial = {e.lower() for e in c["partial_ext"]}
        for p in self._walk(c["dirs"]):
            try:
                st = p.stat()
            except OSError:
                continue
            ext = p.suffix.lower()
            if ext == ".apk" and self._age_days(st) > c["apk_older_than_days"]:
                self._add(p, "downloads", st.st_size)
            elif ext in partial and self._age_days(st) > c["partial_older_than_days"]:
                self._add(p, "downloads", st.st_size)

    def rule_screenshots(self, c):
        for p in self._walk(c["dirs"]):
            try:
                st = p.stat()
            except OSError:
                continue
            if self._age_days(st) > c["older_than_days"]:
                self._add(p, "screenshots", st.st_size)

    def rule_messengers(self, c):
        for p in self._walk(c["dirs"]):
            try:
                st = p.stat()
            except OSError:
                continue
            if self._age_days(st) > c["older_than_days"]:
                self._add(p, "messengers", st.st_size)

    @staticmethod
    def _hash(p: Path, limit: int = None) -> str:
        h = hashlib.sha1()
        with open(p, "rb") as f:
            if limit:
                h.update(f.read(limit))
            else:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        return h.hexdigest()

    def _keeper_rank(self, p: Path, st):
        rel = p.relative_to(self.root).as_posix().lower()
        return (0 if rel.startswith("dcim/camera") else 1, st.st_mtime, len(rel))

    def rule_duplicates(self, c):
        min_size = c["min_size_kb"] * 1024
        by_size: dict[int, list] = {}
        for p in self._walk(c["dirs"]):
            if p.suffix.lower() not in MEDIA_EXT:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size >= min_size:
                by_size.setdefault(st.st_size, []).append((p, st))
        for size, items in by_size.items():
            if len(items) < 2:
                continue
            # сначала быстрый хэш первых 64 КБ, потом полный — только у совпавших
            groups: dict[str, list] = {}
            for p, st in items:
                try:
                    groups.setdefault(self._hash(p, 65536), []).append((p, st))
                except OSError:
                    pass
            for group in groups.values():
                if len(group) < 2:
                    continue
                full: dict[str, list] = {}
                for p, st in group:
                    try:
                        full.setdefault(self._hash(p), []).append((p, st))
                    except OSError:
                        pass
                for same in full.values():
                    if len(same) < 2:
                        continue
                    same.sort(key=lambda x: self._keeper_rank(*x))
                    for p, st in same[1:]:
                        self._add(p, "duplicates", size)

    def rule_empty_dirs(self, c):
        for rel in c["dirs"]:
            top = self.root / rel
            if not top.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(top, topdown=False, onerror=lambda e: None):
                d = Path(dirpath)
                if d == top or self._skip(d) or any(
                        part.startswith(".") for part in d.relative_to(top).parts):
                    continue
                try:
                    left = [x for x in d.iterdir()
                            if x not in self.found and x not in self.empty]
                except OSError:
                    continue
                if not left:
                    self.empty.append(d)

    def rule_big_files(self, c):
        min_size = c["min_size_mb"] * 1024 * 1024
        for p in self._walk(["."]):
            if p in self.found:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size >= min_size:
                self.big.append((size, p))
        self.big.sort(reverse=True)
        del self.big[c["top"]:]

    def scan(self):
        # порядок важен: файл засчитывается первому подошедшему правилу
        for name in ("thumbnails", "downloads", "screenshots", "messengers",
                     "duplicates", "empty_dirs", "big_files"):
            c = self.cfg[name]
            if c.get("enabled"):
                getattr(self, "rule_" + name)(c)
        return self

    # ---------- отчёт ----------
    def report(self, applied: bool) -> str:
        totals: dict[str, list] = {}
        for p, (rule, size) in self.found.items():
            t = totals.setdefault(rule, [0, 0, []])
            t[0] += 1
            t[1] += size
            t[2].append(p)
        total = sum(t[1] for t in totals.values())
        head = "🧹 Уборка выполнена" if applied else "🔎 Отчёт (пока ничего не удалено)"
        lines = [head, ""]
        for rule, title in RULE_TITLES.items():
            if rule == "empty_dirs":
                if self.empty:
                    lines.append(f"• {title}: {len(self.empty)}")
                continue
            if rule in totals:
                cnt, size, paths = totals[rule]
                lines.append(f"• {title}: {cnt} файл(ов), {human(size)}")
                for p in sorted(paths)[:3]:
                    lines.append(f"    {p.relative_to(self.root)}")
                if cnt > 3:
                    lines.append(f"    … и ещё {cnt - 3}")
        if not totals and not self.empty:
            lines.append("Мусора не найдено 👍")
        lines += ["", f"Итого освобождается: {human(total)}"]
        if applied:
            lines.append(f"Файлы в корзине {self.cfg['trash_dir']} ещё {self.cfg['trash_days']} дн. "
                         "Вернуть: python cleaner.py restore")
        else:
            lines.append("Чтобы удалить: python cleaner.py --apply")
        if self.big:
            lines += ["", "📦 Самые большие файлы (не удаляются, решите сами):"]
            for size, p in self.big:
                lines.append(f"    {human(size):>9}  {p.relative_to(self.root)}")
        return "\n".join(lines)

    # ---------- уборка ----------
    def apply(self) -> Path:
        batch_id = datetime.fromtimestamp(self.now).strftime("%Y-%m-%d_%H%M%S")
        batch = self.trash / batch_id
        batch.mkdir(parents=True, exist_ok=True)
        (self.trash / ".nomedia").touch()
        manifest = []
        for p, (rule, _size) in sorted(self.found.items()):
            dest = batch / p.relative_to(self.root)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dest))
                manifest.append({"from": str(p), "to": str(dest), "rule": rule})
            except OSError as e:
                print(f"не удалось переместить {p}: {e}", file=sys.stderr)
        for d in sorted(self.empty, key=lambda x: len(x.parts), reverse=True):
            try:
                d.rmdir()
                manifest.append({"from": str(d), "to": None, "rule": "empty_dirs"})
            except OSError:
                pass
        (batch / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
        media_scan([m["from"] for m in manifest if m["to"]])
        return batch


def media_scan(paths):
    """Сказать галерее, что файлов больше нет (нужен пакет termux-api)."""
    if not paths or not shutil.which("termux-media-scan"):
        return
    for i in range(0, len(paths), 200):
        subprocess.run(["termux-media-scan", *paths[i:i + 200]],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def purge_old(cfg: dict, now: float = None, everything: bool = False) -> int:
    trash = Path(cfg["root"]) / cfg["trash_dir"]
    if not trash.is_dir():
        return 0
    now = now or time.time()
    removed = 0
    for batch in trash.iterdir():
        if not batch.is_dir():
            continue
        if everything or (now - batch.stat().st_mtime) / DAY > cfg["trash_days"]:
            shutil.rmtree(batch, ignore_errors=True)
            removed += 1
    return removed


def restore(cfg: dict, batch_id: str = None) -> int:
    trash = Path(cfg["root"]) / cfg["trash_dir"]
    batches = sorted(b for b in trash.iterdir() if (b / "manifest.json").exists()) if trash.is_dir() else []
    if batch_id:
        batches = [b for b in batches if b.name == batch_id]
    if not batches:
        print("В корзине нечего восстанавливать.")
        return 0
    batch = batches[-1]
    manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    count = 0
    for m in manifest:
        src = m["to"]
        dst = Path(m["from"])
        if src is None:
            dst.mkdir(parents=True, exist_ok=True)
            continue
        if not Path(src).exists() or dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, str(dst))
        count += 1
    shutil.rmtree(batch, ignore_errors=True)
    media_scan([m["from"] for m in manifest if m["to"]])
    print(f"Восстановлено файлов: {count} (уборка {batch.name})")
    return count


def main(argv=None):
    ap = argparse.ArgumentParser(description="Уборка телефона")
    ap.add_argument("command", nargs="?", default="scan", choices=["scan", "restore", "purge"])
    ap.add_argument("batch", nargs="?", help="ID уборки для restore")
    ap.add_argument("--apply", action="store_true", help="действительно убрать файлы в корзину")
    ap.add_argument("--quiet", action="store_true", help="не печатать отчёт (для расписания)")
    args = ap.parse_args(argv)
    cfg = load_config()

    if not Path(cfg["root"]).is_dir():
        sys.exit(f"Нет доступа к {cfg['root']}. В Termux выполните: termux-setup-storage")

    if args.command == "restore":
        restore(cfg, args.batch)
        return
    if args.command == "purge":
        print(f"Корзина очищена, удалено уборок: {purge_old(cfg, everything=True)}")
        return

    purge_old(cfg)
    c = Cleaner(cfg).scan()
    if args.apply:
        c.apply()
    text = c.report(applied=args.apply)
    if not args.quiet:
        print(text)
    notify.send(text)


if __name__ == "__main__":
    main()
