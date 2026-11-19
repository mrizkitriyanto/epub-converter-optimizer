#!/usr/bin/env bash
set -euo pipefail

image=${1:?usage: docker-smoke.sh IMAGE}
token=smoke-token-123456
first=$(docker run -d -p 127.0.0.1::8000 -e ECO_TOKEN="$token" "$image")
second=
cleanup() {
  docker rm -f "$first" >/dev/null 2>&1 || true
  if [ -n "$second" ]; then docker rm -f "$second" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

port=$(docker port "$first" 8000/tcp | sed -n 's/.*://p' | head -n 1)
url="http://127.0.0.1:$port"
ready=0
for _ in $(seq 1 60); do
  if [ "$(curl -sS -o /dev/null -w '%{http_code}' "$url/api/health" 2>/dev/null)" = 200 ]; then
    ready=1
    break
  fi
  sleep 1
done
[ "$ready" = 1 ] || { docker logs "$first"; exit 1; }

[ "$(curl -sS -o /dev/null -w '%{http_code}' "$url/")" = 401 ]
[ "$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $token" "$url/")" = 200 ]
docker exec "$first" sh -c "printf '# A\\n\\nText.\\n' > /data/a.md && eco convert /data/a.md --data /data && test -f /data/a.x4.epub"

second=$(docker run -d "$image")
found=0
for _ in $(seq 1 30); do
  if docker logs "$second" 2>&1 | grep -q '?token='; then found=1; break; fi
  sleep 1
done
[ "$found" = 1 ] || { docker logs "$second"; exit 1; }
echo 'Docker smoke passed'
