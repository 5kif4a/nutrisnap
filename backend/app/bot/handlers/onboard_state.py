"""Shared onboarding ConversationHandler state enum.

Lives in its own module so both `start.py` and `onboard.py` can import it
without creating a circular dependency.
"""

from enum import IntEnum


class OnboardStep(IntEnum):
    SEX = 0
    WEIGHT = 1
    HEIGHT = 2
    AGE = 3
    ACTIVITY = 4
    GOAL = 5
    # Only reached when goal is LOSE or GAIN; MAINTAIN skips straight to save.
    TARGET_WEIGHT = 6
