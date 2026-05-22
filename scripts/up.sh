#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Decrypt sops dotenv → export each line → docker compose. No plaintext on disk.
while IFS='=' read -r k v; do
  [[ -z "$k" || "$k" == \#* ]] && continue
  export "$k=$v"
done < <(sops -d --input-type dotenv --output-type dotenv .env.enc)
exec docker compose up -d --build
