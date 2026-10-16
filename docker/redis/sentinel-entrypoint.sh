#!/bin/sh
# Starts one Redis Sentinel.
#
# Monitors and announces fixed IPs, not hostnames: see docker-compose.yml for why.
#
# The config file is written only on first start. After a failover, Sentinel rewrites this
# file to record the *new* primary; regenerating it on every restart would make a restarted
# sentinel monitor the old (demoted) primary again. /data is a named volume per sentinel.
set -eu

CONF=/data/sentinel.conf
if [ ! -f "$CONF" ]; then
  cat > "$CONF" <<EOF
port 26379
dir /data
sentinel announce-ip ${SENTINEL_ANNOUNCE_HOST}
sentinel monitor ${REDIS_MASTER_NAME} ${REDIS_PRIMARY_HOST} 6379 ${SENTINEL_QUORUM}
sentinel down-after-milliseconds ${REDIS_MASTER_NAME} 5000
sentinel failover-timeout ${REDIS_MASTER_NAME} 20000
sentinel parallel-syncs ${REDIS_MASTER_NAME} 1
EOF
fi
exec redis-sentinel "$CONF"
