#!/bin/bash
set -e

exec ./OpenD \
  -api_ip=0.0.0.0 \
  -api_port=11111
