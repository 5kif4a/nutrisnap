# База данных — конкурентность и race conditions

## Контекст

Bot и API — это два процесса, подключённых к одной PostgreSQL. Реальные конфликты не "bot vs api", а "две конкурентные записи в одну строку". Нужно решить какой уровень изоляции использовать и где ставить точечные блокировки.

---

## Где возможны race conditions

| Сценарий | Где | Серьёзность |
|---|---|---|
| Юзер жмёт "Подтвердить" дважды → 2 одинаковых meal | Bot | средняя |
| Bot пишет meal, юзер в Mini App тут же редактирует | Bot + API | низкая (редко) |
| `/start` отправлен дважды быстро → 2 users с одним telegram_id | Bot | низкая (UNIQUE спасёт) |
| Параллельные lookup одного продукта → INSERT-INSERT в `foods` | Bot / RAG | средняя |
| Пересчёт `total_kcal` на meal после редактирования item | API | высокая (lost update) |

---

## Решение: READ COMMITTED + правильная схема

**Не повышаем уровень изоляции глобально.** READ COMMITTED (дефолт PostgreSQL) — правильный выбор. Проблемы решаются на уровне схемы и точечного локинга, не глобальным SERIALIZABLE.

REPEATABLE READ / SERIALIZABLE дают serialization failures (`could not serialize access due to concurrent update`) которые надо ретраить — лишний код без выигрыша для такого продукта.

---

## 1. Не храним производные данные

Самый частый источник lost update — это `meals.total_kcal`, который надо пересчитывать после изменения `meal_items`. Решение: **не хранить его вообще.**

```sql
-- ❌ Плохо: денормализация → нужен пересчёт → race
CREATE TABLE meals (
  id UUID PRIMARY KEY,
  total_kcal FLOAT,   -- DROP this
  ...
);

-- ✅ Хорошо: считаем на чтение
SELECT
  m.id,
  COALESCE(SUM(mi.kcal), 0) AS total_kcal
FROM meals m
LEFT JOIN meal_items mi ON mi.meal_id = m.id
WHERE m.user_id = $1 AND DATE(m.eaten_at) = $2
GROUP BY m.id;
```

Для NutriSnap с низким трафиком aggregate на read — 1-2ms. Никаких lost updates.

**Применить к схеме `meals`:** убрать поля `total_kcal`, `total_protein_g`, `total_fat_g`, `total_carbs_g`. Считать через SUM по `meal_items` в сервисном слое.

---

## 2. UNIQUE + ON CONFLICT для идемпотентности

```sql
-- users — UNIQUE на telegram_id
CREATE UNIQUE INDEX idx_users_telegram_id ON users(telegram_id);

-- foods cache — UNIQUE на нормализованное имя
CREATE UNIQUE INDEX idx_foods_normalized_name ON foods(LOWER(name));

-- meals — idempotency по telegram update_id
ALTER TABLE meals ADD COLUMN tg_message_id BIGINT;
CREATE UNIQUE INDEX idx_meals_tg_msg ON meals(user_id, tg_message_id)
  WHERE tg_message_id IS NOT NULL;
```

Использование в SQLAlchemy:
```python
from sqlalchemy.dialects.postgresql import insert

# Upsert food cache
stmt = (
    insert(Food)
    .values(name="куриная грудка", kcal_per_100g=165, ...)
    .on_conflict_do_nothing(index_elements=["name"])
)
await session.execute(stmt)
```

---

## 3. SELECT FOR UPDATE для точечного локинга

Только там где две стороны реально конкурентно меняют одну строку (например юзер редактирует meal_item из Mini App):

```python
async def update_meal_item(session, item_id, new_weight_g):
    item = await session.scalar(
        select(MealItem)
        .where(MealItem.id == item_id)
        .with_for_update()   # ← блокировка только этой строки
    )
    item.weight_g = new_weight_g
    item.kcal = item.kcal_per_g * new_weight_g
    await session.commit()
```

`FOR UPDATE` блокирует **только эту строку** в **этой транзакции**. Никаких глобальных локов, никаких serialization failures.

---

## 4. Idempotency-key для бота

PTB даёт `update.update_id` — уникальный per update. Используем для дедупликации повторных webhook-вызовов и спама "Add" кнопкой:

```python
async def on_photo(update, context):
    update_id = update.update_id

    stmt = insert(Meal).values(
        user_id=user.id,
        tg_message_id=update_id,
        ...
    ).on_conflict_do_nothing(index_elements=["user_id", "tg_message_id"])
    result = await session.execute(stmt)

    if result.rowcount == 0:
        return  # duplicate update — тихо игнорируем
```

---

## 5. Транзакционные границы

Одна логическая операция = одна транзакция. Не растягивай транзакцию через ожидание LLM/HTTP — это держит соединение пула слишком долго.

```python
# ❌ Плохо: транзакция держится во время LLM-вызова
async with session.begin():
    meal = await session.get(Meal, meal_id)
    nutrition = await openai_vision(photo)   # 3-5 секунд!
    meal.items = [...]

# ✅ Хорошо: LLM снаружи, БД-операции — короткая транзакция
nutrition = await openai_vision(photo)   # вне транзакции
async with session.begin():
    meal = await session.get(Meal, meal_id, with_for_update=True)
    meal.items = nutrition_to_items(nutrition)
```

---

## Итого — таблица решений

| Что | Уровень / приём |
|---|---|
| Дефолт всех транзакций | **READ COMMITTED** (не трогаем) |
| Upsert users / foods | UNIQUE + `ON CONFLICT` |
| Дедуп сообщений бота | UNIQUE по `(user_id, tg_message_id)` |
| Редактирование item из Mini App | `SELECT ... FOR UPDATE` |
| Тотал калорий на день | aggregate на чтение, не хранить |
| LLM/HTTP вызов | **вне** транзакции |

---

## Когда повышать уровень

Если в будущем появится сложная транзакция с несколькими взаимозависимыми UPDATE (например "перенести 100 ккал из обеда в ужин"), тогда можно для конкретно этой транзакции:

```python
async with session.begin():
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    # ... сложная логика
```

Но это исключение, не правило. На этапе MVP такого нет.

---

## Дополнительно: connection pool

Bot и API — это **два процесса**, каждый со своим pool. Размер pool на каждый процесс:

```python
# app/db/session.py
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=5,         # активных соединений
    max_overflow=10,     # пик
    pool_pre_ping=True,  # проверять перед использованием
    pool_recycle=3600,   # переподключаться раз в час
)
```

На Railway Postgres Hobby лимит ~100 соединений. С 2 процессами по 5+10 = max 30 — комфортный запас.
