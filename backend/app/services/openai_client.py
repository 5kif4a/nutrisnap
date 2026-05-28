"""OpenAI integration — vision / text parser / Whisper transcription.

All public callables are wrapped with @traceable so LangSmith records the
prompt, response, tokens and latency without manual instrumentation.
"""

from __future__ import annotations

import base64
import logging
from functools import lru_cache
from typing import Literal

from langsmith import traceable
from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.core.config import settings
from app.db.models import FoodMetric

logger = logging.getLogger(__name__)


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
    weight_provided: bool = Field(
        default=True,
        description=(
            "False ONLY when the user did NOT write any number/weight for this item "
            "and you fell back to amount=1 with unit=serving/piece. When the user "
            "explicitly wrote any number (grams, pieces, ml, 'стакан', 'бутылка', "
            "'порция') — set True. Photos always have an estimated amount → True."
        ),
    )


class PhotoMealResult(BaseModel):
    """Output of analyze_photo_meal — items + built-in guiderail verdicts.

    The vision call also serves as the photo guiderail (one LLM call instead of
    a separate cheap-check pass). When `is_food_image=False` or `is_safe_image=False`,
    `items` MUST be empty and the graph routes to error_node.
    """

    is_food_image: bool = Field(
        default=True,
        description=(
            "True only when the photo actually contains food / drinks / packaged "
            "groceries / kitchen scale with food. Memes, screenshots, selfies, "
            "landscapes, pets, random objects → False."
        ),
    )
    is_safe_image: bool = Field(
        default=True,
        description=(
            "False when the photo contains NSFW, violence, abuse, or other "
            "disallowed content. Default True for normal food photos."
        ),
    )
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
    # wrap_openai instruments the SDK so each call shows up in LangSmith as an
    # LLM-typed run with prompt/completion tokens — that's what powers the
    # cost column. Without it @traceable still records the call but LangSmith
    # has no usage metadata, so cost stays empty.
    return wrap_openai(AsyncOpenAI(api_key=settings.OPENAI_API_KEY))


# ─── Prompts ─────────────────────────────────────────────────────────────────

_VISION_SYSTEM_PROMPT = """\
You are NutriSnap's nutrition vision analyzer. Identify every food / dish /
drink on the photo and estimate the portion size.

STEP 0 — set the safety flags FIRST:
  is_food_image=False for memes, screenshots, selfies, landscapes, pets,
  random objects, drawings — anything that isn't food / drink / groceries.
  is_safe_image=False for nudity, sexual, violence, gore, hate content.
  When either is False: set items=[], overall_description="non-food" or
  "unsafe content". STOP — do not invent food.

When both flags are True, extract items using this priority for `amount`:

1. KITCHEN SCALE — if a digital scale shows a reading, READ the digits
   exactly (watch 8↔0, 5↔6, 3↔8). Use that number, unit=g (or ml if shown).
   confidence ≥ 0.95. Two scales = two weighed items. Dish on scale = use
   total weight, don't split into ingredients unless each was weighed.

2. BARCODE — if EAN/UPC visible, put ALL digits in `barcode`. Extract
   `brand` from the label. Estimate `amount` from package size if no
   scale (e.g. "Простоквашино Творожок 110г" → amount=110 unit=g).

3. PACKAGING LABEL — read brand + product name when visible. Common
   brands: Простоквашино, Натиже, Коровка из Кореновки, Bonduelle, Makfa,
   President, Snickers, Maxler, Bombbar, Drinkit.

4. VISUAL ESTIMATION (last resort, confidence ≤ 0.7) — plate size 25cm,
   utensils, hand as scale. solid=g, liquid=ml, countable=piece, ready
   meal=serving.

NAMING:
- Russian names for generic foods ("куриная грудка", "гречка отварная").
- Don't translate brand names ("Snickers", "Bonduelle").
- Composite dishes (плов, борщ) = ONE item with total weight.
- `brand` only when actually visible — don't invent.

Output ONLY the structured result.
"""

_TEXT_PARSER_SYSTEM_PROMPT = """\
You parse short Russian Telegram messages describing what the user ate into
structured food items. The user is a fitness-tracking adult who weighs food
in grams. Inedible / abuse / greetings are filtered upstream — assume the
input is about food and parse what you can.

RULES
1. UNIT = grams by default. Any bare number is grams (start or end of line).
   Use `ml` only for liquids with explicit "стакан"=250 / "бутылка"=500.
   Use `piece` only with explicit counts ("2 яйца", "1 банан").
   Use `serving` only with "порция".
2. ONE LINE = ONE ITEM. Composite dishes ("Курица с овощами 95",
   "Тушеная курица с овощами 153") stay whole. Split only when items are
   comma-separated with their own weights OR joined by "и".
3. MULTI-LINE = MULTIPLE ITEMS, one per line. Drop prefixes like "обед:".
4. BRAND only when the word literally appears in the input (any case /
   transliteration). Bare generic words ("nuts", "молоко", "хлеб",
   "протеин") are NOT brands. Normalize Cyrillic transliterations to
   canonical form: бондюэль→Bonduelle, макфа→Makfa, снайкерс/сникерс→Snickers,
   максл/макслер→Maxler, президент→President, натиже→Natige,
   белвита→Belvita, бомбар→Bombbar, рахат→Рахат, простоквашино→Простоквашино,
   коровка из кореновки→Коровка из Кореновки, drinkit/драгкит→Drinkit.
5. `name` ALWAYS keeps the head noun (protein, whey, йогурт, хлеб, гречка).
   Never drop it even with a brand present — that's the biggest lookup
   killer. "Maxler Ultra Whey 30" → name="Whey protein ultra", brand="Maxler".
6. PRESERVE the user's wording inside `name` — keep declension as-is
   ("улитки" stays "улитки", "улитка" stays "улитка"); only fix obvious typos.
7. Supplements ARE food: whey, casein, creatine, protein bars, gainers.
8. WEIGHT_PROVIDED — set False ONLY when the user wrote NO number at all for
   the item and you fall back to amount=1, unit=serving. If any number is
   present (grams, pieces, ml, "стакан", "бутылка", "порция") → True. The
   bot will reprompt the user for the missing weight when this is False.
9. NAME NORMALIZATION for bare nouns — when the user writes ONLY a generic
   noun without any cooking descriptor, expand `name` to the typical
   diary-logging form so external lookup (FatSecret) gets a clean
   hit instead of random matches. Keep the user's number/weight as-is.
     - Grains/cereals (рис, гречка, овсянка, перловка, булгур, киноа,
       манка, пшено) → "<crop> отварной/отварная" (gender by Russian rule)
     - Pasta (макароны, спагетти, паста) → "<x> отварные/-ая"
     - Plain meat (курица, говядина, индейка, свинина, рыба) → "<x> отварная"
     - Tubers (картофель, картошка) → "Картофель отварной"
     - Legumes (фасоль, чечевица, нут, горох) → "<x> отварная/-ой"
   IMPORTANT: only when no other descriptor is present. "Жареная курица 200",
   "рис на пару 150", "Гречка с грибами 200" — leave as-is.

FEW-SHOTS (real user patterns — match these exactly)

"Хлеб 53"                       → [{name:"Хлеб", amount:53, unit:g}]
"Рис 150"                       → [{name:"Рис отварной", amount:150, unit:g}]
"гречка 100"                    → [{name:"Гречка отварная", amount:100, unit:g}]
"курица 200"                    → [{name:"Курица отварная", amount:200, unit:g}]
"Овсянка 80"                    → [{name:"Овсянка отварная", amount:80, unit:g}]
"макароны 90"                   → [{name:"Макароны отварные", amount:90, unit:g}]
"картошка 200"                  → [{name:"Картофель отварной", amount:200, unit:g}]
"Курица с овощами 95"           → [{name:"Курица с овощами", amount:95, unit:g}]
"Жареная курица 180"            → [{name:"Жареная курица", amount:180, unit:g}]
"Рис на пару 120"               → [{name:"Рис на пару", amount:120, unit:g}]
"Фасоль бондюэль 25"            → [{name:"Фасоль", brand:"Bonduelle", amount:25, unit:g}]
"Макароны Макфа улитка 92"      → [{name:"Макароны улитка", brand:"Makfa", amount:92, unit:g}]
"50 гр макароны улитки макфа"   → [{name:"Макароны улитки", brand:"Makfa", amount:50, unit:g}]
"Макароны Макфа улитка 92\\nТушеная курица с овощами 153"
                                → [{name:"Макароны улитка", brand:"Makfa", amount:92, unit:g},
                                   {name:"Тушеная курица с овощами", amount:153, unit:g}]

EDGE CASES

"Nuts 66"                       → [{name:"Орехи", brand:null, amount:66, unit:g}]
"Nestle Nuts 66"                → [{name:"Nuts шоколад", brand:"Nestle", amount:66, unit:g}]
"Maxler Ultra Whey 30"          → [{name:"Whey protein ultra", brand:"Maxler", amount:30, unit:g}]
"Протеин maxler ultra 30"       → [{name:"Протеин ultra", brand:"Maxler", amount:30, unit:g}]
"Сметана President 10% 30"      → [{name:"Сметана 10%", brand:"President", amount:30, unit:g}]
"Простоквашино творожок вишня-банан 110"
                                → [{name:"Творожок вишня-банан", brand:"Простоквашино", amount:110, unit:g}]
"Кефир натиже 2,5% 350"         → [{name:"Кефир 2,5%", brand:"Natige", amount:350, unit:g}]
"Креатин 5"                     → [{name:"Креатин", amount:5, unit:g}]
"200г куриной грудки и 150г гречки"
                                → [{name:"Куриная грудка", amount:200, unit:g},
                                   {name:"Гречка", amount:150, unit:g}]
"стакан молока"                 → [{name:"Молоко", amount:250, unit:ml}]
"съел 2 яйца"                   → [{name:"Яйцо", amount:2, unit:piece}]
"рис"                           → [{name:"Рис", amount:1, unit:serving, weight_provided:false}]
"гречка и курица"               → [{name:"Гречка", amount:1, unit:serving, weight_provided:false},
                                   {name:"Курица", amount:1, unit:serving, weight_provided:false}]
"200г курицы и рис"             → [{name:"Курица", amount:200, unit:g},
                                   {name:"Рис", amount:1, unit:serving, weight_provided:false}]

If nothing parses, return items=[].
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
    """Parse free-form user text into structured food items.

    On `LengthFinishReasonError` (model emitted too many reasoning tokens
    before the JSON), retry once with a stricter "be brief" reminder and
    a higher cap — observed on short inputs where the model spiraled.
    """
    from openai import LengthFinishReasonError

    client = get_openai_client()

    async def _call(*, max_tokens: int, terse: bool) -> TextParseResult:
        messages: list[dict] = [
            {"role": "system", "content": _TEXT_PARSER_SYSTEM_PROMPT},
        ]
        if terse:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Output ONLY the JSON object matching the schema. "
                        "No commentary, no markdown fences, no chain-of-thought."
                    ),
                }
            )
        messages.append({"role": "user", "content": text})
        response = await client.beta.chat.completions.parse(
            model=settings.TEXT_MODEL,
            temperature=0.0,
            max_tokens=max_tokens,
            response_format=TextParseResult,
            messages=messages,
        )
        return response.choices[0].message.parsed or TextParseResult(items=[])

    try:
        return await _call(max_tokens=4000, terse=False)
    except LengthFinishReasonError:
        logger.warning("parse_text_meal hit length limit, retrying terse")
        return await _call(max_tokens=4000, terse=True)


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
Content gate for a meal-logging Telegram bot. Set is_food_intent=TRUE only
when the message describes food / drinks / supplements (with or without an
amount). Profanity as an intensifier next to real food is still food.

Otherwise set FALSE with `category`:
  food      — real food
  greeting  — hi / спасибо / что умеешь / /start
  inedible  — bodily waste, soap, paint, sand, known-inedible plants
              (also when grams are attached: "кал слона 100")
  abuse     — pure profanity, no food noun
  nonsense  — spam / single letters / gibberish

Examples:
  "Курица 200"          → food
  "Бургер охуенный 300" → food   (profanity modifies real food)
  "Привет"              → greeting
  "Кал слона 100"       → inedible
  "Сука пиздец"         → abuse
  "asdf"                → nonsense

When category != "food", is_food_intent=FALSE. Return only the structured result.
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
