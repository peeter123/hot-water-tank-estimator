# Test runner: sshd plus the pinned test requirements and hassfest. See README.md.
FROM ghcr.io/astral-sh/uv:0.13.1-python3.14-trixie-slim

# Never let uv download an interpreter (it would land in root's home, unreadable for the runner user).
# Note: once /opt/venv exists, PATH puts its uv first (Home Assistant's pinned uv), which is fine.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --home-dir /home/runner --shell /bin/bash runner \
    && usermod --password '*' runner \
    && mkdir -p /work /run/sshd /etc/ssh/hostkeys \
    && chown runner:runner /work

# Test requirements go into a fixed venv at build time, so a test run installs nothing.
COPY requirements_test.txt /tmp/requirements_test.txt
RUN uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python -r /tmp/requirements_test.txt \
    && rm /tmp/requirements_test.txt

# hassfest runs from Home Assistant core, at the tag of the homeassistant version in the test venv, in its own venv
# so its extras never change the test environment. That venv gets the test venv's frozen set (wheels proven to
# install here, including pure-Python sdist-only packages such as pyric, so no --only-binary there) plus the extras
# hassfest needs, installed wheels only: a missing wheel fails with a clear message instead of a build attempt
# without a compiler.
COPY docker/test-runner/hassfest_requirements.py /tmp/hassfest_requirements.py
RUN set -eu \
    && echo "== hassfest: tools" \
    && apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && echo "== hassfest: clone core" \
    && HA_VERSION="$(/opt/venv/bin/python -c "import importlib.metadata as m; print(m.version('homeassistant'))")" \
    && echo "homeassistant ${HA_VERSION}" \
    && git clone --depth 1 --branch "${HA_VERSION}" https://github.com/home-assistant/core /opt/ha-core \
    && cd /opt/ha-core \
    && echo "== hassfest: venv from the test venv's frozen set" \
    && uv pip freeze --python /opt/venv/bin/python > /tmp/frozen.txt \
    && uv venv --python /usr/local/bin/python /opt/hassfest-venv \
    && uv pip install --python /opt/hassfest-venv/bin/python -r /tmp/frozen.txt \
    && echo "== hassfest: extras (pipdeptree, tqdm, ruff at core's pins)" \
    && PIPDEPTREE="$(awk -F'==' '/^pipdeptree==/{print $2}' requirements_test.txt)" \
    && TQDM="$(awk -F'==' '/^tqdm==/{print $2}' requirements_test.txt)" \
    && RUFF="$(awk -F'==' '/^ruff==/{print $2}' requirements_test_pre_commit.txt)" \
    && uv pip install --python /opt/hassfest-venv/bin/python --only-binary :all: \
        "pipdeptree==${PIPDEPTREE}" "tqdm==${TQDM}" "ruff==${RUFF}" \
    && echo "== hassfest: requirements of the components it imports" \
    && /opt/venv/bin/python /tmp/hassfest_requirements.py /opt/ha-core > /tmp/components.txt \
    && cat /tmp/components.txt \
    && uv pip install --python /opt/hassfest-venv/bin/python --only-binary :all: \
        -c homeassistant/package_constraints.txt -r /tmp/components.txt \
    && echo "== hassfest: clean up" \
    && rm -rf /opt/ha-core/.git /tmp/frozen.txt /tmp/components.txt /tmp/hassfest_requirements.py \
    && apt-get purge -y --auto-remove git \
    && rm -rf /var/lib/apt/lists/*

COPY docker/test-runner/sshd_config /etc/ssh/sshd_config
COPY docker/test-runner/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker/test-runner/hassfest.sh /usr/local/bin/hassfest
RUN chmod 755 /usr/local/bin/entrypoint.sh /usr/local/bin/hassfest

EXPOSE 2222
VOLUME ["/etc/ssh/hostkeys", "/work"]
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
