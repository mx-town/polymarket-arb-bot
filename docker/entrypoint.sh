#!/bin/bash
set -e

# Create log directory for supervisor
mkdir -p /var/log/supervisor

# Ensure /tmp is writable for IPC files
chmod 1777 /tmp

# Start supervisord
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
