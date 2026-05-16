"""OpenAI integration — vision / text parser / Whisper transcription.

All public callables are wrapped with @traceable so LangSmith records the
prompt, response, tokens and latency without manual instrumentation.
"""

from __future__ import annotations

import base64
from functools import lru_cache

from langsmith import traceable
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.core.config import settings
from app.db.models import FoodMetric


# ─── Output schemas (structured-output contract with the LLM) ────────────────

class ParsedFoodItem(BaseModel):
    """A single food/dish recognized from photo/text/voice."""
    name: str = Field(description="Canonical food name in Russian if applicable")
    amount: float = Field(description="Quantity user has (200 for grams, 1 for piece, etc.)", gt=0)
    unit: FoodMetric = Field(description="Unit of `amount`: g / ml / piece / serving")
    brand: str | None = Field(default=None, description="Brand if visible (e.g. 'President')")
    barcode: str | None = Field(default=None, description="EAN/UPC barcode if visible on packaging")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class PhotoMealResult(BaseModel):
    """Output of analyze_photo_meal — list of items detected on the plate."""
    items: list[ParsedFoodItem]
    overall_description: str = Field(
        default="",
        description="Short human description of what's on the plate (1 sentence)",
    )


class TextParseResult(BaseModel):
    """Output of parse_text_meal — items parsed from free-form text."""
    items: list[ParsedFoodItem]
    is_food_related: bool = Field(
        description="False if user text is not about food (chit-chat, off-topic) — caller will reject"
    )


# ─── OpenAI client ───────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


# ─── Prompts ─────────────────────────────────────────────────────────────────

_VISION_SYSTEM_PROMPT = """\
You are NutriSnap's nutrition vision analyzer. Identify every food / dish / drink
on the photo and estimate the portion size.

Rules:
- Use Russian names for food when possible (e.g. "куриная грудка", not "chicken breast")
  unless it's a brand name (then keep the original brand).
- Estimate `amount` and `unit` realistically based on visual cues (plate size, spoon, hand):
    * solid foods: use `g` with weight in grams
    * liquids: use `ml`
    * countable single items (egg, banana, slice): use `piece` and `amount=N`
    * complete ready meals where weight is hard to estimate: use `serving`
- If you see a packaged product (yogurt cup, can, etc.) — try to read the brand
  and barcode if visible.
- Output ONLY the structured result, no chit-chat.
"""

_TEXT_PARSER_SYSTEM_PROMPT = """\
You parse user messages describing what they ate into a structured list of items.

Examples:
- "200г куриной грудки и 150г гречки" → 2 items, both with unit=g
- "стакан молока" → 1 item, amount=250, unit=ml
- "съел два яйца" → 1 item, amount=2, unit=piece
- "плов" → 1 item, amount=1, unit=serving (unknown weight)
- "обед: рис 150, курица 200, овощи" → 3 items
- "Привет как дела" → set is_food_related=False, items=[]

Rules:
- Russian food names preferred.
- Default amount to 1 serving if quantity is missing AND food is ambiguous in size.
- Multi-line text and forwarded messages: parse every line as a potential item.
- If text mentions meal type ("на завтрак", "обед:", "ужин") — IGNORE for item list
  (meal type is decided by the caller).
"""


# ─── Public callables ────────────────────────────────────────────────────────

@traceable(name="analyze_photo_meal", run_type="llm")
async def analyze_photo_meal(
    image_bytes: bytes,
    *,
    caption: str | None = None,
) -> PhotoMealResult:
    """Detect food items on a photo. Uses GPT-4o Vision with structured output."""
    client = get_openai_client()
    image_b64 = base64.b64encode(image_bytes).decode()

    user_content: list[dict] = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
        }
    ]
    if caption:
        user_content.append(
            {"type": "text", "text": f"Подсказка от пользователя: {caption}"}
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
        max_tokens=500,
        response_format=TextParseResult,
        messages=[
            {"role": "system", "content": _TEXT_PARSER_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        return TextParseResult(items=[], is_food_related=False)
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

Use commonly-known average values (USDA or Russian gov tables).
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
