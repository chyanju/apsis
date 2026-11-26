#!/usr/bin/env bash
# Install the CodeQL CLI bundle (CLI + codeql/python-all) here and this pack's query dependencies.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# pinned; tags at github.com/github/codeql-action/releases
BUNDLE_TAG="${CODEQL_BUNDLE_TAG:-codeql-bundle-v2.25.6}"
PLATFORM="${CODEQL_PLATFORM:-linux64}"   # linux64 | osx64 | win64
URL="https://github.com/github/codeql-action/releases/download/${BUNDLE_TAG}/codeql-bundle-${PLATFORM}.tar.gz"

if [ ! -x "codeql/codeql" ]; then
  echo "Downloading ${BUNDLE_TAG} (${PLATFORM}) ..."
  curl -fL "$URL" -o codeql-bundle.tar.gz
  tar xzf codeql-bundle.tar.gz        # extracts ./codeql/
  rm -f codeql-bundle.tar.gz
fi
export PATH="$HERE/codeql:$PATH"
echo -n "CodeQL: "; codeql version --format=terse || { echo "CLI not runnable"; exit 1; }

if [ -f queries/qlpack.yml ]; then
  codeql pack install queries
fi

echo "Toolchain ready. Smoke test:  CODEQL=$HERE/codeql/codeql python3 run_codeql.py --smoke"
