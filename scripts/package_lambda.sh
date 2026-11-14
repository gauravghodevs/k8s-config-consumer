#!/usr/bin/env bash
set -euo pipefail

YQ_VERSION="v4.44.3"
YQ_SHA256="a2c097180dd884a8d50c956ee16a9cec070f30a7947cf4ebf87d5f36213e9ed7"
STAGE_DIR=$(mktemp -d)
trap 'rm -rf "$STAGE_DIR"' EXIT

wget -qO "${STAGE_DIR}/yq" "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_amd64"
echo "${YQ_SHA256}${STAGE_DIR}/yq" | sha256sum -c - >/dev/null
chmod +x "${STAGE_DIR}/yq"

cp lambda/bootstrap "${STAGE_DIR}/bootstrap"
cp consumer/schema/rules.schema.json "${STAGE_DIR}/rules.schema.json"
chmod +x "${STAGE_DIR}/bootstrap"

rm -f config-validator-lambda.zip
(cd "$STAGE_DIR" && zip -q "${OLDPWD}/config-validator-lambda.zip" bootstrap yq rules.schema.json)
echo "Packaged config-validator-lambda.zip cleanly without dirtying lambda/"
