#!/usr/bin/env bash

if [ -n "${BASH_VERSION:-}" ]; then
    set -euo pipefail
else
    # `curl ... | sh` may use a POSIX shell without pipefail support.
    set -eu
fi

SOURCE="${ONESKILL_SOURCE:-https://github.com/yxhuang/oneskill.git}"
INSTALL_DIR="${HOME:?HOME must be set}/.local/share/oneskill"
BIN_DIR="$HOME/.local/bin"
LINK_PATH="$BIN_DIR/osk"

info() {
    printf '==> %s\n' "$1"
}

error() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

command -v git >/dev/null 2>&1 || error "git is required to install oneskill."

mkdir -p "$(dirname "$INSTALL_DIR")"

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating oneskill in $INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only
elif [ -e "$INSTALL_DIR" ]; then
    error "$INSTALL_DIR already exists but is not a Git checkout; leaving it unchanged."
else
    info "Installing oneskill into $INSTALL_DIR"
    git clone "$SOURCE" "$INSTALL_DIR"
fi

mkdir -p "$BIN_DIR"

if [ -e "$LINK_PATH" ] && [ ! -L "$LINK_PATH" ]; then
    error "$LINK_PATH already exists and is not a symlink; leaving it unchanged."
fi

ln -sfn "$INSTALL_DIR/bin/osk" "$LINK_PATH"
info "Linked $LINK_PATH -> $INSTALL_DIR/bin/osk"

case ":${PATH:-}:" in
    *":$BIN_DIR:"*)
        ;;
    *)
        printf '\nNote: %s is not currently on PATH.\n' "$BIN_DIR"
        printf 'Add this line to your shell rc file (for example ~/.bashrc or ~/.zshrc):\n'
        printf '  export PATH="$HOME/.local/bin:$PATH"\n'
        ;;
esac

printf '\nInstallation complete. Next steps:\n'
printf '  osk init\n'
printf '  osk scan --write\n'
printf '  osk list\n'
