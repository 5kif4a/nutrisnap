# NutriSnap — Claude context

## Что это

Telegram-бот + Mini App для дневника питания с AI-вводом (фото / голос / текст). Клон FatSecret/Calz, но без ручного поиска продуктов: сфоткал тарелку → получил КБЖУ → один тап для записи в приём пищи.

Финальный проект курса **nFactorial LLM Engineer**, дедлайн **20 мая 2026**.

## Стек

| Слой | Технология |
|---|---|
| Bot | python-telegram-bot (PTB) 22+, webhook через FastAPI |
| API | FastAPI, async, uvicorn |
| DB | PostgreSQL 16 + SQLAlchemy 2.0 async + asyncpg + Alembic |
| LLM | OpenAI GPT-4o (vision), GPT-4o-mini (text/routing), Whisper (STT) |
| Agent | LangGraph |
| Vector DB | Qdrant (RAG + опционально семантический кэш) |
| Embeddings | text-embedding-3-small |
| Trace | LangSmith |
| MCP | Python MCP SDK (nutrition server, 3 tools) |
| Frontend | React + Vite + TypeScript + Tailwind + shadcn/ui |
| Mini App | @telegram-apps/sdk-react + @telegram-apps/telegram-ui |
| Deploy | Railway (backend + db + qdrant), Vercel (frontend) |
| Package mgr | uv (Python), yarn (frontend) |

## Структура репозитория

```
nutrisnap/
├── backend/                    # FastAPI + bot + LangGraph + MCP
│   ├── app/
│   │   ├── main.py            # FastAPI entrypoint, /health, /telegram/webhook
│   │   ├── core/config.py     # pydantic-settings, .env
│   │   ├── api/               # роуты Mini App (auth через initData)
│   │   ├── bot/               # PTB handlers
│   │   ├── db/                # SQLAlchemy модели, session
│   │   ├── graph/             # LangGraph граф и ноды
│   │   ├── mcp/               # MCP nutrition server
│   │   ├── rag/               # Qdrant ingest и retrieval
│   │   ├── services/          # FatSecret, бизнес-логика
│   │   └── evals/             # golden dataset + run.py
│   ├── tests/
│   ├── alembic/               # миграции (будут добавлены)
│   ├── Dockerfile             # multi-stage с uv
│   ├── railway.json           # Railway deploy config
│   └── pyproject.toml         # uv зависимости
├── frontend/                   # React Mini App
├── docs/                       # все спецификации проекта
│   ├── specification.md       # детальное ТЗ
│   ├── ARCHITECTURE_VARIANTS.md
│   ├── DATABASE_CONCURRENCY.md
│   ├── NUTRITION_LOOKUP.md    # пайплайн поиска продуктов
│   └── project requirements.md
├── .github/workflows/          # CI/CD
│   ├── backend-ci.yml         # ruff + pytest
│   ├── frontend-ci.yml        # typecheck + lint + build
│   └── evals.yml              # golden dataset on PR + comment
├── .claude/skills/             # навыки автоматизации
├── docker-compose.yml          # postgres + qdrant + api + bot
├── CLAUDE.md                   # ← вы здесь
└── README.md
```

## Архитектура — два варианта

В `docs/ARCHITECTURE_VARIANTS.md` описаны два варианта. **Выбран Вариант B (тонкий LangGraph):** LangGraph остаётся как обёртка для требований курса, но внутри нод — прямой Python код. LLM вызывается только там где без него никак (vision, text parser, STT).

Это даёт latency на текстовый ввод ~0.7с против 3с в полностью агентном варианте.

## Конкурентность БД

См. `docs/DATABASE_CONCURRENCY.md`. Краткое правило:
- READ COMMITTED как дефолт (не трогаем)
- НЕ хранить производные данные (totals считаем на чтение)
- UNIQUE + ON CONFLICT для upsert
- SELECT FOR UPDATE точечно где нужно
- Idempotency-key по `(user_id, tg_message_id)` для дедупа бота
- LLM/HTTP вызовы — **вне** транзакции

## Pipeline поиска продуктов

См. `docs/NUTRITION_LOOKUP.md`. Цепочка приоритетов:

```
1. PostgreSQL local cache       (~80% после прогрева)
2. Qdrant RAG (curated regional + raw foods seed)
3. FatSecret API                ← fallback для редких EN-only продуктов
4. GPT-4o-mini estimate         ← last resort
```

> Open Food Facts удалён из пайплайна: публичный API упирался в rate-limit
> (503). `services/openfoodfacts.py` и `FoodSource.OPEN_FOOD_FACTS` вырезаны.

Каждый успешный внешний lookup → upsert в `foods` с alias'ами. База растёт сама.

## Команды для разработки

### Локальный запуск
```bash
cp backend/.env.example backend/.env  # заполнить ключи
docker compose up                      # postgres + qdrant + api + bot
```

### Backend (uv)
```bash
cd backend
uv sync                                # установить зависимости
uv run uvicorn app.main:app --reload  # dev server
uv run ruff check .                   # lint
uv run ruff format .                   # format
uv run pytest -q                      # тесты
uv run alembic upgrade head           # миграции
uv run alembic revision --autogenerate -m "msg"  # новая миграция
```

### Frontend
```bash
cd frontend
yarn install
yarn dev                               # vite dev server
yarn typecheck
yarn lint
yarn build
```

### Evals
```bash
cd backend
uv run python -m app.evals.run --output results.json
```

## Конвенции кода

### Naming — A/HC/LC pattern

Все имена функций, методов и переменных следуют схеме **Action / High Context / Low Context** (https://github.com/kettanaito/naming-cheatsheet):

```
prefix? + Action + HighContext + LowContext?
```

| Часть | Что это | Примеры |
|---|---|---|
| `prefix?` | префикс-модификатор (опционально) | `is`, `has`, `should`, `min`, `max`, `prev`, `next` |
| `Action` | глагол что функция делает | `get`, `set`, `fetch`, `create`, `update`, `delete`, `compute`, `compose`, `handle`, `parse`, `send`, `validate`, `lookup`, `log` |
| `HighContext` | главная сущность над которой действие | `User`, `Meal`, `Food`, `Photo`, `Voice`, `Barcode`, `Nutrition`, `Skill`, `Embedding` |
| `LowContext?` | уточнение (опционально) | `ByName`, `ByBarcode`, `FromImage`, `ForToday`, `PerMealType` |

**Языковые регистры:**
- Python: `snake_case` (`lookup_food_by_barcode`)
- TypeScript: `camelCase` (`lookupFoodByBarcode`)
- Классы / типы / SQLAlchemy модели: `PascalCase` (`MealItem`, `NutritionLookupNode`)
- Константы: `UPPER_SNAKE_CASE`

**Хорошие примеры из домена NutriSnap:**

| Python (snake_case) | TypeScript (camelCase) | Что делает |
|---|---|---|
| `parse_photo_meal` | `parsePhotoMeal` | разобрать фото в meal items |
| `lookup_food_by_barcode` | `lookupFoodByBarcode` | поиск продукта по штрих-коду |
| `compute_daily_totals` | `computeDailyTotals` | агрегат калорий и БЖУ за день |
| `send_meal_confirmation` | `sendMealConfirmation` | отправить inline-кнопки юзеру |
| `handle_voice_message` | `handleVoiceMessage` | обработчик голосового в боте |
| `fetch_recent_foods_per_meal_type` | `fetchRecentFoodsPerMealType` | quick-add список |
| `is_meal_logged` | `isMealLogged` | boolean: записан ли приём |
| `has_pending_confirmation` | `hasPendingConfirmation` | boolean: ждём подтверждения |
| `should_send_reminder` | `shouldSendReminder` | boolean: пора ли напомнить |
| `prev_meal_eaten_at` | `prevMealEatenAt` | время предыдущего приёма |
| `max_daily_kcal` | `maxDailyKcal` | граница из РСК |

**Плохие примеры (избегать):**

| ❌ Плохо | ✅ Хорошо | Почему |
|---|---|---|
| `data`, `info`, `value` | `meal`, `nutritionData` | бессмысленно |
| `getMealData` (на классе `MealRepo`) | `getMealRepo.get(id)` | дублирование контекста |
| `process` | `parse`, `validate`, `compute` | "process" — мусорный глагол |
| `doStuff`, `helper` | конкретный action+HC | непонятно что делает |
| `usr`, `nbr`, `cnt` | `user`, `number`, `count` | не сокращать |
| `boolean1`, `flag` | `isMealLogged` | булевы с префиксом |
| `userMeals` (в классе `User`) | `meals` | дублирование контекста класса |

**Правила:**
- S-I-D: **S**hort, **I**ntuitive, **D**escriptive
- Английский язык во всём коде (комментарии могут быть RU только если объясняют доменное правило)
- Единственное / множественное число: переменная-коллекция — мн. число (`meals`), одиночное значение — ед. число (`meal`)
- Не дублируй контекст: внутри класса `User` метод `getUserMeals` → просто `getMeals` (User уже подразумевается)
- Функция должна отражать ожидаемый результат: `isMealValid` возвращает bool, `fetchMeal` возвращает meal, `composeNutritionPayload` возвращает payload

**Применение к LangGraph нодам:**
Имя ноды = `<action>_<HC>_node`:
- `parse_photo_node`
- `lookup_nutrition_node`
- `detect_barcode_node`
- `route_input_node`
- `confirm_meal_node`
- `save_meal_node`

### Python
- Async везде где возможно (FastAPI async routes, AsyncSession, httpx.AsyncClient)
- Type hints обязательно
- Pydantic v2 для всех DTO
- SQLAlchemy 2.0 синтаксис (`select()`, `session.scalar()`)
- Структурированный logging — JSON в проде, dev-readable локально

### LLM-вызовы
- Все вызовы через LangChain/LangGraph для трейсинга в LangSmith
- Structured output через Pydantic schema (function calling)
- Параметры (temperature, max_tokens) — в `app/core/config.py` per нода
- Никаких prompt-ов в коде — отдельные файлы `app/graph/prompts/`

### LangGraph граф
Тонкие ноды: каждая делает одну вещь и быстро возвращается. LLM-вызов = одна нода. Бизнес-логика и SQL — в обычных нодах без LLM. Роутинг — pure Python `if/elif`, не LLM.

### БД
- Имена таблиц во мн.числе: `users`, `meals`, `meal_items`, `foods`
- snake_case для колонок
- UUID PK везде
- Timezone-aware timestamps (`TIMESTAMPTZ`)

### Frontend
- TypeScript строгий
- Все API-вызовы через `lib/api.ts` (один helper с `X-Init-Data` заголовком)
- Auth → `useLaunchParams()` от `@telegram-apps/sdk-react`
- UI компоненты из `@telegram-apps/telegram-ui`

## Авторизация Mini App ↔ API

Mini App получает `initData` от Telegram → отправляет в заголовке `X-Init-Data` на каждый запрос → FastAPI верифицирует подпись через PTB `bot.verify_webapp_signature(...)` → достаёт `telegram_id` → находит юзера в БД.

В dev-режиме (`ENV=development`) пустой initData → подставляется фейковый юзер с id=999999.

## Деплой

См. план `~/.claude/plans/humming-fluttering-karp.md` и `docs/specification.md` раздел 15.

- **Backend → Railway** (native GitHub integration, Watch Paths: `backend/**`)
- **Frontend → Vercel** (auto-deploy + preview на PR)
- **GitHub Actions**: backend-ci, frontend-ci, evals на каждый PR

## Не делать без явного запроса

- Не коммитить и не пушить без явной команды
- Не запускать `alembic upgrade head` на проде (только в release command Railway)
- Не менять `docs/project requirements.md` (это от nFactorial)
- Не удалять `docs/nutrisnap_project_requirements_checklist.html`
- Не использовать FatSecret как основной источник (см. `NUTRITION_LOOKUP.md`)

## Что НЕЛЬЗЯ менять (требования курса)

- LangGraph как оркестратор (нельзя заменить простым кодом без графа)
- MCP-сервер с 2+ tools (Nutrition MCP)
- Skill с `SKILL.md` (Kazakh foods skill в `backend/app/skill/`)
- RAG-пайплайн с Qdrant
- LangSmith трейсинг
- Golden dataset 30+ примеров
- A/B эксперимент с метриками

## Что под рукой / Quick refs

- Spec: `docs/specification.md`
- Архитектурные варианты: `docs/ARCHITECTURE_VARIANTS.md`
- Конкурентность БД: `docs/DATABASE_CONCURRENCY.md`
- Поиск продуктов: `docs/NUTRITION_LOOKUP.md`
- Требования курса: `docs/project requirements.md`
- Чек-лист: `docs/nutrisnap_project_requirements_checklist.html`
