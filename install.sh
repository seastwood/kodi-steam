#!/bin/sh
# Install the Steam add-on for the current user.
#
# Idempotent: safe to run again after a pull. This repository is the add-on, so
# the link points at the checkout itself and a pull is all an update takes.
#
# Steam itself is not installed here. The add-on does that, from the sofa, the
# first time somebody chooses it -- which is the whole point of the privileged
# helper this puts in place. A machine that never wants Steam never downloads
# it.
set -eu

REPO="$(cd "$(dirname "$0")" && pwd)"
LIBEXEC=/usr/local/libexec/kodi-steam-install

say() { printf '\n== %s\n' "$1"; }

say "the tests"
for t in "$REPO"/tests/test_*.py; do
  python3 "$t" >/dev/null || { echo "FAILED: $t"; exit 1; }
  echo "passed: $(basename "$t")"
done

say "window tools"
# The add-on raises Steam over Kodi with these. Without them Steam starts and
# stays behind the menu it was started from, which looks exactly like a launch
# that did nothing.
MISSING=""
for tool in wmctrl xdotool; do
  command -v "$tool" >/dev/null 2>&1 || MISSING="$MISSING $tool"
done
if [ -n "$MISSING" ]; then
  echo "installing:$MISSING"
  sudo apt-get update -qq
  # shellcheck disable=SC2086
  sudo apt-get install -y $MISSING
else
  echo "wmctrl and xdotool are here"
fi

say "the installer helper"
# Asked for rather than assumed: it needs a password now so that nobody needs
# one later, in front of a television, and a machine where Steam is already
# installed does not need it at all.
if command -v steam >/dev/null 2>&1; then
  echo "steam is already installed, so the helper is not needed"
  echo "(install it anyway with: $0 --helper)"
  WANT_HELPER=0
else
  WANT_HELPER=1
fi
case "${1:-}" in
  --helper) WANT_HELPER=1 ;;
  # For a machine being set up over SSH, where a sudo prompt has no terminal to
  # appear on, and for anybody who would rather not have the rule at all: the
  # add-on falls back to Flathub, which needs no root.
  --no-helper) WANT_HELPER=0 ;;
esac

if [ "$WANT_HELPER" = 1 ]; then
  sudo install -D -m 0755 "$REPO/system/kodi-steam-install" "$LIBEXEC"
  sudo install -D -m 0440 "$REPO/system/kodi-steam-sudoers" /etc/sudoers.d/kodi-steam
  # A malformed sudoers file locks the machine out of sudo entirely, so check
  # it and take it straight back out if it does not parse.
  if sudo visudo -cf /etc/sudoers.d/kodi-steam >/dev/null; then
    echo "installed $LIBEXEC, and the rule that lets the add-on run it"
  else
    sudo rm -f /etc/sudoers.d/kodi-steam
    echo "the sudoers rule did not parse and was removed;" >&2
    echo "the add-on will offer the Flathub version instead" >&2
  fi
fi

say "the menu icon"
# kodi-retrobox builds its home menu from ~/.kodi/media/consoles, and looks for
# _steam.png there. Anywhere else this is harmless: nothing reads it.
if [ -d "$HOME/.kodi/media/consoles" ]; then
  cp -f "$REPO/media/_steam.png" "$HOME/.kodi/media/consoles/_steam.png"
  echo "copied _steam.png into ~/.kodi/media/consoles"
else
  echo "no ~/.kodi/media/consoles; skipped (only kodi-retrobox uses it)"
fi

say "the Kodi add-on"
if [ -d "$HOME/.kodi/addons" ]; then
  ln -sfn "$REPO" "$HOME/.kodi/addons/script.steam"
  echo "linked into ~/.kodi/addons"
  # Kodi reads its add-on list once, at startup. Until it rescans, the add-on
  # is on disk and unknown -- and a menu entry pointing at it answers with
  # "you need to install this add-on", which sounds like a packaging fault
  # rather than a stale cache.
  if pgrep -x kodi.bin >/dev/null 2>&1 && [ -x /usr/bin/kodi-send ]; then
    kodi-send --action="UpdateLocalAddons" >/dev/null 2>&1 || true
    echo "asked the running Kodi to rescan its add-ons"
    echo "if it still offers to install it, restart Kodi once --"
    echo "a rescan does not always take for a brand new add-on"
  fi
else
  echo "no ~/.kodi/addons yet; run Kodi once, then run this again"
fi

say "done"
echo "Open it from Kodi: Programs -> Steam, or RunScript(script.steam)."
