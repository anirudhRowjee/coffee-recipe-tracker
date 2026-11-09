from datetime import date, datetime, timezone
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    password_hash: Optional[str] = None  # no password yet = can't sign in
    is_admin: bool = Field(default=False, sa_column_kwargs={"server_default": "0"})
    must_change_password: bool = Field(default=False, sa_column_kwargs={"server_default": "0"})

    beans: List["Bean"] = Relationship(back_populates="user")
    brewers: List["Brewer"] = Relationship(back_populates="user")
    grinders: List["Grinder"] = Relationship(back_populates="user")


class UserSession(SQLModel, table=True):
    """One signed-in browser. Stores a hash of the cookie's token, never the token."""
    token_hash: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Bean(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    origin: Optional[str] = None
    roast_level: Optional[str] = None
    flavor_notes: Optional[str] = None
    notes: Optional[str] = None
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    accent_color: Optional[str] = None  # "#rrggbb" picked from the bag photo
    mesh_colors: Optional[str] = None  # four comma-separated "#rrggbb", one per corner of the gradient
    image_version: Optional[int] = None  # set when a photo exists; bumps on each upload to bust caches

    user: Optional["User"] = Relationship(back_populates="beans")
    bags: List["BeanBag"] = Relationship(back_populates="bean")
    recipes: List["Recipe"] = Relationship(back_populates="bean")


class BeanImage(SQLModel, table=True):
    """The bag photo. Its own table, with no relationship from Bean, so that
    loading beans never loads image bytes. In the database rather than on disk
    so backups, deploys and rollbacks cover it."""
    bean_id: int = Field(primary_key=True, foreign_key="bean.id")
    data: bytes
    content_type: str = "image/jpeg"


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


class RecipeLine(SQLModel, table=True):
    """A named recipe ("Coffee Chronicler", "2 cup") for one bean/brewer/grinder.

    Its versions are the Recipe rows pointing at it. A combination can have
    several lines, each with its own versions, brews, deltas and recommendations.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    bean_id: int = Field(foreign_key="bean.id")
    brewer_id: int = Field(foreign_key="brewer.id")
    grinder_id: int = Field(foreign_key="grinder.id")
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    recipes: List["Recipe"] = Relationship(back_populates="line")


class Recipe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    bean_id: int = Field(foreign_key="bean.id")
    brewer_id: int = Field(foreign_key="brewer.id")
    grinder_id: int = Field(foreign_key="grinder.id")
    # Nullable only so the column can be added with ALTER TABLE; the startup
    # migration assigns every recipe to a line and new recipes always get one.
    line_id: Optional[int] = Field(default=None, foreign_key="recipeline.id")

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
    line: Optional[RecipeLine] = Relationship(back_populates="recipes")
    brews: List["Brew"] = Relationship(back_populates="recipe")


class Brew(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id")
    bag_id: int = Field(foreign_key="beanbag.id")
    notes: Optional[str] = None
    rating: Optional[int] = None  # 1-5 stars
    recommended_param: Optional[str] = None
    recommended_delta: Optional[float] = None
    recommended_rationale: Optional[str] = None
    brewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    recipe: Optional[Recipe] = Relationship(back_populates="brews")
    bag: Optional[BeanBag] = Relationship(back_populates="brews")


class PlannedBrew(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    bag_id: int = Field(foreign_key="beanbag.id")
    brewer_id: int = Field(foreign_key="brewer.id")
    grinder_id: int = Field(foreign_key="grinder.id")
    # None = whichever named recipe is the default for the combination when
    # the plan is opened (plans made from the browse page don't pick one).
    line_id: Optional[int] = Field(default=None, foreign_key="recipeline.id")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Delta(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    from_recipe_id: int = Field(foreign_key="recipe.id")
    to_recipe_id: int = Field(foreign_key="recipe.id")

    changed_param: str
    delta_amount: float
    rationale: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
