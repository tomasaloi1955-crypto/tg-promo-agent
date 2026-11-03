-- Схема бота «Нейропоток». Бот выполняет этот файл при каждом запуске
-- (всё через IF NOT EXISTS) — руками ничего создавать не нужно.
-- База должна быть СВОЯ (не та же, что у sister-bot).

CREATE TABLE IF NOT EXISTS users (
    tg_id            BIGINT PRIMARY KEY,
    username         TEXT,
    first_name       TEXT,
    source           TEXT,                     -- метка рекламы из /start src_xxx
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    goal             TEXT,                     -- biz | job | freelance | curious
    level            TEXT,                     -- zero | chat | code
    slot             TEXT,                     -- day | evening
    tz               TEXT NOT NULL DEFAULT 'Asia/Almaty',
    started_at       TIMESTAMPTZ,              -- анкета пройдена = день 1
    paid_at          TIMESTAMPTZ,              -- первая покупка
    unsubscribed     BOOLEAN NOT NULL DEFAULT false,
    blocked          BOOLEAN NOT NULL DEFAULT false,
    awaiting_feedback_day INT
);
CREATE INDEX IF NOT EXISTS users_started_idx ON users (started_at);
CREATE INDEX IF NOT EXISTS users_source_idx  ON users (source);

-- Уроки интенсива: n = 1..3, 4 — видео-презентация курса
CREATE TABLE IF NOT EXISTS lessons (
    n          INT  PRIMARY KEY CHECK (n BETWEEN 1 AND 20),
    video      TEXT,                           -- file_id Telegram, doc:file_id или ссылка
    text       TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- «✅ Задание сделано» — одна отметка на урок
CREATE TABLE IF NOT EXISTS completions (
    tg_id      BIGINT NOT NULL REFERENCES users (tg_id),
    day        INT    NOT NULL,                -- номер урока
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tg_id, day)
);

-- Отзывы на «Как вам интенсив?»; approved: NULL — ждёт модерации
CREATE TABLE IF NOT EXISTS feedback (
    id         BIGSERIAL PRIMARY KEY,
    tg_id      BIGINT NOT NULL REFERENCES users (tg_id),
    day        INT,
    mood       TEXT,
    text       TEXT,
    approved   BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS feedback_pending_idx ON feedback (approved) WHERE approved IS NULL;

-- Журнал отправок: каждое плановое сообщение — один раз
CREATE TABLE IF NOT EXISTS sends (
    tg_id   BIGINT NOT NULL REFERENCES users (tg_id),
    key     TEXT   NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tg_id, key)
);

CREATE TABLE IF NOT EXISTS admin_alerts (
    key     TEXT PRIMARY KEY,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Оплаты: tribute | stars | manual; status: paid | pending | rejected; raw->>'plan' — тариф
CREATE TABLE IF NOT EXISTS payments (
    id          BIGSERIAL PRIMARY KEY,
    tg_id       BIGINT NOT NULL,
    provider    TEXT   NOT NULL,
    external_id TEXT   UNIQUE,
    amount      NUMERIC,
    currency    TEXT,
    status      TEXT   NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw         JSONB
);
CREATE INDEX IF NOT EXISTS payments_tg_idx ON payments (tg_id);
