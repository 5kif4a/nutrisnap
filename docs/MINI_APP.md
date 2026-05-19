# NutriSnap Mini App

React + Vite + TypeScript + Tailwind + **@telegram-apps/sdk-react** Telegram
Mini App (стек по CLAUDE.md). Two screens
(spec `docs/specification.md` §6, scope = **Dashboard + Профиль**):

- **Дневник (Dashboard)** — переключение дат, круговой прогресс по калориям,
  бары Б/Ж/У, приёмы пищи за день (раскрываются), кнопка «+ Добавить»
  (закрывает Mini App → возврат в чат бота).
- **Профиль** — пол / вес / рост / возраст / активность / цель → сохранение
  пересчитывает суточную норму (Mifflin-St Jeor, общий код с ботом).

## Backend API (`backend/app/api/`)

| Метод | Путь | Назначение |
|---|---|---|
| `GET`  | `/api/me`  | Профиль + цели КБЖУ |
| `PUT`  | `/api/me`  | Обновить профиль, пересчитать норму |
| `GET`  | `/api/day?date=YYYY-MM-DD` | Тоталы + цели + приёмы пищи за день (UTC) |

**Авторизация** — заголовок `X-Init-Data` (raw Telegram WebApp initData),
проверка HMAC-SHA256 подписи ботовым токеном (`app/api/deps.py`).
В `ENV=development` пустой `X-Init-Data` → dev-юзер `telegram_id=999999`,
чтобы фронт работал в обычном браузере без Telegram.

## Локальный запуск (тест в браузере)

```bash
# 1. Бэкенд (postgres + миграции + API) — порт 8000
docker compose up -d --build postgres migrate api

# (опционально) бот, чтобы записывать еду фото/голосом/текстом
docker compose up -d --build bot

# 2. Фронтенд — порт 5173
cd frontend
npm install
npm run dev
```

Открой **http://localhost:5173** в браузере. Vite проксирует `/api` →
`http://localhost:8000`, поэтому CORS не мешает, а пустой initData
автоматически даёт dev-юзера.

Быстрая проверка API без фронта:

```bash
curl localhost:8000/api/me
curl -X PUT localhost:8000/api/me -H 'Content-Type: application/json' \
  -d '{"sex":"male","weight_kg":78,"height_cm":180,"age":30,"activity":"moderate","goal":"lose"}'
curl 'localhost:8000/api/day'
```

> Чтобы появились приёмы пищи на Dashboard — подними `bot`, напиши боту в
> Telegram (фото/текст), подтверди приём. Бот и Mini App используют одну БД,
> но **разных** пользователей: бот — твой реальный `telegram_id`, dev-фронт —
> `999999`. Для совпадения данных открой Mini App внутри Telegram (см. ниже)
> либо временно ходи к API с реальным `X-Init-Data`.

## Открыть внутри Telegram (когда дойдём до прода)

Telegram грузит Mini App только по **HTTPS**. Локальный `http://localhost`
для кнопки в боте не подойдёт. Варианты на потом:

1. **Деплой** (требование курса): фронт → Vercel (`frontend/vercel.json` готов),
   API → Railway (`backend/railway.json`). Затем:
   - на Railway задать env `MINI_APP_URL` = URL фронта (Vercel) и
     `WEBHOOK_BASE_URL` = публичный URL API (чтобы зарегистрировался webhook);
     pre-deploy command: `alembic upgrade head`.
   - в `frontend` env `VITE_API_URL` = URL API (Railway).
   - в боте `MINI_APP_URL` (https) → в `/start` появится кнопка
     «📊 Открыть дневник» (`WebAppInfo`), уже реализовано в `start.py`.
2. **Туннель для отладки**: `cloudflared tunnel --url http://localhost:5173`
   → полученный https-URL прописать как `MINI_APP_URL` бота.

## Telegram-интеграция (`src/telegram.ts`)

Используется `@telegram-apps/sdk-react@^3` (требование курса). Весь SDK
инкапсулирован в одном модуле со стабильным публичным API
(`getInitData` / `applyTheme` / `initTelegram` / `closeToBot` /
`greetingName` / `isInTelegram` / `useTelegramTheme`) — `api.ts` и страницы
от SDK не зависят.

- `initTelegram()` (вызов в `main.tsx`): `isTMA()` → `init()` +
  `restoreInitData()` + `mountMiniAppSync()` + `mountThemeParamsSync()` +
  `expandViewport()`.
- `getInitData()` → `retrieveRawInitData()` для заголовка `X-Init-Data`.
- `useTelegramTheme()` — React-хук на `useSignal(themeParamsState)` /
  `useSignal(isMiniAppDark)`, реактивно мапит тему Telegram в CSS-переменные
  `--tg-*`; подключён в `App.tsx`.
- Тег `telegram-web-app.js` в `index.html` **не нужен** — SDK v3 сам
  управляет мостом.

**Браузерный фолбэк**: вне Telegram `isTMA()` → false, сигналы пустые,
`getInitData()` возвращает `VITE_TEST_INIT_DATA`/`''` → бэкенд подставляет
dev-юзера (`telegram_id=999999`). Поэтому Mini App открывается и в обычном
браузере на `http://localhost:5173`.
