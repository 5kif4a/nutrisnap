# NutriSnap — Техническое задание

## 1. Продукт

**NutriSnap** — Telegram-бот + Mini App для ведения дневника питания. Аналог FatSecret/Calz, но с AI-вводом: фото, голос, текст — без ручного поиска продуктов.

**Целевая боль:** в FatSecret нужно вручную искать каждый продукт, вводить граммы, это долго. NutriSnap решает это одним тапом — сфоткал тарелку, получил КБЖУ.

---

## 2. Стек технологий

| Слой | Технология |
|---|---|
| Telegram Bot | python-telegram-bot (PTB), async |
| Backend API | FastAPI, async |
| База данных | PostgreSQL + SQLAlchemy async |
| LLM | GPT-4o (vision), GPT-4o-mini (текст/роутинг) |
| STT | OpenAI Whisper |
| Агент | LangGraph |
| Vector DB | Qdrant (self-hosted) |
| Embeddings | text-embedding-3-small |
| Мониторинг | LangSmith |
| Frontend | React + Vite + Tailwind CSS + shadcn/ui |
| MCP | Python MCP SDK |
| Контейнеризация | Docker + docker-compose |
| Деплой | Railway |

---

## 3. Архитектура системы

```
User (Telegram)
    │
    ▼
PTB Bot Handler
    │
    ▼
FastAPI Backend
    │
    ▼
LangGraph Agent
    ├── input_router       → определяет тип: фото / текст / голос
    ├── vision_node        → GPT-4o Vision → список продуктов + граммовка
    ├── stt_node           → Whisper → текст
    ├── text_parser_node   → GPT-4o-mini → структурированный список продуктов
    ├── nutrition_lookup   → FatSecret API / RAG / MCP tool
    ├── confirm_node       → human-in-the-loop: юзер подтверждает / правит
    └── save_node          → сохранение в PostgreSQL
         │
         ├── MCP Nutrition Server
         │    ├── search_food(name) → КБЖУ на 100г
         │    ├── log_meal(products, meal_type, date) → сохранить приём
         │    └── get_daily_summary(user_id, date) → сводка за день
         │
         └── RAG Pipeline (Qdrant)
              ├── Источники: USDA, кураторская база региональных блюд (KZ, RU, UZ, ...)
              ├── Chunking: 1 chunk = 1 продукт
              ├── Embeddings: text-embedding-3-small
              └── Reranker: по similarity score
```

---

## 4. Сущности базы данных

### users
```sql
id          UUID PRIMARY KEY
telegram_id BIGINT UNIQUE NOT NULL
username    TEXT
-- Профиль для расчёта РСК
sex         VARCHAR(10)   -- male / female
weight_kg   FLOAT
height_cm   FLOAT
age         INT
activity    VARCHAR(20)   -- sedentary / light / moderate / active / very_active
goal        VARCHAR(20)   -- lose / maintain / gain
-- Рассчитанные РСК
tdee_kcal   INT
protein_g   INT
fat_g       INT
carbs_g     INT
created_at  TIMESTAMP
```

### meals (приёмы пищи)
```sql
id          UUID PRIMARY KEY
user_id     UUID REFERENCES users
meal_type   VARCHAR(20)   -- breakfast / lunch / dinner / snack
eaten_at    TIMESTAMP
total_kcal  FLOAT
total_protein_g FLOAT
total_fat_g FLOAT
total_carbs_g   FLOAT
source      VARCHAR(20)   -- photo / voice / text
raw_input   TEXT          -- оригинальное сообщение/описание
created_at  TIMESTAMP
```

### meal_items (продукты в приёме)
```sql
id          UUID PRIMARY KEY
meal_id     UUID REFERENCES meals
food_name   TEXT
weight_g    FLOAT
kcal        FLOAT
protein_g   FLOAT
fat_g       FLOAT
carbs_g     FLOAT
fatsecret_id TEXT         -- ID в FatSecret если найдено
```

### foods (локальный кэш продуктов)
```sql
id          UUID PRIMARY KEY
name        TEXT
name_aliases TEXT[]        -- "куриная грудка", "куриное филе", "chicken breast"
kcal_per_100g    FLOAT
protein_per_100g FLOAT
fat_per_100g     FLOAT
carbs_per_100g   FLOAT
source      VARCHAR(20)   -- fatsecret / usda / off / custom / curated / llm_estimate
cuisine     VARCHAR(16)   -- kz / ru / uz / ge / tr / ... (optional regional tag)
fatsecret_id TEXT
```

---

## 5. Telegram Bot — сценарии

### 5.1 Онбординг (новый пользователь)
```
/start
→ Приветствие + объяснение функционала
→ Вопросы для расчёта РСК (пол, вес, рост, возраст, активность, цель)
→ Расчёт TDEE (формула Миффлина-Сан Жеора)
→ Показать рассчитанные нормы (калории, белки, жиры, углеводы)
→ Предложить открыть Mini App
```

### 5.2 Добавление приёма пищи

**Через фото:**
```
User → отправляет фото [с опциональным caption]
Bot → "Анализирую фото... 🔍"
LangGraph → vision_node → GPT-4o Vision
→ "Нашёл: куриная грудка ~200г, рис ~150г, огурец ~80г
   КБЖУ: 520 ккал | Б: 52г | Ж: 8г | У: 58г
   
   Тип приёма: [Завтрак] [Обед] [Ужин] [Перекус]"
User → нажимает тип приёма
Bot → "Записано в обед! 🥗"
```

**Через текст:**
```
User → "200г куриной грудки и 150г гречки"
LangGraph → text_parser_node → nutrition_lookup
→ то же подтверждение
```

**Через голос:**
```
User → голосовое "записал двести грамм творога на завтрак"
Bot → "Транскрибирую... 🎙"
LangGraph → stt_node → Whisper → text_parser_node → nutrition_lookup
→ подтверждение
```

**Пересылаемые сообщения:**
- Парсить текст из пересланного сообщения как текстовый ввод

### 5.3 Запрос статистики
```
/today       → сводка за сегодня
/week        → за неделю
/open        → открыть Mini App
```

### 5.4 Рассылки (scheduled jobs PTB)
- **Утро (8:00):** "Доброе утро! Цель на сегодня: 2100 ккал. Удачи 💪"
- **Вечер (20:00):** если < 50% нормы за день — "Не забудь поужинать! До нормы осталось X ккал"

### 5.5 Фильтрация нерелевантных сообщений
- Guardrail на входе: если сообщение не про еду — "Я помогаю только с дневником питания 🥦"
- Output guard: если КБЖУ > 5000 ккал на одну порцию — запросить уточнение

---

## 6. Mini App (React)

### Страницы

**1. Дашборд (главная)**
- Дата (навигация влево/вправо)
- Кольцевой прогресс-бар калорий (съедено / норма)
- Прогресс-бары Б / Ж / У
- Блоки приёмов пищи (завтрак, обед, ужин, перекус) с раскрытием
- Кнопка "+ Добавить" (открывает бота)

**2. Дневник / Календарь**
- Месячный календарь
- Цветовая индикация дней (зелёный — в норме, жёлтый — немного, красный — мало)
- Клик по дню → детальная статистика

**3. Профиль / Настройки**
- Текущие данные (пол, вес, рост, возраст, активность, цель)
- Редактирование → пересчёт РСК
- Текущие нормы КБЖУ

### UI
- Дизайн: минималистичный, как у Botfather Mini App
- Шрифты, отступы, цвета — под Telegram тему (светлая/тёмная)
- Компоненты: shadcn/ui + Tailwind

---

## 7. LangGraph — детальный граф

```python
# Ноды
input_router      # классифицирует: photo / text / voice / forward
vision_node       # GPT-4o Vision → [{name, weight_g, confidence}]
stt_node          # Whisper → текст
text_parser_node  # GPT-4o-mini → [{name, weight_g}]
nutrition_lookup  # MCP search_food → [{...кбжу}] + RAG fallback
confirm_node      # human-in-the-loop, ждёт callback от юзера
edit_node         # если юзер поправил — обновить данные
save_node         # MCP log_meal → PostgreSQL

# Рёбра
input_router → (photo → vision_node)
input_router → (text/forward → text_parser_node)
input_router → (voice → stt_node → text_parser_node)
vision_node → nutrition_lookup
text_parser_node → nutrition_lookup
nutrition_lookup → confirm_node
confirm_node → (confirmed → save_node)
confirm_node → (edited → edit_node → nutrition_lookup)  # цикл
save_node → END
```

---

## 8. MCP Nutrition Server

**Файл:** `mcp_server/nutrition_server.py`

```python
# Tool 1
search_food(name: str, limit: int = 5) -> list[FoodItem]
# Поиск в: 1) локальный кэш PostgreSQL, 2) FatSecret API, 3) RAG/Qdrant
# Возвращает: [{id, name, kcal_100g, protein_100g, fat_100g, carbs_100g, source}]

# Tool 2
log_meal(user_id: str, meal_type: str, items: list[MealItem], eaten_at: str) -> MealSummary
# Записывает приём пищи в PostgreSQL
# Возвращает: {meal_id, total_kcal, total_protein, total_fat, total_carbs}

# Tool 3
get_daily_summary(user_id: str, date: str) -> DailySummary
# Возвращает: {date, meals: [...], total_kcal, total_protein, total_fat, total_carbs, goal_kcal, pct_complete}
```

---

## 9. Skill

**Файл:** `skill/SKILL.md`

Триггеры: "посчитай калории", "запиши еду", "что я ел сегодня", "сколько калорий в ...", "запиши завтрак/обед/ужин"

References: таблица популярных казахстанских блюд с КБЖУ (бешбармак, баурсаки, манты, лагман, плов, самса, курт)

---

## 10. RAG-пайплайн

- **Источник данных:** USDA SR Legacy (CSV, ~9000 продуктов) + ручная таблица ~200 КЗ блюд
- **Chunking:** 1 документ = 1 продукт (`name | aliases | kcal | protein | fat | carbs | per_100g`)
- **Embeddings:** `text-embedding-3-small` (1536 dim, $0.02/1M tokens)
- **Vector DB:** Qdrant, коллекция `foods`, метаданные: source, kcal, category
- **Retrieval:** top-5 по cosine similarity
- **Reranker:** отбор по similarity score > 0.75, иначе fallback на FatSecret API
- **Зачем:** FatSecret не знает региональные блюда СНГ (бешбармак, борщ, плов, хинкали), RAG дополняет кураторской базой

---

## 11. Мониторинг (LangSmith)

Что логировать в каждом трейсе:
- Тип ввода (photo/text/voice)
- Промпт vision_node + ответ + confidence
- RAG: запрос, top-5 chunks, scores
- FatSecret API: запрос + ответ
- Финальный JSON продуктов
- Латентность каждой ноды
- Стоимость в токенах

---

## 12. Evals

### Golden dataset (30 примеров)
- 15 фото еды (тарелки) → эталонный КБЖУ вручную
- 10 текстовых описаний → эталон
- 5 edge cases: смешанные блюда, КЗ еда, нестандартные порции

### Метрики
1. **Accuracy распознавания** — % правильно определённых блюд
2. **MAPE калорий** — средняя % ошибка ккал vs эталон
3. **LLM-as-judge** — GPT-4o оценивает полноту ответа (1-5)

### A/B эксперимент
- **A:** GPT-4o Vision, temp=0.1
- **B:** GPT-4o-mini Vision, temp=0.1, расширенный промпт
- Метрики: accuracy, MAPE, latency, cost/req
- Прогон: 30 примеров из golden dataset

---

## 13. Гиперпараметры LLM

| Нода | Модель | Temperature | Max tokens | Причина |
|---|---|---|---|---|
| vision_node | gpt-4o | 0.1 | 800 | Лучшее качество Vision |
| text_parser_node | gpt-4o-mini | 0.0 | 500 | Детерминизм, дешевле |
| input_router | gpt-4o-mini | 0.0 | 50 | Классификация, дешево |
| stt | whisper-1 | — | — | STT, параметры неприменимы |

---

## 14. Docker-compose

```yaml
services:
  bot:       # PTB бот
  api:       # FastAPI
  qdrant:    # векторная БД
  postgres:  # основная БД
  langfuse:  # (опционально, или LangSmith cloud)
```

---

## 15. Деплой

- Backend (FastAPI + Bot): Railway
- Qdrant: Railway или self-hosted VPS
- PostgreSQL: Railway Postgres
- Mini App frontend: статика на Railway / Vercel
- Telegram Bot: webhook через Railway URL

---

## 16. Приоритеты реализации (5 дней)

| День | Задачи |
|---|---|
| 1 | БД схема + миграции, PTB бот skeleton, FastAPI базовые роуты, онбординг |
| 2 | LangGraph граф (фото+текст), GPT-4o Vision, Whisper STT, LangSmith трейсинг |
| 3 | RAG пайплайн (Qdrant + USDA данные), MCP-сервер, FatSecret API |
| 4 | React Mini App (дашборд + календарь), Skill + SKILL.md, scheduled jobs |
| 5 | Golden dataset 30 примеров, A/B эксперимент, ARCHITECTURE.md, EVALS.md, README, презентация |

---

## 17. Артефакты к сдаче (дедлайн 20 мая)

- [ ] GitHub репозиторий + README.md
- [ ] ARCHITECTURE.md с Mermaid-диаграммой
- [ ] EVALS.md с golden dataset + метрики + A/B результаты
- [ ] SKILL.md
- [ ] Презентация 10-15 слайдов (Google Slides)
- [ ] Рабочий Telegram бот (задеплоен на Railway)
