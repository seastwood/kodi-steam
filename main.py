"""Steam on the television, from the Kodi menu.

One entry, one thing: choosing STEAM starts Big Picture and gets out of the
way. There is no listing to browse here, because Steam has one of its own that
is built for a controller, and a second menu in front of it would only be a
worse copy of that.

What this does have to handle is the machine where Steam is not installed at
all -- which is the difference between a menu entry and a menu entry that
works for somebody who has just built this box. It offers to install it, says
what that costs in time and bandwidth before starting, and opens Big Picture
when it is done.
"""

import json
import os
import sys

import xbmc
import xbmcaddon
import xbmcgui

sys.path.insert(0, xbmcaddon.Addon().getAddonInfo("path"))

import steam_core

TITLE = "Steam"

# Roughly what the client pulls down before it will show anything. Said out
# loud in the question: "install Steam?" on a television reads as an instant
# thing, and this is a wait worth choosing knowingly rather than discovering.
DOWNLOAD_SIZE = "about 1 GB"


def notify(message, icon=xbmcgui.NOTIFICATION_INFO, ms=4000):
    xbmcgui.Dialog().notification(TITLE, message, icon, ms)


def log(message, level=xbmc.LOGINFO):
    xbmc.log("script.steam: %s" % message, level)


def start_big_picture():
    """Start Steam, then hold it in front of Kodi until it settles.

    Kodi keeps the foreground and does not step aside for something started
    underneath it, so the window has to be raised -- repeatedly, because Kodi
    takes it back for a few seconds afterwards. This is the same arrangement
    RetroArch and the PC games already use on this machine.
    """
    argv = steam_core.launch_argv()
    if not argv:
        return offer_install()

    if not guests_warned():
        return

    if steam_core.running():
        # Not an error, and not a reason to start a second client: it is
        # already here, it is only behind Kodi.
        notify("Already running -- bringing it forward")
    else:
        problem = steam_core.start(argv)
        if problem:
            log("could not start %s: %s" % (" ".join(argv), problem),
                xbmc.LOGERROR)
            xbmcgui.Dialog().ok(TITLE, "Steam would not start.\n\n" + problem)
            return
        log("started %s" % " ".join(argv))
        notify("Starting Big Picture...")

    progress = xbmcgui.DialogProgressBG()
    progress.create(TITLE, "Waiting for Steam...")
    try:
        found = steam_core.bring_forward()
    finally:
        progress.close()

    if not found:
        # It was started and nothing ever appeared. Steam updating itself on a
        # slow line looks exactly like this for a while, so this is worded as
        # patience rather than as a failure -- and it says the one thing worth
        # trying, which is choosing it again once the update has finished.
        log("no Steam window appeared within %ss" % steam_core.WAIT_FOR_WINDOW,
            xbmc.LOGWARNING)
        xbmcgui.Dialog().ok(
            TITLE,
            "Steam was started but has not shown a window yet.\n\n"
            "It updates itself before the first screen appears, which can "
            "take a few minutes on a slow connection. Choose Steam again in a "
            "moment and it will be brought forward.")


# The one command that turns the Flathub machine into a package machine. Said
# in full, with the path, because somebody reading it is at a television and
# will be typing it somewhere else entirely.
HELPER_SETUP = "~/kodi-steam/install.sh --helper"


# Remembered per machine: whoever said "it is on" is the person who set it up,
# and asking them again every evening is how a warning turns into something
# people dismiss without reading.
ACKED = "family-view-acknowledged"


def acknowledged():
    return xbmcaddon.Addon().getSetting(ACKED) == "true"


def guests_warned():
    """Ask before putting Steam in front of guests with no Family View.

    True to carry on, False if the answer was to stop.

    Only when somebody is actually connected. A warning that appears when
    nobody is there is a warning about nothing, and it is the same dialog
    every time somebody plays alone.
    """
    open_session, guests = steam_core.guests_connected()
    if not open_session or not guests:
        return True
    state = steam_core.family_view()
    if state == "unknown" and acknowledged():
        return True

    who = "1 guest is" if guests == 1 else "%d guests are" % guests
    if state == "off":
        message = ("Family View has never been set up on this machine, and "
                   + who + " connected to Fourth Player right now.\n\n"
                   "Their controllers stop at Steam's own menus, but not at "
                   "the overlay they can open from inside a game -- and that "
                   "reaches the store.\n\n"
                   "Settings > Family in Big Picture is where the PIN lives.")
    else:
        message = ("Family View has been set up here, but nothing on this "
                   "machine can say whether it is switched on -- Steam keeps "
                   "that where it cannot be read.\n\n" + who + " connected "
                   "to Fourth Player right now, and the overlay they can open "
                   "from inside a game reaches the store.")

    dialog = xbmcgui.Dialog()
    if state == "unknown" and hasattr(dialog, "yesnocustom"):
        # Three answers, because "yes I set it up" is a different thing from
        # "start it anyway just now", and only one of them is worth
        # remembering.
        answer = dialog.yesnocustom(TITLE, message, "It is on, stop asking",
                                    "Not now", "Start anyway")
        if answer == 2:
            xbmcaddon.Addon().setSetting(ACKED, "true")
            return True
        return answer == 1
    return bool(dialog.yesno(TITLE, message, nolabel="Not now",
                             yeslabel="Start anyway"))


def offer_install():
    """Steam is not here. Offer to fetch it, and say what that involves.

    Three machines to speak to, and they want different things said. One has
    the helper and can simply be asked. One has Flatpak only, and should be
    told how to get the better version before being offered the other. One has
    neither, and needs directions rather than a button.
    """
    route, argv = steam_core.install_route()
    if not route:
        xbmcgui.Dialog().ok(
            TITLE,
            "Steam is not installed, and there is no way to install it from "
            "here.\n\n"
            "Run this once, at a terminal:\n"
            "    " + HELPER_SETUP + "\n\n"
            "It puts the privileged helper in place, and after that this "
            "screen installs Steam on its own.")
        return

    if route == "apt":
        question = ("Steam is not installed on this machine.\n\n"
                    "Install the Steam package now? It downloads "
                    + DOWNLOAD_SIZE + " and takes several minutes. You can "
                    "keep using Kodi while it runs.")
        yes = "Install Steam"
    else:
        # Flathub is what this machine can do unaided, and it works -- but the
        # package is the better answer on a machine with controllers in it, so
        # the way to get that is offered first rather than buried in a README
        # nobody is holding.
        question = ("Steam is not installed on this machine.\n\n"
                    "The package version needs one command at a terminal "
                    "first:\n"
                    "    " + HELPER_SETUP + "\n"
                    "after which this screen installs it for you.\n\n"
                    "Or install the Flathub version now, for this user only. "
                    "It needs no password, downloads " + DOWNLOAD_SIZE + ", "
                    "and works -- its sandbox is simply one more thing between "
                    "Steam and your controllers.")
        yes = "Install Flathub"

    if not xbmcgui.Dialog().yesno(TITLE, question, nolabel="Not now",
                                  yeslabel=yes):
        return

    if not install_with_progress(route, argv):
        return

    if not steam_core.installed():
        # The install said it worked and Steam is still not here. Nothing
        # useful is left to try automatically, so say what happened.
        xbmcgui.Dialog().ok(
            TITLE,
            "The install finished but Steam still cannot be found.\n\n"
            "Check the Kodi log for what the installer said.")
        return

    notify("Steam installed")
    take_valves_icon()
    # Straight into it: somebody who just waited through a download asked for
    # Steam, not for a confirmation that Steam exists.
    start_big_picture()


def take_valves_icon():
    """Put Valve's own icon on the menu tile, now that there is one.

    The tile is written at install time, when the only picture available is
    the drawing this add-on ships -- the real one arrives with the client and
    not before. So it is written again here, the moment the client exists.

    And Kodi is told to forget what it had. It caches every image it draws,
    keyed by path, and the tile keeps its path: a file replaced underneath
    that key is not something Kodi goes looking for, so without this the new
    icon is on the disk and the old one is on the menu, which looks exactly
    like the copy having failed.
    """
    def on_disk():
        try:
            with open(os.path.expanduser(steam_core.TILE), "rb") as reading:
                return reading.read()
        except OSError:
            return None

    before = on_disk()
    used = steam_core.refresh_tile()
    if not used:
        return
    if on_disk() == before:
        # Nothing changed, so there is nothing stale to throw away. This runs
        # on every launch now, and clearing the cache each time would make
        # Kodi re-read and re-cache the tile for no reason.
        return
    log("menu tile now %s" % used)
    try:
        found = json.loads(xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "Textures.GetTextures",
            "params": {"filter": {"field": "url", "operator": "contains",
                                  "value": "_steam.png"},
                       "properties": ["url"]}})))
        for texture in found.get("result", {}).get("textures", []):
            xbmc.executeJSONRPC(json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "Textures.RemoveTexture",
                "params": {"textureid": texture["textureid"]}}))
    except Exception as exc:          # noqa: BLE001 - a stale icon is not fatal
        log("could not clear the cached tile: %s" % exc, xbmc.LOGWARNING)


def install_with_progress(route, argv):
    """Run the install, showing what it is doing. True if it succeeded."""
    progress = xbmcgui.DialogProgressBG()
    progress.create(TITLE, "Installing Steam...")
    lines = []

    def line(text):
        text = text.strip()
        if not text:
            return
        lines.append(text)
        # The last line of apt or flatpak output is a fair description of what
        # is happening now: fetching, unpacking, setting up.
        progress.update(50, TITLE, text[:60])

    log("installing via %s: %s" % (route, " ".join(argv)))
    try:
        ok, tail = steam_core.install(argv, line)
    finally:
        progress.close()

    if ok:
        return True

    log("install failed: %s" % tail, xbmc.LOGERROR)
    # An apt route that failed on a machine with flatpak has somewhere else to
    # go, and asking beats sending somebody to a terminal.
    if route == "apt" and steam_core.can_flatpak():
        if xbmcgui.Dialog().yesno(
                TITLE,
                "The Steam package could not be installed.\n\n" + tail[:180] +
                "\n\nTry the Flathub version instead? It installs for this "
                "user and needs no password.",
                nolabel="No", yeslabel="Try Flathub"):
            return install_with_progress(*steam_core.flatpak_route())
        return False

    xbmcgui.Dialog().ok(TITLE, "Steam could not be installed.\n\n" + tail[:200])
    return False


if __name__ == "__main__":
    # Before anything else, because the application may have been installed
    # since the last run and by some other route -- apt, a software centre,
    # somebody's own build. Those leave the menu showing the drawing this
    # add-on ships, for ever, and nothing else was ever going to notice.
    # Cheap when there is nothing to do: it compares the file it would write
    # with the file already there and stops.
    try:
        take_valves_icon()
    except Exception as exc:          # noqa: BLE001 - a tile is not the job
        log("could not check the menu tile: %s" % exc, xbmc.LOGWARNING)
    start_big_picture()
