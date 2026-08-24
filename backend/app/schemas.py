"""Request/response validation.

Replaces the hand-rolled field whitelist this file grew out of. The important
difference isn't type coercion — it's that a bad field now produces a specific
422 telling the client which field and why, instead of being silently dropped
and logged as a meal with no calories.
"""
import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

MealType = Literal["breakfast", "lunch", "dinner", "snack"]
MealSource = Literal["barcode", "photo", "manual", "recent"]

# Per 100g, nothing edible exceeds pure fat (884 kcal). Values past this are
# data-entry noise, not food.
MAX_KCAL_100G = 900


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def lowercase(cls, v: str) -> str:
        return v.strip().lower()


class MealIn(BaseModel):
    """One meal as the phone sends it.

    `client_id` is minted on-device at creation time and is the sync identity —
    see routes/meals.py. `updated_at` is the CLIENT's edit clock and is used
    only to resolve competing edits; it is never used as a pull cursor.
    """
    model_config = ConfigDict(extra="ignore")

    client_id: str = Field(min_length=8, max_length=64)
    name: Optional[str] = Field(default=None, max_length=200)
    brand: Optional[str] = Field(default=None, max_length=200)
    barcode: Optional[str] = Field(default=None, max_length=20)

    serving_g: Optional[float] = Field(default=None, ge=0, le=10_000)
    calories: Optional[float] = Field(default=None, ge=0, le=20_000)
    protein_g: Optional[float] = Field(default=None, ge=0, le=2_000)
    carbs_g: Optional[float] = Field(default=None, ge=0, le=2_000)
    fat_g: Optional[float] = Field(default=None, ge=0, le=2_000)
    fiber_g: Optional[float] = Field(default=None, ge=0, le=1_000)
    sugar_g: Optional[float] = Field(default=None, ge=0, le=2_000)
    sodium_mg: Optional[float] = Field(default=None, ge=0, le=100_000)

    meal_type: Optional[MealType] = None
    eaten_at: dt.datetime
    source: MealSource = "manual"

    model_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    user_edited: bool = False
    deleted: bool = False
    updated_at: Optional[dt.datetime] = None


class SyncRequest(BaseModel):
    """A sync round trip: push local edits, pull everything since the cursor."""
    model_config = ConfigDict(extra="ignore")

    since: Optional[dt.datetime] = None
    changes: list[MealIn] = Field(default_factory=list, max_length=500)
