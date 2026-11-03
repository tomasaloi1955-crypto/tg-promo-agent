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
STYLE = "Прочитай по-русски тепло, спокойно и уверенно, как подруга, которая объясняет понятно: "

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
    def __init__(self) -> None:
        from google import genai
        from google.genai import types
        self.types = types
        self.client = genai.Client(api_key=env("GEMINI_API_KEY"))
        self.model = env("TTS_MODEL") or self._pick_model()
        self.voice = env("VOICE") or "Kore"
        print(f"TTS: {self.model}, голос {self.voice}")

    def _pick_model(self) -> str:
        names = [m.name.split("/")[-1] for m in self.client.models.list() if "tts" in m.name.lower()]
        print("Доступные TTS-модели:", ", ".join(names) or "нет")
        if not names:
            sys.exit("Нет TTS-моделей для этого ключа Gemini.")
        names.sort(key=lambda n: ("flash" not in n, "preview" in n, n))
        return names[0]

    def speak(self, text: str) -> bytes:
        t = self.types
        cfg = t.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=t.SpeechConfig(voice_config=t.VoiceConfig(
                prebuilt_voice_config=t.PrebuiltVoiceConfig(voice_name=self.voice))))
        for attempt in range(6):
            try:
                r = self.client.models.generate_content(model=self.model, contents=STYLE + text, config=cfg)
                return r.candidates[0].content.parts[0].inline_data.data
            except Exception as e:
                wait = 20 * (attempt + 1)
                print(f"  TTS ошибка ({type(e).__name__}: {str(e)[:150]}), жду {wait} с")
                time.sleep(wait)
        raise RuntimeError("TTS не ответил после 6 попыток")


class Silent:
    def speak(self, text: str) -> bytes:          # ~ 14 символов в секунду речи
        return b"\x00\x00" * int(RATE * max(2.0, len(text) / 14))


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

    parts = []
    for i, s in enumerate(scenes):
        wav = WORK / f"s{n}_{i}.wav"
        write_wav(wav, tts.speak(s["voice"]))
        clip = WORK / f"s{n}_{i}.mp4"
        dur = duration(wav) + 0.45                 # маленькая пауза между сценами
        run(["ffmpeg", "-y", "-loop", "1", "-i", cards[i]["path"], "-i", str(wav),
             "-af", "apad=pad_dur=0.45", "-t", f"{dur:.2f}",
             "-vf", "scale=1080:1920,format=yuv420p", "-r", "30",
             "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
             "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "1", str(clip)])
        parts.append(clip)
        print(f"  сцена {i + 1}/{len(scenes)}: {dur:.1f} с")
    lst = WORK / f"s{n}.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    out = OUT / f"short_{n}_{short['slug']}.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
         "-movflags", "+faststart", str(out)])
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
    tts = Silent() if env("TTS") == "silent" else Gemini()
    only = {x.strip() for x in env("ONLY").split(",") if x.strip()}
    made = []
    for s in SHORTS:
        if only and str(s["id"]) not in only:
            continue
        print(f"Shorts {s['id']}: {s['title']}")
        made.append((s, build(s, tts)))
    for s, path in made:
        info = (OUT / (path.stem + ".txt")).read_text(encoding="utf-8")
        send_to_owner(path, f"🎬 Shorts {s['id']} готов\n\n{info}")
    print(f"Готово: {len(made)} видео в {OUT}")


if __name__ == "__main__":
    main()
