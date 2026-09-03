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
# kodi-retrobox builds its home menu from ~/.kodi/media/consoles and looks for
# _steam.png there. Anywhere else this is harmless: nothing reads it.
#
# Valve's own icon if this machine has one, which it does the moment Steam is
# installed: it is the icon somebody is looking for on a menu, and no drawing
# of mine is going to be recognised faster than the real one. What this
# repository ships is a fallback rather than a preference -- a trademark is a
# poor thing to vendor into a project, and a machine with no Steam on it yet
# still needs a tile.
ICON="$REPO/media/_steam.png"
for candidate in /usr/share/icons/hicolor/256x256/apps/steam.png \
                 /usr/share/icons/hicolor/48x48/apps/steam.png \
                 /usr/share/pixmaps/steam.png; do
  [ -f "$candidate" ] && { ICON="$candidate"; break; }
done
if [ -d "$HOME/.kodi/media/consoles" ]; then
  cp -f "$ICON" "$HOME/.kodi/media/consoles/_steam.png"
  echo "menu tile from $ICON"
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

say "telling Kodi it may run it"
# Finding an add-on and being willing to run it are two different things. Kodi
# registers one it finds on disk with enabled=0, and then answers
# RunScript(script.steam) with "Not executing non-existing script" -- which
# reads as a broken add-on and is really a switch nobody has thrown. Nobody at
# a television has any reason to guess that, so this throws it.
python3 - <<'ENABLE' || echo "could not enable it here; turn it on in Settings -> Add-ons -> My add-ons -> Program add-ons -> Steam"
import base64, glob, json, os, re, sqlite3, subprocess, sys, time, urllib.request

ADDON = "script.steam"
home = os.path.expanduser("~")
dbs = sorted(glob.glob(os.path.join(home, ".kodi/userdata/Database/Addons*.db")))
running = subprocess.run(["pgrep", "-x", "kodi.bin"],
                         capture_output=True).returncode == 0


def enabled_in_db():
    if not dbs:
        return None
    con = sqlite3.connect("file:%s?mode=ro" % dbs[-1], uri=True)
    try:
        row = con.execute("select enabled from installed where addonID=?",
                          (ADDON,)).fetchone()
    finally:
        con.close()
    return None if row is None else bool(row[0])


if enabled_in_db():
    print("already enabled")
    sys.exit(0)

if running:
    # Through Kodi itself, because Kodi holds this in memory while it runs and
    # writes it back on the way out: an edit made underneath it is undone at
    # the next shutdown, silently.
    settings = os.path.join(home, ".kodi/userdata/guisettings.xml")
    text = open(settings, encoding="utf-8").read() if os.path.exists(settings) else ""

    def setting(name, default=""):
        found = re.search(r'<setting id="%s"[^>]*>([^<]*)</setting>' % name, text)
        return found.group(1) if found else default

    if setting("services.webserver") != "true":
        print("Kodi is running and its web service is off, so it cannot be "
              "asked to enable the add-on.")
        print("Either turn on Settings -> Services -> Control -> Allow remote "
              "control via HTTP, or close Kodi and run this again.")
        sys.exit(1)
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": "Addons.SetAddonEnabled",
                       "params": {"addonid": ADDON, "enabled": True}}).encode()
    url = "http://127.0.0.1:%s/jsonrpc" % setting("services.webserverport", "8080")
    request = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
    if setting("services.webserverauthentication", "true") == "true":
        pair = "%s:%s" % (setting("services.webserverusername", "kodi"),
                          setting("services.webserverpassword"))
        request.add_header("Authorization",
                           "Basic " + base64.b64encode(pair.encode()).decode())
    answer = json.load(urllib.request.urlopen(request, timeout=10))
    if answer.get("result") != "OK":
        print("Kodi would not enable it: %s" % answer)
        sys.exit(1)
    print("Kodi has been told to enable it")
    sys.exit(0)

# Kodi is not running, so its database is ours to write -- which is what
# kodi-retrobox's kodi-setup.sh does for every add-on at install time.
if not dbs:
    print("no add-on database yet; run Kodi once, then run this again")
    sys.exit(1)
con = sqlite3.connect(dbs[-1])
now = time.strftime("%Y-%m-%d %H:%M:%S")
with con:
    if enabled_in_db() is None:
        con.execute("insert into installed(addonID, enabled, installDate) "
                    "values(?, 1, ?)", (ADDON, now))
    else:
        con.execute("update installed set enabled=1, disabledReason=0 "
                    "where addonID=?", (ADDON,))
con.close()
print("enabled in %s" % os.path.basename(dbs[-1]))
ENABLE

say "done"
echo "Open it from Kodi: Programs -> Steam, or RunScript(script.steam)."
