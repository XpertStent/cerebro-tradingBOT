#!/bin/bash
set -e

if [ -n "${MOOMOO_LOGIN_PASSWORD:-}" ]; then
    PASSWORD_MD5=$(printf '%s' "$MOOMOO_LOGIN_PASSWORD" | md5sum | awk '{print $1}')

    exec ./OpenD \
      -login_account="${MOOMOO_LOGIN_ACCOUNT}" \
      -login_pwd_md5="${PASSWORD_MD5}" \
      -api_ip=0.0.0.0 \
      -api_port=11111
else
    exec ./OpenD \
      -login_account="${MOOMOO_LOGIN_ACCOUNT}" \
      -login_by_remember=1 \
      -api_ip=0.0.0.0 \
      -api_port=11111
fi
