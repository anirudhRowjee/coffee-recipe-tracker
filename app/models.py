from datetime import date, datetime
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel


class Bean(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    origin: Optional[str] = None
    roast_level: Optional[str] = None
    roast_date: Optional[date] = None
    flavor_notes: Optional[str] = None
    notes: Optional[str] = None

    recipes: List["Recipe"] = Relationship(back_populates="bean")


class Brewer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    method: Optional[str] = None
    notes: Optional[str] = None

    recipes: List["Recipe"] = Relationship(back_populates="brewer")


class Grinder(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    notes: Optional[str] = None

    recipes: List["Recipe"] = Relationship(back_populates="grinder")


class Recipe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    bean_id: int = Field(foreign_key="bean.id")
    brewer_id: int = Field(foreign_key="brewer.id")
    grinder_id: int = Field(foreign_key="grinder.id")

    dose_g: float
    water_ml: float
    temp_c: float
    grind_size: str
    recipe_text: Optional[str] = None
    notes: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    previous_recipe_id: Optional[int] = Field(default=None, foreign_key="recipe.id")

    bean: Optional[Bean] = Relationship(back_populates="recipes")
    brewer: Optional[Brewer] = Relationship(back_populates="recipes")
    grinder: Optional[Grinder] = Relationship(back_populates="recipes")


class Delta(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    from_recipe_id: int = Field(foreign_key="recipe.id")
    to_recipe_id: int = Field(foreign_key="recipe.id")

    changed_param: str
    delta_amount: float
    rationale: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
