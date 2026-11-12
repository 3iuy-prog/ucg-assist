#!/bin/sh
# 로컬 .env 에 DJANGO_SECRET_KEY 를 만든다. 이미 있으면 그대로 둔다(키가 바뀌면 세션이 모두 끊긴다).
set -eu
cd "$(dirname "$0")/.."
if [ -f .env ] && grep -q '^DJANGO_SECRET_KEY=.' .env; then
  echo ".env 에 DJANGO_SECRET_KEY 가 이미 있습니다."
  exit 0
fi
umask 077
key=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')
printf 'DJANGO_SECRET_KEY=%s\n' "$key" >> .env
mkdir -p db
echo ".env 를 만들었습니다(값은 출력하지 않습니다)."
