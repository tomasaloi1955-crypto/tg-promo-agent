# Мультики для YouTube Shorts — «My Arabic»

Генератор коротких обучающих мультиков (вертикальное видео 1080×1920, 30–60 с):
2D-персонажи в халиджи-стиле, сцены (маджлис ночью/днём, кухня), субтитры
**арабский + транслитерация + русский**, карточки «Диалект vs Фусха», «Слово»,
перемотка времени, звуковые эффекты и **озвучка** голосами Edge TTS
(кувейтский, эмиратский, саудовский арабский + русский диктор).

## Как получить видео (без компьютера)

1. GitHub → вкладка **Actions** → **«Мультики для YouTube Shorts (арабский)»** → **Run workflow**.
2. Через ~3–5 минут ролики придут в Telegram от бота промо-агента
   (используются те же секреты `BOT_TOKEN` и `OWNER_ID`), а также лежат в **Artifacts** запуска.
3. Загружаете MP4 в YouTube как Shorts.

## Как сделать новую серию

Скопируйте `episodes/ep01_where_were_you.json`, поменяйте реплики — и запустите workflow.

| Шаг | Что делает |
|---|---|
| `{"scene": "majlis_night", "clock": "23:00", "cast": {"dad": 0.72}}` | сцена + кто стоит где (0 — слева, 1 — справа). Сцены: `majlis_night`, `majlis_day`, `kitchen_day` |
| `{"hook": "Текст *с подсветкой*"}` | крупная надпись поверх сцены, читает русский диктор |
| `{"enter": "son", "to": 0.28}` / `{"exit": "son"}` | персонаж входит / уходит |
| `{"say": "dad", "mood": "angry", "ar": "...", "tr": "...", "ru": "...", "speak": "..."}` | реплика. `mood`: neutral, happy, angry, sad, surprised. `speak` — что читает голос (можно с огласовками), если отличается от `ar` |
| `{"compare": {"left": {...}, "right": {...}}}` | карточка «Диалект vs Фусха» (каждая сторона озвучивается) |
| `{"card": {"label": "СЛОВО", "ar": "...", "tr": "...", "ru": "..."}}` | карточка слова |
| `{"rewind": "18:00"}` | эффект перемотки времени |
| `{"wait": 1.0}` | пауза |

Слова в `*звёздочках*` подсвечиваются. Фоновая музыка выключена; включить — `"music": true` в JSON эпизода. Персонажи (`characters`): типы `man`, `boy`,
`woman`, `girl`, `grandpa`; голос — любой из Edge TTS (`ar-KW-FahedNeural`,
`ar-KW-NouraNeural`, `ar-AE-HamdanNeural`, `ar-AE-FatimaNeural`, `ar-SA-HamedNeural`,
`ar-SA-ZariyahNeural`, `ar-QA-MoazNeural`, `ar-QA-AmalNeural`...), `pitch`/`rate` — выше/быстрее.

## Локально

```bash
pip install -r shorts/requirements.txt   # + ffmpeg
python shorts/make_short.py shorts/episodes/ep01_where_were_you.json --out out
python shorts/make_short.py shorts/episodes/*.json --preview --out out   # только кадры JPG
```

Шрифты: Cairo и Nunito (SIL Open Font License).
