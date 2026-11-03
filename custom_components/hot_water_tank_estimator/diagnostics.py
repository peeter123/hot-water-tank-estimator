"""Diagnostics of a tank."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .calibration import PARAMETER_BOUNDS
from .estimator import TankConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TankConfigEntry
) -> dict[str, Any]:
    """Return the options, the model state, the source availability, the recent events and the calibration."""
    estimator = entry.runtime_data
    calibrator = estimator.calibrator
    model = estimator.model
    return {
        "options": dict(entry.options),
        "state": {
            "t_avg": model.t_avg,
            "t_ch": model.t_ch,
            "t_cold": model.t_cold,
            "t_ambient": model.ambient_temperature(dt_util.utcnow()),
            "cold_fraction": model.cold_fraction,
            "outputs": {
                "tank_litres": model.outputs.tank_litres,
                "shower_litres": model.outputs.shower_litres,
                "percent_charged": model.outputs.percent_charged,
                "shower_minutes": model.outputs.shower_minutes,
            },
            "heating": model.heating,
            "shower_detected": model.shower_detected,
            "model": model.to_dict(),
        },
        "sources": estimator.source_availability(),
        "events": estimator.recent_events(),
        "calibration": {
            "parameters": {
                name: {
                    "value": calibrator.value_of(name),
                    "source": calibrator.source_of(name),
                }
                for name in PARAMETER_BOUNDS
            },
            "samples": calibrator.sample_count,
            "last_error": calibrator.last_error,
            "mean_abs_error": calibrator.mean_abs_error(),
            "closures": [closure.as_dict() for closure in calibrator.closures],
            "quiet_estimates": list(calibrator.quiet_estimates),
            "width_estimates": list(calibrator.width_estimates),
            "shower_flow_history": list(calibrator.shower_flows),
            "undo": (
                None
                if calibrator.undo_record is None
                else calibrator.undo_record.as_dict()
            ),
        },
    }
