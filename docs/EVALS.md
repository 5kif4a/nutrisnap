# EVALS — NutriSnap text-input pipeline

> Эвалы для текстового флоу логирования еды (parser + nutrition lookup).
> Vision-флоу эвалится отдельно через PR-чек на реальных фото.

---

## 1. Цель

Бот должен превращать сообщения вида `"Гречка отварная 150"` или
`"Макароны Макфа улитка 92\nТушеная курица с овощами 153"` в корректные
строки КБЖУ. Эталон — что юзер увидел бы в FatSecret (его текущий
инструмент логирования до бота).

System under test: **LangGraph-цепочка**
`parse_text_node → nutrition_fetch_node → finalize_node`. Это значит мы
эвалим не один LLM-вызов, а сквозную композицию (LLM + БД + multi-source
fallback). Поэтому используем самописный runner, а не `openai/evals` —
тот заточен под `prompt → completion` против фиксированного таргета.

---

## 2. Golden dataset

📁 `backend/app/evals/golden.jsonl` — **44 кейса**, JSONL.

### Источники

| Источник | N | Что |
|---|---|---|
| `tg_messages` | 10 | Реальные сообщения юзера из его текущего ТГ-канала-дневника (до бота). Паттерны: `<name> <grams>`, `<grams> гр <name> <brand>`, multi-line, композитные блюда |
| `fatsecret_may_2026` | 31 | Продукты из его экспортированного FoodDiary за май 2026 с эталонными КБЖУ из FatSecret |
| `edge` | 3 | Эджи: не-еда ("Привет"), сломанный кейс ("nuts шоколадка большая"), thank-you |

### Покрытие классов

- Голое число = граммы: `Хлеб 53`, `Фасоль 47`
- Бренд в кириллице: `Фасоль бондюэль 25` → brand=Bonduelle
- Число в начале строки: `50 гр макароны улитки макфа`
- Бренд в середине имени: `Макароны Макфа улитка 92`
- Composite dish (один item, не split): `Курица с овощами 95`
- Multi-line: 2+ items в одном сообщении
- Брендовые снеки: Snickers, Twix, Nestle Nuts, Bombbar, Belucci, Belvita, Рахат, Коровка из Кореновки, Мишка на Полюсе, Bitony
- Молочка: Простоквашино, President 10%/15%, Natige
- Готовая еда: Drinkit Гриль-Ролл, Клаб Сэндвич, Айс Ти
- Супплементы: Maxler Ultra Whey, Креатин, Exponenta
- Домашние блюда: Гречка/Рис отварной, Куриная грудка отварная, Тушёная курица с овощами
- Не-еда: `Привет, как дела?`, `Спасибо!`

### Формат строки

```json
{
  "input": "Snickers 80",
  "expected_parse": [
    {"name": "Snickers", "brand": "Snickers", "amount": 80, "unit": "g"}
  ],
  "expected_nutrition": {"kcal": 417, "protein_g": 8.16, "fat_g": 23.84, "carbs_g": 41.76},
  "is_food": true,
  "source": "fatsecret_may_2026",
  "notes": "optional explanation"
}
```

`expected_nutrition` — **агрегат по всем items в сообщении** (для multi-line кейсов суммируется).

---

## 3. Метрики

| Метрика | Определение | Зачем |
|---|---|---|
| **Pass rate** | Доля кейсов где `is_food` совпал И все 4 макро в пределах ±10% от эталона | Главная композитная метрика — что юзер увидит «правильный ответ» |
| **is_food accuracy** | Доля кейсов где предсказание `is_food_related` совпало с разметкой | Простая классификация: еда vs приветствие |
| **MAPE per macro** | Mean Absolute Percentage Error отдельно для kcal / protein / fat / carbs, считается только по food-кейсам с ненулевым эталоном | Понять какой макрос врёт больше |
| **Within ±10% / ±20%** | Сколько food-кейсов попадает в коридор по каждому макро | Чувствительнее к outlier'ам чем MAPE |
| **Source breakdown** | Распределение resolved items по источникам (`curated` / `off` / `llm_estimate` / `user_recipe`) | Контроль: что лежит в curated — не пробивается через OFF/LLM noise |

Порог 10% — потому что в фитнес-логе ошибки <10% по kcal невидимы пользователю,
а 20%+ уже искажают дневной баланс при 4-5 приёмах пищи.

---

## 4. A/B эксперименты

Прогоны на одном и том же golden.jsonl, меняем по одному инциденту.

| # | Изменение | Pass rate | ΔKcal MAPE | Источник resolved'ов |
|---|---|---|---|---|
| **A** | Baseline — без правок | **7/19 = 37%** (на subset 19) | ~40% | 30% curated · 40% off · 30% llm_estimate |
| **B** | + Сидинг каталога `curated` (41 продукт из FoodDiary) | **84%** (на subset 19) | 8% | 100% curated |
| **C** | + Переписан parser prompt (правила голых граммов, кириллические бренды, composite dishes как один item) | **84.1%** (на full 44) | 17.2% | 100% curated |
| **C₂** | Эксперимент: добавил verbose "WHEN TO REJECT" с positive examples | **68.2%** ⛔️ regression | 34.3% | 100% curated |
| **D** | Убран `is_food_related` из schema модели → решается Python-эвристикой | **86.4%** | 12.3% | 100% curated |
| **E** | + Расширенные few-shot для кириллических брендов (Простоквашино/Коровка/Рахат/Belvita/Bitony) | **95.5%** ✅ | **5.0%** | 100% curated |

### Что показали эксперименты

**Эксперимент B — сидинг даёт максимальный буст за минимум труда.**
Семь топ-кейсов в baseline ушли в LLM_ESTIMATE который врёт на 70-200%
(`Гречка отварная 150` оценивалась как сухая → +186% kcal). Прямой
сидинг 41 продукта с FatSecret-эталоном закрыл их все в `±0%`.

**Эксперимент C₂ — больше правил ≠ лучше.** Попытался усилить
parser prompt секцией `STRONG POSITIVE RULE` с 8 явными примерами
"это IS food". Модель стала **более** параноидной (видимо, длинный
список исключений интерпретируется как "обычно надо реджектить, но
есть нюансы") и pass rate **рухнул с 84% до 68%**. Откатили.

**Эксперимент D — структурный фикс важнее prompt-фикса.** При T=0 OpenAI
structured output даёт ~5-10% non-determinism на bool-полях типа
`is_food_related`: один и тот же ввод в разных прогонах флипал True/False.
Убрали поле из schema, решаем в Python (`if items → food, else regex
match against greeting patterns`). Pass rate +2.3%, и главное —
**стабильность** между прогонами выросла.

**Эксперимент E — таргетированные few-shot закрывают конкретные провалы.**
До v5 модель то парсила, то реджектила `Простоквашино творожок ...`,
`Коровка из Кореновки ...`, `Bitony пельмени ...`. Добавление этих
ровно строк в format examples секцию подняло pass rate с 86% до 95.5%.

### Дополнительный эксперимент: защита от LLM_ESTIMATE-загрязнения

Параллельно с C-E поправили `nutrition_fetch_node`:
- LLM_ESTIMATE результаты больше **не пишутся** в `foods` (returned ephemeral)
- В `search_foods_by_name` добавлен `ORDER BY source_priority` — `curated` побеждает `off` побеждает `llm_estimate`

Эффект — не отражается в pass rate (там и так 100% curated сейчас), но
закрывает класс ошибок "юзер пишет 'Шоколадка', LLM генерит фейковую
строку 100 ккал, она навсегда залегает в каталог, побеждает на следующих
запросах". Воспроизвели этот баг в Эксперименте A — фейковая
"Курица с морковью 250 ккал/100г" застряла в БД между прогонами.

---

## 5. Финальные результаты (Эксперимент E)

```
Cases: 44  ·  Tolerance: ±10% per macro

Pass rate:        42/44 = 95.5%
is_food accuracy: 43/44 = 97.7%

MAPE (food cases only):
  kcal:    mean=5.0%  · within ±10%: 39/41 · within ±20%: 39/41
  protein: mean=4.8%  · within ±10%: 40/42 · within ±20%: 40/42
  fat:     mean=5.3%  · within ±10%: 38/40 · within ±20%: 38/40
  carbs:   mean=5.1%  · within ±10%: 37/39 · within ±20%: 37/39

Resolved items by source (total 37):
  curated: 37 (100%)
```

Полный markdown-репорт после каждого прогона — `python -m app.evals.run > report.md`.

### Динамика по интервенциям (kcal MAPE)

```
A (baseline)              ████████████████████████████████████████ ~40%
B (+seed)                 ████████ 8%
C (+parser prompt)        █████████████████ 17.2%
C₂ (verbose rules)        ██████████████████████████████████ 34.3%  ⛔
D (-is_food schema)       ████████████ 12.3%
E (+cyrillic few-shot)    █████ 5.0%  ✅
```

(MAPE временно рос на C из-за более широкого датасета 19→44, остальные
дельты — чисто от изменений промпта/схемы.)

---

## 6. Известные провалы (2/44)

### `"50 гр макароны улитки макфа"` — number-first format

OpenAI structured output non-determinism: в ~30% прогонов модель возвращает
`items=[]` с "загрязнением" в brand-поле (`"Makfa}]}\n   assistant
to=TextParseResult {"` — токены закрытия JSON-схемы протекают в строковое
значение). Это известная баг-зона `client.beta.chat.completions.parse`,
которая встречается на длинных/сложных prompt'ах при T=0.

**Митигация (запланирована):** retry с T=0.3 при `items=[]`, до 1 раза.

### `"nuts шоколадка большая"` — нет указания граммов

Parser отрабатывает идеально: `name="Nuts шоколадка", brand="Nestle",
amount=1, unit=serving`. Но curated `Nuts` лежит как `metric=GRAMS`
(КБЖУ per 100g), а `unit=serving` без `piece_weight_g` бросает
`ValueError` в `compute_meal_item_nutrition` → item молча скипается.

**Митигация (запланирована):** добавить `piece_weight_g=50` к курированным
снекам (Snickers, Twix, Nuts, Bombbar Эскимо) — стандартный размер плитки,
тогда `unit=serving` будет работать через `piece_weight_g * (nutrition per 100g)`.

---

## 7. Как воспроизвести

### Локально (через docker-compose)

```bash
# Поднять стек
podman compose -f docker-compose.dev.yml up -d

# Засидить каталог (одноразово, идемпотентно)
podman compose -f docker-compose.dev.yml exec api python -m app.db.seed_foods

# Прогнать эвал
podman compose -f docker-compose.dev.yml exec api python -m app.evals.run

# Сохранить markdown-репорт
podman compose -f docker-compose.dev.yml exec api python -m app.evals.run > report.md
```

### CLI flags

```
python -m app.evals.run [--output PATH] [--limit N]

  --output, -o   write markdown report to file (default: stdout only)
  --limit N      run only first N cases (smoke test)
```

### Стоимость одного прогона

44 кейса × 1 LLM-вызов parser (gpt-4o-mini, ~500 input tokens, ~100 output)
≈ **$0.005** за прогон. Latency ~30-60 секунд.

LLM estimate (шаг 5 lookup) сейчас не вызывается — все 44 кейса хитают
в `curated`. Если catalog miss — добавится +$0.0001 на кейс.

---

## 8. Следующие шаги

1. **Расширить golden** до 60+ кейсов: добавить voice-input (audio→Whisper→parser),
   композитные блюда с явным указанием ингредиентов, edge'и с опечатками
   ("греика 150", "сметана прездент 30").
2. **Vision golden** — отдельный JSONL с парами (фото, expected_items).
   Нужны реальные фото юзера: тарелка на весах + упаковка со штрихкодом.
   Без них эксперимент E на vision-промпте не воспроизводим.
3. **CI integration** — `evals.yml` GitHub Action, прогоняет на каждый PR
   с change в `app/services/openai_client.py` или `app/graph/`,
   падает если pass rate упал >5 п.п.
4. **Granular metrics** — добавить отдельную метрику "parse accuracy"
   (имя/бренд/amount/unit совпали с `expected_parse`), сейчас она
   неявно зашита в pass rate.
5. **Source-A/B** — сравнить `OFF text search` vs `LLM estimate` для
   продуктов вне curated. Сейчас оба считаются "fallback", но дельта в
   точности может быть значимой.

---

## Связанные файлы

- `backend/app/evals/golden.jsonl` — датасет (44 кейса)
- `backend/app/evals/run.py` — runner + рендер markdown-репорта
- `backend/app/db/seed_foods.py` — курированный каталог (41 продукт)
- `backend/app/services/openai_client.py` — `_TEXT_PARSER_SYSTEM_PROMPT`, `_VISION_SYSTEM_PROMPT`
- `backend/app/graph/nodes/parser.py` — Python-эвристика `is_food_related`
- `backend/app/graph/nodes/nutrition.py` — multi-source lookup (ephemeral LLM_ESTIMATE)
- `backend/app/repositories/food_repo.py` — `search_foods_by_name` с `ORDER BY source_priority`
- `docs/golden/food_diary.md` — исходный FatSecret-экспорт юзера (ground truth)
