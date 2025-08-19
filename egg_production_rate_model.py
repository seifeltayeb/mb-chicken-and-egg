from datetime import datetime,timedelta
def hybrid_hen_production(age_years):
    """
    Returns weekly egg production for hybrid hens based on age in years.
    
    Args:
        age_years (float): Age of hen in years
        
    Returns:
        float: Eggs per week (0-7)
    """
    if age_years <= 0:
        return 0.0
    elif age_years <= 1.0:  # Linear rise to peak
        daily_rate = 0.95 * age_years
    elif age_years <= 1.5:  # Plateau with slight decline
        daily_rate = 0.95 - 0.06 * (age_years - 1.0)
    elif age_years <= 6.0:  # Polynomial decline
        x = age_years - 1.5
        daily_rate = 0.92 - 0.08 * x - 0.11 * x**2
    else:
        daily_rate = 0.0
    
    # Convert daily rate to weekly production (multiply by 7)
    weekly_production = max(0.0, daily_rate * 7)
    return weekly_production

def purebred_hen_production(age_years):
    """
    Returns weekly egg production for pure-breed hens based on age in years.
    
    Args:
        age_years (float): Age of hen in years
        
    Returns:
        float: Eggs per week (0-7)
    """
    if age_years <= 0:
        return 0.0
    elif age_years <= 1.5:  # Linear rise to peak
        daily_rate = 0.92 * (age_years / 1.5)
    elif age_years <= 2.0:  # Plateau with slight decline
        daily_rate = 0.92 - 0.06 * (age_years - 1.5)
    elif age_years <= 6.0:  # Polynomial decline
        x = age_years - 2.0
        daily_rate = 0.89 - 0.06 * x - 0.10 * x**2
    else:
        daily_rate = 0.0
    
    # Convert daily rate to weekly production (multiply by 7)
    weekly_production = max(0.0, daily_rate * 7)
    return weekly_production
