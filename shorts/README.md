# Мультики для YouTube Shorts — «My Arabic»

Генератор коротких обучающих мультиков (вертикальное видео 1080×1920, 30–60 с):
2D-персонажи в халиджи-стиле, сцены (маджлис ночью/днём, кухня), субтитры
**арабский + транслитерация + русский**, карточки «Диалект vs Фусха», «Слово»,
перемотка времени, звуковые эффекты и **озвучка** голосами Edge TTS
(кувейтский, эмиратский, саудовский арабский + русский диктор).

## Автопостинг (каждый день, сам)

Workflow **«Автопостинг Shorts»** (`autopost.yml`) каждый день в 16:17 по Москве публикует один ролик:
через день **«Слово дня»** (100 роликов, `words.py` → [`WORDS.md`](WORDS.md)) и **урок-диалог**
(100 роликов, [`DIALOGS.md`](DIALOGS.md)) — всего 200 дней контента. Всё собирается с озвучкой. Если голос не сработал — немой ролик не публикуется. Отчёт приходит от бота.
Платформа без настроенных секретов просто пропускается.

Секреты: GitHub → Settings → Secrets and variables → Actions → New repository secret.

**Telegram-канал** — уже настроен на `myarabicl` (другой канал — секрет `TG_CHANNEL`).
Публикует ваш аккаунт (сессия промо-агента), он должен быть админом канала.

**«Для детей» на YouTube** — включено (`YT_MADE_FOR_KIDS: "true"` в `autopost.yml`).

**YouTube «Arabic for everyone»** — один раз, ~10 минут:
1. console.cloud.google.com → создать проект → «APIs & Services» → Library → включить **YouTube Data API v3**.
2. «OAuth consent screen» → External → заполнить название и почту → Publish app (статус **In production**,
   иначе токен умрёт через 7 дней).
3. «Credentials» → Create credentials → OAuth client ID → тип **TVs and Limited Input devices**.
   Скопировать Client ID и Client secret в секреты `YT_CLIENT_ID` и `YT_CLIENT_SECRET`.
4. Actions → **«YouTube: авторизация»** → Run workflow. Бот пришлёт ссылку и код: откройте на телефоне,
   выберите канал **Arabic for everyone**, введите код. Бот пришлёт токен → секрет `YT_REFRESH_TOKEN`.
5. ⚠️ Google публикует видео из новых API-проектов только как **приватные**, пока проект не пройдёт
   проверку: подайте заявку «YouTube API Services — Audit and Quota Extension» (бесплатно, форма Google).
   До одобрения видео будут загружаться приватными — их можно открыть вручную в YouTube Studio.

**Instagram Reels** — аккаунт должен быть **профессиональным** (Автор или Бизнес):
1. developers.facebook.com → My Apps → Create app → тип Business → продукт **Instagram** →
   «API setup with Instagram login» → добавить свой аккаунт → **Generate token**.
2. Секреты: `IG_ACCESS_TOKEN` = этот токен, `IG_USER_ID` = ID аккаунта (показан там же).
3. Токен живёт 60 дней — когда истечёт, бот напишет ошибку Instagram; сгенерируйте новый и обновите секрет.

**Свои старые ролики** (если появятся) — см. [`old/README.md`](old/README.md): они пойдут вместо «Слова дня».

Ручной запуск: Actions → «Автопостинг Shorts» → Run workflow (можно указать только одну платформу).

## Как получить видео (без компьютера)

1. GitHub → вкладка **Actions** → **«Мультики для YouTube Shorts (арабский)»** → **Run workflow**,
   укажите номера уроков «с» и «по» (например 1–10; за раз можно все 1–100, это ~1 час).
2. Через ~3–5 минут ролики придут в Telegram от бота промо-агента
   (используются те же секреты `BOT_TOKEN` и `OWNER_ID`), а также лежат в **Artifacts** запуска.
3. Загружаете MP4 в YouTube как Shorts.

## 100 готовых диалогов

Все диалоги (литературный арабский) — в `dialogs.py`, читаемый список — в [`DIALOGS.md`](DIALOGS.md).
Чтобы поправить реплику: отредактируйте `dialogs.py` и выполните `python shorts/dialogs.py` —
файлы `episodes/dialog_001.json … dialog_100.json` пересоберутся.

Сцены: `street_day` (улица), `park_day` (парк), `beach_day` (пляж), `courtyard_day` (двор мечети),
`desert_night` (пустыня, шатёр, костёр), `shop_day` (магазин), `classroom_day` (класс), `cafe_day` (кафе),
`clinic_day` (врач), `airport_day` (аэропорт), `bedroom_night` (спальня), `kitchen_day`, `majlis_day`, `majlis_night`.

В каждом ролике: заставка (4 варианта), диалог с наездом камеры на говорящего, эмоции над головой
(звёздочки, «!», слеза, злость) со звуками, машущая рука, птицы/звёзды/огонь, в конце —
викторина «Проверь себя» с отсчётом 3-2-1 и ответом. Музыки нет.

Контроль акыды: `dialogs.py` не соберёт эпизоды, если в тексте есть клятвы не Аллахом, «удача»,
амулеты, гороскопы и т. п. (список `FORBIDDEN`). Персонажи: Ахмад, Юсуф, Марьям, папа, мама, дедушка,
учительница, продавец, прохожий, таксист, гость, врач.

## Формат сценария (если писать JSON вручную)

| Шаг | Что делает |
|---|---|
| `{"scene": "majlis_night", "clock": "23:00", "cast": {"dad": 0.72}}` | сцена + кто стоит где (0 — слева, 1 — справа). Сцены: `majlis_night`, `majlis_day`, `kitchen_day` |
| `{"hook": "Текст *с подсветкой*"}` | крупная надпись поверх сцены, читает русский диктор |
| `{"enter": "son", "to": 0.28}` / `{"exit": "son"}` | персонаж входит / уходит |
| `{"say": "dad", "mood": "angry", "ar": "...", "tr": "...", "ru": "...", "speak": "..."}` | реплика. `mood`: neutral, happy, angry, sad, surprised. `speak` — что читает голос (можно с огласовками), если отличается от `ar` |
| `{"compare": {"left": {...}, "right": {...}}}` | карточка «Диалект vs Фусха» (каждая сторона озвучивается) |
| `{"card": {"label": "СЛОВО", "ar": "...", "tr": "...", "ru": "..."}}` | карточка слова |
| `{"quiz": {"ru": "...", "ar": "...", "tr": "..."}}` | викторина: «Как сказать…?» → 3-2-1 → ответ |
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
