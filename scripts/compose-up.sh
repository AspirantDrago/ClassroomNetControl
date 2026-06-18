#!/usr/bin/env bash
set -euo pipefail

./scripts/update-build-info.sh

docker compose -f infra/docker-compose.yml --env-file .env up -d --build --force-recreate "$@"
