#!/bin/bash
# Sign the Mac app with KinoDraw's own self-signed identity (the same recipe as a local signing certificate),
# so every release keeps the same code-signing requirement and macOS keeps saved sign-ins across updates without
# asking again. It is not Apple notarization: a first-time user still clicks Open Anyway once.
#
#   MACOS_SIGN_P12=<base64 of the .p12> MACOS_SIGN_P12_PASSWORD=... packaging/sign-macos.sh "dist/KinoDraw.app"
#
# CI takes both values from repository secrets; the private key never enters git. It runs on a throwaway runner:
# codesign only uses a trusted identity, so the certificate is trusted for code signing there (needs sudo).
set -euo pipefail
app="$1"
: "${MACOS_SIGN_P12:?set MACOS_SIGN_P12 (base64 of the .p12)}"
: "${MACOS_SIGN_P12_PASSWORD:?set MACOS_SIGN_P12_PASSWORD}"
tmp="${RUNNER_TEMP:-$(mktemp -d)}"
kc="$tmp/doodle-sign.keychain-db"
kcpass="$(openssl rand -hex 16)"

echo "$MACOS_SIGN_P12" | base64 --decode > "$tmp/identity.p12"
security create-keychain -p "$kcpass" "$kc"
security set-keychain-settings -lut 3600 "$kc"
security unlock-keychain -p "$kcpass" "$kc"
security import "$tmp/identity.p12" -k "$kc" -P "$MACOS_SIGN_P12_PASSWORD" -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S apple-tool:,apple: -s -k "$kcpass" "$kc" >/dev/null
rm -f "$tmp/identity.p12"
security list-keychains -d user -s "$kc" $(security list-keychains -d user | tr -d '"')

security find-certificate -a -p "$kc" > "$tmp/signing-cert.pem"
sudo security add-trusted-cert -d -r trustRoot -p codeSign -k /Library/Keychains/System.keychain "$tmp/signing-cert.pem"
id=$(security find-identity -v -p codesigning "$kc" | awk 'NR==1 && $2 ~ /^[0-9A-F]{40}$/ {print $2}')
[ -n "$id" ] || { echo "no valid signing identity after import" >&2; exit 1; }

codesign --force --deep --sign "$id" --keychain "$kc" "$app"
codesign --verify --deep --strict "$app"
codesign -d -r- "$app" 2>&1 | grep 'certificate leaf'      # the stable requirement, not a per-build cdhash
