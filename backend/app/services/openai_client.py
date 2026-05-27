"""OpenAI integration — vision / text parser / Whisper transcription.

All public callables are wrapped with @traceable so LangSmith records the
prompt, response, tokens and latency without manual instrumentation.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from langsmith import traceable
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.core.config import settings
from app.db.models import FoodMetric


# ─── Output schemas (structured-output contract with the LLM) ────────────────


class ParsedFoodItem(BaseModel):
    """A single food/dish recognized from photo/text/voice."""

    name: str = Field(description="Canonical food name in Russian if applicable")
    amount: float = Field(
        description="Quantity user has (200 for grams, 1 for piece, etc.)", gt=0
    )
    unit: FoodMetric = Field(description="Unit of `amount`: g / ml / piece / serving")
    brand: str | None = Field(
        default=None, description="Brand if visible (e.g. 'President')"
    )
    barcode: str | None = Field(
        default=None, description="EAN/UPC barcode if visible on packaging"
    )
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class PhotoMealResult(BaseModel):
    """Output of analyze_photo_meal — list of items detected on the plate."""

    items: list[ParsedFoodItem]
    overall_description: str = Field(
        default="",
        description="Short human description of what's on the plate (1 sentence)",
    )


class TextParseResult(BaseModel):
    """Output of parse_text_meal — items parsed from free-form text.

    `is_food_related` is NOT in the schema on purpose. We saw the model
    flip-flop on it across identical T=0 requests, sometimes returning
    `is_food_related=False, items=[]` for clear branded foods like
    "Простоквашино творожок 110". Force the model to commit to items
    only — the caller decides food-vs-not from len(items) + a Python
    heuristic on the input text.
    """

    items: list[ParsedFoodItem]


# ─── OpenAI client ───────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


# ─── Prompts ─────────────────────────────────────────────────────────────────

_VISION_SYSTEM_PROMPT = """\
You are NutriSnap's nutrition vision analyzer. Identify every food / dish / drink
on the photo and estimate the portion size.

══════════════════════════════════════════════════════════════════════════════
PRIORITY ORDER — read these signals in order; STOP at first hit per item
══════════════════════════════════════════════════════════════════════════════

1. **KITCHEN SCALE DISPLAY** (highest priority for amount)
   If a digital scale shows a weight reading anywhere in the photo:
     - READ the digits exactly from the LCD/LED display
     - Most scales show grams; if 'oz' / 'ml' / 'lb' is visible on the screen,
       use that unit and convert mentally (1 oz ≈ 28g, 1 lb ≈ 454g)
     - Use that number as `amount`, with `unit=g` (or `ml` for liquids)
     - This OVERRIDES visual estimation completely. `confidence` ≥ 0.95
     - Watch for digit ambiguity: 8↔0, 5↔6, 3↔8 — re-check segments
     - Decimal separator is usually a dot or comma — both mean fraction of gram
     - If TWO scales are visible (e.g., user weighed two ingredients separately),
       associate each weight with the food on that scale; create separate items
   - If the dish is on the scale and contains ingredients you can identify,
     STILL use the scale weight as the total dish amount (do NOT split among
     visible ingredients unless the user clearly weighed each one separately)

2. **BARCODE on packaging**
   If any barcode (EAN-13, EAN-8, UPC-A) is visible on a package:
     - READ ALL barcode digits and put them in the `barcode` field exactly
     - This lets the backend pull exact nutrition from Open Food Facts —
       far more reliable than guessing KBJU visually
     - Also extract `brand` from the package label
     - Estimate `amount` from the package size if no scale is shown
       (e.g., "Простоквашино Творожок 110г" → amount=110, unit=g)

3. **PACKAGING LABEL — brand and product name**
   Even without a barcode, if you can read brand + product name from the
   package, populate `brand` and `name`. Common Russian brands you may see:
   Простоквашино, Натиже, Коровка из Кореновки, Мишка на Полюсе, Рахат,
   Bonduelle, Makfa, President, Snickers, Twix, Nestle Nuts, Bombbar, Bootybar,
   Maxler, Exponenta, Drinkit.

4. **VISUAL PORTION ESTIMATION** (last resort, only when nothing above works)
   Use plate size (assume standard 25cm dinner plate), utensils, hand size as
   reference. Confidence here should be ≤ 0.7.
     - solid foods: `unit=g`
     - liquids: `unit=ml`
     - countable items (egg, banana, slice): `unit=piece`, `amount=N`
     - ready meals where weight is hard to estimate: `unit=serving`

══════════════════════════════════════════════════════════════════════════════
NAMING & OUTPUT RULES
══════════════════════════════════════════════════════════════════════════════

- Use Russian names for generic food ("куриная грудка", "гречка отварная",
  "рис отварной"). Do NOT translate brand names — keep "Snickers", "Bonduelle".
- For composite dishes (плов, борщ, тушёная курица с овощами) keep the dish
  as ONE item with the total scale weight; do not split into ingredients
  unless they were weighed separately.
- `brand` field: only populate if a brand is actually visible on packaging.
  Do not invent a brand from generic food appearance.
- Output ONLY the structured result, no chit-chat.
"""

_TEXT_PARSER_SYSTEM_PROMPT = """\
You parse short Telegram messages describing what the user ate into a structured
list of food items. The user is a fitness-tracking adult who logs meals in
Russian. They mostly weigh food in grams.

──────────────────────────────────────────────────────────────────────────────
CORE RULES — apply in this order
──────────────────────────────────────────────────────────────────────────────

1. UNIT DEFAULT = GRAMS
   Any bare number in a line is grams. Do NOT use `serving` or `piece` unless
   the user explicitly typed "порция", "шт.", "штука", "стакан", "бутылка".
   Implicit "г" / "гр" / "грамм" is the default.

   Number can appear at the START or END of the line — either is grams.

2. ONE LINE = ONE ITEM (compound dishes stay whole)
   "Курица с овощами 95"           → ONE item: name="Курица с овощами", amount=95g
   "Тушеная курица с овощами 153"  → ONE item, NOT 3 items
   "Курица с морковью 110"         → ONE item, NOT курица+морковь split

   Only split when items are clearly separated by commas with their own weights
   OR explicit conjunctions like "и" between weighed items:
   "200г курицы и 150г гречки"     → 2 items
   "рис 150, курица 200, фасоль 50"→ 3 items
   "обед: рис 150, курица 200"     → 2 items (drop "обед:" prefix)

3. MULTI-LINE = MULTIPLE ITEMS (one per line)
   "Макароны Макфа улитка 92\\nТушеная курица с овощами 153"
   → 2 items, both unit=g, line 2 stays as ONE composite dish.

4. BRAND EXTRACTION (always to a separate `brand` field)
   Brands can appear anywhere in the line and in any case (lowercase too).
   Always normalize to the canonical Latin form. Common aliases the user uses:

     бондюэль / Бондюэль   → "Bonduelle"
     макфа   / Макфа       → "Makfa"
     снайкерс / сникерс     → "Snickers"
     твикс                  → "Twix"
     натс / nuts            → "Nestle" (brand=Nestle, name should include "Nuts")
     максл / макслер / maxler → "Maxler"
     президент / president  → "President"
     натиже / natige        → "Natige"
     простоквашино          → "Простоквашино"
     драгкит / drinkit       → "Drinkit"
     рахат                  → "Рахат"
     белуччи / belucci      → "Belucci"
     белвита / belvita      → "Belvita"
     bombbar / бомбар       → "Bombbar"
     bootybar / бутибар     → "Bootybar"
     mishka на полюсе / мишка на полюсе → "Мишка на Полюсе"
     коровка из кореновки   → "Коровка из Кореновки"
     bitony / битони        → "Bitony"
     ehrmann / эрманн       → "Ehrmann"
     exponenta / экспонента → "Exponenta"
     bonduelle              → "Bonduelle"

   Brand goes into `brand`. `name` is the product type WITHOUT the brand word:
   "Фасоль бондюэль 25"       → name="Фасоль", brand="Bonduelle", amount=25, unit=g
   "Макароны Макфа улитка 92" → name="Макароны улитка", brand="Makfa", amount=92, unit=g
   "50 гр макароны улитки макфа" → name="Макароны улитки", brand="Makfa", amount=50, unit=g
   "Сметана President 10% 30" → name="Сметана 10%", brand="President", amount=30, unit=g
   "Snickers 80"              → name="Snickers", brand="Snickers", amount=80, unit=g
   "Nestle Nuts 66"           → name="Nuts", brand="Nestle", amount=66, unit=g
   "Maxler Ultra Whey 30"     → name="Ultra Whey", brand="Maxler", amount=30, unit=g

5. SUPPLEMENTS AND PROTEIN BARS ARE FOOD
   Protein powders (whey, casein), creatine, mass gainers, protein bars,
   meal-replacement drinks, energy bars — ALL count as food.
   "Maxler Ultra Whey 30"  → is_food_related=TRUE, parse normally
   "Креатин 5"             → is_food_related=TRUE
   "Bombbar эскимо 70"     → is_food_related=TRUE
   "Bootybar 60"           → is_food_related=TRUE

6. PIECE / SERVING ONLY WHEN EXPLICIT
   Use unit=piece only when user explicitly counts items: "съел 2 яйца",
   "1 банан", "три ломтика хлеба".
   Use unit=serving only for prepared food with a portion word: "порция плова",
   "1 порция супа".
   "стакан молока"   → amount=250, unit=ml
   "бутылка колы"    → amount=500, unit=ml

   NEVER default to piece/serving when a number is present — that number is grams.

7. AMBIGUOUS / DESCRIPTIVE WORDS — do not invent splits
   "большая", "маленькая", "целая" → adjectives, keep with the name, don't create extra items.
   "nuts шоколадка большая" → 1 item: name="Nuts шоколадка", brand="Nestle",
                              amount=1, unit=serving (no number given;
                              fallback to 1 serving is OK ONLY when no number exists).

8. is_food_related — DEFAULT TRUE
   Set is_food_related=TRUE for ANY message that contains food, drinks, or
   supplements (even a single word like "хлеб" is food). The schema default
   is TRUE — only set it to FALSE for pure greetings/help-requests that
   contain NO food or brand words:
     "Привет"  /  "Спасибо"  /  "Что умеешь?"  /  "/start"
   When in doubt, set is_food_related=TRUE and parse what you can.

──────────────────────────────────────────────────────────────────────────────
FORMAT EXAMPLES (canonical)
──────────────────────────────────────────────────────────────────────────────
Input → Output

"Хлеб 53"
  → [{name:"Хлеб", amount:53, unit:g}]

"Курица с овощами 95"
  → [{name:"Курица с овощами", amount:95, unit:g}]

"Тушеная курица с овощами 153"
  → [{name:"Тушеная курица с овощами", amount:153, unit:g}]

"Курица с морковью 110"
  → [{name:"Курица с морковью", amount:110, unit:g}]

"Фасоль бондюэль 25"
  → [{name:"Фасоль", brand:"Bonduelle", amount:25, unit:g}]

"50 гр макароны улитки макфа"
  → [{name:"Макароны улитки", brand:"Makfa", amount:50, unit:g}]

"Макароны Макфа улитка 92\\nТушеная курица с овощами 153"
  → [
      {name:"Макароны улитка", brand:"Makfa", amount:92, unit:g},
      {name:"Тушеная курица с овощами", amount:153, unit:g}
    ]

"Snickers 80"  → [{name:"Snickers", brand:"Snickers", amount:80, unit:g}]
"Nestle Nuts 66" → [{name:"Nuts", brand:"Nestle", amount:66, unit:g}]
"Maxler Ultra Whey 30" → [{name:"Ultra Whey", brand:"Maxler", amount:30, unit:g}]
"Сметана President 10% 30" → [{name:"Сметана 10%", brand:"President", amount:30, unit:g}]
"Bombbar эскимо 70" → [{name:"Эскимо", brand:"Bombbar", amount:70, unit:g}]
"Гречка отварная 150" → [{name:"Гречка отварная", amount:150, unit:g}]

"Простоквашино творожок вишня-банан 110"
  → [{name:"Творожок вишня-банан", brand:"Простоквашино", amount:110, unit:g}]
"Коровка из Кореновки мороженое лакомка 100"
  → [{name:"Мороженое лакомка", brand:"Коровка из Кореновки", amount:100, unit:g}]
"Рахат зефир бело-розовый 40"
  → [{name:"Зефир бело-розовый", brand:"Рахат", amount:40, unit:g}]
"Belvita печенье какао 46"
  → [{name:"Печенье какао", brand:"Belvita", amount:46, unit:g}]
"Bitony пельмени говяжьи 170"
  → [{name:"Пельмени говяжьи", brand:"Bitony", amount:170, unit:g}]
"Bonduelle кукуруза сладкая 90"
  → [{name:"Кукуруза сладкая", brand:"Bonduelle", amount:90, unit:g}]
"Drinkit гриль-ролл 190"
  → [{name:"Гриль-ролл", brand:"Drinkit", amount:190, unit:g}]
"Кефир натиже 2,5% 350"
  → [{name:"Кефир 2,5%", brand:"Natige", amount:350, unit:g}]
"Креатин 5"
  → [{name:"Креатин", amount:5, unit:g}]

"200г куриной грудки и 150г гречки"
  → [{name:"Куриная грудка", amount:200, unit:g}, {name:"Гречка", amount:150, unit:g}]

"стакан молока" → [{name:"Молоко", amount:250, unit:ml}]
"съел два яйца" → [{name:"Яйцо", amount:2, unit:piece}]
"1 порция плова" → [{name:"Плов", amount:1, unit:serving}]

"Привет, как дела?" → is_food_related:FALSE, items:[]
"""


# ─── Public callables ────────────────────────────────────────────────────────


@traceable(name="analyze_photo_meal", run_type="llm")
async def analyze_photo_meal(
    images: bytes | list[bytes],
    *,
    caption: str | None = None,
) -> PhotoMealResult:
    """Detect food items on one or more photos.

    Accepts either a single bytes object or a list (Telegram album). All
    images are sent in one Vision call so the model can de-duplicate items
    across angles / additional photos.
    """
    client = get_openai_client()
    if isinstance(images, (bytes, bytearray)):
        images_list = [bytes(images)]
    else:
        images_list = list(images)

    user_content: list[dict] = []
    for img in images_list:
        img_b64 = base64.b64encode(img).decode()
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
            }
        )
    if caption:
        user_content.append(
            {"type": "text", "text": f"Подсказка от пользователя: {caption}"}
        )
    if len(images_list) > 1:
        user_content.append(
            {
                "type": "text",
                "text": (
                    f"На фото пользователя {len(images_list)} кадра/ракурса — "
                    "может быть один объект с разных сторон или разные блюда/ингредиенты. "
                    "Объединяй одинаковые объекты в один item."
                ),
            }
        )

    response = await client.beta.chat.completions.parse(
        model=settings.VISION_MODEL,
        temperature=0.1,
        max_tokens=800,
        response_format=PhotoMealResult,
        messages=[
            {"role": "system", "content": _VISION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        return PhotoMealResult(items=[], overall_description="(could not parse image)")
    return parsed


@traceable(name="parse_text_meal", run_type="llm")
async def parse_text_meal(text: str) -> TextParseResult:
    """Parse free-form user text into structured food items."""
    client = get_openai_client()
    response = await client.beta.chat.completions.parse(
        model=settings.TEXT_MODEL,
        temperature=0.0,
        # 500 was too tight for multi-line meals — the model would emit the
        # opening JSON but get truncated mid-array, raising LengthFinishReason.
        # 2000 gives headroom for ~15 items, still well under the model max.
        max_tokens=2000,
        response_format=TextParseResult,
        messages=[
            {"role": "system", "content": _TEXT_PARSER_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        return TextParseResult(items=[])
    return parsed


class NutritionEstimate(BaseModel):
    """LLM's best guess of KBJU per 100g/100ml/1 piece for a generic food."""

    name: str
    metric: FoodMetric
    kcal: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    piece_weight_g: float | None = Field(default=None, ge=0)


_NUTRITION_ESTIMATE_PROMPT = """\
You are a nutrition database. Given a food/dish name, return realistic average
nutrition values per the natural metric:
- per 100g for solid foods (meat, vegetables, grains, dishes)
- per 100ml for liquids
- per 1 piece for clearly countable items (one egg, one banana, one slice)
- per 1 serving for prepared dishes where weight is hard to standardize

Use commonly-known average values from standard nutrition references.
For composite dishes (плов, борщ, лагман) — use an averaged recipe.
"""


@traceable(name="estimate_nutrition", run_type="llm")
async def estimate_nutrition(food_name: str) -> NutritionEstimate:
    """Last-resort fallback: ask LLM for typical KBJU when no external source matched."""
    client = get_openai_client()
    response = await client.beta.chat.completions.parse(
        model=settings.TEXT_MODEL,
        temperature=0.0,
        max_tokens=200,
        response_format=NutritionEstimate,
        messages=[
            {"role": "system", "content": _NUTRITION_ESTIMATE_PROMPT},
            {"role": "user", "content": food_name},
        ],
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        # Conservative default — empty data is better than fake.
        return NutritionEstimate(
            name=food_name,
            metric=FoodMetric.GRAMS,
            kcal=0,
            protein_g=0,
            fat_g=0,
            carbs_g=0,
        )
    return parsed


@traceable(name="transcribe_voice", run_type="llm")
async def transcribe_voice(audio_bytes: bytes, *, filename: str = "voice.ogg") -> str:
    """Transcribe a Telegram voice note via Whisper."""
    client = get_openai_client()
    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=(filename, audio_bytes),
        language="ru",
        response_format="text",
    )
    # When response_format="text", the SDK returns a plain string.
    if isinstance(response, str):
        return response.strip()
    return getattr(response, "text", "").strip()


# ─── Content moderation / food-intent classifier ─────────────────────────────


class FoodIntentResult(BaseModel):
    """Verdict of the input-moderation gate that runs before parsing.

    `is_food_intent=False` blocks the message from reaching the parser, so
    inedible substances (feces, soap, sand) and pure abuse never get logged
    as food. The bot answers with the standard "I'm only for the diary" line.
    """

    is_food_intent: bool = Field(
        description=(
            "True only when the user is describing or asking about food / drink "
            "/ supplements they ate or want to log."
        )
    )
    category: Literal["food", "greeting", "abuse", "inedible", "nonsense"] = Field(
        default="food",
        description="Why the message was (not) classified as food.",
    )


_FOOD_INTENT_SYSTEM_PROMPT = """\
You are a content gate for a meal-logging Telegram bot. Decide whether to let
the message through to the food parser.

Set is_food_intent=TRUE ONLY when the message describes one or more
foods / drinks / supplements / dishes / cooking ingredients, with or without
an amount. Profanity used as an intensifier alongside real food is still food.

Set is_food_intent=FALSE for everything else:
 - GREETINGS / chit-chat / help requests
   ("привет", "что умеешь", "как дела", "спасибо")
 - INEDIBLE substances (bodily waste, soap, sand, paint, garbage, plants
   known to be inedible) — even if a number/grams is attached
   ("кал слона 100", "говно 50", "земля 30", "мыло 20")
 - PURE PROFANITY / abuse without a real food noun
   ("сука пиздец", "иди нахуй", "мудак")
 - NONSENSE / spam / single letters

Examples:
 "Курица 200"                 → food
 "Гречка отварная 150"        → food
 "Бургер был охуенный 300"    → food         (profanity modifies real food)
 "Ебать как вкусно курица 200" → food
 "Привет"                     → greeting
 "что ты умеешь"              → greeting
 "Спасибо"                    → greeting
 "Кал слона 100"              → inedible
 "Говно 50"                   → inedible
 "Сука пиздец"                → abuse
 "Иди нахуй"                  → abuse
 "asdf"                       → nonsense

When the category is anything other than "food", set is_food_intent=FALSE.
Return only the structured result.
"""


@traceable(name="classify_food_intent", run_type="llm")
async def classify_food_intent(text: str) -> FoodIntentResult:
    """Single-shot LLM gate: decide if the user message is about food."""
    client = get_openai_client()
    response = await client.beta.chat.completions.parse(
        model=settings.TEXT_MODEL,
        temperature=0.0,
        max_tokens=50,
        response_format=FoodIntentResult,
        messages=[
            {"role": "system", "content": _FOOD_INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    parsed = response.choices[0].message.parsed
    # On parsing failure we err on the side of letting the message through —
    # the downstream parser still rejects clear inedibles via its own rule.
    if parsed is None:
        return FoodIntentResult(is_food_intent=True, category="food")
    return parsed


@traceable(name="moderate_text", run_type="llm")
async def moderate_text(text: str) -> bool:
    """OpenAI Moderation API — True when the input is flagged for abuse / harm.

    Free, fast (~50ms) safety layer that covers sexual / hate / violence /
    self-harm / harassment categories in many languages. Pairs with the
    food-intent classifier above (which catches inedibles + greetings).
    """
    client = get_openai_client()
    try:
        result = await client.moderations.create(
            model="omni-moderation-latest", input=text
        )
    except Exception:
        # Network blip or quota — don't block the user on infra issues.
        return False
    return bool(result.results and result.results[0].flagged)
