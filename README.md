# kodi-steam

Steam in Big Picture, from the Kodi home menu, driven with the controller you
are already holding. It installs Steam for you if the machine has not got it.

Built for a Kodi machine used as a games console — the same sofa,
the same pad, the same menu the emulators are on. It sits beside
[kodi-retrobox](https://github.com/seastwood/kodi-retrobox), which puts the
entry on the home screen when this add-on is installed, and works on any Kodi
without it.

## What it does

- **Starts Big Picture** — `steam -gamepadui`, the interface built for a
  controller, and then holds it in front of Kodi. That second half is the part
  that is easy to miss: Kodi runs fullscreen and does not step aside for
  something started underneath it, so a launch without it looks exactly like a
  launch that did nothing.
- **Installs Steam if it is missing** — the first time somebody chooses it on
  a machine with no Steam, it says what the download costs and fetches it. No
  terminal, no password, no keyboard.
- **Comes back** — quit Steam and Kodi is where you left it, because it never
  went anywhere.
- **Does not start a second client** — choosing Steam while Steam is running
  brings the one that is already here forward.

## Installing

```sh
git clone git@github.com:seastwood/kodi-steam.git
cd kodi-steam
./install.sh
```

`install.sh` links the checkout into `~/.kodi/addons/script.steam`, makes sure
`wmctrl` and `xdotool` are present, puts the menu tile where kodi-retrobox
looks for it, tells Kodi it may run the add-on, and — the one part that needs
a password — installs the helper that lets the add-on install Steam later
without one.

That third step is not a formality. Kodi registers an add-on it finds on disk
with `enabled=0`, and then answers `RunScript(script.steam)` with *"Not
executing non-existing script"* — which reads as a broken add-on and is really
a switch nobody has thrown. A running Kodi is asked through its own JSON-RPC,
because it holds that state in memory and writes it back on the way out, so an
edit made underneath it is silently undone at the next shutdown; a stopped one
has its database written directly, which is what kodi-retrobox's
`kodi-setup.sh` does for every add-on at install time.

The menu tile is Valve's own icon when the machine has one, and finding it is
less obvious than it looks. `/usr/share/icons/hicolor/256x256/apps/steam.png`
is named exactly right and, on Debian and Ubuntu, is **a picture of cardboard
boxes** — it belongs to `steam-installer`, and the packaging system's idea of
a package is not what somebody scanning a menu for Steam is looking for. The
real one comes with the client:
`~/.steam/debian-installation/deb-installer/steam-launcher/icons/256/steam.png`.

So the client's own icon is preferred, the theme's is used only where `dpkg`
says the client's package put it there (or where there is no dpkg to ask), and
the drawing in this repository is the fallback for a machine that has not got
Steam yet — a trademark is a poor thing to vendor into a project. The tile is
written again the moment the add-on finishes installing Steam, because until
then the good icon does not exist, and Kodi is told to forget the cached copy
at the same time: it caches images by path, the tile keeps its path, and a
file replaced underneath that key is not something Kodi goes looking for.

A pull is all an update takes: the repository *is* the add-on, so there is
nothing to copy into place.

## How Steam gets installed

Two routes, and which one is used is decided by what the machine has.

**The package**, on Ubuntu and Mint, is `steam-installer`, which needs root.
An add-on cannot ask for a password on a television, so the privileged half is
one script — `/usr/local/libexec/kodi-steam-install` — with a sudoers rule
naming that script and nothing else. apt itself is never handed to sudo:
`apt-get install ./anything.deb` runs a maintainer script as root, so a rule
permitting apt permits everything.

On a machine where that setup has not been done, the add-on says so and gives
the command — `./install.sh --helper` — rather than quietly settling for the
other route without mentioning it.

**Flathub** is the fallback, and it needs no root at all — `flatpak install
--user`. It is second rather than first because the sandbox sits between Steam
and the machine's controllers, which is the one thing a games console cannot
afford. On a machine with no helper installed, it is what you get, and it
works.

## Which window, and why any of that is needed

Kodi keeps the foreground. Steam is started detached — `start_new_session`, the
same call `plugin.program.retroarch` makes, because the add-on is a menu entry
that ends and Steam is an evening — and then raised over Kodi with `wmctrl`,
repeatedly for a few seconds, because Kodi reclaims the foreground for a while
after losing it.

The window to raise is the largest one whose title mentions Steam, not the
first: the client maps small helper windows beside the real one, and raising a
1×1 window puts nothing on the screen while reporting success. That is
`pcgame_launch.py`'s finding on this machine, arrived at the hard way with
Call of Duty 4.

## Guests, and the store

This machine may have [Fourth Player](https://github.com/seastwood/Fourth-Player)
on it, which wires somebody in another house to a virtual pad here. That pad is
read by whatever has the foreground, so Fourth Player withholds a guest's
frames while Steam's own interface is in front — a guest can play a Steam game
with you and cannot walk into the store.

One gap survives that, and it is the reason this add-on asks a question. From
*inside* a game, the Steam button opens the overlay; the foreground window is
still the game, so the frames keep flowing, and the overlay reaches the store.
Nothing here can close that. **Family View** can, and it is Valve's own: a PIN
in front of the store, the settings and the library, in Big Picture under
Settings → Family.

So when Big Picture is asked for while guests are actually connected, this
checks whether Family View has ever been set up, and says so if it has not.
Whether it is *switched on* is not something it will claim: Steam keeps that in
a signed binary blob, and a wrong guess in the reassuring direction is the one
mistake worth avoiding — so a machine that has one is asked once and then
remembered. Nobody connected means no question, because a warning about nobody
is how people learn to dismiss warnings.

## Running the tests

```sh
python3 tests/test_steam.py
python3 tests/test_addon.py
python3 tests/test_guests.py
```

Neither touches a real Steam, a real apt, or a real screen: `sh` and `popen`
are the only two ways `steam_core.py` reaches the outside world and both are
stubbed. That matters more than usual here — the code under test can start a
gigabyte-long download and a program that takes over the display.

## Licence

MIT. See [LICENSE](LICENSE).
