"""The packaging: that the pieces still call each other by the same names.

None of this is clever, and all of it has broken something before in projects
shaped like this one. An add-on id is written down in five places -- addon.xml,
the symlink install.sh makes, the RunScript() a menu entry carries, the log
lines, this suite -- and Kodi's answer to a mismatch is "you need to install
this add-on", which sounds like a packaging fault rather than a typo.

The sudoers rule is the other half: it names a path, steam_core.py names a
path, and if those two ever drift the add-on asks for a password on a
television and nobody sees why.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def read(name):
    with open(os.path.join(ROOT, name)) as handle:
        return handle.read()


ADDON_ID = "script.steam"

print("addon.xml")
root = ET.parse(os.path.join(ROOT, "addon.xml")).getroot()
check(root.get("id") == ADDON_ID, "the add-on is %s" % ADDON_ID)
script = root.find("./extension[@point='xbmc.python.script']")
check(script is not None and script.get("library") == "main.py",
      "and Kodi is pointed at main.py")
check(os.path.exists(os.path.join(ROOT, "main.py")), "which is there")
icon = root.find(".//icon")
check(icon is not None and os.path.exists(os.path.join(ROOT, icon.text)),
      "the icon named in the metadata exists")
check(root.find("./requires/import[@addon='xbmc.python']") is not None,
      "and it declares the Python it is written against")

print("install.sh")
install = read("install.sh")
check(".kodi/addons/" + ADDON_ID in install,
      "links the checkout in under the same id")
check("tests/test_*.py" in install or "test_*.py" in install,
      "and runs this suite before it installs anything")
check("wmctrl" in install and "xdotool" in install,
      "makes sure the window tools are here, which the launch depends on")

print("Kodi is told it may run it")
# The fault this exists for: Kodi registered the add-on with enabled=0 and
# answered RunScript(script.steam) with "Not executing non-existing script",
# which reads as a broken add-on and is a switch nobody threw.
check("SetAddonEnabled" in install,
      "a running Kodi is asked through its own API, not edited underneath")
check("enabled=1" in install and "disabledReason=0" in install,
      "and a stopped one has its database written, the way kodi-retrobox does")
check("Not executing non-existing script" in install,
      "with the message it fixes written down beside it")

print("the menu icon is Valve's where the machine has it")
check("/usr/share/icons/hicolor/256x256/apps/steam.png" in install,
      "the system icon is preferred: it is the one somebody is looking for")
check("$REPO/media/_steam.png" in install,
      "and what this repository ships is the fallback, not the preference")

print("the privileged half")
core = read("steam_core.py")
helper = re.search(r'HELPER = "([^"]+)"', core).group(1)
rule = read("system/kodi-steam-sudoers")
check(helper in rule,
      "the sudoers rule names the same path steam_core.py runs: %s" % helper)
check(rule.strip().endswith(helper),
      "and nothing after it -- a rule with an argument wildcard is a way in")
check("NOPASSWD" in rule, "no password, because there is no keyboard")
check(helper in install, "and install.sh puts the helper at that path")

script_text = read("system/kodi-steam-install")
check("steam-installer" in script_text,
      "the helper installs the package Ubuntu and Mint ship")
# Counting commands rather than mentions: the comment above them explains
# why apt is not handed to sudo directly, and says "apt-get install" to do it.
commands = [line for line in script_text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
check(sum("apt-get install" in line for line in commands) == 1,
      "and installs exactly one thing, once")
check(os.access(os.path.join(ROOT, "system/kodi-steam-install"), os.X_OK),
      "the helper is executable in the repository, so install.sh copies it so")

print("main.py talks to the outside world through steam_core")
main = read("main.py")
check("import steam_core" in main, "it imports the core")
check("subprocess" not in main,
      "and runs nothing itself: one file reaches the machine, and it is tested")
check('xbmc.log("script.steam' in main,
      "log lines carry the add-on id, so they can be found in kodi.log")

print("the menu icon")
check(os.path.exists(os.path.join(ROOT, "media/_steam.png")),
      "the tile kodi-retrobox looks for is in the repository")
check("_steam.png" in install, "and install.sh puts it where that menu reads")

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("all good")
