#!/bin/sh
# LOCAL DEVELOPMENT ONLY: SQLite, e-mails to the DEV OUTBOX, http://127.0.0.1:8800 (never expose this to clients).
set -eu
cd "$(dirname "$0")"
export MQC_ENV=dev MQC_DATABASE_URL="sqlite:///$(pwd)/dev-data/central.sqlite" MQC_PUBLIC_URL=http://127.0.0.1:8800 \
       MQC_MAIL_MODE=dev-outbox MQC_SECURE_COOKIES=0 MQC_SIGNING_KEY_FILE="$(pwd)/dev-data/lease.pem" MQC_ENV_FILE=/nonexistent
[ -f dev-data/data_key ] || { mkdir -p dev-data; python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())" > dev-data/data_key; }
export MQC_DATA_KEY="$(cat dev-data/data_key)"
[ -f dev-data/lease.pem ] || python -m mqcentral gen-keys --out dev-data/lease.pem >/dev/null
python -m mqcentral migrate
python -m mqcentral serve --port 8800
