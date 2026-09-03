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
# Which icon that is comes from steam_core.py rather than from a list here,
# because the answer is not obvious and is worth having in one place: Valve's
# own, from inside the client's installation, and never Debian's
# /usr/share/icons/hicolor/256x256/apps/steam.png, which belongs to
# `steam-installer` and is a picture of cardboard boxes.
USED=$(python3 -c "import sys; sys.path.insert(0, '$REPO'); import steam_core; \
print(steam_core.refresh_tile('$REPO/media/_steam.png') or '')")
if [ -n "$USED" ]; then
  echo "menu tile from $USED"
else
  echo "no ~/.kodi/media/consoles; skipped (only kodi-retrobox uses it)"
fi

say "the Kodi add-on"
LINK="$HOME/.kodi/addons/script.steam"
if [ -d "$HOME/.kodi/addons" ]; then
  # Already where Kodi looks? Then there is nothing to link, and trying is
  # worse than doing nothing: `ln -sfn dir dir` does not replace a directory
  # with a link to itself, it puts a link *inside* it. kodi-retrobox clones
  # this repository straight into ~/.kodi/addons/script.steam, so this is the
  # ordinary case there rather than a corner of one.
  if [ "$(readlink -f "$REPO")" = "$(readlink -f "$LINK" 2>/dev/null)" ]; then
    echo "already in ~/.kodi/addons; nothing to link"
  else
    ln -sfn "$REPO" "$LINK"
    echo "linked into ~/.kodi/addons"
  fi
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

say "telling Kodi about it"
# Two things Kodi will not work out for itself.
#
# It registers an add-on it finds on disk with enabled=0, and then answers
# RunScript(script.steam) with "Not executing non-existing script" -- which
# reads as a broken add-on and is really a switch nobody has thrown.
#
# And it caches every image it draws, by path. The tile was replaced above,
# at the same path, so without this the old picture is what stays on the
# menu -- which looked exactly like the copy having silently failed.
python3 - <<'TELL' || echo "could not finish; enable it in Settings -> Add-ons -> My add-ons -> Program add-ons -> Steam"
import base64, glob, json, os, re, sqlite3, subprocess, sys, time, urllib.request

ADDON = "script.steam"
TILE = "_steam.png"
home = os.path.expanduser("~")
addon_dbs = sorted(glob.glob(os.path.join(home, ".kodi/userdata/Database/Addons*.db")))
texture_dbs = sorted(glob.glob(os.path.join(home, ".kodi/userdata/Database/Textures*.db")))
running = subprocess.run(["pgrep", "-x", "kodi.bin"],
                         capture_output=True).returncode == 0
settings = os.path.join(home, ".kodi/userdata/guisettings.xml")
text = open(settings, encoding="utf-8").read() if os.path.exists(settings) else ""


def setting(name, default=""):
    found = re.search(r'<setting id="%s"[^>]*>([^<]*)</setting>' % name, text)
    return found.group(1) if found else default


def call(method, params):
    """One JSON-RPC call to the Kodi that is running."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
    url = "http://127.0.0.1:%s/jsonrpc" % setting("services.webserverport", "8080")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    if setting("services.webserverauthentication", "true") == "true":
        pair = "%s:%s" % (setting("services.webserverusername", "kodi"),
                          setting("services.webserverpassword"))
        request.add_header("Authorization",
                           "Basic " + base64.b64encode(pair.encode()).decode())
    return json.load(urllib.request.urlopen(request, timeout=15))


def enabled_in_db():
    if not addon_dbs:
        return None
    con = sqlite3.connect("file:%s?mode=ro" % addon_dbs[-1], uri=True)
    try:
        row = con.execute("select enabled from installed where addonID=?",
                          (ADDON,)).fetchone()
    finally:
        con.close()
    return None if row is None else bool(row[0])


def forget_tile_while_running():
    got = call("Textures.GetTextures",
               {"filter": {"field": "url", "operator": "contains", "value": TILE},
                "properties": ["url"]})
    cached = got.get("result", {}).get("textures", [])
    for one in cached:
        call("Textures.RemoveTexture", {"textureid": one["textureid"]})
    return len(cached)


def forget_tile_while_stopped():
    if not texture_dbs:
        return 0
    con = sqlite3.connect(texture_dbs[-1])
    with con:
        rows = list(con.execute("select id, cachedurl from texture "
                                "where url like ?", ("%" + TILE + "%",)))
        for _id, cachedurl in rows:
            # The picture as well as the row: a row without its file is
            # rebuilt, a file without its row is never looked at again.
            try:
                os.remove(os.path.join(home, ".kodi/userdata/Thumbnails", cachedurl))
            except OSError:
                pass
        con.execute("delete from texture where url like ?", ("%" + TILE + "%",))
    con.close()
    return len(rows)


if running:
    if setting("services.webserver") != "true":
        print("Kodi is running and its web service is off, so it cannot be "
              "asked to enable the add-on or to forget the old tile.")
        print("Either turn on Settings -> Services -> Control -> Allow remote "
              "control via HTTP, or close Kodi and run this again.")
        sys.exit(1)
    if enabled_in_db():
        print("already enabled")
    else:
        # Through Kodi itself, because it holds this in memory while it runs
        # and writes it back on the way out: an edit made underneath a running
        # Kodi is undone at the next shutdown, silently.
        answer = call("Addons.SetAddonEnabled", {"addonid": ADDON, "enabled": True})
        if answer.get("result") != "OK":
            print("Kodi would not enable it: %s" % answer)
            sys.exit(1)
        print("enabled")
    print("dropped %d cached copy(ies) of the menu tile" % forget_tile_while_running())
    sys.exit(0)

# Kodi is not running, so its databases are ours to write -- which is what
# kodi-retrobox's kodi-setup.sh does for every add-on at install time.
if not addon_dbs:
    print("no add-on database yet; run Kodi once, then run this again")
    sys.exit(1)
con = sqlite3.connect(addon_dbs[-1])
now = time.strftime("%Y-%m-%d %H:%M:%S")
with con:
    if enabled_in_db() is None:
        con.execute("insert into installed(addonID, enabled, installDate) "
                    "values(?, 1, ?)", (ADDON, now))
    else:
        con.execute("update installed set enabled=1, disabledReason=0 "
                    "where addonID=?", (ADDON,))
con.close()
print("enabled in %s" % os.path.basename(addon_dbs[-1]))
print("dropped %d cached copy(ies) of the menu tile" % forget_tile_while_stopped())
TELL

say "done"
echo "Open it from Kodi: Programs -> Steam, or RunScript(script.steam)."
