#!/bin/sh
set -eu

UNIFONT_VER="17.0.03"
BASE_URL="https://unifoundry.com/pub/unifont/unifont-${UNIFONT_VER}/font-builds"
SIGNING_KEY_URL="https://unifoundry.com/1A09227B1F435A33_public.asc"

FONT_GZ="unifont_all-${UNIFONT_VER}.hex.gz"
SIG="${FONT_GZ}.sig"
OUT="unifont_all-${UNIFONT_VER}.hex"

for cmd in curl gpg gzip; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "error: required tool '$cmd' not found" >&2
        exit 1
    }
done

echo "Downloading Unifont ${UNIFONT_VER}..."
curl -fsSLO "${BASE_URL}/${FONT_GZ}"
curl -fsSLO "${BASE_URL}/${SIG}"

curl -fsSL "${SIGNING_KEY_URL}" -o unifoundry-signing-key.asc
gpg --import unifoundry-signing-key.asc

if ! gpg --list-keys >/dev/null 2>&1; then
    echo "warning: no GPG keys present; signature verification will fail" >&2
fi

echo "Verifying signature..."
gpg --verify "${SIG}" "${FONT_GZ}"

echo "Unpacking font..."
gzip -dc "${FONT_GZ}" > "${OUT}"
