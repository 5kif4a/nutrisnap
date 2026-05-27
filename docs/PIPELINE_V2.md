# Pipeline V2 — rethink

> Дата: 2026-05-27
> Статус: design draft, не имплементировано
> Контекст: после анализа реальных trace'ов из LangSmith (см. dataset
> `d1d4c995-f398-41f1-8580-fc0a6f6fc6bd`) обнаружили, что текущий пайплайн
> систематически промахивается на «разнобойных» текстовых инпутах юзера.

## 1. Две боли, которые надо решить

### Боль 1 — logging known foods is slow & unreliable

Юзер пишет в разнобой («Maxler протеин 30», «Nuts 66 гр», «гречка 150»), и
агент не находит то, что юзер уже ел вчера. Текущая цепочка lookup
`PG ilike → OFF text → fuzzy match` **не учитывает личную историю**
пользователя — каждый раз идёт глобальный поиск.

FatSecret силён именно тем, что **«My Foods» / «Recently Eaten»** — это
первый источник, а не fallback.

### Боль 2 — cooking ceremony, 4 микродействия на одно блюдо

Юзер готовит дома → фоткает каждый ингредиент → взвешивает →
вручную считает среднее КБЖУ через другой LLM → логает. Это бесит.

Текущий `recipe_builder` (см. memory `[[recipe_builder]]`) частично это
закрывает, но **всё ещё требует серии фоток** и не даёт «one-shot»
ввода типа «грудка 250 + лук 100 + рис 150 → готовое 480г».

## 2. Архитектурная дыра

Текущий lookup chain спроектирован как «глобальный продуктовый каталог
для всех». Но **food-tracking — это персональная задача**: 80% логов
юзера = 50 продуктов из его репертуара. В пайплайне нет источника
«foods this user has eaten before» как приоритетного шага.

Следствие: модель каждый раз «угадывает заново» то, что юзер уже
подтвердил неделю назад. Отсюда галлюцинации брендов и lookup'ы в
случайные продукты OFF.

## 3. Новый пайплайн

```
text / photo / voice
    │
    ▼
┌──────────────────────────────────┐
│ parse_intent_node                │  тонкий промпт ~30 строк
│  → ParsedItem[] (name, brand,    │  без brand alias table
│    amount, unit, barcode?)       │  без duplicated examples
└──────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────┐
│ resolve_food_layered:            │
│                                  │
│  1. user_foods_recent (30d)      │  ← НОВЫЙ tier
│  2. user_foods_frequent (allt)   │  ← НОВЫЙ tier
│  3. global_catalog (Qdrant)      │  curated + cached OFF
│  4. OFF barcode (если есть)      │
│  5. OFF text (brand hard-filter) │
│  6. ASK USER / SKIP              │  ← НЕ llm_estimate для брендов
└──────────────────────────────────┘
    │
    ├──── confidence ≥ 0.85 ────► auto-accept
    │
    └──── confidence < 0.85 ────► disambiguate
                                  bot шлёт inline keyboard:
                                  «А) Maxler Ultra Whey 30g
                                   Б) Maxler Special Mass 30g
                                   В) ввести вручную»
    │
    ▼
┌──────────────────────────────────┐
│ on_commit:                       │
│  → upsert user_foods             │
│      frequency++                 │
│      last_eaten = now()          │
│  → reindex Qdrant (fire-forget)  │
└──────────────────────────────────┘
```

### Что меняется относительно текущей версии

| Слой | Сейчас | V2 |
|---|---|---|
| Парсер | 187-строчный промпт с brand aliases | ~30 строк, brand norm в Python, контекст из RAG |
| Lookup tier 1 | глобальный PG ilike | **user_foods (personal layer)** |
| Lookup tier 2 | OFF text без brand filter | Qdrant semantic с brand-rerank |
| Failure mode | silent fuzzy match → bad data | **disambiguation inline** |
| LLM estimate | для всего что не нашлось | только generics без бренда (уже сделано) |
| food_intent gate | отдельный LLM call | Python heuristic + Moderation API |

## 4. Recipe sub-pipeline — collapse the ceremony

Цель: довести «приготовил дома → залогал» до **одного сообщения** или
**одной серии фоток**, а дальше — авто-расчёт per-100g cooked dish и
сохранение как личный food для будущего one-tap.

### Entry A — text one-shot

```
юзер: «куриная грудка 250, лук 100, морковь 80, рис 150, масло 20
       → готовое 480г»
   ↓
parse_intent → 5 ингредиентов + cooked_weight_g=480
   ↓
resolve_food_layered для каждого (тот же layered pipeline)
   ↓
sum → total_kcal / P / F / C
divide by 480 → per-100g cooked dish
   ↓
LLM (1 короткий call) → predict_name → «Курица с рисом и овощами»
   ↓
save_user_recipe (см. food_repo.save_user_recipe)
   ↓ next time:
юзер пишет «Курица с рисом 150» → instant hit в user_foods_recent
```

### Entry B — photo album с весами

Текущий photo flow уже умеет в multi-photo album (см. `photo_buffer.py`).
Расширяем vision-промпт: распознать что на каждом кадре одни весы +
ингредиент → отдать ParsedItem[] со scale-weights → отдать в тот же
recipe sub-pipeline. Финализация по кнопке «Готово» (memory
`[[recipe_builder]]`).

Различие с текущим: **не «следующий ингредиент → следующая фотка»**, а
серия фоток разом → один сводный draft.

## 5. Влияние на промпты и RAG

### Промпты сокращаются

- `TEXT_PARSER_SYSTEM_PROMPT`: 187 → ~30 строк
  - убираем brand alias table (уходит в Python normalizer)
  - убираем дублирующиеся FORMAT EXAMPLES
  - убираем rule про is_food_related (поля нет в схеме)
  - оставляем: core rules + 5 ключевых few-shots
- `FOOD_INTENT_SYSTEM_PROMPT`: удаляется целиком вместе с
  `classify_food_intent` — Python heuristic + Moderation API закрывают use case
- `VISION_SYSTEM_PROMPT`: остаётся, но расширяется на multi-ingredient
  recipe recognition
- `NUTRITION_ESTIMATE_PROMPT`: остаётся, вызывается только на generics

### RAG становится load-bearing

Сейчас Qdrant обслуживает только `/recommend`. В V2 он — ядро lookup'а:

- `user_foods` collection (per-user, namespaced by user_id) — embeddings от
  `food_name + brand + aliases`
- `global_foods` collection — curated regional + cached OFF/Vision results
- Перед парсером: top-K relevant entries → инжектим в parser prompt как
  context (опционально, L2 enhancement)
- В lookup'е: semantic search → rerank по brand-match + confidence score

## 6. Структуры данных, которые нужно добавить

### Personal food layer

Опции (надо выбрать):

**A) Materialized view `user_foods_agg`**
```sql
SELECT
  meal_items.user_id,
  meal_items.food_id,
  meal_items.food_name,
  COUNT(*) AS frequency,
  MAX(meal_items.eaten_at) AS last_eaten,
  AVG(meal_items.amount) AS typical_amount
FROM meal_items
WHERE eaten_at >= now() - interval '90 days'
GROUP BY user_id, food_id, food_name
```

Refresh по cron или on-commit. Минус: stale data между refresh.

**B) Денормализованная таблица `user_food_stats`**
Триггер на `meal_items` insert → upsert в `user_food_stats(user_id,
food_id, frequency, last_eaten, typical_amount)`. Плюс: всегда свежо,
быстрые запросы. Минус: триггер, согласованность.

**C) On-the-fly query**
Прямой `SELECT FROM meal_items WHERE user_id=...` с агрегацией.
Плюс: zero infra. Минус: с ростом данных тормозит, кэшировать придётся.

**Предлагаемое:** старт с C (on-the-fly + Redis cache на 5 минут), при
росте users мигрировать на B.

### Disambiguation state

Когда бот шлёт inline keyboard с альтернативами, нужно где-то держать
state «пользователь юзер X выбирает между этими 3 вариантами для item Y».

Сейчас уже есть `meal_drafts.py` — можно расширить, или новая
ephemeral таблица `disambiguation_drafts` с TTL=10min.

## 7. Что NOT в скоупе V2

- Замена LangGraph на что-то другое (требование курса)
- Уход от MCP server (требование курса)
- Изменение `foods` core schema
- Удаление FatSecret кода (уже за флагом, остаётся)

## 8. Открытые вопросы

1. **User foods aggregate** — A/B/C из секции 6? Пока склоняюсь к C+cache.
2. **Confidence threshold** для disambiguation — эмпирически после прогона
   evals на реальных логах из dataset.
3. **Recipe entry-point** — оставить отдельную кнопку «Recipe» под
   фото, или все multi-item inputs автоматически идут recipe-flow'ом?
4. **Cleanup кривых meal_items** из прошлого (например, «cruesly mélange
   de noix» вместо «Nuts») — оставить как есть, или batch-job на
   re-resolution с новым pipeline?
5. **Embedding cost** — каждый lookup = 1 OpenAI embedding call. На
   масштабе users × meals в день это деньги. Кэшировать embeddings по
   нормализованному тексту?

## 9. Метрики успеха

Прежде чем имплементировать — определить, как меряем:

- **Match accuracy** на golden dataset (см. `app/evals/`) — % случаев,
  когда `resolved_item.name` семантически соответствует `text_input`
- **Time-to-log** — медиана времени от первого сообщения до commit
  (включая disambiguation тапы)
- **Repeat-log latency** — на сколько быстрее логать **повторное**
  блюдо vs первое (это и есть USP personal layer)
- **Hallucination rate** — % `llm_estimate` items в общем числе resolved
  (target: < 5%)

## 10. Переход — фазы

**Фаза 1 — quick wins (1-2 дня, без новых таблиц):**
- Урезать `TEXT_PARSER_SYSTEM_PROMPT` до ~30 строк
- Удалить `food_intent` gate (Python heuristic заменит)
- Brand normalizer в Python

**Фаза 2 — personal layer (3-5 дней):**
- `user_food_stats` on-the-fly query + Redis cache
- Lookup chain: добавить user-foods как первый tier
- Метрики до/после на golden dataset

**Фаза 3 — RAG в парсере и lookup'е (5-7 дней):**
- Qdrant index per-user foods
- Semantic search в lookup chain
- Confidence-driven disambiguation UX

**Фаза 4 — recipe one-shot (3-4 дня):**
- Парсер: распознать «X + Y + Z → готовое N» формат
- Vision: multi-ingredient на одном фото
- save_user_recipe → автоматический alias generation

---

> Связанные документы:
> - `docs/specification.md` — оригинальное ТЗ
> - `docs/ARCHITECTURE_VARIANTS.md` — обоснование «тонкий LangGraph»
> - `docs/NUTRITION_LOOKUP.md` — текущая цепочка lookup'а
> - `docs/DATABASE_CONCURRENCY.md` — правила работы с БД (учитываем при
>   проектировании `user_food_stats`)
