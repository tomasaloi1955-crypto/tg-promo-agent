# -*- coding: utf-8 -*-
"""Собирает Shorts: начитка (Gemini TTS) + сцены (cards.js) → mp4 1080×1920.

Переменные:
  GEMINI_API_KEY  ключ Gemini (секрет промо-агента). TTS=silent — без голоса, для проверки.
  VOICE           голос Gemini (по умолчанию Kore — спокойный женский)
  TTS_MODEL       модель TTS (по умолчанию — первая доступная с «tts» в названии)
  ONLY            номера Shorts через запятую (по умолчанию все)
  BOT_TOKEN, OWNER_ID — если заданы, готовые видео бот пришлёт вам в Telegram
Результат: ai-course/shorts/out/short_<n>_<slug>.mp4 (+ .txt с названием и описанием).
"""
import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts import SHORTS  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
WORK = OUT / "work"
RATE = 24000
# Без инструкции перед текстом: модель иногда читает её вслух. Тон задаёт сам голос (VOICE).

DESCRIPTION = (
    "Бесплатный мини-интенсив для сестёр: свой бот за 3 вечера 👉 {bot_link}\n"
    "Канал в Telegram: {channel}\n\n"
    "#ии #нейросети #телеграмбот #удаленка #вайбкодинг #работаиздома #shorts"
)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


class Gemini:
    """Озвучка Gemini. В ноябре 2026 старые TTS-модели убрали — пробуем аудиовыход новых моделей."""
    CANDIDATES = ("gemini-omni-flash-preview", "gemini-2.5-flash-preview-tts", "gemini-3.8-flash", "gemini-3.5-flash")

    def __init__(self) -> None:
        from google import genai
        from google.genai import types
        self.types = types
        self.client = genai.Client(api_key=env("GEMINI_API_KEY"))
        self.voice = env("VOICE") or "Kore"
        self.model = env("TTS_MODEL") or self._pick_model()
        print(f"TTS: Gemini {self.model}")

    def _pick_model(self) -> str:
        for name in self.CANDIDATES:
            for with_voice in (True, False):
                try:
                    self._call(name, "Проверка.", with_voice)
                    self.with_voice = with_voice
                    return name
                except Exception as e:
                    print(f"  {name} (голос {'задан' if with_voice else 'по умолчанию'}): не подходит "
                          f"({type(e).__name__}: {str(e)[:140]})")
        raise RuntimeError("нет модели Gemini с аудиовыходом")

    def _call(self, model: str, text: str, with_voice: bool = True) -> tuple[bytes, str]:
        t = self.types
        kw = {"response_modalities": ["AUDIO"]}
        if with_voice:
            kw["speech_config"] = t.SpeechConfig(voice_config=t.VoiceConfig(
                prebuilt_voice_config=t.PrebuiltVoiceConfig(voice_name=self.voice)))
        r = self.client.models.generate_content(model=model, contents=text, config=t.GenerateContentConfig(**kw))
        part = r.candidates[0].content.parts[0].inline_data
        if not part or not part.data:
            raise RuntimeError("ответ без аудио")
        return part.data, (part.mime_type or "")

    def save(self, text: str, path: Path) -> None:
        for attempt in range(4):
            try:
                data, mime = self._call(self.model, text, getattr(self, "with_voice", True))
                break
            except Exception as e:
                msg = str(e)
                print(f"  TTS ошибка ({type(e).__name__}: {msg[:300]})", flush=True)
                if "PerDay" in msg or "per day" in msg.lower():
                    raise QuotaError("дневной лимит озвучки Gemini исчерпан") from e
                time.sleep(30 * (attempt + 1))
        else:
            raise RuntimeError("TTS не ответил после 4 попыток")
        if "L16" in mime or "pcm" in mime.lower() or not mime:
            write_wav(path, data)                    # сырой PCM 16 бит, 24 кГц
        else:                                        # wav/mp3/ogg — приводим к wav
            raw = path.with_suffix(".raw")
            raw.write_bytes(data)
            run(["ffmpeg", "-y", "-i", str(raw), "-ac", "1", "-ar", str(RATE), str(path)])


class Piper:
    """Бесплатный открытый синтезатор речи (офлайн). Голос: ru_RU-irina-medium (женский)."""
    URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/{v}/{q}/ru_RU-{v}-{q}.onnx"

    def __init__(self) -> None:
        import requests
        from piper import PiperVoice
        voice, quality = (env("PIPER_VOICE") or "irina-medium").rsplit("-", 1)
        model = WORK / f"ru_RU-{voice}-{quality}.onnx"
        for suffix in ("", ".json"):
            target = Path(str(model) + suffix)
            if not target.exists():
                r = requests.get(self.URL.format(v=voice, q=quality) + suffix, timeout=120)
                r.raise_for_status()
                target.write_bytes(r.content)
        self.voice = PiperVoice.load(str(model))
        print(f"TTS: Piper ru_RU-{voice}-{quality}")

    def save(self, text: str, path: Path) -> None:
        from piper import SynthesisConfig
        tmp = path.with_suffix(".piper.wav")
        with wave.open(str(tmp), "wb") as wf:
            self.voice.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=1.08))
        run(["ffmpeg", "-y", "-i", str(tmp), "-ac", "1", "-ar", str(RATE), str(path)])


class QuotaError(RuntimeError):
    pass


class Silent:
    def save(self, text: str, path: Path) -> None:   # ~ 14 символов в секунду речи
        write_wav(path, b"\x00\x00" * int(RATE * max(2.0, len(text) / 14)))


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def build(short: dict, tts) -> Path:
    n, scenes = short["id"], short["scenes"]
    cards = [{"path": str(WORK / f"s{n}_{i}.png"), "card": s["card"], "sub": s.get("sub", ""),
              "accent": s.get("accent", "code"), "n": i + 1, "total": len(scenes)} for i, s in enumerate(scenes)]
    spec = WORK / f"s{n}.json"
    spec.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    run(["node", str(HERE / "cards.js"), str(spec)])

    # Один запрос озвучки на весь ролик (бесплатный лимит Gemini маленький),
    # сцены сменяются пропорционально длине своей фразы.
    wav = WORK / f"s{n}.wav"
    tts.save(" ".join(s["voice"] for s in scenes), wav)
    total = duration(wav) + 0.6
    weights = [len(s["voice"]) + 12 for s in scenes]
    durs = [total * w / sum(weights) for w in weights]
    lst = WORK / f"s{n}_img.txt"
    lst.write_text("".join(f"file '{c['path']}'\nduration {d:.3f}\n" for c, d in zip(cards, durs))
                   + f"file '{cards[-1]['path']}'\n", encoding="utf-8")
    out = OUT / f"short_{n}_{short['slug']}.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(wav),
         "-af", "apad=pad_dur=0.6", "-t", f"{total:.2f}",
         "-vf", "scale=1080:1920,format=yuv420p", "-r", "30", "-vsync", "cfr",
         "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "1",
         "-movflags", "+faststart", str(out)])
    print(f"  {total:.1f} с, сцены: " + ", ".join(f"{d:.1f}" for d in durs), flush=True)
    bot = env("BOT_USERNAME").lstrip("@")
    link = f"https://t.me/{bot}?start=src_youtube_s{n}" if bot else "(ссылка на бота — добавить)"
    (OUT / f"short_{n}_{short['slug']}.txt").write_text(
        f"Название:\n{short['title']}\n\nОписание:\n" + DESCRIPTION.format(
            bot_link=link, channel="https://t.me/Halalaifreya")
        + f"\n\nЗакреплённый комментарий:\nБесплатный интенсив «Свой бот за 3 вечера» 👉 {link}\n",
        encoding="utf-8")
    return out


def send_to_owner(path: Path, caption: str) -> None:
    token, owner = env("BOT_TOKEN"), env("OWNER_ID")
    if not (token and owner):
        return
    import requests
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendVideo",
                          data={"chat_id": owner, "caption": caption[:1024], "supports_streaming": "true",
                                "width": 1080, "height": 1920},
                          files={"video": f}, timeout=300)
    print("  → в Telegram:", "ok" if r.ok and r.json().get("ok") else r.text[:200])


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    mode = env("TTS") or "auto"
    if mode == "silent":
        tts = Silent()
    elif mode == "piper":
        tts = Piper()
    else:
        try:
            tts = Gemini()
        except Exception as e:
            print(f"Gemini не озвучивает ({e}) — беру Piper")
            tts = Piper()
    only = {x.strip() for x in env("ONLY").split(",") if x.strip()}
    made, failed = [], []
    for s in SHORTS:
        if only and str(s["id"]) not in only:
            continue
        print(f"Shorts {s['id']}: {s['title']}", flush=True)
        try:
            made.append((s, build(s, tts)))
        except QuotaError as e:
            print(f"⛔ {e}")
            failed.append(s["id"])
            break
        except Exception as e:
            print(f"⚠️ Shorts {s['id']} не собран: {type(e).__name__}: {e}")
            failed.append(s["id"])
    for s, path in made:
        info = (OUT / (path.stem + ".txt")).read_text(encoding="utf-8")
        send_to_owner(path, f"🎬 Shorts {s['id']} готов\n\n{info}")
    print(f"Готово: {len(made)} видео в {OUT}" + (f"; не собраны: {failed}" if failed else ""))
    if not made:
        sys.exit(1)


if __name__ == "__main__":
    main()
