"""Valve's own first-run prompt, which nobody at a television can answer.

The Debian package is a launcher; the client itself is fetched the first time
it runs, and before doing that the launcher puts up a desktop dialog --
"Steam is proprietary (binary-only) software", Install or Cancel. Seen on a
console built from scratch: choosing Install from the Kodi menu installed the
package, started Steam, and left a GTK dialog sitting over Kodi that wants a
mouse. There is no mouse. The menu had just asked the same question and been
answered.

So a `zenity` that answers Install goes on PATH for that one launch. It is not
a way around consent -- the consent happened in the add-on's own dialog, in
words on the television -- it is a way past the second copy of a question,
which is the copy nobody can reach.

Two things keep that honest: it only happens while the client is genuinely
missing, detected the same way the launcher detects it, and it is on PATH for
that launch and nothing else.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import steam_core                                               # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


print("when the client has never been fetched")
folder = tempfile.mkdtemp()
steam_core.STEAM_DIR = folder
check(steam_core.needs_bootstrap() is True,
      "an empty install is recognised as one that will be asked about")

# The files the launcher checks for, made real and executable.
for part in steam_core.STEAM_BOOTSTRAPPED:
    path = os.path.join(folder, part)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write("#!/bin/sh\n")
    os.chmod(path, 0o755)
check(steam_core.needs_bootstrap() is False,
      "and once they are all there, it is not -- which is exactly when the "
      "prompt stops appearing")

os.chmod(os.path.join(folder, "steam.sh"), 0o644)
check(steam_core.needs_bootstrap() is True,
      "one of them not being runnable is enough, the same test the launcher "
      "makes")

print("\nthe answer it puts on PATH")
where = tempfile.mkdtemp()
check(steam_core.answer_first_run(where) == where, "it is written")
stub = os.path.join(where, "zenity")
check(os.access(stub, os.X_OK), "and it can be run")
check(subprocess.run([stub, "--question", "--text=anything"]).returncode == 0,
      "and answers zero, which is the affirmative button -- Install here")

print("\nand it is not left lying on PATH afterwards")
source = open(os.path.join(ROOT, "steam_core.py")).read()
start = source[source.index("def start(argv)"):]
start = start[:start.index("\nreturn \"\"") + 12] if "\nreturn \"\"" in start else start
check("needs_bootstrap()" in start,
      "the stub is only prepared when the client is actually missing")
check('env["PATH"]' in start and "environment()" in start,
      "and it goes on a copy of the environment for this launch, not on the "
      "add-on's own PATH")

print()
if fails:
    print("FAILED: %d" % len(fails))
    for line in fails:
        print("  " + line)
    sys.exit(1)
print("test_firstrun: all ok")
