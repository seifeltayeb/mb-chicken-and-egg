import math
from typing import Union
import math
import json
import csv
import random
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import (
    MetaData,
    text,
    delete,
    create_engine,
    Column,
    Integer,
    String,
    Table,
    Enum,
    ForeignKey,
    Boolean,
    Date,
    insert
)
import sqlalchemy

print(sqlalchemy.__version__)

from dotenv import dotenv_values

env_vars = dotenv_values(".env")

if env_vars["chicken_db_conn_uri"]:
    engine = create_engine(env_vars["chicken_db_conn_uri"])
else:
    print("Connection URI not found")

metadata_obj = MetaData()
metadata_obj.reflect(bind=engine, extend_existing=True)


# Open the CSV file in read mode ('r')
with open("seed_chicken_name_list.csv", "r", newline="") as file:
    reader = csv.reader(file)
    headers = next(reader)
    chicken_names = [dict(zip(headers, i)) for i in reader]
    chicken_name_list = [chicken_name["name"] for chicken_name in chicken_names]


Number = Union[int, float]

chicken_breed_attributes = {
    "Fayoumi": {
        "id": 1,
        "rooster": {"lower": 1.35, "upper": 1.8},
        "hen": {"lower": 0.9, "upper": 1.6},
        "k": {"lower": 0.25, "upper": 0.35},
        "t_inflect": {"lower": 7, "upper": 9},
        "laying_start": 19,
        "eggs_per_year": {"lower": 150, "upper": 205},
    },
    "Leghorn": {
        "id": 2,
        "rooster": {"lower": 2.4, "upper": 3.4},
        "hen": {"lower": 2.0, "upper": 2.5},
        "k": {"lower": 0.25, "upper": 0.35},
        "t_inflect": {"lower": 8, "upper": 9.5},
        "laying_start": 18,
        "eggs_per_year": {"lower": 280, "upper": 320},
    },
    "Minorca": {
        "id": 3,
        "rooster": {"lower": 3.2, "upper": 3.6},
        "hen": {"lower": 2.7, "upper": 3.6},
        "k": {"lower": 0.18, "upper": 0.28},
        "t_inflect": {"lower": 9, "upper": 11},
        "laying_start": 26,
        "eggs_per_year": {"lower": 120, "upper": 220},
    },
}


calendar_date = [
    datetime.strptime("2020-01-01", "%Y-%m-%d") + timedelta(i)
    for i in range(0, 365 * 3, 1)
]


def gompertz_weight(
    final_weight: Number, age_weeks: Number, k: Number = 0.30, t_inflect: Number = 9.0
) -> float:
    """
    Estimate chicken weight at a given age using the Gompertz growth model.

    W(t) = A * exp( -exp( -k * (t - t_i) ) )

    Args:
        final_weight (float): Asymptotic (adult) weight A, in kg.
        age_weeks (float): Age t in weeks.
        k (float): Growth-rate parameter (per week). Larger => steeper growth.
        t_inflect (float): Inflection time t_i (weeks). At t = t_i, W = A / e.

    Returns:
        float: Estimated weight at age t (kg).
    """
    if final_weight <= 0:
        raise ValueError("final_weight must be > 0")
    return float(final_weight * math.exp(-math.exp(-k * (age_weeks - t_inflect))))


def eggs_per_day(age_years, E_max, onset_mid, onset_k, decline_mid, decline_k):
    onset = 1.0 / (1.0 + math.exp(-onset_k * (age_years - onset_mid)))
    decline = 1.0 / (1.0 + math.exp(-decline_k * (decline_mid - age_years)))
    return E_max * onset * decline


# Hybrid preset (from the fit)
hybrid = dict(
    E_max=1.05,
    onset_mid=0.7,
    onset_k=5.736082483928185,
    decline_mid=4.5,
    decline_k=1.0952358022404196,
)

# Pure-breed preset (from the fit)
pure = dict(
    E_max=0.9619640365505124,
    onset_mid=1.1,
    onset_k=3.8745574217015415,
    decline_mid=5.008975071779161,
    decline_k=1.7811289846681426,
)

print("Hybrid @ 1.0y:", eggs_per_day(1.0, **hybrid))
print("Pure   @ 1.5y:", eggs_per_day(1.5, **pure))

print(sorted(metadata_obj.tables.keys()))

def start_hatchery():

    used_names = []
    pioneer_chickens = []

    for breed in chicken_breed_attributes.keys():
        ## spawn roosters
        breed = chicken_breed_attributes[breed]

        chosen_name = random.choice(list(set(chicken_name_list) - set(used_names)))
        used_names.append(chosen_name)

        rooster = {
            "name": chosen_name,
            "sex": "R",
            "hatching_date": datetime.strptime("2020-01-01", "%Y-%m-%d")
            - timedelta(math.floor(random.uniform(1.00, 1.50) * 365)),
            "current_weight": round(random.uniform(
                breed["rooster"]["lower"], breed["rooster"]["upper"]
            ),2),
            "breed_id": breed["id"],
            "favourite_song_id": random.randint(1, 100),
        }

        pioneer_chickens.append(rooster)
        ## spawn hens
        for c in range(1, random.randint(3, 5)):
            chosen_name = random.choice(list(set(chicken_name_list) - set(used_names)))
            used_names.append(chosen_name)
            hen = {
                "name": chosen_name,
                "sex": "H",
                "hatching_date": datetime.strptime("2020-01-01","%Y-%m-%d")
                - timedelta(math.floor(random.uniform(1.00, 1.50) * 365)),
                "current_weight": round(random.uniform(
                    breed["rooster"]["lower"], breed["rooster"]["upper"]
                ),2),
                "breed_id": breed["id"],
                "favourite_song_id": random.randint(1, 100),
            }
            pioneer_chickens.append(hen)

    with engine.connect() as connection:
      connection.execute(text("ALTER SEQUENCE chicken_id_seq RESTART WITH 10000"))
      connection.commit()

    with engine.connect() as connection:
      chicken_table = metadata_obj.tables["chicken"]
      connection.execute(delete(chicken_table))
      start_hatchery_stmt = insert(chicken_table).values(pioneer_chickens)
      res = connection.execute(start_hatchery_stmt)
      connection.commit()


start_hatchery()
