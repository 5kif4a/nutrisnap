# Nutrition Lookup — пайплайн поиска продуктов

## Цель

Найти КБЖУ любого продукта или блюда: от сырых ингредиентов до брендовых упакованных товаров (например "сметана President 10%") и казахских национальных блюд.

---

## Цепочка приоритетов

| # | Источник | Покрытие | Цена |
|---|---|---|---|
| 1 | PostgreSQL local cache | ~80% после "прогрева" базы | 10ms |
| 2 | Qdrant RAG (curated regional + raw foods) | западные продукты, семантика | 50ms + embedding |
| 3 | Open Food Facts (barcode) | бренды, упаковки (President, Coca-Cola) | 200ms |
| 4 | Open Food Facts (text search) | бренды без штрих-кода | 300ms |
| 5 | FatSecret API | редкие EN-only продукты | 500ms |
| 6 | GPT-4o-mini estimate | last resort, "оцени КБЖУ для X" | 1-2s + cost |

**Главный принцип:** база растёт сама. Каждый успешный lookup сохраняется в локальный кэш с alias'ами. Через месяц 90% запросов из PostgreSQL.

---

## Featureset

### F1. Barcode scanning через фото

**User story:** "Я фоткаю штрих-код на упаковке President → получаю точные КБЖУ"

**Реализация:**
- LangGraph нода `barcode_detector_node` перед `vision_node`
- `pyzbar` для декодирования штрих-кода из изображения
- Запрос в Open Food Facts API: `https://world.openfoodfacts.org/api/v2/product/{barcode}.json`
- Если штрих-код найден и есть данные — пропустить vision_node, сразу в save
- Если нет — fallback на GPT-4o Vision (читает этикетку напрямую)

**Зависимости:** `pyzbar`, `Pillow`

### F2. Open Food Facts text search

**User story:** "Я пишу 'сметана president' → нахожу её в базе"

**Реализация:**
- HTTP клиент в `app/services/openfoodfacts.py`
- Endpoint: `https://world.openfoodfacts.org/api/v2/search?q={query}&lang=ru&fields=product_name_ru,brands,nutriments`
- Без авторизации, без whitelist, без ключа

### F3. Локальный кэш с alias'ами и брендами

**Изменения схемы `foods`:**
```sql
ALTER TABLE foods ADD COLUMN brand TEXT;
ALTER TABLE foods ADD COLUMN barcode TEXT;
CREATE INDEX idx_foods_barcode ON foods(barcode) WHERE barcode IS NOT NULL;
CREATE INDEX idx_foods_brand ON foods(brand);

-- aliases уже TEXT[] из спецификации
```

**Каждый успешный lookup → upsert в foods:**
```python
INSERT INTO foods (name, aliases, brand, barcode, kcal_per_100g, ...)
VALUES (...)
ON CONFLICT (barcode) DO UPDATE SET
  aliases = array_append(foods.aliases, EXCLUDED.aliases[1]),
  ...
```

### F4. Vision-чтение этикетки

**User story:** "Я фоткаю упаковку — Vision сам читает таблицу пищевой ценности с этикетки"

**Реализация:**
- Расширить системный промпт `vision_node`:
  > "Если на упаковке видна таблица пищевой ценности — извлеки точные значения калорий, белков, жиров, углеводов на 100г. Также извлеки название бренда и штрих-код если виден."
- Структурированный вывод (Pydantic schema): `{name, brand, barcode?, kcal_100g, ...}`
- Если Vision вернул barcode → cross-check с OFF API → взять данные OFF (надёжнее этикетки)

### F5. MCP tool `lookup_by_barcode`

Добавить в MCP-сервер четвёртый tool:

```python
@mcp.tool()
async def lookup_by_barcode(barcode: str) -> FoodItem | None:
    """Lookup food product by EAN/UPC barcode via Open Food Facts."""
```

### F6. KZ-блюда — ручная локальная база

Seed `foods` таблицу с **кураторской базой региональных блюд СНГ** (~200-500 записей). `source = 'curated'`, `cuisine` — тег по региону (`kz`, `ru`, `uz`, `ge`, ...). Стартовый набор:

- **KZ:** бешбармак, баурсаки, манты, лагман, плов, самса, курт, казы, шужык, бауырсак, чак-чак
- **RU:** борщ, окрошка, солянка, пельмени, оливье, гречка с тушёнкой
- **UZ:** плов узбекский, шурпа, лагман, манты, самса
- **GE:** хачапури, хинкали, чахохбили, харчо

Дизайн открыт к расширению на любую страну СНГ — поле `cuisine` строковое, без enum-ограничений. Источник — таблицы из [Skill](../backend/app/skill/references/).

### F7. UGC — пользовательские блюда

**User story:** "Я приготовил своё блюдо 'мамин борщ' → добавляю его в базу один раз → пользуюсь как обычным продуктом"

**Реализация:**
- В Mini App: страница "Мои блюда" → форма добавления (название, КБЖУ на 100г, или загрузка фото)
- Хранение: `foods` с `source='custom'` и `created_by_user_id=user.id`
- В поиске сначала свои блюда юзера, потом общие

### F10. Quick add — недавние и частые продукты per meal type

**User story:** "У меня одни и те же 10-15 продуктов крутятся в одних приёмах. Хочу добавлять овсянку на завтрак одним тапом без AI"

**Зачем:**
- 90% рациона — повторяющиеся продукты
- Latency: 50мс вместо 5с (без LLM-вызова)
- Cost: $0 вместо $0.005 на запрос
- UX как у FatSecret/Calz — главная причина что люди возвращаются

**Реализация:**

**SQL recent (per meal_type):**
```sql
SELECT DISTINCT ON (mi.food_name)
  mi.food_name, mi.kcal, mi.protein_g, mi.fat_g, mi.carbs_g,
  mi.weight_g, m.eaten_at AS last_eaten
FROM meal_items mi
JOIN meals m ON mi.meal_id = m.id
WHERE m.user_id = $1 AND m.meal_type = $2
ORDER BY mi.food_name, m.eaten_at DESC
LIMIT 10;
```

**SQL frequent (последние 30 дней):**
```sql
SELECT mi.food_name,
       COUNT(*) AS freq,
       AVG(mi.weight_g) AS avg_weight,
       AVG(mi.kcal) AS avg_kcal
FROM meal_items mi
JOIN meals m ON mi.meal_id = m.id
WHERE m.user_id = $1
  AND m.meal_type = $2
  AND m.eaten_at > NOW() - INTERVAL '30 days'
GROUP BY mi.food_name
HAVING COUNT(*) >= 2
ORDER BY freq DESC, MAX(m.eaten_at) DESC
LIMIT 10;
```

**Индексы:**
```sql
CREATE INDEX idx_meals_user_type_eaten
  ON meals(user_id, meal_type, eaten_at DESC);
CREATE INDEX idx_meal_items_meal_name
  ON meal_items(meal_id, food_name);
```

**API:**
```
GET /api/foods/quick?meal_type=breakfast
→ { "recent": [...], "frequent": [...] }
```

**Бот UX:**
- `/add breakfast` → inline keyboard с топ-5 часто употребляемых + топ-3 недавних
- Один тап → INSERT без LLM
- Опционально: smart-предложения по времени суток (8 утра → автоматически предложить "Завтрак")

**Mini App UX:**
- Страница "Добавить" с табами: Часто / Недавно / Мои блюда / Поиск
- Chip-список для quick add

### F11. Smart meal type inference

**User story:** "Я пишу '200г творога' в 9 утра → бот автоматически предполагает что это завтрак"

**Реализация:**
```python
def infer_meal_type(now: datetime) -> str:
    hour = now.hour
    if 6 <= hour < 11: return "breakfast"
    if 11 <= hour < 16: return "lunch"
    if 16 <= hour < 22: return "dinner"
    return "snack"
```

- Используется как default в `confirm_node`
- Юзер всё равно может переключить кнопками
- В будущем — ML предсказание по истории конкретного юзера

### F12. Forward & batch parsing

**User stories:**
- "Я по ходу дня скидываю в Избранное Telegram заметки типа 'Рис 150', 'кофе с молоком', 'обед: 200г курицы и салат'. Хочу пересылать пачкой в бот и чтобы он сам разнёс по приёмам."
- "Диетолог / тренер / мама пишет мне 'на ужин: 200г лосося, 100г риса, овощи' — пересылаю в бот, бот логирует."
- "Друг считает за меня калории и присылает — я форвардю в бот."

**Реализация:**

1. **Forward handling** в `meal_handler`:
   ```python
   if update.message.forward_origin is not None:
       # Сохраняем оригинальный timestamp если есть — для backfill
       eaten_at = update.message.forward_date or datetime.now(UTC)
       source = InputSource.TEXT  # но логировать что это форвард в raw_input
   ```

2. **Batch parsing** — `text_parser_node` обрабатывает многострочный текст:
   ```
   Рис 150
   Кофе с молоком
   Куриная грудка 200
   ```
   → парсер возвращает массив items, каждый с КБЖУ. Если в строках видна разметка приёмов (`завтрак:`, `обед:`) — разбивает на несколько `Meal`.

3. **Bulk import из Saved Messages:**
   - Команда `/import` → юзер форвардит несколько сообщений подряд
   - Бот собирает все за 30 секунд таймаут → отправляет одной пачкой в graph
   - Подтверждение списком с inline кнопками "✅ Записать всё / ✏️ Править"

4. **Backfill дат:**
   - Если форвард — берём `forward_date` как `eaten_at`
   - Если в тексте упомянуто "вчера / сегодня утром / в обед" — парсим LLM-ом
   - Иначе — текущее время + smart meal_type inference (F11)

**Зачем это важно:**
Это **главный workflow** который ломается в FatSecret. Юзер быстро записывает себе на ходу, потом не возвращается к ручному вводу — и пропускает записи. NutriSnap превращает "заметку себе" в готовую запись приёма пищи за один форвард.

---

## Граф (обновлённый)

```
input_router
  ├─ photo
  │    ├─ barcode_detector_node  (pyzbar)
  │    │    ├─ found → off_lookup_by_barcode → nutrition_fetch
  │    │    └─ not found → vision_node
  │    └─ vision_node (GPT-4o с расширенным промптом)
  │         └─ если в выводе есть barcode → cross-check с OFF
  │
  ├─ voice → stt → text_parser
  └─ text  → text_parser

text_parser → nutrition_fetch
nutrition_fetch:
  → asyncio.gather(
      pg_cache.search(name),
      qdrant_search(name),
      off_text_search(name),
    )
  → если ничего → fatsecret (translate to EN)
  → если и это пусто → gpt_estimate(name)
```

---

## Список задач для реализации

- [ ] **F1** Добавить `barcode_detector_node` в LangGraph + `pyzbar` в зависимости
- [ ] **F2** Сервис `app/services/openfoodfacts.py` с двумя методами: `lookup_by_barcode`, `text_search`
- [ ] **F3** Миграция Alembic: добавить `brand`, `barcode`, индексы
- [ ] **F4** Обновить промпт `vision_node` для чтения этикеток + Pydantic schema с полями brand/barcode
- [ ] **F5** Добавить tool `lookup_by_barcode` в MCP-сервер
- [ ] **F6** Seed-скрипт `scripts/seed_curated_foods.py` с кураторской базой региональных блюд СНГ (KZ/RU/UZ/GE...), tag по `cuisine`
- [ ] **F7** UGC: API + Mini App страница "Мои блюда"
- [ ] **F8** Обновить `nutrition_fetch` с цепочкой приоритетов (local → qdrant → OFF → FatSecret → GPT estimate)
- [ ] **F9** Кэш upsert: каждый успешный внешний lookup сохраняется в `foods` с alias'ами
- [ ] **F10** Quick add: API + бот inline keyboard с recent/frequent per meal_type
- [ ] **F11** Smart meal type inference по времени суток в `confirm_node`
- [ ] **F12** Forward & batch parsing — обрабатывать пересланные сообщения (от друзей/диетологов) и многострочные заметки ("рис 150\nкурица 200")

---

## Внешние сервисы — ключи

| Сервис | Нужен ключ? | Whitelist IP? | Бесплатно? |
|---|---|---|---|
| Open Food Facts | ❌ нет | ❌ нет | ✅ да |
| FatSecret | ✅ Client ID + Secret | ✅ нужен (запасной источник) | ✅ Basic free |
| OpenAI (Vision/GPT) | ✅ | ❌ | ❌ |

---

## Решённые на защите вопросы

- **Q: Почему не основной источник FatSecret?**
  A: Whitelist IP несовместим с динамическим IP Railway без $5/мес add-on. Plus русский язык только в Premier тарифе ($250/мес). FatSecret оставлен как fallback для редких западных продуктов.

- **Q: Как обрабатываются казахские блюда?**
  A: Ручная локальная база ~200 KZ блюд (бешбармак, манты, и т.д.) seed'ится при первом запуске. Этого нет ни в FatSecret, ни в OFF.

- **Q: Зачем Open Food Facts, если есть FatSecret?**
  A: OFF — это база со штрих-кодами упакованных товаров, включая President в КЗ. У FatSecret фокус на ресторанной/готовой еде, нет barcode lookup в Basic тарифе.
