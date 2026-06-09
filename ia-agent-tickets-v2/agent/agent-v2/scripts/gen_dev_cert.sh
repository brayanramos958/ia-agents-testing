#!/bin/bash
# Generate self-signed certificate for HTTPS development/demo.
# For production: use Let's Encrypt via Caddy or nginx.
set -e

CERT_DIR="/app/certs"
mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "$CERT_DIR/key.pem" \
    -out "$CERT_DIR/cert.pem" \
    -subj "/C=CO/O=ITS/CN=sara-its-demo.local" \
    -addext "subjectAltName=DNS:localhost,DNS:sara-its-demo.local,IP:127.0.0.1" \
    2>/dev/null

echo "✅ Self-signed certificate generated in $CERT_DIR"
ls -la "$CERT_DIR/"
