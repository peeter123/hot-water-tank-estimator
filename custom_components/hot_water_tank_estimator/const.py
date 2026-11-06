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
DEFAULT_AMBIENT_FALLBACK = 3.0  # hours the last ambient sensor reading holds
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
DEFAULT_SHOWER_END_MINUTES = 5.0  # minutes
DEFAULT_NEXT_SHOWER_MINUTES = 5.0  # minutes
DEFAULT_SESSION_GAP = 60.0  # seconds
DEFAULT_MAX_DRAW = 100.0  # litres per reading
DEFAULT_POWER_THRESHOLD = 100.0  # W

# Shower flow (design D6): a detected shower with at least this many minutes of flow is a sample
# of the shower flow history, which keeps the last `SHOWER_HISTORY` samples. The rolling flow of
# a shower in progress covers its last `ROLLING_FLOW_SECONDS` of flow and needs
# `ROLLING_FLOW_MIN_SECONDS` of flow in the shower.
SHOWER_MIN_MINUTES = 3.0
SHOWER_HISTORY = 10
ROLLING_FLOW_SECONDS = 120.0
ROLLING_FLOW_MIN_SECONDS = 60.0

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
# A heating run shorter than this does not mix the tank: it adds its heat but does not charge.
MIN_RUN_MINUTES = 15.0

# Config entry keys. Everything the user sets is stored in the entry options. The tuning values
# use the field names of `ModelOptions`, in the units shown in the options form: the sensor height
# and the thermocline width are percentages there, and fractions in the model.
CONF_VOLUME = "volume"  # litres
CONF_TANK_SENSOR = "tank_sensor"
CONF_SENSOR_HEIGHT = "sensor_height"  # percent
CONF_WATER_METER = "water_meter"
CONF_ENERGY_COUNTER = "energy_counter"
CONF_POWER_SENSOR = "power_sensor"
CONF_HEATING_ACTIVE = "heating_active"
CONF_FLOW_SENSOR = "flow_sensor"
CONF_RETURN_SENSOR = "return_sensor"
CONF_HUMIDITY_SENSORS = "humidity_sensors"
CONF_COLD_SENSOR = "cold_sensor"
CONF_AMBIENT_SENSOR = "ambient_sensor"
CONF_THERMOCLINE_WIDTH = "thermocline_width"  # percent
CONF_LOCKS = "locks"
CONF_HISTORY_DAYS = "history_days"

# The sensor entities the model reads, as keys of the entry options (humidity is a list).
SOURCE_KEYS = (
    CONF_TANK_SENSOR,
    CONF_WATER_METER,
    CONF_ENERGY_COUNTER,
    CONF_POWER_SENSOR,
    CONF_HEATING_ACTIVE,
    CONF_FLOW_SENSOR,
    CONF_RETURN_SENSOR,
    CONF_COLD_SENSOR,
    CONF_AMBIENT_SENSOR,
)

# Limits of the config flow.
MIN_VOLUME = 20.0  # litres
MAX_VOLUME = 2000.0  # litres
MIN_SENSOR_HEIGHT = 20.0  # percent
MAX_SENSOR_HEIGHT = 80.0  # percent
DEFAULT_HISTORY_DAYS = 30
MIN_HISTORY_DAYS = 1
MAX_HISTORY_DAYS = 30

# The first start when the tank sensor has no reading.
FALLBACK_TEMPERATURE = 50.0  # C

# The runtime ticks the model this often; the dispatcher signal carries the entry id.
TICK_MINUTES = 5
SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"
DIAGNOSTIC_EVENTS = 100

# Persistence.
STORAGE_VERSION = 1
STORAGE_SAVE_DELAY = 60  # seconds

# Actions.
SERVICE_SET_TANK_STATE = "set_tank_state"
SERVICE_RECALIBRATE = "recalibrate"
ATTR_TANK_AVERAGE = "tank_average"
ATTR_CHARGED_TEMPERATURE = "charged_temperature"
ATTR_DAYS = "days"
