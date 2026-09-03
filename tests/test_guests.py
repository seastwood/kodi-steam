"""The warning before Steam goes up in front of people in other houses.

Fourth Player wires a guest somewhere else to a virtual pad on this machine,
and that pad is read by whatever has the foreground. Fourth Player now
withholds those frames while Steam's own interface is in front, which closes
most of it. One gap survives: from *inside* a Steam game the Steam button
opens the overlay, the foreground window is still the game, so the frames keep
flowing -- and the overlay reaches the store.

Family View is the answer to that gap and it is Valve's rather than ours. So
this asks, once, before Big Picture goes up while guests are connected.

What is held still: the question is only asked when somebody is actually
there; a machine that has never set Family View up is told so plainly; a
machine that has is never told it is *safe*, because the setting is a signed
blob nobody here can read and a wrong guess in the reassuring direction is the
one mistake worth avoiding; and asking Fourth Player anything at all cannot
fail loudly, because most machines running this add-on have never heard of it.
"""
import importlib.machinery
import importlib.util
import os
import socket
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ldr = importlib.machinery.SourceFileLoader(
    "steam_core", os.path.join(ROOT, "steam_core.py"))
core = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("steam_core", ldr))
ldr.exec_module(core)

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


print("asking Fourth Player whether anybody is there")
core.CONTROL_SOCKET = os.path.join(tempfile.mkdtemp(), "nothing.sock")
check(core.guests_connected() == (False, 0),
      "a machine with no Fourth Player on it answers no, and does not raise")


def serve(reply):
    """A one-shot stand-in for the server's control socket."""
    path = os.path.join(tempfile.mkdtemp(), "fourth-player.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    listener.listen(1)

    def once():
        conn, _ = listener.accept()
        with conn:
            conn.recv(4096)
            conn.sendall((reply + "\n").encode())
        listener.close()

    threading.Thread(target=once, daemon=True).start()
    core.CONTROL_SOCKET = path


serve('{"ok": true, "open": true, "guests": 2}')
check(core.guests_connected() == (True, 2), "two guests are two guests")
serve('{"ok": true, "open": false}')
check(core.guests_connected() == (False, 0), "a closed session is nobody")
serve('{"ok": true, "open": true, "guests": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}')
check(core.guests_connected() == (True, 3),
      "and a list of guests is counted rather than misread as a number")
serve('not json at all')
check(core.guests_connected() == (False, 0),
      "an answer nobody can parse is no session, not a traceback")

print("whether Family View has ever been set up")
folder = tempfile.mkdtemp()
config = os.path.join(folder, "userdata", "1", "config")
os.makedirs(config)
path = os.path.join(config, "localconfig.vdf")
core.LOCALCONFIGS = (os.path.join(folder, "userdata/*/config/localconfig.vdf"),)

open(path, "w").write('"UserLocalConfigStore"\n{\n\t"friends"\n\t{\n\t}\n}\n')
check(core.family_view() == "off",
      "no ParentalSettings block at all: never set up, and said so plainly")

open(path, "w").write('"x"\n{\n\t"ParentalSettings"\n\t{\n\t\t"settings"\t\t""\n\t}\n}\n')
check(core.family_view() == "off", "an empty settings blob is the same thing")

open(path, "w").write('"x"\n{\n\t"ParentalSettings"\n\t{\n\t\t"settings"\t\t"0986d06002000000004800"\n'
                      '\t\t"Signature"\t\t"9753"\n\t}\n}\n')
check(core.family_view() == "unknown",
      "a blob that is there is never read as 'on': it is signed, undocumented, "
      "and guessing in the reassuring direction is the one mistake to avoid")

core.LOCALCONFIGS = (os.path.join(folder, "nothing/*/here.vdf"),)
check(core.family_view() == "off",
      "and a machine with no Steam config is not quietly assumed safe")

print("when the warning is shown")
main = open(os.path.join(ROOT, "main.py")).read()
warned = main.split("def guests_warned")[1].split("\ndef ")[0]
check("if not open_session or not guests:" in warned
      and "return True" in warned.split("if not open_session")[1][:40],
      "not when nobody is connected: that is a warning about nothing")
check('state == "unknown" and acknowledged()' in warned,
      "and not again once somebody has said they set it up")
check("store" in warned and "overlay" in warned,
      "the message names the actual gap rather than gesturing at danger")
check("if not guests_warned():\n        return" in main,
      "and Steam does not start when the answer is no")

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("all good")
