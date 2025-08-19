import enum
import csv
from sqlalchemy import (
    MetaData,
    create_engine,
    Column,
    Integer,
    Numeric,
    String,
    Table,
    Enum,
    ForeignKey,
    Boolean,
    Date,
    insert,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM
from sqlalchemy.ext.declarative import declarative_base
from dotenv import dotenv_values

env_vars = dotenv_values(".env")

if env_vars["chicken_db_conn_uri"]:
    engine = create_engine(env_vars["chicken_db_conn_uri"])
else:
    print("Connection URI not found")

metadata_obj = MetaData()

metadata_obj.reflect(bind=engine, extend_existing=True)
metadata_obj.drop_all(engine, checkfirst=False)


class ChickenSex(enum.Enum):
    H = "Hen"
    R = "Rooster"


class EggColor(enum.Enum):
    white = "white"
    cream = "cream"


################
## Table Schemas
################

## laying spots schema
laying_spot = Table(
    "laying_spot",
    metadata_obj,
    Column("id", Integer, primary_key=True),
    Column("location", String),
    Column("is_near_window", Boolean, nullable=False),
)

## egg table schema
egg = Table(
    "egg",
    metadata_obj,
    Column("id", String, primary_key=True),
    Column("laying_chicken_id", ForeignKey("chicken.id"), nullable=False),
    Column("rooster_id", ForeignKey("chicken.id"),nullable=False),
    Column("egg_color", Enum(EggColor), nullable=False),
    Column("laying_spot_id", ForeignKey("laying_spot.id"), nullable=False),
    Column("laying_date", Date, nullable=False),
    Column("hatching_successful",Boolean,default=True)
)

## chicken table schema
chicken = Table(
    "chicken",
    metadata_obj,
    Column("id", Integer, primary_key=True),
    Column("name", String, nullable=False),
    Column("sex", Enum(ChickenSex), nullable=False),
    Column("hatching_date", Date, nullable=True),
    Column("current_weight", Numeric, nullable=True),
    Column("egg_id", String, ForeignKey("egg.id"), nullable=True),
    Column("breed_id",ForeignKey("breed.id"),nullable=False),
    Column("favourite_song_id", Integer, ForeignKey("song.id")),
    Column("expired",Boolean,nullable=True,default=False)
)

## song table schema
song = Table(
    "song",
    metadata_obj,
    Column("id", Integer, primary_key=True),
    Column("title", String),
    Column("artist", String),
)

## breed table schema
breed = Table(
    "breed",
    metadata_obj,
    Column("id", Integer, primary_key=True),
    Column("name", String),
    Column("comb_type", String),
    Column("egg_colors", ARRAY(ENUM(EggColor, create_type=True))),
)

metadata_obj.create_all(engine, checkfirst=False)


# Open the CSV file in read mode ('r')
with open("seed_song_list.csv", "r", newline="") as file:
    reader = csv.reader(file)
    headers = next(reader)
    song_list = [dict(zip(headers, i)) for i in reader]

with engine.connect() as connection:
    print("Inserting songs...")
    res = connection.execute(insert(song).values(song_list))
    connection.commit()
    print("Songs succesfully inserted!")


with engine.connect() as connection:
    print("Inserting breeds...")
    breed_data = [
        {"name": "Fayoumi", "comb_type": "single", "egg_colors": ["white", "cream"]},
        {"name": "Leghorn", "comb_type": ["single", "rose"], "egg_colors": ["white"]},
        {"name": "Minorca", "comb_type": ["single", "rose"], "egg_colors": ["white"]},
    ]
    res = connection.execute(insert(breed).values(breed_data))
    connection.commit()
    print("Breeds succesfully inserted!")
