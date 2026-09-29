#!/usr/bin/env bash
# Lädt die GitHub CLI (gh) als einzelnes Binary nach bin/ – nur für dependabotbot, ohne systemweite Installation.
# Erneut ausführen, um auf die neueste Version zu aktualisieren.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")/.."

case "$(uname -m)" in
  x86_64) arch=amd64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *) echo "Nicht unterstützte Architektur: $(uname -m)" >&2; exit 1 ;;
esac

version="$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))')"
name="gh_${version}_linux_${arch}"
base="https://github.com/cli/cli/releases/download/v${version}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

curl -fsSL -o "$tmp/$name.tar.gz" "$base/$name.tar.gz"
curl -fsSL -o "$tmp/checksums.txt" "$base/gh_${version}_checksums.txt"
(cd "$tmp" && grep " $name.tar.gz\$" checksums.txt | sha256sum --check --quiet)

tar -xzf "$tmp/$name.tar.gz" -C "$tmp"
mkdir -p bin
install -m 755 "$tmp/$name/bin/gh" bin/gh
echo "gh $version nach bin/gh installiert."
