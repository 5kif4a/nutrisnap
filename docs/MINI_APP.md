# NutriSnap Mini App

React + Vite + TypeScript + Tailwind + **@telegram-apps/sdk-react** +
**@telegram-apps/telegram-ui** Telegram Mini App (стек по CLAUDE.md).
Три экрана (spec `docs/specification.md` §6):

- **Сегодня (Dashboard)** — переключение дат, круговой прогресс по калориям,
  бары Б/Ж/У, приёмы пищи за день (раскрываются), кнопка «+ Добавить»
  (закрывает Mini App → возврат в чат бота).
- **Календарь** — месячная сетка с цветовой индикацией дней (зелёный — в
  норме, жёлтый — немного, красный — мало, серый — нет записей/нормы),
  навигация по месяцам, тап по дню → открывает его на экране «Сегодня».
- **Профиль** — пол / вес / рост / возраст / активность / цель → сохранение
  пересчитывает суточную норму (Mifflin-St Jeor, общий код с ботом).

## Backend API (`backend/app/api/`)

| Метод | Путь | Назначение |
|---|---|---|
| `GET`  | `/api/me`  | Профиль + цели КБЖУ |
| `PUT`  | `/api/me`  | Обновить профиль, пересчитать норму |
| `GET`  | `/api/day?date=YYYY-MM-DD` | Тоталы + цели + приёмы пищи за день (UTC) |
| `GET`  | `/api/month?month=YYYY-MM` | По дню: kcal + статус (green/yellow/red/empty) за месяц |

Пороги статуса дня = `kcal / дневная норма`: `≥0.85` зелёный, `≥0.5`
жёлтый, иначе красный; нет нормы/еды → серый. Константы `GREEN_RATIO` /
`YELLOW_RATIO` в `app/api/routes.py`.

**Авторизация** — заголовок `X-Init-Data` (raw Telegram WebApp initData),
проверка HMAC-SHA256 подписи ботовым токеном (`app/api/deps.py`).
В `ENV=development` пустой `X-Init-Data` → dev-юзер (`DEV_FAKE_TELEGRAM_ID`
в `app/api/deps.py`, сейчас `339532463` — реальный id, чтобы в браузере
видеть данные из бота), чтобы фронт работал без Telegram.

## Локальный запуск (тест в браузере)

```bash
# 1. Бэкенд (postgres + миграции + API) — порт 8000
docker compose up -d --build postgres migrate api

# (опционально) бот, чтобы записывать еду фото/голосом/текстом
docker compose up -d --build bot

# 2. Фронтенд — порт 5173
cd frontend
yarn install
yarn dev
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

> Чтобы появились приёмы пищи на «Сегодня»/«Календаре» — подними `bot`,
> напиши боту в Telegram (фото/текст), подтверди приём. Бот и Mini App
> используют одну БД; dev-фронт ходит под `DEV_FAKE_TELEGRAM_ID` — он сейчас
> равен реальному id, поэтому в браузере видно данные из бота. Внутри
> Telegram юзер берётся из подписанного `initData`.

## Открыть внутри Telegram (когда дойдём до прода)

Telegram грузит Mini App только по **HTTPS**. Локальный `http://localhost`
для кнопки в боте не подойдёт. Варианты на потом:

1. **Деплой**: фронт → Vercel (`frontend/vercel.json` готов),
   API → Railway (`backend/railway.json`). Затем:
   - на Railway задать env `MINI_APP_URL` = URL фронта (Vercel) и
     `WEBHOOK_BASE_URL` = публичный URL API (чтобы зарегистрировался webhook);
     pre-deploy command: `alembic upgrade head`.
   - в `frontend` env `VITE_API_URL` = URL API (Railway).
   - в боте `MINI_APP_URL` (https) → в `/start` появится кнопка
     «📊 Открыть дневник» (`WebAppInfo`), уже реализовано в `start.py`.
2. **Туннель для отладки**: `cloudflared tunnel --url http://localhost:5173`
   → полученный https-URL прописать как `MINI_APP_URL` бота.

## UI-кит (`@telegram-apps/telegram-ui@^2`)

Нативные Telegram-компоненты:

- `<AppRoot>` оборачивает приложение (`App.tsx`) — авто-детект платформы и
  светлой/тёмной темы; стили подключены в `main.tsx`
  (`@telegram-apps/telegram-ui/dist/styles.css`).
- `Tabbar` + `Tabbar.Item` — нижняя навигация (`components/TabBar.tsx`).
- Профиль: `List` / `Section` / `Input` / `SegmentedControl` / `Select` /
  `Button`. Dashboard: `Button` для «+ Добавить».
- Кастомные виджеты оставлены свои (в telegram-ui таких нет): кольцо
  калорий (`CircularProgress`), бары Б/Ж/У (`MacroBar`), сетка календаря —
  стилизованы под тему Telegram через CSS-переменные `--tg-*`.

## Telegram-интеграция (`src/telegram.ts`)

Используется `@telegram-apps/sdk-react@^3` (мост/инициализация/тема). Весь
SDK инкапсулирован в одном модуле со стабильным публичным API
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
dev-юзера (`DEV_FAKE_TELEGRAM_ID`). Поэтому Mini App открывается и в обычном
браузере на `http://localhost:5173`.
