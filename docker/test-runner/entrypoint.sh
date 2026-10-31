#!/bin/sh
# Install the authorized keys, create the missing host key, then run sshd in the foreground.
set -eu

if [ -z "${AUTHORIZED_KEYS:-}" ]; then
    echo "AUTHORIZED_KEYS is not set" >&2
    exit 1
fi

install -d -m 700 -o runner -g runner /home/runner/.ssh
printf '%s\n' "${AUTHORIZED_KEYS}" > /home/runner/.ssh/authorized_keys
chown runner:runner /home/runner/.ssh/authorized_keys
chmod 600 /home/runner/.ssh/authorized_keys

# The host key lives in a volume, so clients' known_hosts stays valid across rebuilds.
key=/etc/ssh/hostkeys/ssh_host_ed25519_key
if [ ! -f "${key}" ]; then
    ssh-keygen -q -t ed25519 -N '' -f "${key}"
fi
chmod 600 "${key}"

chown runner:runner /work
exec /usr/sbin/sshd -D -e
