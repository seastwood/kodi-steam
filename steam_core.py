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

import os
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


# The two ways this module reaches the outside world, named so a test can
# replace them. Nothing else here calls subprocess directly.
popen = subprocess.Popen


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


def native():
    """Steam from a package, if it is on the path."""
    return shutil.which("steam")


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
