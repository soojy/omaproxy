#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
target="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/soojy.omaproxy"
omarchy plugin validate "$source_dir"
if [[ "$source_dir" != "$target" ]]; then
  mkdir -p "$target/scripts" "$target/assets"
  cp "$source_dir/manifest.json" "$source_dir/BarWidget.qml" "$source_dir/README.md" "$source_dir/LICENSE" "$target/"
  cp "$source_dir"/scripts/*.py "$target/scripts/"
  cp "$source_dir/LimitModel.js" "$target/"
  cp "$source_dir"/assets/* "$target/assets/"
fi
omarchy-shell shell rescanPlugins
omarchy plugin enable soojy.omaproxy
echo 'OmaProxy is in your bar. Open it to set up the proxy.'
