from datetime import date, datetime, timezone
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str

    beans: List["Bean"] = Relationship(back_populates="user")
    brewers: List["Brewer"] = Relationship(back_populates="user")
    grinders: List["Grinder"] = Relationship(back_populates="user")


class Bean(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    origin: Optional[str] = None
    roast_level: Optional[str] = None
    flavor_notes: Optional[str] = None
    notes: Optional[str] = None
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    user: Optional["User"] = Relationship(back_populates="beans")
    bags: List["BeanBag"] = Relationship(back_populates="bean")
    recipes: List["Recipe"] = Relationship(back_populates="bean")


class BeanBag(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    bean_id: int = Field(foreign_key="bean.id")

    roast_date: Optional[date] = None
    purchase_date: Optional[date] = None
    initial_quantity_g: float
    low_threshold_g: float = 50.0
    is_frozen: bool = False
    frozen_date: Optional[date] = None
    thaw_date: Optional[date] = None
    is_completed: bool = False
    notes: Optional[str] = None

    bean: Optional[Bean] = Relationship(back_populates="bags")
    brews: List["Brew"] = Relationship(back_populates="bag")


class Brewer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    method: Optional[str] = None
    notes: Optional[str] = None
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    user: Optional["User"] = Relationship(back_populates="brewers")
    recipes: List["Recipe"] = Relationship(back_populates="brewer")


class Grinder(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    notes: Optional[str] = None
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    user: Optional["User"] = Relationship(back_populates="grinders")
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

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    previous_recipe_id: Optional[int] = Field(default=None, foreign_key="recipe.id")

    bean: Optional[Bean] = Relationship(back_populates="recipes")
    brewer: Optional[Brewer] = Relationship(back_populates="recipes")
    grinder: Optional[Grinder] = Relationship(back_populates="recipes")
    brews: List["Brew"] = Relationship(back_populates="recipe")


class Brew(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id")
    bag_id: int = Field(foreign_key="beanbag.id")
    notes: Optional[str] = None
    recommended_param: Optional[str] = None
    recommended_delta: Optional[float] = None
    recommended_rationale: Optional[str] = None
    brewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    recipe: Optional[Recipe] = Relationship(back_populates="brews")
    bag: Optional[BeanBag] = Relationship(back_populates="brews")


class Delta(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    from_recipe_id: int = Field(foreign_key="recipe.id")
    to_recipe_id: int = Field(foreign_key="recipe.id")

    changed_param: str
    delta_amount: float
    rationale: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
