# Moomoo OpenD Docker

Portable Docker setup for Moomoo OpenD.

## Required environment variables

MOOMOO_LOGIN_ACCOUNT
MOOMOO_LOGIN_PASSWORD

The entrypoint converts the plaintext password to MD5 internally before starting OpenD.

## Start

docker compose up -d --build

## API

Port: 11111
