#!/bin/bash
set -e

# Create log directory for supervisor
mkdir -p /var/log/supervisor

# /tmp is writable by default in the container. If mounted from host (-v /tmp:/tmp),
# we cannot chmod it; rely on host permissions.

# Start supervisord
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
