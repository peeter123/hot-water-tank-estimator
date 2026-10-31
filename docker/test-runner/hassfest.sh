#!/bin/sh
# Validate the integration in the synced source folder (first argument) with Home Assistant's hassfest.
# Exit status 255 means the runner itself is broken (the client treats it as a tool failure).
src="${1:?usage: hassfest SOURCE_DIR [HASSFEST_ARGS...]}"
shift
export PATH="/opt/hassfest-venv/bin:${PATH}"  # hassfest runs ruff from PATH
cd /opt/ha-core || exit 255
exec /opt/hassfest-venv/bin/python -m script.hassfest --action validate \
    --integration-path "${src}/custom_components/hot_water_tank_estimator" "$@"
