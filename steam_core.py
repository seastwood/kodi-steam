"""Finding Steam, installing it if it is not here, and starting Big Picture.

Nothing in this file imports Kodi. Everything is paths and subprocesses, so
the tests can run it on a laptop with neither Kodi nor Steam on it -- which is
also why every command goes through `sh()` rather than being called directly:
one function to stub, and no test can start a two-gigabyte download by
accident.

Two ways Steam can be here, and they are not equivalent. A native package gets
at controllers through udev the way everything else on this machine does; the
Flatpak is sandboxed, and the sandbox is exactly the sort of thing that ends
with a pad that works everywhere except in the one place you sat down to use
it. So native is preferred and Flatpak is the fallback -- but the fallback
earns its place, because it installs without root at all, and a machine where
nobody has set up the privileged helper can still get Steam from the sofa.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import time

FLATPAK_APP = "com.valvesoftware.Steam"

# The flag that starts the interface a controller drives. `-bigpicture` is the
# older name and current clients still answer to it, but they call this one the
# gamepad UI, which is the thing being asked for.
BIG_PICTURE = "-gamepadui"

# The privileged half, installed by install.sh: a fixed script that installs
# one named package, with a sudoers rule naming that script and nothing else.
# apt itself is never handed to sudo -- `apt-get install ./anything.deb` runs a
# maintainer script as root, so a rule permitting apt permits everything.
HELPER = "/usr/local/libexec/kodi-steam-install"

# Steam takes its time on a cold start: the client updates itself before it
# draws anything. A minute is long enough for that on a slow line and short
# enough that a launch which is never going to work does not sit there for
# ever.
WAIT_FOR_WINDOW = 60.0
POLL = 0.5
# Kodi runs fullscreen and takes the foreground back, so being raised once is
# not enough -- the same finding pcgame_launch.py was written around.
RAISE_TRIES = 8
RAISE_GAP = 0.7


# The three ways this module reaches the outside world, named so a test can
# replace them. Nothing else here calls subprocess, and nothing else asks the
# filesystem whether a picture is there.
popen = subprocess.Popen
exists = os.path.isfile


def sh(*argv, **kw):
    """Run a command and return its output, or "" if it could not be run.

    Everything this module does to the outside world goes through here.
    """
    timeout = kw.get("timeout", 20)
    try:
        done = subprocess.run(list(argv), capture_output=True, text=True,
                              timeout=timeout, env=environment())
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout


def environment():
    """The environment a program started from Kodi needs.

    Kodi's own environment has DISPLAY in it, but a script run through
    kodi-send or a service may not, and a Steam that cannot find the display
    exits immediately with nothing on screen to say why.
    """
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    return env


# Where Debian and Ubuntu put game binaries. On the path of an interactive
# shell, by way of /etc/profile -- and that is the whole problem: Kodi is
# started by a session manager, and what a login shell would have put in PATH
# is not something a program inheriting the session's environment can count
# on. The console this was written for does have it; another machine having it
# is luck, and a Steam that is installed but invisible is the worst of both
# answers, because the add-on would offer to install what is already there.
GAME_BINS = ("/usr/games", "/usr/local/games")


def native():
    """Steam from a package, if it is anywhere this can find it."""
    found = shutil.which("steam")
    if found:
        return found
    for folder in GAME_BINS:
        candidate = os.path.join(folder, "steam")
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def flatpak_app():
    """Whether the Flatpak is installed, for this user or system-wide."""
    if not shutil.which("flatpak"):
        return False
    listed = sh("flatpak", "list", "--app", "--columns=application")
    return any(line.strip() == FLATPAK_APP for line in listed.splitlines())


def launch_argv():
    """How to start Big Picture here, or None if Steam is not installed."""
    exe = native()
    if exe:
        return [exe, BIG_PICTURE]
    if flatpak_app():
        return ["flatpak", "run", FLATPAK_APP, BIG_PICTURE]
    return None


def installed():
    return launch_argv() is not None


def install_route():
    """How Steam could be installed here: (name, argv), or (None, None).

    Native first, for the reason at the top of this file. The helper has to
    exist -- without it there is no way to reach apt from a Kodi add-on that
    does not involve a password prompt on a television.
    """
    if os.path.exists(HELPER):
        return "apt", ["sudo", "-n", HELPER]
    if shutil.which("flatpak"):
        return "flatpak", ["flatpak", "install", "--user", "--assumeyes",
                           "--noninteractive", "flathub", FLATPAK_APP]
    return None, None


# Where Valve's own icon is, in the order worth trying.
#
# Not /usr/share/icons/hicolor/*/apps/steam.png first, and on Debian and
# Ubuntu not at all: there, that file belongs to `steam-installer` and is a
# picture of cardboard boxes -- the packaging system's idea of a package,
# which is honest about what the package is and nothing like what somebody
# scanning a menu for Steam is looking for. It was the obvious path, it is
# named exactly right, and it is wrong.
#
# The client brings the real one with it, so these all live inside an
# installation rather than in the distribution's icon theme.
ICON_PATHS = (
    "~/.steam/debian-installation/deb-installer/steam-launcher/icons/256/steam.png",
    "~/.steam/root/deb-installer/steam-launcher/icons/256/steam.png",
    "~/.local/share/Steam/deb-installer/steam-launcher/icons/256/steam.png",
    "~/.local/share/flatpak/app/com.valvesoftware.Steam/current/active/files/"
    "share/icons/hicolor/256x256/apps/com.valvesoftware.Steam.png",
    "/var/lib/flatpak/app/com.valvesoftware.Steam/current/active/files/"
    "share/icons/hicolor/256x256/apps/com.valvesoftware.Steam.png",
)

# The distribution's own, which is right on distributions that package the
# real client and wrong on the ones that package an installer for it. Asked
# about rather than assumed, since the file cannot be told apart by looking.
THEME_ICON = "/usr/share/icons/hicolor/256x256/apps/steam.png"

# Where kodi-retrobox's menu looks for the tile.
TILE = "~/.kodi/media/consoles/_steam.png"


def theme_icon_is_valves():
    """Whether the icon theme's steam.png came with Steam or with an installer.

    dpkg knows who put it there. `steam-installer` is the package whose icon
    is a stack of boxes; anything else -- Arch's `steam`, a distribution that
    ships the client itself -- put Valve's own there.
    """
    if not exists(THEME_ICON):
        return False
    if not shutil.which("dpkg"):
        return True                     # not a dpkg distribution: trust it
    owner = sh("dpkg", "-S", THEME_ICON)
    return bool(owner) and "steam-installer" not in owner


def best_icon():
    """Valve's icon if this machine has one, else None."""
    for path in ICON_PATHS:
        full = os.path.expanduser(path)
        if exists(full):
            return full
    return THEME_ICON if theme_icon_is_valves() else None


def refresh_tile(fallback=None):
    """Put the best icon available on the menu tile. Returns what it used.

    Called at install time and again after Steam itself is installed, because
    the good icon does not exist until the client does -- the first time this
    runs on a machine there is nothing but the fallback, and the second time
    there is Valve's own.
    """
    tile = os.path.expanduser(TILE)
    if not os.path.isdir(os.path.dirname(tile)):
        return None                     # no kodi-retrobox here; nothing reads it
    source = best_icon() or fallback
    if not source or not exists(source):
        return None
    try:
        with open(source, "rb") as reading:
            data = reading.read()
        if os.path.exists(tile):
            with open(tile, "rb") as existing:
                if existing.read() == data:
                    return tile         # already right; do not disturb the cache
        with open(tile, "wb") as writing:
            writing.write(data)
    except OSError:
        return None
    return source


# ---- who else is holding a controller, and what it can reach ----------------
#
# Fourth Player wires a guest in another house to a virtual pad on this
# machine. That pad is read by whatever has the foreground, which is the whole
# reason Fourth Player now withholds a guest's frames while Steam's own
# interface is in front. One gap survives that, and it is the gap this warning
# exists for: from *inside* a Steam game, the Steam button opens the overlay,
# and the foreground window is still the game -- so the frames keep flowing and
# the overlay is a store with a saved card in it.
#
# Family View is the answer to that, and it is Valve's rather than ours: a PIN
# in front of the store, the settings and the library. So before Big Picture
# goes up in front of guests who are already connected, it is worth asking
# whether that PIN exists.

CONTROL_SOCKET = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                              "fourth-player.sock")
LOCALCONFIG = "~/.steam/debian-installation/userdata/*/config/localconfig.vdf"
LOCALCONFIGS = (
    LOCALCONFIG,
    "~/.steam/steam/userdata/*/config/localconfig.vdf",
    "~/.local/share/Steam/userdata/*/config/localconfig.vdf",
)


def guests_connected():
    """(session open, how many guests) according to Fourth Player itself.

    Asked over its control socket rather than read out of its files: the
    socket is the interface it offers, the files are its business, and one of
    them holds the session's credentials.

    Anything at all going wrong is "no session": this is a question asked
    before starting Steam, and a machine with no Fourth Player on it must not
    be interrogated about one.
    """
    try:
        import socket as socketlib
        with socketlib.socket(socketlib.AF_UNIX, socketlib.SOCK_STREAM) as sock:
            sock.settimeout(3)
            sock.connect(CONTROL_SOCKET)
            sock.sendall(b'{"cmd": "status"}\n')
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        answer = json.loads(data or b"{}")
    except Exception:                 # noqa: BLE001 - no session, whatever the reason
        return False, 0
    if not answer.get("open"):
        return False, 0
    guests = answer.get("guests")
    if isinstance(guests, list):
        guests = len(guests)
    return True, int(guests or 0)


def family_view():
    """"off", or "unknown" -- and never "on".

    Steam keeps this in localconfig.vdf as a signed binary blob under
    ParentalSettings. Whether the blob is *there* is a fact worth reading:
    with no block and no settings, Family View has never been set up on this
    machine and the answer is a confident "off".

    What the blob says is another matter. It is undocumented, signed, and
    Valve's to change, and a wrong guess in the reassuring direction is the
    one mistake this must not make -- so it is never decoded, and a machine
    that has one is "unknown" rather than "on". Unknown is asked about once
    and then remembered, because crying wolf at every launch is how a warning
    becomes something people learn to dismiss.
    """
    for pattern in LOCALCONFIGS:
        for path in sorted(glob.glob(os.path.expanduser(pattern))):
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
            except OSError:
                continue
            block = re.search(r'"ParentalSettings"\s*\{(.*?)\}', text, re.S)
            if not block:
                return "off"
            settings = re.search(r'"settings"\s*"([^"]*)"', block.group(1))
            return "unknown" if settings and settings.group(1).strip() else "off"
    return "off"


def can_flatpak():
    """Whether the Flathub route is available at all."""
    return bool(shutil.which("flatpak"))


def flatpak_route():
    """The Flathub route on its own, for when the package route has failed."""
    return "flatpak", ["flatpak", "install", "--user", "--assumeyes",
                       "--noninteractive", "flathub", FLATPAK_APP]


def install(argv, on_line=None):
    """Run an install, feeding each line of output to `on_line`.

    Returns (ok, tail). The tail is the last few lines, which is what a
    failure has to be explained with: apt says why on the line before it
    stops, and a dialog saying "it failed" without that is a dead end.

    Line by line rather than at the end, because this is a download somebody
    is watching a progress bar for, and a bar that says nothing for four
    minutes is indistinguishable from one that has hung.
    """
    try:
        proc = popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     text=True, env=environment())
    except OSError as exc:
        return False, str(exc)
    tail = []
    for line in proc.stdout:
        line = line.rstrip()
        tail.append(line)
        del tail[:-6]
        if on_line:
            on_line(line)
    code = proc.wait()
    return code == 0, "\n".join(tail)


def running():
    """Whether Steam is already up.

    By process name rather than by window: the client can be running with no
    window at all -- minimised to the tray, or still starting -- and starting a
    second one is how you get two clients arguing over the same account.
    """
    out = sh("ps", "-eo", "comm")
    names = {line.strip() for line in out.splitlines()}
    return bool(names & {"steam", "steamwebhelper"})


def window():
    """The largest window that looks like Steam, or None.

    Largest rather than first, and for the same reason pcgame_launch.py picks
    that way: Steam maps small helper windows -- the update box, the tray icon
    -- alongside the one worth looking at, and raising a 1x1 window puts
    nothing on the screen while reporting success.
    """
    best, best_area = None, -1
    for line in sh("wmctrl", "-lG").splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        title = parts[7].lower()
        if "steam" not in title:
            continue
        try:
            area = int(parts[4]) * int(parts[5])
        except ValueError:
            continue
        if area > best_area:
            best, best_area = parts[0], area
    return best


def raise_window(wid):
    """Put a window in front of Kodi and make it fill the screen."""
    sh("wmctrl", "-i", "-a", wid)
    sh("wmctrl", "-i", "-b", "add,fullscreen", wid)
    try:
        sh("xdotool", "windowactivate", "--sync", str(int(wid, 16)))
    except ValueError:
        pass


def start(argv):
    """Start Steam and leave it running after this script exits.

    start_new_session so it does not die with the add-on -- the same call
    plugin.program.retroarch makes for RetroArch, and for the same reason: the
    add-on is a menu entry that ends, and the thing it started is a session
    somebody is going to spend an evening in.
    """
    try:
        subprocess.Popen(argv, env=environment(), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return str(exc)
    return ""


def bring_forward(deadline=None):
    """Wait for Steam's window and hold it in front of Kodi.

    Returns True if a window was ever found. Kodi does not step aside for
    something started underneath it, and it reclaims the foreground for a
    while after losing it, so this raises repeatedly rather than once.
    """
    stop = (time.time() + WAIT_FOR_WINDOW) if deadline is None else deadline
    wid = None
    while time.time() < stop:
        wid = window()
        if wid:
            break
        time.sleep(POLL)
    if not wid:
        return False
    for _ in range(RAISE_TRIES):
        raise_window(wid)
        time.sleep(RAISE_GAP)
    return True
