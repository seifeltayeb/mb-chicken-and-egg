import math
from typing import Union, Dict, List, Tuple
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
    insert,
    select,
    update,
    and_
)
from dotenv import dotenv_values

env_vars = dotenv_values(".env")
if env_vars["chicken_db_conn_uri"]:
    engine = create_engine(env_vars["chicken_db_conn_uri"])
else:
    print("Connection URI not found")

metadata_obj = MetaData()
metadata_obj.reflect(bind=engine, extend_existing=True)

# ---------------------- Configuration ----------------------
RANDOM_SEED = 977122
SIM_DAYS = 365 * 3
TARGET_POPULATION = 1000  # Our goal!

# Biology-ish parameters (with randomization ranges)
EGG_INCUBATION_DAYS_MIN = 19
EGG_INCUBATION_DAYS_MAX = 23  # Natural variation in incubation
CHICK_MATURITY_DAYS_MIN = 110  # Some chicks mature faster
CHICK_MATURITY_DAYS_MAX = 140  # Others take longer
HEN_LAY_PROB_PER_DAY = 0.85  # Base probability, will add individual variation
BROODY_CLUTCH_MIN = 6
BROODY_CLUTCH_MAX = 12  # Variable clutch sizes
BROODY_SIT_ALL_FERTILIZED = True

# Mortality rates (with seasonal and individual variation)
CHICK_MORTALITY_RATE_BASE = 0.0005  # Base rate, will be modified
JUVENILE_MORTALITY_RATE_BASE = 0.0003
ADULT_MORTALITY_RATE_BASE = 0.0001

# Seasonal effects (with some randomness)
SPRING_LAYING_BONUS_MIN = 1.3
SPRING_LAYING_BONUS_MAX = 1.7  # Variable spring boost
WINTER_LAYING_PENALTY_MIN = 0.6
WINTER_LAYING_PENALTY_MAX = 0.9  # Variable winter impact
SUMMER_MORTALITY_INCREASE = 1.1

# Window effect on hatching (with variation)
NEAR_WINDOW_HATCH_BONUS_MIN = 1.15
NEAR_WINDOW_HATCH_BONUS_MAX = 1.35  # Variable window benefits

NUM_INCUBATION_SPOTS = 200  # Increased capacity for more eggs

random.seed(RANDOM_SEED)

# Load chicken names
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
        "egg_colors": ["white", "cream"]
    },
    "Leghorn": {
        "id": 2,
        "rooster": {"lower": 2.4, "upper": 3.4},
        "hen": {"lower": 2.0, "upper": 2.5},
        "k": {"lower": 0.25, "upper": 0.35},
        "t_inflect": {"lower": 8, "upper": 9.5},
        "laying_start": 18,
        "eggs_per_year": {"lower": 280, "upper": 320},
        "egg_colors": ["white"]
    },
    "Minorca": {
        "id": 3,
        "rooster": {"lower": 3.2, "upper": 3.6},
        "hen": {"lower": 2.7, "upper": 3.6},
        "k": {"lower": 0.18, "upper": 0.28},
        "t_inflect": {"lower": 9, "upper": 11},
        "laying_start": 26,
        "eggs_per_year": {"lower": 120, "upper": 220},
        "egg_colors": ["white"]
    },
}

def get_season(date: datetime) -> str:
    """Determine season based on date"""
    month = date.month
    if month in [3, 4, 5]:
        return "spring"
    elif month in [6, 7, 8]:
        return "summer"
    elif month in [9, 10, 11]:
        return "fall"
    else:
        return "winter"

def get_seasonal_modifier(date: datetime, modifier_type: str) -> float:
    """Get seasonal modifier for laying or mortality with randomization"""
    season = get_season(date)
    
    if modifier_type == "laying":
        if season == "spring":
            return random.uniform(SPRING_LAYING_BONUS_MIN, SPRING_LAYING_BONUS_MAX)
        elif season == "winter":
            return random.uniform(WINTER_LAYING_PENALTY_MIN, WINTER_LAYING_PENALTY_MAX)
        else:
            return random.uniform(0.95, 1.05)  # Slight variation in fall/summer
    
    elif modifier_type == "mortality":
        if season == "summer":
            return random.uniform(1.0, SUMMER_MORTALITY_INCREASE + 0.2)  # 1.0 to 1.3
        elif season == "winter":
            return random.uniform(1.0, 1.15)  # Slight winter mortality increase
        else:
            return random.uniform(0.9, 1.1)  # Spring/fall variation
    
    return 1.0

def gompertz_weight(final_weight: Number, age_weeks: Number, k: Number = 0.30, t_inflect: Number = 9.0) -> float:
    """Estimate chicken weight using Gompertz growth model"""
    if final_weight <= 0:
        raise ValueError("final_weight must be > 0")
    return float(final_weight * math.exp(-math.exp(-k * (age_weeks - t_inflect))))

def calculate_mortality_chance(chicken: dict, current_date: datetime) -> float:
    """Calculate daily mortality chance based on age and season with randomization"""
    if chicken["hatching_date"] is None:
        return 0.0
    
    # Ensure consistent datetime comparison
    hatching_date = chicken["hatching_date"]
    if isinstance(hatching_date, datetime):
        age_days = (current_date - hatching_date).days
    else:
        # Convert date to datetime for comparison
        hatching_datetime = datetime.combine(hatching_date, datetime.min.time())
        age_days = (current_date - hatching_datetime).days
    
    seasonal_modifier = get_seasonal_modifier(current_date, "mortality")
    individual_variation = random.uniform(0.7, 1.3)  # Individual health variation
    
    if age_days < 30:
        base_rate = CHICK_MORTALITY_RATE_BASE
    elif age_days < random.randint(CHICK_MATURITY_DAYS_MIN, CHICK_MATURITY_DAYS_MAX):
        base_rate = JUVENILE_MORTALITY_RATE_BASE
    else:
        base_rate = ADULT_MORTALITY_RATE_BASE
    
    return base_rate * seasonal_modifier * individual_variation

def should_hen_lay_today(hen: dict, current_date: datetime, breed_info: dict) -> bool:
    """Determine if hen should lay an egg today with natural variation"""
    if hen["hatching_date"] is None:
        return False
    
    # Ensure we're comparing datetime objects consistently
    hatching_date = hen["hatching_date"]
    if isinstance(hatching_date, datetime):
        age_weeks = (current_date - hatching_date).days / 7
    else:
        # Convert date to datetime for comparison
        hatching_datetime = datetime.combine(hatching_date, datetime.min.time())
        age_weeks = (current_date - hatching_datetime).days / 7
    
    # Check if hen is mature enough to lay (with some individual variation)
    maturity_weeks = breed_info["laying_start"] + random.randint(-2, 3)  # ±2-3 weeks variation
    if age_weeks < maturity_weeks:
        return False
    
    # Apply seasonal modifier with randomization
    seasonal_modifier = get_seasonal_modifier(current_date, "laying")
    
    # Individual hen characteristics (some hens are naturally better layers)
    individual_modifier = random.uniform(0.7, 1.4)  # 30% worse to 40% better
    
    # Base probability with all modifiers
    lay_probability = HEN_LAY_PROB_PER_DAY * seasonal_modifier * individual_modifier
    
    # Add some daily randomness (weather, mood, etc.)
    daily_variation = random.uniform(0.8, 1.2)
    final_probability = lay_probability * daily_variation
    
    # Cap at reasonable maximum
    final_probability = min(final_probability, 0.95)
    
    return random.random() < final_probability

def get_available_laying_spots(connection) -> List[dict]:
    """Get all laying spots from database"""
    laying_spot_table = metadata_obj.tables["laying_spot"]
    spots = connection.execute(select(laying_spot_table)).all()
    return [dict(row._mapping) for row in spots]

def create_laying_spots_if_needed(connection):
    """Create laying spots if they don't exist"""
    laying_spot_table = metadata_obj.tables["laying_spot"]
    existing_spots = connection.execute(select(laying_spot_table)).all()
    
    if len(existing_spots) == 0:
        print("Creating laying spots...")
        spots_data = []
        for i in range(NUM_INCUBATION_SPOTS):
            spots_data.append({
                "location": f"Nest_{i+1}",
                "is_near_window": i < (NUM_INCUBATION_SPOTS // 3)  # 1/3 near windows
            })
        
        connection.execute(insert(laying_spot_table).values(spots_data))
        connection.commit()
        print(f"Created {NUM_INCUBATION_SPOTS} laying spots")

def lay_egg(connection, hen: dict, roosters: List[dict], laying_spots: List[dict], current_date: datetime, breed_info: dict):
    """Create a new egg from a hen - PURE BREEDS ONLY"""
    if not roosters:
        return  # No roosters available for fertilization
    
    # 🧬 BREED PURITY: Filter roosters to same breed as hen
    same_breed_roosters = [r for r in roosters if r["breed_id"] == hen["breed_id"]]
    
    if not same_breed_roosters:
        # No same-breed roosters available - no egg laid to maintain purity
        if random.random() < 0.01:  # Rare warning to avoid spam
            breed_name = None
            for name, info in chicken_breed_attributes.items():
                if info["id"] == hen["breed_id"]:
                    breed_name = name
                    break
            print(f"⚠️  No {breed_name} roosters available for {hen['name']} - maintaining breed purity")
        return
    
    # Choose a random rooster from same breed only
    rooster = random.choice(same_breed_roosters)
    
    # Choose a random laying spot
    laying_spot = random.choice(laying_spots)
    
    # Determine egg color based on breed
    egg_color = random.choice(breed_info["egg_colors"])
    
    # Create unique egg ID
    egg_id = f"egg_{current_date.strftime('%Y%m%d')}_{hen['id']}_{random.randint(1000, 9999)}"
    
    egg_data = {
        "id": egg_id,
        "laying_chicken_id": hen["id"],
        "rooster_id": rooster["id"],
        "egg_color": egg_color,
        "laying_spot_id": laying_spot["id"],
        "laying_date": current_date.date(),
        "hatching_successful": True  # Will be determined later during incubation
    }
    
    egg_table = metadata_obj.tables["egg"]
    connection.execute(insert(egg_table).values([egg_data]))
    
    # Occasional pure breeding confirmation
    if random.random() < 0.05:  # 5% chance to log pure breeding
        # Find breed name from the breed_id
        breed_name = "Unknown"
        for name, info in chicken_breed_attributes.items():
            if info["id"] == hen["breed_id"]:
                breed_name = name
                break
        print(f"🧬 Pure {breed_name}: {hen['name']} + {rooster['name']} → egg at {laying_spot['location']}")

def process_incubating_eggs(connection, current_date: datetime):
    """Process eggs that should hatch today with natural variation"""
    egg_table = metadata_obj.tables["egg"]
    laying_spot_table = metadata_obj.tables["laying_spot"]
    
    # Find eggs that are ready to hatch (with individual incubation time variation)
    # Check eggs laid within the incubation range
    min_hatch_date = current_date.date() - timedelta(days=EGG_INCUBATION_DAYS_MAX)
    max_hatch_date = current_date.date() - timedelta(days=EGG_INCUBATION_DAYS_MIN)
    
    potential_eggs = connection.execute(
        select(egg_table, laying_spot_table.c.is_near_window)
        .join(laying_spot_table, egg_table.c.laying_spot_id == laying_spot_table.c.id)
        .where(
            and_(
                egg_table.c.laying_date >= min_hatch_date,
                egg_table.c.laying_date <= max_hatch_date,
                egg_table.c.hatching_successful == True
            )
        )
    ).all()
    
    hatched_chicks = []
    failed_hatch_eggs = []
    
    for egg_row in potential_eggs:
        egg = dict(egg_row._mapping)
        
        # Calculate actual incubation time for this specific egg
        days_since_laying = (current_date.date() - egg["laying_date"]).days
        
        # Each egg has its own incubation period (genetic + environmental variation)
        individual_incubation_days = random.randint(EGG_INCUBATION_DAYS_MIN, EGG_INCUBATION_DAYS_MAX)
        
        # Only process eggs that have reached their individual incubation time
        if days_since_laying < individual_incubation_days:
            continue
            
        # Calculate hatch success probability with natural variation
        base_hatch_rate = random.uniform(0.88, 0.96)  # Natural variation in base rate
        
        # Window bonus with variation
        if egg["is_near_window"]:
            window_bonus = random.uniform(NEAR_WINDOW_HATCH_BONUS_MIN, NEAR_WINDOW_HATCH_BONUS_MAX)
            hatch_rate = base_hatch_rate * window_bonus
        else:
            hatch_rate = base_hatch_rate
        
        # Seasonal effects with variation
        seasonal_modifier = get_seasonal_modifier(current_date, "mortality")
        hatch_rate = hatch_rate * (1.8 - (seasonal_modifier * 0.8))  # Inverse relationship with variation
        
        # Incubation time effects (eggs that take longer have slightly lower success)
        if individual_incubation_days > 21:
            hatch_rate *= 0.95  # 5% penalty for longer incubation
        elif individual_incubation_days < 20:
            hatch_rate *= 0.92  # 8% penalty for shorter incubation (underdeveloped)
        
        # Add some random daily variation (humidity, temperature fluctuations, etc.)
        daily_variation = random.uniform(0.9, 1.1)
        hatch_rate *= daily_variation
        
        # Cap at reasonable maximum
        hatch_rate = min(hatch_rate, 0.98)
        
        if random.random() < hatch_rate:
            # Successful hatch - create new chick
            used_names = get_used_names(connection)
            available_names = list(set(chicken_name_list) - set(used_names))
            
            if available_names:
                chick_name = random.choice(available_names)
                # Natural sex ratio with slight variation
                chick_sex = random.choices(["H", "R"], weights=[52, 48])[0]  # Slightly more hens
                
                # Get breed info from parent
                parent_chicken = connection.execute(
                    select(metadata_obj.tables["chicken"])
                    .where(metadata_obj.tables["chicken"].c.id == egg["laying_chicken_id"])
                ).first()
                
                if parent_chicken:
                    breed_id = parent_chicken.breed_id
                    
                    # 🧬 BREED PURITY: Verify parents are same breed (they should be due to pure breeding)
                    father_chicken = connection.execute(
                        select(metadata_obj.tables["chicken"])
                        .where(metadata_obj.tables["chicken"].c.id == egg["rooster_id"])
                    ).first()
                    
                    # Confirm pure breeding worked
                    if father_chicken and parent_chicken.breed_id == father_chicken.breed_id:
                        breed_status = "pure"
                    else:
                        breed_status = "mixed"  # Shouldn't happen with pure breeding
                        print(f"⚠️  Unexpected mixed breeding detected in egg {egg['id']}")
                    
                    # Variable birth weight
                    birth_weight = round(random.uniform(0.025, 0.055), 3)  # 25-55g variation
                    
                    chick_data = {
                        "name": chick_name,
                        "sex": chick_sex,
                        "hatching_date": current_date.date(),
                        "current_weight": birth_weight,
                        "egg_id": egg["id"],
                        "breed_id": breed_id,
                        "favourite_song_id": random.randint(1, 100),
                        "expired": False
                    }
                    
                    hatched_chicks.append(chick_data)
                    if random.random() < 0.1:  # Only print 10% of hatches to reduce spam
                        breed_name = None
                        for name, info in chicken_breed_attributes.items():
                            if info["id"] == breed_id:
                                breed_name = name
                                break
                        print(f"🐣 Pure {breed_name} chick '{chick_name}' hatched after {individual_incubation_days} days ({'window' if egg['is_near_window'] else 'interior'})")
        else:
            # Failed to hatch
            failed_hatch_eggs.append(egg["id"])
            if random.random() < 0.05:  # Only print 5% of failures
                print(f"💀 Egg {egg['id']} failed to hatch after {individual_incubation_days} days")
    
    # Insert new chicks
    if hatched_chicks:
        chicken_table = metadata_obj.tables["chicken"]
        connection.execute(insert(chicken_table).values(hatched_chicks))
    
    # Mark failed eggs
    if failed_hatch_eggs:
        connection.execute(
            update(egg_table)
            .where(egg_table.c.id.in_(failed_hatch_eggs))
            .values(hatching_successful=False)
        )
    
    connection.commit()
    return len(hatched_chicks)

def get_used_names(connection) -> List[str]:
    """Get all currently used chicken names"""
    chicken_table = metadata_obj.tables["chicken"]
    chickens = connection.execute(
        select(chicken_table.c.name)
        .where(chicken_table.c.expired == False)
    ).all()
    return [row.name for row in chickens]

def update_chicken_weights(connection, current_date: datetime):
    """Update weights of growing chickens"""
    chicken_table = metadata_obj.tables["chicken"]
    living_chickens = connection.execute(
        select(chicken_table)
        .where(chicken_table.c.expired == False)
    ).all()
    
    for chicken_row in living_chickens:
        chicken = dict(chicken_row._mapping)
        if chicken["hatching_date"] is None:
            continue
        
        # Ensure consistent datetime comparison
        hatching_date = chicken["hatching_date"]
        if isinstance(hatching_date, datetime):
            age_weeks = (current_date - hatching_date).days / 7
        else:
            # Convert date to datetime for comparison
            hatching_datetime = datetime.combine(hatching_date, datetime.min.time())
            age_weeks = (current_date - hatching_datetime).days / 7
        
        # Get breed info
        breed_name = None
        for name, info in chicken_breed_attributes.items():
            if info["id"] == chicken["breed_id"]:
                breed_name = name
                break
        
        if breed_name:
            breed_info = chicken_breed_attributes[breed_name]
            
            if chicken["sex"] == "R":
                final_weight = random.uniform(breed_info["rooster"]["lower"], breed_info["rooster"]["upper"])
            else:
                final_weight = random.uniform(breed_info["hen"]["lower"], breed_info["hen"]["upper"])
            
            k = random.uniform(breed_info["k"]["lower"], breed_info["k"]["upper"])
            t_inflect = random.uniform(breed_info["t_inflect"]["lower"], breed_info["t_inflect"]["upper"])
            
            new_weight = gompertz_weight(final_weight, age_weeks, k, t_inflect)
            
            connection.execute(
                update(chicken_table)
                .where(chicken_table.c.id == chicken["id"])
                .values(current_weight=round(new_weight, 3))
            )
    
    connection.commit()

def run_daily_simulation(current_date: datetime):
    """Run one day of the simulation"""
    
    with engine.connect() as connection:
        # Check current population
        chicken_table = metadata_obj.tables["chicken"]
        current_population = connection.execute(
            select(chicken_table)
            .where(chicken_table.c.expired == False)
        ).rowcount
        
        # If we've reached our target, celebrate and continue monitoring
        if current_population >= TARGET_POPULATION:
            if current_date.day == 1:  # Monthly celebration
                print(f"\n🎉 TARGET ACHIEVED! {current_population} chickens on {current_date.date()}")
            return current_population
        
        # Ensure laying spots exist
        create_laying_spots_if_needed(connection)
        
        # Get current state
        living_chickens = connection.execute(
            select(chicken_table)
            .where(chicken_table.c.expired == False)
        ).all()
        
        chickens = [dict(row._mapping) for row in living_chickens]
        hens = [c for c in chickens if c["sex"] == "H"]
        roosters = [c for c in chickens if c["sex"] == "R"]
        
        # Show population progress
        season = get_season(current_date)
        if current_date.day % 10 == 0:  # Every 10 days
            progress = (current_population / TARGET_POPULATION) * 100
            print(f"\n📊 Day {(current_date - datetime.strptime('2020-01-01', '%Y-%m-%d')).days}")
            print(f"   Population: {current_population}/1000 ({progress:.1f}%) - {len(hens)}H, {len(roosters)}R")
            print(f"   Season: {season}")
        
        # Get laying spots
        laying_spots = get_available_laying_spots(connection)
        
        # 🧬 BREED PURITY: Group chickens by breed for monitoring
        breed_groups = {}
        for chicken in chickens:
            breed_id = chicken["breed_id"]
            if breed_id not in breed_groups:
                breed_groups[breed_id] = {"hens": [], "roosters": [], "breed_name": ""}
                
            # Get breed name
            for name, info in chicken_breed_attributes.items():
                if info["id"] == breed_id:
                    breed_groups[breed_id]["breed_name"] = name
                    break
            
            if chicken["sex"] == "H":
                breed_groups[breed_id]["hens"].append(chicken)
            else:
                breed_groups[breed_id]["roosters"].append(chicken)
        
        # Process egg laying by breed to ensure pure breeding
        eggs_laid_today = 0
        breeding_warnings = []
        
        for breed_id, group in breed_groups.items():
            breed_hens = group["hens"]
            breed_roosters = group["roosters"]
            breed_name = group["breed_name"]
            
            if not breed_roosters and breed_hens:
                breeding_warnings.append(f"No {breed_name} roosters for {len(breed_hens)} hens")
                continue
            
            # Process each hen in this breed
            for hen in breed_hens:
                if should_hen_lay_today(hen, current_date, chicken_breed_attributes[breed_name]):
                    lay_egg(connection, hen, breed_roosters, laying_spots, current_date, chicken_breed_attributes[breed_name])
                    eggs_laid_today += 1
        
        # Process hatching
        chicks_hatched = process_incubating_eggs(connection, current_date)
        
        # Process mortality
        deceased_chickens = []
        
        for chicken_row in living_chickens:
            chicken = dict(chicken_row._mapping)
            mortality_chance = calculate_mortality_chance(chicken, current_date)
            
            if random.random() < mortality_chance:
                deceased_chickens.append(chicken["id"])
                # Calculate age for reporting
                if chicken["hatching_date"]:
                    hatching_date = chicken["hatching_date"]
                    if isinstance(hatching_date, datetime):
                        age_days = (current_date - hatching_date).days
                    else:
                        hatching_datetime = datetime.combine(hatching_date, datetime.min.time())
                        age_days = (current_date - hatching_datetime).days
                else:
                    age_days = "unknown"
                
                if current_date.day % 10 == 0:  # Only print occasionally to reduce spam
                    print(f"💀 {chicken['name']} has died at age {age_days} days")
        
        # Mark chickens as expired
        if deceased_chickens:
            connection.execute(
                update(chicken_table)
                .where(chicken_table.c.id.in_(deceased_chickens))
                .values(expired=True)
            )
            connection.commit()
        
        # Update weights weekly
        if current_date.day % 7 == 0:
            update_chicken_weights(connection, current_date)
        
        # Daily summary for significant events
        if eggs_laid_today > 0 or chicks_hatched > 0:
            print(f"   📈 {eggs_laid_today} eggs laid, {chicks_hatched} chicks hatched")
        
        # Show breeding warnings occasionally
        if breeding_warnings and current_date.day % 10 == 0:
            for warning in breeding_warnings:
                print(f"   ⚠️  {warning}")
        
        return current_population

def start_hatchery():
    """Create initial breeding population optimized for growth"""
    used_names = []
    pioneer_chickens = []
    
    # Start with more chickens for faster growth
    for breed in chicken_breed_attributes.keys():
        breed_info = chicken_breed_attributes[breed]
        
        # Create 2-3 roosters per breed for genetic diversity
        for r in range(random.randint(2, 3)):
            chosen_name = random.choice(list(set(chicken_name_list) - set(used_names)))
            used_names.append(chosen_name)
            
            # Randomize age slightly
            age_variation = random.randint(-60, 60)  # ±2 months variation
            hatching_date = datetime.strptime("2020-01-01", "%Y-%m-%d") - timedelta(
                days=math.floor(random.uniform(0.8, 1.2) * 365) + age_variation
            )
            
            rooster = {
                "name": chosen_name,
                "sex": "R",
                "hatching_date": hatching_date,
                "current_weight": round(random.uniform(
                    breed_info["rooster"]["lower"], breed_info["rooster"]["upper"]
                ), 2),
                "breed_id": breed_info["id"],
                "favourite_song_id": random.randint(1, 100),
                "expired": False
            }
            pioneer_chickens.append(rooster)
        
        # Create 8-12 hens per breed for maximum egg production
        for h in range(random.randint(8, 12)):
            chosen_name = random.choice(list(set(chicken_name_list) - set(used_names)))
            used_names.append(chosen_name)
            
            # Randomize age slightly
            age_variation = random.randint(-45, 45)  # ±1.5 months variation
            hatching_date = datetime.strptime("2020-01-01", "%Y-%m-%d") - timedelta(
                days=math.floor(random.uniform(0.8, 1.2) * 365) + age_variation
            )
            
            hen = {
                "name": chosen_name,
                "sex": "H",
                "hatching_date": hatching_date,
                "current_weight": round(random.uniform(
                    breed_info["hen"]["lower"], breed_info["hen"]["upper"]
                ), 2),
                "breed_id": breed_info["id"],
                "favourite_song_id": random.randint(1, 100),
                "expired": False
            }
            pioneer_chickens.append(hen)
    
    return pioneer_chickens

def run_growth_optimized_simulation():
    """Run simulation optimized to reach 1000 chickens"""
    print("🎯 GOAL: Reach 1000 chickens!")
    print("Starting optimized growth simulation...\n")
    
    # Initialize with breeding population
    with engine.connect() as connection:
        connection.execute(text("ALTER SEQUENCE chicken_id_seq RESTART WITH 10000"))
        connection.commit()
        
        chicken_table = metadata_obj.tables["chicken"]
        connection.execute(delete(chicken_table))
        
        pioneer_chickens = start_hatchery()
        start_hatchery_stmt = insert(chicken_table).values(pioneer_chickens)
        connection.execute(start_hatchery_stmt)
        connection.commit()
        
        print(f"🐔 Started with {len(pioneer_chickens)} breeding chickens")
    
    start_date = datetime.strptime("2020-01-01", "%Y-%m-%d")
    target_reached = False
    target_day = None
    
    for day_offset in range(SIM_DAYS):
        current_date = start_date + timedelta(days=day_offset)
        current_population = run_daily_simulation(current_date)
        
        # Check if we reached our target
        if current_population >= TARGET_POPULATION and not target_reached:
            target_reached = True
            target_day = day_offset
            years = target_day / 365
            print(f"\n🎉🎉🎉 SUCCESS! 🎉🎉🎉")
            print(f"🏆 Reached {current_population} chickens on day {target_day} ({years:.1f} years)")
            print(f"📅 Date: {current_date.date()}")
            
            # Continue for a bit to see stable population
            continue
        
        # Stop if we've been above target for 30 days (stable)
        if target_reached and day_offset > target_day + 30:
            break
        
        # Monthly detailed reports
        if day_offset % 30 == 0 and day_offset > 0:
            with engine.connect() as connection:
                chicken_table = metadata_obj.tables["chicken"]
                egg_table = metadata_obj.tables["egg"]
                
                living_chickens = connection.execute(
                    select(chicken_table)
                    .where(chicken_table.c.expired == False)
                ).all()
                
                total_eggs = connection.execute(select(egg_table)).rowcount
                hatched_eggs = connection.execute(
                    select(egg_table)
                    .where(egg_table.c.hatching_successful == True)
                ).rowcount
                
                hens = [c for c in living_chickens if c.sex == "H"]
                roosters = [c for c in living_chickens if c.sex == "R"]
                
                # 🧬 BREED PURITY: Detailed breed breakdown
                breed_breakdown = {}
                for chicken in living_chickens:
                    breed_id = chicken.breed_id
                    if breed_id not in breed_breakdown:
                        breed_breakdown[breed_id] = {"hens": 0, "roosters": 0, "name": ""}
                        for name, info in chicken_breed_attributes.items():
                            if info["id"] == breed_id:
                                breed_breakdown[breed_id]["name"] = name
                                break
                    
                    if chicken.sex == "H":
                        breed_breakdown[breed_id]["hens"] += 1
                    else:
                        breed_breakdown[breed_id]["roosters"] += 1
                
                print(f"\n📊 MONTH {day_offset//30} REPORT ({current_date.strftime('%B %Y')}):")
                print(f"   🐔 Population: {len(living_chickens)} ({len(hens)} hens, {len(roosters)} roosters)")
                
                # Show breed-specific breakdown
                for breed_id, counts in breed_breakdown.items():
                    breed_total = counts["hens"] + counts["roosters"]
                    print(f"   └─ {counts['name']}: {breed_total} ({counts['hens']}H, {counts['roosters']}R)")
                
                print(f"   🥚 Total eggs: {total_eggs}")
                print(f"   🐣 Hatched: {hatched_eggs} ({hatched_eggs/total_eggs*100:.1f}% success)" if total_eggs > 0 else "   🐣 No eggs yet")
                print(f"   📈 Progress: {len(living_chickens)}/1000 ({len(living_chickens)/10:.1f}%)")
                
                if not target_reached:
                    estimated_days = (TARGET_POPULATION - len(living_chickens)) / max(1, (len(living_chickens) - len(pioneer_chickens)) / day_offset) if day_offset > 0 else "calculating..."
                    if isinstance(estimated_days, (int, float)):
                        print(f"   ⏰ Estimated days to target: {estimated_days:.0f}")

if __name__ == "__main__":
    run_growth_optimized_simulation()
    
    # Final comprehensive statistics
    with engine.connect() as connection:
        chicken_table = metadata_obj.tables["chicken"]
        egg_table = metadata_obj.tables["egg"]
        
        all_chickens = connection.execute(select(chicken_table)).all()
        living_chickens = [c for c in all_chickens if not c.expired]
        deceased_chickens = [c for c in all_chickens if c.expired]
        
        total_eggs = connection.execute(select(egg_table)).all()
        hatched_eggs = [e for e in total_eggs if e.hatching_successful]
        
        hens = [c for c in living_chickens if c.sex == "H"]
        roosters = [c for c in living_chickens if c.sex == "R"]
        
        # 🧬 FINAL BREED PURITY ANALYSIS
        breed_analysis = {}
        for chicken in living_chickens:
            breed_id = chicken.breed_id
            if breed_id not in breed_analysis:
                breed_analysis[breed_id] = {"hens": 0, "roosters": 0, "total": 0, "name": ""}
                for name, info in chicken_breed_attributes.items():
                    if info["id"] == breed_id:
                        breed_analysis[breed_id]["name"] = name
                        break
            
            breed_analysis[breed_id]["total"] += 1
            if chicken.sex == "H":
                breed_analysis[breed_id]["hens"] += 1
            else:
                breed_analysis[breed_id]["roosters"] += 1
        
        print(f"\n" + "="*50)
        print(f"🏆 FINAL CHICKEN EMPIRE STATISTICS 🏆")
        print(f"="*50)
        print(f"🐔 Final living population: {len(living_chickens)}")
        print(f"   └─ 🐓 Hens: {len(hens)}")
        print(f"   └─ 🐓 Roosters: {len(roosters)}")
        
        # 🧬 BREED BREAKDOWN
        print(f"\n🧬 PURE BREED BREAKDOWN:")
        for breed_id, analysis in breed_analysis.items():
            percentage = (analysis["total"] / len(living_chickens)) * 100
            print(f"   └─ {analysis['name']}: {analysis['total']} chickens ({percentage:.1f}%)")
            print(f"      • {analysis['hens']} hens, {analysis['roosters']} roosters")
        
        print(f"\n💀 Total deceased: {len(deceased_chickens)}")
        print(f"🥚 Total eggs laid: {len(total_eggs)}")
        print(f"🐣 Successfully hatched: {len(hatched_eggs)}")
        print(f"📊 Overall hatch rate: {len(hatched_eggs)/len(total_eggs)*100:.1f}%" if total_eggs else "No eggs")
        print(f"🎯 Target achieved: {'✅ YES' if len(living_chickens) >= TARGET_POPULATION else '❌ NO'}")
        
        # 🧬 BREED PURITY STATUS
        print(f"\n🧬 BREED PURITY STATUS: ✅ MAINTAINED")
        print(f"   • All chickens are purebred (no cross-breeding allowed)")
        print(f"   • Genetic integrity preserved across all breeds")
        
        if len(living_chickens) >= TARGET_POPULATION:
            print(f"\n🎉 Congratulations! Your pure-breed chicken empire has reached {len(living_chickens)} chickens!")
            print(f"🏆 Achievement: 1000+ chickens with maintained breed purity!")
        else:
            print(f"\n📈 Keep growing! You need {TARGET_POPULATION - len(living_chickens)} more chickens.")
            
        # Show any breed balance issues
        print(f"\n⚖️  BREED BALANCE ANALYSIS:")
        for breed_id, analysis in breed_analysis.items():
            if analysis["roosters"] == 0 and analysis["hens"] > 0:
                print(f"   ⚠️  {analysis['name']}: NO ROOSTERS - breeding stopped!")
            elif analysis["roosters"] > 0 and analysis["hens"] == 0:
                print(f"   ⚠️  {analysis['name']}: NO HENS - no egg production!")
            elif analysis["total"] > 0:
                ratio = analysis["hens"] / max(1, analysis["roosters"])
                print(f"   ✅ {analysis['name']}: {ratio:.1f} hens per rooster (optimal: 8-12)")
        
        print(f"\n🔬 Run the lineage SQL queries to explore family relationships!")