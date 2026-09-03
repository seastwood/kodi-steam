"""Finding Steam, choosing how to install it, and getting it in front of Kodi.

Nothing real is touched: `sh` and `popen` are the only two ways steam_core
reaches the outside world, and both are replaced here. That matters more than
usual for this add-on -- the thing under test can start a gigabyte-long
download and a program that takes over the screen, and a test suite that could
do either by accident is not one anybody would run twice.

What is worth holding still: native Steam is preferred over the Flatpak (the
sandbox is between a pad and the machine, which is the one thing this box
cannot afford), the largest window wins when Steam maps several, and an
install that fails says why -- a dialog reading "it failed" with the reason
thrown away is a dead end on a television.
"""
import importlib.machinery
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ldr = importlib.machinery.SourceFileLoader(
    "steam_core", os.path.join(os.path.dirname(HERE), "steam_core.py"))
core = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("steam_core", ldr))
ldr.exec_module(core)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


class FakeShutil:
    """`which`, answering from a set of names that are pretended to exist."""

    def __init__(self, present):
        self.present = set(present)

    def which(self, name):
        return "/usr/bin/" + name if name in self.present else None


def stub(present=(), output=None, games=()):
    """Put the module in a machine of our choosing.

    `games` matters as much as `present` does: /usr/games is looked in as well
    as PATH, so a suite that stubs only PATH passes on a laptop and fails on
    the machine this is for -- which is precisely what it did, the first time
    it was run on a console with Steam actually installed.
    """
    core.shutil = FakeShutil(present)
    core.GAME_BINS = tuple(games)
    table = output or {}
    calls = []

    def fake_sh(*argv, **kw):
        calls.append(list(argv))
        for key, value in table.items():
            if key in argv:
                return value
        return ""

    core.sh = fake_sh
    return calls


print("which Steam is here")
stub(present=["steam"])
check(core.launch_argv() == ["/usr/bin/steam", "-gamepadui"],
      "a packaged Steam is started straight, in the gamepad interface")
check(core.installed() is True, "and counts as installed")

stub(present=["flatpak"], output={"list": "org.videolan.VLC\n"})
check(core.launch_argv() is None,
      "flatpak being installed is not Steam being installed")

stub(present=["flatpak"],
     output={"list": "org.videolan.VLC\ncom.valvesoftware.Steam\n"})
check(core.launch_argv() ==
      ["flatpak", "run", "com.valvesoftware.Steam", "-gamepadui"],
      "the Flatpak is used when there is no package")

stub(present=["steam", "flatpak"],
     output={"list": "com.valvesoftware.Steam\n"})
check(core.launch_argv()[0] == "/usr/bin/steam",
      "and the package wins when both are here -- the sandbox is not free")

stub(present=[])
check(core.launch_argv() is None and core.installed() is False,
      "a machine with neither has neither")

# Kodi does not necessarily inherit an interactive shell's PATH, and Debian
# puts steam in /usr/games. Found by looking, or a machine with Steam on it is
# offered Steam again.
GAMES = os.path.dirname(os.path.abspath(__file__))
here = os.path.join(GAMES, "steam")
try:
    with open(here, "w") as handle:
        handle.write("#!/bin/sh\n")
    os.chmod(here, 0o755)
    stub(present=[], games=[GAMES])
    check(core.native() == here,
          "steam in /usr/games is found even when PATH has never heard of it")
    check(core.launch_argv() == [here, "-gamepadui"],
          "and is what gets started")
finally:
    os.unlink(here)

print("how it would be installed")
core.HELPER = os.path.join(HERE, "does-not-exist")
stub(present=["flatpak"])
route, argv = core.install_route()
check(route == "flatpak" and argv[:3] == ["flatpak", "install", "--user"],
      "with no helper, Flathub -- for this user, so no password is needed")
check("--noninteractive" in argv and "--assumeyes" in argv,
      "and nothing that stops to ask a question nobody can answer from a sofa")

core.HELPER = __file__          # any path that exists
stub(present=["flatpak"])
route, argv = core.install_route()
check(route == "apt" and argv == ["sudo", "-n", __file__],
      "with the helper in place, the package route, through sudo -n")
check(core.can_flatpak() is True, "and Flathub is still there to fall back to")

stub(present=[])
core.HELPER = os.path.join(HERE, "does-not-exist")
check(core.install_route() == (None, None),
      "a machine with no way in says so rather than guessing")

print("whether it is already running")
stub(output={"comm": "systemd\nkodi.bin\nsteamwebhelper\n"})
check(core.running() is True, "steamwebhelper counts: the client is up")
stub(output={"comm": "systemd\nkodi.bin\n"})
check(core.running() is False, "and a machine without it is not running Steam")

print("which window to raise")
WINDOWS = (
    "0x03000001  0 100  100  1     1   retro Steam\n"
    "0x03000007  0 0    0    1920  1080 retro Steam Big Picture Mode\n"
    "0x02000003  0 0    0    1920  1080 retro Kodi\n")
stub(output={"-lG": WINDOWS})
check(core.window() == "0x03000007",
      "the big one, not the first one -- Steam maps small helpers beside it")
stub(output={"-lG": "0x02000003  0 0 0 1920 1080 retro Kodi\n"})
check(core.window() is None, "and Kodi's own window is not Steam's")
stub(output={"-lG": "rubbish\n0x1 0 a b c d retro Steam\n"})
check(core.window() is None, "a line that does not parse is skipped, not fatal")

print("raising it")
calls = stub(output={"-lG": WINDOWS})
core.raise_window("0x03000007")
check(["wmctrl", "-i", "-a", "0x03000007"] in calls,
      "wmctrl is asked to bring it forward")
check(any(c[:2] == ["xdotool", "windowactivate"] and c[-1] == "50331655"
          for c in calls),
      "and xdotool is given the id as the decimal it expects")

print("installing, out loud")


class FakeProc:
    def __init__(self, lines, code):
        self.stdout = iter(lines)
        self.code = code

    def wait(self):
        return self.code


def stub_install(lines, code):
    def fake_popen(argv, **kw):
        return FakeProc(lines, code)
    core.popen = fake_popen


seen = []
stub_install(["Reading package lists...", "Setting up steam-installer", ""], 0)
ok, tail = core.install(["sudo", "-n", "helper"], seen.append)
check(ok is True, "a clean run is a success")
check(seen[0] == "Reading package lists...",
      "and every line is offered as it arrives, not banked until the end")

stub_install(["E: Unable to locate package steam-installer"], 100)
ok, tail = core.install(["sudo", "-n", "helper"], None)
check(ok is False and "Unable to locate package" in tail,
      "a failure comes back with what was said, which is the only useful part")


def refuse(argv, **kw):
    raise OSError("No such file or directory: 'sudo'")


core.popen = refuse
ok, tail = core.install(["sudo", "-n", "helper"], None)
check(ok is False and "No such file" in tail,
      "and a command that cannot even start is a failure, not a traceback")

print("the display")
os.environ.pop("DISPLAY", None)
check(core.environment()["DISPLAY"] == ":0",
      "a program started from Kodi is told which screen to use")
os.environ["DISPLAY"] = ":1"
check(core.environment()["DISPLAY"] == ":1",
      "and a display that is already set is left alone")

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("all good")
