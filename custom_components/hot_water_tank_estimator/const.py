"""Constants for the Hot Water Tank Estimator integration."""

DOMAIN = "hot_water_tank_estimator"

# Physics. Volumetric heat capacity of water near 20-60 C, in Wh per litre and kelvin.
WATER_HEAT_CAPACITY_WH = 1.163

# Defaults of the tuning values: the numbers of the integration-setup defaults scenarios.
# Fractions are stored as fractions (0.5 is a sensor height of 50 %), temperatures in C.
DEFAULT_SENSOR_HEIGHT = 0.5  # fraction of the tank from the bottom
DEFAULT_THERMOCLINE_WIDTH = 0.35  # fraction of the tank
DEFAULT_USABLE_FRACTION = 0.85
DEFAULT_MIX_TEMPERATURE = 38.0  # C
DEFAULT_MAX_TEMPERATURE = 95.0  # C
DEFAULT_SENSOR_TOLERANCE = 1.5  # K
DEFAULT_SENSOR_MARGIN = 2.0  # K
DEFAULT_AMBIENT_TEMPERATURE = 20.0  # C
DEFAULT_COLD_MEAN = 12.5  # C
DEFAULT_COLD_AMPLITUDE = 5.0  # K
DEFAULT_COLD_COLDEST_DAY = 46  # day of the year

DEFAULT_LOSS_COEFFICIENT = 0.004  # per hour
DEFAULT_OTHER_HOT_SHARE = 0.2
DEFAULT_STARTUP_ENERGY = 0.0  # kWh
DEFAULT_SHOWER_FLOW = 7.5  # L/min
DEFAULT_HUMIDITY_RISE = 6.0  # percentage points
DEFAULT_HUMIDITY_WINDOW = 60.0  # minutes
DEFAULT_LONG_DRAW_MINUTES = 0.0  # 0 is off
DEFAULT_RECLASSIFY_WINDOW = 10.0  # minutes
DEFAULT_SESSION_GAP = 60.0  # seconds
DEFAULT_MAX_DRAW = 100.0  # litres per reading
DEFAULT_POWER_THRESHOLD = 100.0  # W

# Fixed model constants, not options.
# The counter timeout finds the end of a run this long after the last energy counter increase;
# the run itself ended at that increase.
HEATING_TIMEOUT_SECONDS = 600.0
CHARGE_WINDOW_SECONDS = (
    120.0  # flow and return are read over this window before a run ends
)
DETECTOR_HOLD_SECONDS = (
    900.0  # an unavailable heating detector holds the state this long
)
# Counter increases this long after a run ended still count towards that run's energy.
COUNTER_LAG_SECONDS = 600.0
