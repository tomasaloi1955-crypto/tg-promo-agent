"""«Слово дня» — 100 коротких роликов по одному слову (литературный арабский).

Ролик: заставка «Слово дня» → персонаж говорит фразу-пример со словом →
второй персонаж повторяет слово → викторина «Как сказать…?» → ответ.

    python shorts/words.py     # пересобрать shorts/episodes/word_NNN.json и shorts/WORDS.md
"""

import json
from pathlib import Path

from dialogs import CHARACTERS, FORBIDDEN

HERE = Path(__file__).resolve().parent

# (слово, транслит, перевод, пример по-арабски, транслит примера, перевод примера, сцена[, кто говорит])
# В примере слово выделено *звёздочками*.
WORDS = [
    # ── Дом ──
    ("بيت", "bayt", "дом", "هذا *بيتي* الجديد", "hādhā *baytī* l-jadīd", "Это мой новый *дом*", "majlis_day", "ahmad"),
    ("باب", "bāb", "дверь", "افتح *الباب* من فضلك", "iftah *al-bāb* min fadlik", "Открой *дверь*, пожалуйста", "majlis_day", "mom"),
    ("نافذة", "nāfidha", "окно", "*النافذة* مفتوحة", "*an-nāfidha* maftūha", "*Окно* открыто", "kitchen_day", "mom"),
    ("غرفة", "ghurfa", "комната", "هذه *غرفتي*", "hādhihi *ghurfatī*", "Это моя *комната*", "bedroom_night", "maryam"),
    ("كرسي", "kursī", "стул", "اجلس على *الكرسي*", "ijlis 'alā *l-kursī*", "Садись на *стул*", "classroom_day"),
    ("طاولة", "tāwila", "стол", "المفتاح على *الطاولة*", "al-miftāh 'alā *t-tāwila*", "Ключ на *столе*", "kitchen_day", "mom"),
    ("سرير", "sarīr", "кровать", "*السرير* مريح", "*as-sarīr* murīh", "*Кровать* удобная", "bedroom_night", "maryam"),
    ("مفتاح", "miftāh", "ключ", "أين *المفتاح*؟", "ayna *l-miftāh*?", "Где *ключ*?", "majlis_day", "dad"),
    ("مطبخ", "matbakh", "кухня", "أمي في *المطبخ*", "ummī fī *l-matbakh*", "Мама на *кухне*", "kitchen_day", "ahmad"),
    ("مصباح", "misbāh", "лампа", "*المصباح* جميل", "*al-misbāh* jamīl", "*Лампа* красивая", "bedroom_night", "maryam"),
    # ── Еда ──
    ("ماء", "mā'", "вода", "أشرب *الماء*", "ashrabu *l-mā'*", "Я пью *воду*", "kitchen_day", "ahmad"),
    ("خبز", "khubz", "хлеб", "*الخبز* طازج", "*al-khubz* tāzaj", "*Хлеб* свежий", "shop_day", "seller"),
    ("حليب", "halīb", "молоко", "أحب *الحليب*", "uhibbu *l-halīb*", "Я люблю *молоко*", "kitchen_day", "maryam"),
    ("تمر", "tamr", "финики", "*التمر* حلو", "*at-tamr* hulw", "*Финики* сладкие", "majlis_day", "grandpa"),
    ("تفاحة", "tuffāha", "яблоко", "هذه *تفاحة* حمراء", "hādhihi *tuffāha* hamrā'", "Это красное *яблоко*", "shop_day", "seller"),
    ("أرز", "aruzz", "рис", "*الأرز* جاهز", "*al-aruzz* jāhiz", "*Рис* готов", "kitchen_day", "mom"),
    ("لحم", "lahm", "мясо", "نأكل *اللحم* والأرز", "na'kulu *l-lahm* wa-l-aruzz", "Мы едим *мясо* и рис", "kitchen_day", "dad"),
    ("سمك", "samak", "рыба", "أحب *السمك*", "uhibbu *s-samak*", "Я люблю *рыбу*", "beach_day", "ahmad"),
    ("عصير", "'asīr", "сок", "*عصير* البرتقال لذيذ", "*'asīr* al-burtuqāl ladhīdh", "Апельсиновый *сок* вкусный", "cafe_day", "yusuf"),
    ("شاي", "shāy", "чай", "تفضل *الشاي*", "tafaddal *ash-shāy*", "Угощайся *чаем*", "desert_night", "grandpa"),
    # ── Семья ──
    ("أب", "ab", "папа", "*أبي* في البيت", "*abī* fī l-bayt", "Мой *папа* дома", "majlis_day", "maryam"),
    ("أم", "umm", "мама", "*أمي* تحبني", "*ummī* tuhibbunī", "*Мама* меня любит", "kitchen_day", "ahmad"),
    ("أخ", "akh", "брат", "هذا *أخي* أحمد", "hādhā *akhī* ahmad", "Это мой *брат* Ахмад", "majlis_day", "maryam"),
    ("أخت", "ukht", "сестра", "*أختي* صغيرة", "*ukhtī* saghīra", "Моя *сестра* маленькая", "majlis_day", "ahmad"),
    ("جد", "jadd", "дедушка", "*جدي* طيب", "*jaddī* tayyib", "Мой *дедушка* добрый", "majlis_day", "maryam"),
    ("جدة", "jadda", "бабушка", "*جدتي* في الحديقة", "*jaddatī* fī l-hadīqa", "*Бабушка* в саду", "park_day", "ahmad"),
    ("ابن", "ibn", "сын", "هذا *ابني* أحمد", "hādhā *bnī* ahmad", "Это мой *сын* Ахмад", "majlis_day", "dad"),
    ("بنت", "bint", "девочка, дочь", "مريم *بنت* ذكية", "maryam *bint* dhakiyya", "Марьям — умная *девочка*", "kitchen_day", "mom"),
    ("صديق", "sadīq", "друг", "يوسف *صديقي*", "yūsuf *sadīqī*", "Юсуф — мой *друг*", "park_day", "ahmad"),
    ("طفل", "tifl", "ребёнок", "*الطفل* يلعب", "*at-tifl* yal'ab", "*Ребёнок* играет", "park_day", "mom"),
    # ── Школа ──
    ("صفحة", "safha", "страница", "اقرأ هذه *الصفحة*", "iqra' hādhihi *s-safha*", "Прочитай эту *страницу*", "classroom_day"),
    ("قلم", "qalam", "ручка", "*قلمي* أزرق", "*qalamī* azraq", "Моя *ручка* синяя", "classroom_day", "ahmad"),
    ("دفتر", "daftar", "тетрадь", "اكتب في *الدفتر*", "uktub fī *d-daftar*", "Пиши в *тетради*", "classroom_day"),
    ("مدرسة", "madrasa", "школа", "أذهب إلى *المدرسة*", "adhhabu ilā *l-madrasa*", "Я иду в *школу*", "street_day", "ahmad"),
    ("معلمة", "mu'allima", "учительница", "*المعلمة* في الفصل", "*al-mu'allima* fī l-fasl", "*Учительница* в классе", "classroom_day", "maryam"),
    ("طالب", "tālib", "ученик", "أنا *طالب* مجتهد", "anā *tālib* mujtahid", "Я старательный *ученик*", "classroom_day", "ahmad"),
    ("درس", "dars", "урок", "*الدرس* سهل", "*ad-dars* sahl", "*Урок* лёгкий", "classroom_day"),
    ("سؤال", "su'āl", "вопрос", "عندي *سؤال*", "'indī *su'āl*", "У меня *вопрос*", "classroom_day", "maryam"),
    ("جواب", "jawāb", "ответ", "*الجواب* صحيح", "*al-jawāb* sahīh", "*Ответ* правильный", "classroom_day"),
    ("حرف", "harf", "буква", "الألف أول *حرف*", "al-alif awwal *harf*", "Алиф — первая *буква*", "classroom_day"),
    # ── Природа ──
    ("شمس", "shams", "солнце", "*الشمس* حارة", "*ash-shams* hārra", "*Солнце* жаркое", "beach_day", "ahmad"),
    ("قمر", "qamar", "луна", "*القمر* جميل الليلة", "*al-qamar* jamīl al-layla", "*Луна* сегодня красивая", "desert_night", "grandpa"),
    ("نجمة", "najma", "звезда", "انظر إلى *النجمة*", "unzur ilā *n-najma*", "Смотри на *звезду*", "desert_night", "grandpa"),
    ("بحر", "bahr", "море", "*البحر* أزرق", "*al-bahr* azraq", "*Море* синее", "beach_day", "maryam"),
    ("شجرة", "shajara", "дерево", "*الشجرة* كبيرة", "*ash-shajara* kabīra", "*Дерево* большое", "park_day", "ahmad"),
    ("زهرة", "zahra", "цветок", "هذه *زهرة* جميلة", "hādhihi *zahra* jamīla", "Это красивый *цветок*", "park_day", "maryam"),
    ("سماء", "samā'", "небо", "*السماء* صافية", "*as-samā'* sāfiya", "*Небо* ясное", "park_day", "ahmad"),
    ("مطر", "matar", "дождь", "*المطر* رحمة", "*al-matar* rahma", "*Дождь* — милость", "street_day", "dad"),
    ("رمل", "raml", "песок", "*الرمل* حار", "*ar-raml* hārr", "*Песок* горячий", "beach_day", "ahmad"),
    ("نخلة", "nakhla", "пальма", "*النخلة* طويلة", "*an-nakhla* tawīla", "*Пальма* высокая", "street_day", "maryam"),
    # ── Тело ──
    ("رأس", "ra's", "голова", "*رأسي* يؤلمني", "*ra'sī* yu'limunī", "У меня болит *голова*", "clinic_day", "ahmad"),
    ("عين", "'ayn", "глаз", "*عيني* تؤلمني", "*'aynī* tu'limunī", "У меня болит *глаз*", "clinic_day", "ahmad"),
    ("أذن", "udhun", "ухо", "أسمع *بأذني*", "asma'u *bi-udhunī*", "Я слышу *ухом*", "clinic_day", "ahmad"),
    ("أنف", "anf", "нос", "*أنفي* أحمر", "*anfī* ahmar", "Мой *нос* красный", "clinic_day", "ahmad"),
    ("فم", "fam", "рот", "افتح *فمك*", "iftah *famak*", "Открой *рот*", "clinic_day", "doctor"),
    ("يد", "yad", "рука", "اغسل *يدك*", "ighsil *yadak*", "Помой *руку*", "kitchen_day", "mom"),
    ("رجل", "rijl", "нога", "*رجلي* تؤلمني", "*rijlī* tu'limunī", "У меня болит *нога*", "clinic_day", "ahmad"),
    ("قلب", "qalb", "сердце", "*قلبك* سليم", "*qalbuka* salīm", "Твоё *сердце* здорово", "clinic_day", "doctor"),
    ("سن", "sinn", "зуб", "نظف *أسنانك*", "nazzif *asnānak*", "Почисти *зубы*", "bedroom_night", "mom"),
    ("شعر", "sha'r", "волосы", "*شعري* أسود", "*sha'rī* aswad", "Мои *волосы* чёрные", "majlis_day", "ahmad"),
    # ── Цвета и описания ──
    ("أحمر", "ahmar", "красный", "السيارة *حمراء*", "as-sayyāra *hamrā'*", "Машина *красная*", "street_day", "ahmad"),
    ("أزرق", "azraq", "синий", "السماء *زرقاء*", "as-samā' *zarqā'*", "Небо *синее*", "park_day", "maryam"),
    ("أخضر", "akhdar", "зелёный", "العشب *أخضر*", "al-'ushb *akhdar*", "Трава *зелёная*", "park_day", "ahmad"),
    ("أبيض", "abyad", "белый", "ثوبي *أبيض*", "thawbī *abyad*", "Моя одежда *белая*", "majlis_day", "ahmad"),
    ("أسود", "aswad", "чёрный", "الليل *أسود*", "al-layl *aswad*", "Ночь *чёрная*", "desert_night", "grandpa"),
    ("كبير", "kabīr", "большой", "البيت *كبير*", "al-bayt *kabīr*", "Дом *большой*", "street_day", "maryam"),
    ("صغير", "saghīr", "маленький", "الكوب *صغير*", "al-kūb *saghīr*", "Стакан *маленький*", "cafe_day", "yusuf"),
    ("جميل", "jamīl", "красивый", "المسجد *جميل*", "al-masjid *jamīl*", "Мечеть *красивая*", "courtyard_day", "ahmad"),
    ("جديد", "jadīd", "новый", "قلمي *جديد*", "qalamī *jadīd*", "Моя ручка *новая*", "classroom_day", "maryam"),
    ("سريع", "sarī'", "быстрый", "الطائرة *سريعة*", "at-tā'ira *sarī'a*", "Самолёт *быстрый*", "airport_day", "ahmad"),
    # ── Глаголы ──
    ("يأكل", "ya'kulu", "ест", "أحمد *يأكل* التفاحة", "ahmad *ya'kulu* t-tuffāha", "Ахмад *ест* яблоко", "kitchen_day", "mom"),
    ("يشرب", "yashrabu", "пьёт", "مريم *تشرب* الحليب", "maryam *tashrabu* l-halīb", "Марьям *пьёт* молоко", "kitchen_day", "mom"),
    ("يذهب", "yadhhabu", "идёт", "أبي *يذهب* إلى المسجد", "abī *yadhhabu* ilā l-masjid", "Папа *идёт* в мечеть", "courtyard_day", "ahmad"),
    ("يكتب", "yaktubu", "пишет", "الطالب *يكتب* الدرس", "at-tālib *yaktubu* d-dars", "Ученик *пишет* урок", "classroom_day"),
    ("يقرأ", "yaqra'u", "читает", "جدي *يقرأ* القرآن", "jaddī *yaqra'u* l-qur'ān", "Дедушка *читает* Коран", "majlis_night", "maryam"),
    ("ينام", "yanāmu", "спит", "الطفل *ينام*", "at-tifl *yanām*", "Ребёнок *спит*", "bedroom_night", "mom"),
    ("يلعب", "yal'abu", "играет", "يوسف *يلعب* بالكرة", "yūsuf *yal'abu* bi-l-kura", "Юсуф *играет* с мячом", "park_day", "ahmad"),
    ("يفتح", "yaftahu", "открывает", "أمي *تفتح* الباب", "ummī *taftahu* l-bāb", "Мама *открывает* дверь", "majlis_day", "maryam"),
    ("يجلس", "yajlisu", "сидит", "*أجلس* مع جدي", "*ajlisu* ma'a jaddī", "Я *сижу* с дедушкой", "desert_night", "ahmad"),
    ("يسمع", "yasma'u", "слышит", "*أسمع* الأذان", "*asma'u* l-adhān", "Я *слышу* азан", "courtyard_day", "ahmad"),
    # ── Город ──
    ("مسجد", "masjid", "мечеть", "*المسجد* قريب", "*al-masjid* qarīb", "*Мечеть* близко", "courtyard_day", "grandpa"),
    ("سوق", "sūq", "рынок", "نذهب إلى *السوق*", "nadhhabu ilā *s-sūq*", "Мы идём на *рынок*", "shop_day", "mom"),
    ("شارع", "shāri'", "улица", "*الشارع* طويل", "*ash-shāri'* tawīl", "*Улица* длинная", "street_day", "yusuf"),
    ("سيارة", "sayyāra", "машина", "*سيارة* أبي جديدة", "*sayyārat* abī jadīda", "Папина *машина* новая", "street_day", "ahmad"),
    ("مستشفى", "mustashfā", "больница", "*المستشفى* كبير", "*al-mustashfā* kabīr", "*Больница* большая", "clinic_day", "doctor"),
    ("مطار", "matār", "аэропорт", "نحن في *المطار*", "nahnu fī *l-matār*", "Мы в *аэропорту*", "airport_day", "dad"),
    ("طائرة", "tā'ira", "самолёт", "*الطائرة* في السماء", "*at-tā'ira* fī s-samā'", "*Самолёт* в небе", "airport_day", "maryam"),
    ("حديقة", "hadīqa", "парк, сад", "*الحديقة* جميلة", "*al-hadīqa* jamīla", "*Парк* красивый", "park_day", "maryam"),
    ("مدينة", "madīna", "город", "*مدينتي* كبيرة", "*madīnatī* kabīra", "Мой *город* большой", "street_day", "yusuf"),
    ("دكان", "dukkān", "лавка, магазин", "*الدكان* مفتوح", "*ad-dukkān* maftūh", "*Магазин* открыт", "shop_day", "seller"),
    # ── Время и вера ──
    ("يوم", "yawm", "день", "اليوم *يوم* جميل", "al-yawm *yawm* jamīl", "Сегодня прекрасный *день*", "park_day", "ahmad"),
    ("ليل", "layl", "ночь", "*الليل* هادئ", "*al-layl* hādi'", "*Ночь* тихая", "desert_night", "grandpa"),
    ("صباح", "sabāh", "утро", "*صباح* الخير", "*sabāh* al-khayr", "Доброе *утро*", "kitchen_day", "mom"),
    ("مساء", "masā'", "вечер", "*مساء* الخير", "*masā'* al-khayr", "Добрый *вечер*", "majlis_night", "grandpa"),
    ("أسبوع", "usbū'", "неделя", "في *الأسبوع* سبعة أيام", "fī *l-usbū'* sab'at ayyām", "В *неделе* семь дней", "classroom_day"),
    ("شهر", "shahr", "месяц", "رمضان *شهر* كريم", "ramadān *shahr* karīm", "Рамадан — щедрый *месяц*", "desert_night", "grandpa"),
    ("سنة", "sana", "год", "في *السنة* اثنا عشر شهرا", "fī *s-sana* ithnā 'ashara shahran", "В *году* двенадцать месяцев", "classroom_day"),
    ("صلاة", "salāh", "молитва", "*الصلاة* نور", "*as-salāh* nūr", "*Молитва* — свет", "courtyard_day", "grandpa"),
    ("قرآن", "qur'ān", "Коран", "أقرأ *القرآن* كل يوم", "aqra'u *l-qur'ān* kulla yawm", "Я читаю *Коран* каждый день", "majlis_night", "grandpa"),
    ("سلام", "salām", "мир", "*السلام* عليكم", "*as-salāmu* 'alaykum", "*Мир* вам", "courtyard_day", "ahmad"),
]

# кто говорит по умолчанию в сцене, и кто слушает-повторяет
DEFAULT_SPEAKER = {"classroom_day": "teacher", "kitchen_day": "mom", "clinic_day": "doctor", "shop_day": "seller",
                   "airport_day": "dad", "majlis_day": "dad", "bedroom_night": "maryam", "desert_night": "grandpa",
                   "courtyard_day": "grandpa", "majlis_night": "grandpa", "cafe_day": "yusuf"}


def listener_for(speaker: str, scene: str) -> str:
    if scene == "clinic_day" and speaker != "doctor":
        return "doctor"
    if speaker == "ahmad":
        return "yusuf" if scene in ("park_day", "street_day", "cafe_day", "courtyard_day") else "maryam"
    return "ahmad"


def episode(n: int, w: tuple) -> dict:
    ar, tr, ru, ex_ar, ex_tr, ex_ru, scene = w[:7]
    speaker = w[7] if len(w) > 7 else DEFAULT_SPEAKER.get(scene, "ahmad")
    listener = listener_for(speaker, scene)
    return {
        "title": f"Слово дня #{n}: *{ru}*",
        "channel": "MY ARABIC",
        "footer": "Учим арабский по мультикам",
        "narrator": {"ar": "ar-SA-HamedNeural", "ru": "ru-RU-SvetlanaNeural"},
        "characters": {k: CHARACTERS[k] for k in (speaker, listener)},
        "beats": [
            {"scene": scene, "cast": {speaker: 0.3, listener: 0.72}},
            {"hook": f"Слово дня: *«{ru}»*", "speak": f"Слово дня: {ru}"},
            {"say": speaker, "mood": "happy", "ar": ex_ar, "tr": ex_tr, "ru": ex_ru},
            {"say": listener, "mood": "surprised", "ar": f"*{ar}*", "tr": f"*{tr}*", "ru": f"*{ru}*", "speak": ar},
            {"quiz": {"ru": ru, "ar": ar, "tr": tr}},
        ],
        "outro": "Повтори вслух — и *подпишись*!",
        "outro_speak": "Повтори вслух и подпишись!",
    }


def main():
    assert len(WORDS) == 100, len(WORDS)
    for n, w in enumerate(WORDS, 1):
        for t in (w[0], w[3]):
            for bad, why in FORBIDDEN.items():
                if bad in t.replace("*", ""):
                    raise SystemExit(f"Слово {n}: «{t}» — {why}")
    out = HERE / "episodes"
    for old in out.glob("word_*.json"):
        old.unlink()
    md = ["# 100 «Слов дня» для Shorts «My Arabic»", "", "Файлы: `shorts/episodes/word_NNN.json` (из `shorts/words.py`).", ""]
    for n, w in enumerate(WORDS, 1):
        (out / f"word_{n:03d}.json").write_text(json.dumps(episode(n, w), ensure_ascii=False, indent=1), encoding="utf-8")
        md.append(f"{n}. **{w[0]}** — _{w[1]}_ — {w[2]}. Пример: {w[3].replace('*', '')} — _{w[4].replace('*', '')}_ — {w[5].replace('*', '')}")
    (HERE / "WORDS.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"✓ {len(WORDS)} слов → {out}")


if __name__ == "__main__":
    main()
