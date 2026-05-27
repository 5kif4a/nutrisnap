"""Seed `foods` table with the user's most frequently eaten products.

Source of nutrition values: foods.fatsecret.com export
(see docs/golden/food_diary.md). Per-100g (or per-100ml) values
recomputed from the report's portion-level entries.

Aliases capture the messy way users type product names: lowercase brands,
cyrillic-transliterated brands (Bonduelle → бондюэль), brand-first vs
brand-last, alternative dish names.

Run:
    podman compose -f docker-compose.dev.yml exec api python -m app.db.seed_foods

Idempotent: deletes existing `source='curated'` rows (only those without
a creator user — never touches user-generated rows) and re-inserts.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import delete, select

from app.db.models import Food, FoodMetric, FoodSource
from app.db.session import async_session_factory

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SeedFood:
    name: str
    metric: FoodMetric
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    aliases: list[str]
    brand: str | None = None
    piece_weight_g: float | None = None


# ─── Catalog ───────────────────────────────────────────────────────────────
#
# Values are per 100g (metric=g) or per 100ml (metric=ml) unless otherwise noted.
# Aliases include cyrillic-translit brand variants, brand-first/last orderings,
# and common short forms the user actually types in Telegram.

CATALOG: list[SeedFood] = [
    # ── Home cooking staples ───────────────────────────────────────────────
    SeedFood(
        name="Гречка отварная",
        metric=FoodMetric.GRAMS,
        kcal=120,
        protein_g=3.22,
        fat_g=4.17,
        carbs_g=19.05,
        aliases=[
            "гречка",
            "гречка варёная",
            "гречка вареная",
            "гречневая каша",
            "каша гречневая",
        ],
    ),
    SeedFood(
        name="Рис отварной",
        metric=FoodMetric.GRAMS,
        kcal=123,
        protein_g=2.91,
        fat_g=0.37,
        carbs_g=26.05,
        aliases=["рис", "рис варёный", "рис вареный", "рисовая каша"],
    ),
    SeedFood(
        name="Куриная грудка отварная",
        metric=FoodMetric.GRAMS,
        kcal=134,
        protein_g=23.08,
        fat_g=4.0,
        carbs_g=0,
        aliases=[
            "куриная грудка варёная",
            "куриная грудка вареная",
            "отварная куриная грудка",
            "варёная куриная грудка",
            "филе куриное отварное",
            "куриное филе варёное",
        ],
    ),
    SeedFood(
        name="Куриные грудки запечённые",
        metric=FoodMetric.GRAMS,
        kcal=165,
        protein_g=31.0,
        fat_g=3.6,
        carbs_g=0,
        aliases=[
            "куриная грудка запечённая",
            "куриная грудка запеченная",
            "запечённая куриная грудка",
            "куриная грудка в духовке",
        ],
    ),
    SeedFood(
        name="Тушёная курица с овощами",
        metric=FoodMetric.GRAMS,
        kcal=80,
        protein_g=13.9,
        fat_g=1.1,
        carbs_g=3.7,
        aliases=[
            "тушеная курица с овощами",
            "курица с овощами",
            "курица тушёная с овощами",
            "курица тушеная с овощами",
            "тушёная курица овощи",
            "курица с морковью",
            "курица с морковкой",
            "курица с овощами и морковью",
            "курица морковь",
        ],
    ),
    SeedFood(
        name="Тушёная куриная грудка с овощами",
        metric=FoodMetric.GRAMS,
        kcal=101,
        protein_g=16.2,
        fat_g=1.7,
        carbs_g=4.0,
        aliases=[
            "тушеная куриная грудка с овощами",
            "куриная грудка с овощами",
            "куриная грудка тушёная с овощами",
        ],
    ),
    SeedFood(
        name="Морковь по-корейски",
        metric=FoodMetric.GRAMS,
        kcal=121,
        protein_g=0.89,
        fat_g=9.0,
        carbs_g=10.3,
        aliases=["корейская морковь", "морковь корейская", "морковка по-корейски"],
    ),
    SeedFood(
        name="Кимчи",
        metric=FoodMetric.GRAMS,
        kcal=22,
        protein_g=1.73,
        fat_g=0.31,
        carbs_g=4.16,
        aliases=["кимчхи", "kimchi"],
    ),
    SeedFood(
        name="Помидоры",
        metric=FoodMetric.GRAMS,
        kcal=18,
        protein_g=0.88,
        fat_g=0.2,
        carbs_g=3.92,
        aliases=["помидор", "томаты", "томат", "tomato"],
    ),
    SeedFood(
        name="Спаржа",
        metric=FoodMetric.GRAMS,
        kcal=20,
        protein_g=2.2,
        fat_g=0.12,
        carbs_g=3.88,
        aliases=["спаржа варёная", "спаржа отварная", "asparagus"],
    ),
    SeedFood(
        name="Хлеб пшеничный",
        metric=FoodMetric.GRAMS,
        kcal=265,
        protein_g=9.0,
        fat_g=3.0,
        carbs_g=49.0,
        aliases=["хлеб", "хлеб белый", "пшеничный хлеб", "белый хлеб", "тостовый хлеб"],
    ),
    # ── Branded canned / pasta ──────────────────────────────────────────────
    SeedFood(
        name="Красная фасоль",
        brand="Bonduelle",
        metric=FoodMetric.GRAMS,
        kcal=85,
        protein_g=5.4,
        fat_g=0.8,
        carbs_g=14.0,
        aliases=[
            "фасоль",
            "фасоль бондюэль",
            "красная фасоль бондюэль",
            "фасоль bonduelle",
            "бондюэль фасоль",
            "фасоль красная",
            "консервированная фасоль",
        ],
    ),
    SeedFood(
        name="Кукуруза сладкая",
        brand="Bonduelle",
        metric=FoodMetric.GRAMS,
        kcal=80,
        protein_g=2.6,
        fat_g=1.0,
        carbs_g=15.2,
        aliases=[
            "кукуруза",
            "кукуруза бондюэль",
            "сладкая кукуруза",
            "консервированная кукуруза",
            "бондюэль кукуруза",
        ],
    ),
    SeedFood(
        name="Макароны улитки",
        brand="Makfa",
        metric=FoodMetric.GRAMS,
        kcal=342,
        protein_g=12.0,
        fat_g=1.3,
        carbs_g=70.5,
        aliases=[
            "макароны макфа",
            "макфа улитки",
            "макфа улитка",
            "макароны макфа улитки",
            "макароны макфа улитка",
            "улитки макфа",
            "макароны улитка",
            "паста улитки",
            "макфа",
            "макароны",
        ],
    ),
    SeedFood(
        name="Лаваш",
        brand="Романовский Продукт",
        metric=FoodMetric.GRAMS,
        kcal=235,
        protein_g=7.5,
        fat_g=1.0,
        carbs_g=49.0,
        aliases=["лаваш романовский", "романовский лаваш", "тонкий лаваш"],
    ),
    # ── Dairy ───────────────────────────────────────────────────────────────
    SeedFood(
        name="Сметана 10%",
        brand="President",
        metric=FoodMetric.GRAMS,
        kcal=117,
        protein_g=2.2,
        fat_g=10.0,
        carbs_g=4.2,
        aliases=[
            "сметана president 10%",
            "president сметана 10%",
            "сметана 10",
            "сметана президент 10%",
            "президент сметана 10%",
            "сметана president",
            "сметана 10 процентов",
        ],
    ),
    SeedFood(
        name="Сметана 15%",
        brand="President",
        metric=FoodMetric.GRAMS,
        kcal=161,
        protein_g=2.2,
        fat_g=15.0,
        carbs_g=4.0,
        aliases=[
            "сметана president 15%",
            "president сметана 15%",
            "сметана 15",
            "сметана президент 15%",
            "президент сметана 15%",
        ],
    ),
    SeedFood(
        name="Кефир 2,5%",
        brand="Natige",
        metric=FoodMetric.GRAMS,
        kcal=49,
        protein_g=2.8,
        fat_g=2.5,
        carbs_g=3.9,
        aliases=[
            "кефир натиже",
            "натиже кефир",
            "натиже кефир 2,5",
            "натиже кефир 2.5",
            "кефир натиже 2,5%",
            "натиже 2,5",
            "natige кефир",
            "кефир 2,5",
        ],
    ),
    SeedFood(
        name="Кефир Protein",
        brand="Natige",
        metric=FoodMetric.GRAMS,
        kcal=52,
        protein_g=2.8,
        fat_g=2.5,
        carbs_g=4.6,
        aliases=[
            "натиже кефир protein",
            "natige кефир протеин",
            "кефир протеиновый натиже",
            "натиже протеин",
        ],
    ),
    SeedFood(
        name="Творожок Вишня-Банан",
        brand="Простоквашино",
        metric=FoodMetric.GRAMS,
        kcal=110,
        protein_g=6.8,
        fat_g=3.6,
        carbs_g=12.7,
        aliases=[
            "простоквашино творожок вишня-банан",
            "творожок простоквашино вишня банан",
            "творожок вишня банан",
            "творожок простоквашино",
        ],
    ),
    SeedFood(
        name="Творожок Голубика-Банан",
        brand="Простоквашино",
        metric=FoodMetric.GRAMS,
        kcal=112,
        protein_g=6.8,
        fat_g=3.6,
        carbs_g=13.0,
        aliases=[
            "простоквашино творожок голубика-банан",
            "творожок голубика банан",
            "творожок простоквашино голубика",
        ],
    ),
    # ── Sweets / snacks ─────────────────────────────────────────────────────
    SeedFood(
        name="Snickers",
        brand="Snickers",
        metric=FoodMetric.GRAMS,
        kcal=521,
        protein_g=10.2,
        fat_g=29.8,
        carbs_g=52.2,
        aliases=[
            "сникерс",
            "snickers батончик",
            "сникерс батончик",
            "батончик сникерс",
            "снайкерс",
        ],
    ),
    SeedFood(
        name="Twix",
        brand="Twix",
        metric=FoodMetric.GRAMS,
        kcal=494,
        protein_g=4.4,
        fat_g=24.0,
        carbs_g=64.4,
        aliases=["твикс", "twix батончик", "твикс батончик", "батончик твикс"],
    ),
    SeedFood(
        name="Nuts",
        brand="Nestle",
        metric=FoodMetric.GRAMS,
        kcal=479,
        protein_g=4.7,
        fat_g=21.0,
        carbs_g=66.0,
        aliases=[
            "nestle nuts",
            "натс",
            "натс батончик",
            "nuts батончик",
            "nuts шоколадка",
            "шоколадка nuts",
            "nuts шоколад",
            "nuts большая",
            "nestle nuts батончик",
        ],
    ),
    SeedFood(
        name="Milky Way",
        brand="Milky Way",
        metric=FoodMetric.GRAMS,
        kcal=450,
        protein_g=3.1,
        fat_g=16.5,
        carbs_g=72.0,
        aliases=["милки вей", "milky way шоколад", "милки вей шоколад"],
    ),
    SeedFood(
        name="Зефир Бело-Розовый",
        brand="Рахат",
        metric=FoodMetric.GRAMS,
        kcal=320,
        protein_g=1.0,
        fat_g=0.1,
        carbs_g=80.0,
        aliases=[
            "рахат зефир",
            "зефир рахат",
            "зефир бело-розовый рахат",
            "рахат зефир бело розовый",
            "зефир",
        ],
    ),
    SeedFood(
        name="Зефир ванильный",
        brand="Belucci",
        metric=FoodMetric.GRAMS,
        kcal=309,
        protein_g=1.0,
        fat_g=0.0,
        carbs_g=77.0,
        aliases=["белуччи зефир", "белуччи зефир ванильный", "зефир белуччи"],
    ),
    SeedFood(
        name="Утреннее печенье какао",
        brand="Belvita",
        metric=FoodMetric.GRAMS,
        kcal=455,
        protein_g=8.1,
        fat_g=16.0,
        carbs_g=66.0,
        aliases=[
            "белвита печенье",
            "печенье белвита",
            "белвита какао",
            "belvita печенье",
        ],
    ),
    SeedFood(
        name="Эскимо протеиновое",
        brand="Bombbar",
        metric=FoodMetric.GRAMS,
        kcal=297,
        protein_g=15.0,
        fat_g=14.0,
        carbs_g=12.0,
        aliases=[
            "бомбар эскимо",
            "bombbar эскимо",
            "bombbar мороженое",
            "бомбар мороженое",
            "протеиновое эскимо",
            "бомббар эскимо",
        ],
    ),
    SeedFood(
        name="Crunch Chocolate Fondant",
        brand="Bootybar",
        metric=FoodMetric.GRAMS,
        kcal=317,
        protein_g=28.3,
        fat_g=10.0,
        carbs_g=13.3,
        aliases=[
            "bootybar crunch",
            "bootybar шоколад",
            "бутибар",
            "бутибар батончик",
            "bootybar батончик",
        ],
    ),
    SeedFood(
        name="Пломбир с Вишней",
        brand="Коровка из Кореновки",
        metric=FoodMetric.GRAMS,
        kcal=240,
        protein_g=3.5,
        fat_g=12.0,
        carbs_g=30.0,
        aliases=[
            "коровка из кореновки пломбир",
            "пломбир коровка из кореновки",
            "коровка пломбир вишня",
            "коровка из кореновки вишня",
        ],
    ),
    SeedFood(
        name="Мороженое Лакомка",
        brand="Коровка из Кореновки",
        metric=FoodMetric.GRAMS,
        kcal=250,
        protein_g=4.0,
        fat_g=15.0,
        carbs_g=25.0,
        aliases=[
            "коровка из кореновки мороженое",
            "коровка из кореновки лакомка",
            "коровка лакомка",
            "лакомка мороженое",
            "мороженое коровка",
        ],
    ),
    SeedFood(
        name="Эскимо Пломбир 15%",
        brand="Мишка на Полюсе",
        metric=FoodMetric.GRAMS,
        kcal=340,
        protein_g=2.8,
        fat_g=24.2,
        carbs_g=26.2,
        aliases=[
            "мишка на полюсе эскимо",
            "мишка на полюсе пломбир",
            "мишка эскимо",
            "мишка на полюсе мороженое",
            "эскимо мишка",
        ],
    ),
    SeedFood(
        name="Пломбир со сгущёнкой",
        brand="Золотой Стандарт",
        metric=FoodMetric.GRAMS,
        kcal=267,
        protein_g=4.1,
        fat_g=13.7,
        carbs_g=31.3,
        aliases=[
            "золотой стандарт пломбир",
            "пломбир со сгущенкой золотой стандарт",
            "золотой стандарт сгущёнка",
            "пломбир сгущенка",
        ],
    ),
    # ── Supplements ─────────────────────────────────────────────────────────
    SeedFood(
        name="Ultra Whey",
        brand="Maxler",
        metric=FoodMetric.GRAMS,
        kcal=390,
        protein_g=77.0,
        fat_g=6.7,
        carbs_g=7.3,
        aliases=[
            "maxler ultra whey",
            "maxler whey",
            "ultra whey",
            "максл ultra whey",
            "макслер ультра вэй",
            "протеин maxler",
            "вэй maxler",
            "сывороточный протеин maxler",
            "whey протеин",
        ],
    ),
    SeedFood(
        name="Креатин",
        metric=FoodMetric.GRAMS,
        kcal=0,
        protein_g=88.0,
        fat_g=0,
        carbs_g=0,
        aliases=["creatine", "креатин моногидрат", "креатин порошок"],
    ),
    SeedFood(
        name="High Pro",
        brand="Exponenta",
        metric=FoodMetric.GRAMS,
        kcal=60,
        protein_g=12.0,
        fat_g=0,
        carbs_g=2.5,
        aliases=[
            "exponenta high pro",
            "экспонента high pro",
            "экспонента протеин",
            "exponenta протеиновый напиток",
            "high pro экспонента",
        ],
    ),
    # ── Drinkit (ready-made cafe items) ─────────────────────────────────────
    SeedFood(
        name="Гриль-Ролл с Цыплёнком BBQ",
        brand="Drinkit",
        metric=FoodMetric.GRAMS,
        kcal=185,
        protein_g=11.3,
        fat_g=6.8,
        carbs_g=19.6,
        aliases=[
            "drinkit гриль ролл",
            "дринкит гриль ролл",
            "гриль ролл bbq",
            "ролл bbq drinkit",
            "drinkit гриль-ролл с цыпленком bbq",
        ],
    ),
    SeedFood(
        name="Клаб Сэндвич с Курицей",
        brand="Drinkit",
        metric=FoodMetric.GRAMS,
        kcal=158,
        protein_g=8.8,
        fat_g=8.4,
        carbs_g=12.0,
        aliases=[
            "drinkit клаб сэндвич",
            "дринкит клаб сэндвич",
            "клаб сэндвич с курицей",
            "сэндвич drinkit",
            "club sandwich drinkit",
        ],
    ),
    SeedFood(
        name="Айс Ти Ташкентский",
        brand="Drinkit",
        metric=FoodMetric.MILLILITERS,
        kcal=66,
        protein_g=0.2,
        fat_g=0.1,
        carbs_g=15.8,
        aliases=[
            "drinkit айс ти",
            "дринкит айс ти",
            "айс ти ташкентский",
            "ташкентский айс ти",
            "ice tea drinkit",
            "drinkit ice tea",
        ],
    ),
    # ── Pelmeni (one of the recurring branded items) ───────────────────────
    SeedFood(
        name="Пельмени говяжьи",
        brand="Bitony",
        metric=FoodMetric.GRAMS,
        kcal=221,
        protein_g=10.5,
        fat_g=7.9,
        carbs_g=28.1,
        aliases=[
            "битони пельмени",
            "пельмени битони",
            "bitony пельмени говяжьи",
            "пельмени говяжьи",
            "битони говяжьи пельмени",
        ],
    ),
]


async def seed() -> None:
    """Wipe and re-insert the curated catalog. Idempotent."""
    async with async_session_factory() as session:
        # Only touch system-curated rows (no creator). Untouches OFF, LLM_ESTIMATE,
        # user recipes, and anything someone added via the bot.
        deleted = await session.execute(
            delete(Food).where(
                Food.source == FoodSource.CURATED,
                Food.created_by_user_id.is_(None),
            )
        )
        logger.info("Wiped %d existing curated rows", deleted.rowcount or 0)

        for item in CATALOG:
            session.add(
                Food(
                    name=item.name,
                    aliases=item.aliases,
                    brand=item.brand,
                    barcode=None,
                    cuisine=None,
                    metric=item.metric,
                    kcal=item.kcal,
                    protein_g=item.protein_g,
                    fat_g=item.fat_g,
                    carbs_g=item.carbs_g,
                    piece_weight_g=item.piece_weight_g,
                    servings=[],
                    source=FoodSource.CURATED,
                    external_id=None,
                    created_by_user_id=None,
                )
            )

        await session.commit()
        count_result = await session.execute(
            select(Food.id).where(Food.source == FoodSource.CURATED)
        )
        total_count = len(list(count_result.scalars().all()))
        logger.info(
            "Inserted %d curated foods (total in DB: %d)", len(CATALOG), total_count
        )
        print(
            f"✅ Seeded {len(CATALOG)} curated foods (total curated in DB: {total_count})"
        )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    await seed()


if __name__ == "__main__":
    asyncio.run(main())
