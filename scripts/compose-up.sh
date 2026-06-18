#!/usr/bin/env bash
set -euo pipefail

BUILD_INFO_FILE=".build-info.json"

git_commit_count="$(git rev-list --count HEAD)"
built_at="$(date -Iseconds)"

previous_git_commit_count=""
previous_compose_build_number="-1"

if [ -f "$BUILD_INFO_FILE" ]; then
  previous_git_commit_count="$(python3 -c "import json; print(json.load(open('$BUILD_INFO_FILE')).get('git_commit_count', ''))")"
  previous_compose_build_number="$(python3 -c "import json; print(json.load(open('$BUILD_INFO_FILE')).get('compose_build_number', -1))")"
fi

if [ "$previous_git_commit_count" = "$git_commit_count" ]; then
  compose_build_number=$((previous_compose_build_number + 1))
else
  compose_build_number=0
fi

version="v ${git_commit_count}.${compose_build_number}"

python3 - <<PY
import json

data = {
    "git_commit_count": int("$git_commit_count"),
    "compose_build_number": int("$compose_build_number"),
    "version": "$version",
    "built_at": "$built_at",
}

with open("$BUILD_INFO_FILE", "w", encoding="utf-8") as file:
    json.dump(data, file, ensure_ascii=False, indent=2)
    file.write("\\n")
PY

echo "Build info updated: $version, $built_at"

docker compose -f infra/docker-compose.yml --env-file .env up -d --build --remove-orphans --force-recreate "$@"
