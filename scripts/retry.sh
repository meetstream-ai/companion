#!/usr/bin/env bash
#
# Retry a command a few times with growing pauses.
#
#     scripts/retry.sh npm ci
#
# Release builds pull Electron, npm and PyPI artifacts from CDNs that
# occasionally answer 5xx. Electron's postinstall is the fragile one: it
# fetches its binary with its own HTTP client, so npm's fetch-retries setting
# does not cover it, and a single gateway timeout failed the whole release and
# skipped publishing. Wrapping the network steps means a flake costs a pause
# instead of a re-run.
set -uo pipefail

attempts=${RETRY_ATTEMPTS:-3}
delay=${RETRY_DELAY:-15}

for (( attempt = 1; attempt <= attempts; attempt++ )); do
    "$@" && exit 0
    status=$?
    if (( attempt == attempts )); then
        echo "::error::'$*' failed after ${attempts} attempts (exit ${status})"
        exit "${status}"
    fi
    echo "::warning::'$*' failed (exit ${status}); retrying in ${delay}s [${attempt}/${attempts}]"
    sleep "${delay}"
    delay=$(( delay * 2 ))
done
