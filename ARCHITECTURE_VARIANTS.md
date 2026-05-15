# NutriSnap — Два варианта архитектуры

---

## Вариант A: Агентная (LangGraph-first)

Весь флоу обработки сообщения идёт через LangGraph граф. Каждый шаг — нода. Агент сам решает что вызвать.

### Схема

```
PTB Handler
    │
    ▼
FastAPI POST /process
    │
    ▼
LangGraph Graph
    │
    ├─[START]─▶ input_router_node
    │               │ LLM классифицирует тип (photo/text/voice/irrelevant)
    │               │
    │         ┌─────┼─────┬──────────┐
    │         ▼     ▼     ▼          ▼
    │     vision  stt   text      guardrail
    │     _node   _node _parser   _node → END (отказ)
    │         │     │     │
    │         └──▶ nutrition_lookup_node
    │                   │ MCP search_food + RAG + FatSecret
    │                   ▼
    │             confirm_node
    │             │ ждёт human-in-the-loop callback
    │             │
    │         ┌───┴───┐
    │         ▼       ▼
    │      save     edit_node
    │      _node        │ LLM парсит правку юзера
    │         │         └──▶ nutrition_lookup_node (цикл)
    │         ▼
    │        END
    │
    └── MCP Nutrition Server (отдельный процесс)
         ├── search_food(name)
         ├── log_meal(...)
         └── get_daily_summary(...)
```

### Реализация нод

```python
# input_router_node — LLM классифицирует входящее сообщение
async def input_router_node(state: AgentState) -> AgentState:
    response = await llm.ainvoke([
        SystemMessage("Classify: photo / text / voice / irrelevant"),
        HumanMessage(state["raw_input"])
    ])
    state["input_type"] = response.content
    return state

# nutrition_lookup_node — агент сам вызывает MCP tools
async def nutrition_lookup_node(state: AgentState) -> AgentState:
    agent = create_react_agent(llm, tools=[search_food, log_meal])
    result = await agent.ainvoke({"messages": state["parsed_items"]})
    state["nutrition_data"] = result
    return state

# edit_node — LLM парсит что юзер поправил
async def edit_node(state: AgentState) -> AgentState:
    response = await llm.ainvoke(f"User edited: {state['edit_text']}")
    state["parsed_items"] = response.content
    return state
```

### Плюсы
- Граф наглядный, легко объяснить на защите
- human-in-the-loop встроен нативно через `interrupt()`
- Легко добавить новые ноды без переписывания
- LangSmith трейсит каждую ноду автоматически
- Требование курса закрывается полностью

### Минусы
- **Медленно:** input_router — лишний LLM вызов (~0.3-0.5с)
- **Непредсказуемо:** агент может не туда вызвать tool
- **Дорого:** каждое сообщение = 3-5 LLM вызовов
- Сложнее дебажить когда агент "думает не так"
- Latency на текстовый ввод: **~2-3 секунды**

### Примерная стоимость на сообщение
| Шаг | Модель | ~$cost |
|---|---|---|
| input_router | gpt-4o-mini | $0.0001 |
| text_parser | gpt-4o-mini | $0.0002 |
| nutrition_lookup agent | gpt-4o-mini | $0.0005 |
| **Итого (текст)** | | **~$0.0008** |
| vision_node | gpt-4o | $0.005 |
| **Итого (фото)** | | **~$0.006** |

---

## Вариант B: Прямой код (Thin LangGraph)

LangGraph используется как обёртка для соответствия требованиям курса, но внутри нод — прямые вызовы без агентного мышления. Роутинг, поиск, сохранение — чистый Python.

### Схема

```
PTB Handler
    │  message.photo? → "photo"
    │  message.voice? → "voice"     ← pure Python, no LLM
    │  message.text?  → "text"
    │
    ▼
FastAPI POST /process
    │
    ▼
LangGraph Graph (тонкая обёртка)
    │
    ├─[START]─▶ route_node
    │               │ if/elif по типу PTB message — NO LLM
    │               │
    │         ┌─────┼──────┐
    │         ▼     ▼      ▼
    │     vision   stt    text
    │     _node   _node   _parser_node
    │     GPT-4o  Whisper gpt-4o-mini structured output
    │         │     │      │
    │         └─────┴──────┘
    │                │
    │         nutrition_fetch_node
    │         │  asyncio.gather(
    │         │    fatsecret_api(name),     ← HTTP call
    │         │    qdrant_search(name),     ← vector search
    │         │    pg_cache_lookup(name)    ← SQL
    │         │  ) → merge → best match    NO LLM
    │                │
    │         confirm_node
    │         │  send inline keyboard → wait callback  NO LLM
    │                │
    │         ┌──────┴──────┐
    │         ▼             ▼
    │      save_node    adjust_node
    │      INSERT SQL   parse adjustment  ← gpt-4o-mini (только здесь)
    │         │         → back to fetch
    │         ▼
    │        END
    │
    └── MCP Nutrition Server
         ├── search_food   ← вызывается из nutrition_fetch_node
         ├── log_meal      ← вызывается из save_node
         └── get_daily_summary
```

### Реализация нод

```python
# route_node — чистый Python, 0 LLM вызовов
async def route_node(state: GraphState) -> GraphState:
    msg = state["telegram_message"]
    if msg.get("photo"):
        state["input_type"] = "photo"
    elif msg.get("voice"):
        state["input_type"] = "voice"
    elif msg.get("text"):
        text = msg["text"]
        # простая эвристика guardrail — ключевые слова еды
        state["input_type"] = "text" if is_food_related(text) else "irrelevant"
    return state

# nutrition_fetch_node — параллельный поиск без LLM
async def nutrition_fetch_node(state: GraphState) -> GraphState:
    items = state["parsed_items"]
    results = []
    for item in items:
        pg, fs, qdrant = await asyncio.gather(
            pg_cache.search(item["name"]),
            fatsecret.search(item["name"]),
            qdrant_client.search(item["name"])
        )
        best = pick_best(pg, fs, qdrant)   # просто score сравнение
        results.append({**best, "weight_g": item["weight_g"]})
    state["nutrition_data"] = results
    return state

# is_food_related — keyword guardrail, no LLM
FOOD_KEYWORDS = {"съел", "ел", "завтрак", "обед", "ужин", "калории",
                 "грамм", "кг", "мл", "порция", "блюдо", "перекус"}
def is_food_related(text: str) -> bool:
    return any(kw in text.lower() for kw in FOOD_KEYWORDS)
```

### Плюсы
- **Быстро:** текстовый ввод за ~0.5-0.8с
- **Дёшево:** 1 LLM вызов вместо 3-5
- Предсказуемо — код делает ровно то что написано
- Легко дебажить
- Guardrail через keywords — мгновенно

### Минусы
- Keyword guardrail не поймает "что у меня с белком?" (не содержит ключевых слов)
- Нужно вручную поддерживать FOOD_KEYWORDS
- На защите нужно объяснять почему граф "тонкий"

### Примерная стоимость на сообщение
| Шаг | Модель | ~$cost |
|---|---|---|
| text_parser | gpt-4o-mini | $0.0002 |
| **Итого (текст)** | | **~$0.0002** |
| vision_node | gpt-4o | $0.005 |
| **Итого (фото)** | | **~$0.005** |

---

## Сравнение

| Параметр | A: Агентная | B: Прямой код |
|---|---|---|
| Latency (текст) | ~2-3с | ~0.5-0.8с |
| Latency (фото) | ~5-7с | ~4-6с |
| Cost/msg (текст) | ~$0.0008 | ~$0.0002 |
| Cost/msg (фото) | ~$0.006 | ~$0.005 |
| Предсказуемость | средняя | высокая |
| Кол-во LLM вызовов | 3-5 | 1 (текст) / 1 (фото) |
| Соответствие требованиям курса | полное | полное* |
| Сложность реализации | высокая | средняя |
| Удобство для защиты | отличное | хорошее |

*LangGraph граф есть, ветвления есть, human-in-the-loop есть — требование выполнено.

---

## Рекомендация

**Использовать Вариант B** с одним исключением: оставить `input_router` как LLM-ноду если хочется показать на защите "умный роутинг". В остальном — прямой код.

**Гибридный подход:**
```
route_node          → Python if/elif (скорость)
vision_node         → GPT-4o (необходимо)
text_parser_node    → gpt-4o-mini structured output (необходимо)
stt_node            → Whisper API (необходимо)
nutrition_fetch     → asyncio.gather HTTP+SQL+Qdrant (скорость)
confirm_node        → PTB inline keyboard (скорость)
save_node           → SQL INSERT (скорость)
```

Единственные LLM вызовы: **vision / text_parser / stt** — то есть только там где без AI физически не обойтись.

---

## Guardrail детали (Вариант B)

```python
# Input guard — два уровня
def input_guard(message) -> GuardResult:
    # Уровень 1: быстрый keyword check (0ms)
    if is_food_related(message.text):
        return GuardResult.PASS
    # Уровень 2: если непонятно — gpt-4o-mini classifier (300ms)
    # Только для неоднозначных случаев
    return llm_classify(message.text)

# Output guard — range check (0ms)
def output_guard(nutrition: NutritionData) -> bool:
    return (
        0 < nutrition.kcal < 5000 and
        0 < nutrition.protein < 300 and
        0 < nutrition.fat < 200 and
        0 < nutrition.carbs < 500
    )
```
