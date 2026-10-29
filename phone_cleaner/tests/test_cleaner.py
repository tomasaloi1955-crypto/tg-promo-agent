import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cleaner  # noqa: E402

NOW = time.time()


def mk(root: Path, rel: str, data: bytes = b"x" * 20000, age_days: float = 0) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    t = NOW - age_days * cleaner.DAY
    os.utime(p, (t, t))
    return p


def cfg_for(root: Path) -> dict:
    cfg = cleaner._merge(cleaner.DEFAULT_CONFIG, {"root": str(root)})
    cfg["protect"] = ["Documents/Важное"]
    return cfg


def test_scan_apply_restore(tmp_path):
    photo = mk(tmp_path, "DCIM/Camera/IMG_1.jpg", b"A" * 30000, age_days=100)
    dup = mk(tmp_path, "Pictures/Telegram/copy.jpg", b"A" * 30000, age_days=5)
    fresh_shot = mk(tmp_path, "DCIM/Screenshots/new.png", age_days=2)
    old_shot = mk(tmp_path, "DCIM/Screenshots/old.png", b"S" * 20000, age_days=40)
    wa_old = mk(tmp_path, "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/a.jpg",
                b"W" * 20000, age_days=90)
    wa_new = mk(tmp_path, "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/b.jpg",
                b"V" * 20000, age_days=3)
    apk = mk(tmp_path, "Download/game.apk", b"P" * 20000, age_days=10)
    part = mk(tmp_path, "Download/film.mp4.crdownload", b"C" * 20000, age_days=2)
    keep_doc = mk(tmp_path, "Download/passport.pdf", b"D" * 20000, age_days=400)
    thumb = mk(tmp_path, "DCIM/.thumbnails/123.jpg", age_days=1)
    protected = mk(tmp_path, "Documents/Важное/IMG_1.jpg", b"A" * 30000, age_days=500)
    (tmp_path / "Pictures/EmptyAlbum").mkdir(parents=True)

    c = cleaner.Cleaner(cfg_for(tmp_path), now=NOW).scan()
    rules = {p: r for p, (r, _) in c.found.items()}
    assert rules == {
        dup: "duplicates", old_shot: "screenshots", wa_old: "messengers",
        apk: "downloads", part: "downloads", thumb: "thumbnails",
    }
    assert tmp_path / "Pictures/EmptyAlbum" in c.empty
    assert "Итого" in c.report(applied=False)

    c.apply()
    for p in rules:
        assert not p.exists()
    for p in (photo, fresh_shot, wa_new, keep_doc, protected):
        assert p.exists()
    assert (tmp_path / ".PhoneCleanerTrash/.nomedia").exists()

    # корзину сканер не трогает
    again = cleaner.Cleaner(cfg_for(tmp_path), now=NOW).scan()
    assert not any(".PhoneCleanerTrash" in str(p) for p in again.found)

    assert cleaner.restore(cfg_for(tmp_path)) == len(rules)
    for p in rules:
        assert p.exists()
    assert (tmp_path / "Pictures/EmptyAlbum").is_dir()


def test_purge_old(tmp_path):
    cfg = cfg_for(tmp_path)
    old = tmp_path / ".PhoneCleanerTrash/2020-01-01_000000"
    old.mkdir(parents=True)
    t = NOW - 40 * cleaner.DAY
    os.utime(old, (t, t))
    (tmp_path / ".PhoneCleanerTrash/new").mkdir()
    assert cleaner.purge_old(cfg, now=NOW) == 1
    assert not old.exists()
