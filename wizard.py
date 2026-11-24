"""tidyinbox setup: a step-by-step guide from nothing to a sorted inbox."""
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

import tidyinbox as ti

HERE = Path(__file__).resolve().parent
REPO = "https://github.com/makavli/tidyinbox"
STEPS = 6

GOOGLE_STEPS = """\
  tidyinbox reaches Gmail through a small Google app that only you use. It is free.
  In the Google Cloud console:
   1. Create a project (project picker in the top bar; any name).
   2. Enable the Gmail API (APIs & Services > Library > Gmail API > Enable).
   3. Google Auth Platform > Get started (or Branding):
        app name: anything without "Google" or "Gmail" in it
        support email and developer contact: your address
        audience: External
      Leave the logo empty: a logo makes Google require a review of the app.
   4. Audience > Test users > Add users: your own Gmail address.
   5. Clients > Create client > Desktop app > Create, then Download JSON.
      Leave "Use this client for an AI-powered agent" unticked."""

KEY_CHOICE = """\
  1) Weekly sign-in (simplest). The app stays in "Testing", where Google expires the key every 7 days.
     When it does, the scheduled sort shows a box that signs you in again in two clicks (Windows),
     or you run: python tidyinbox.py auth
  2) Permanent key. You publish the app ("In production"). Google then asks for a home page and a
     privacy policy link; this project's pages can serve. If Google refuses them, choose 1."""

PUBLISH_STEPS = f"""\
  In Google Auth Platform:
   1. Branding > App domain:
        Application home page:       {REPO}
        Application privacy policy:  {REPO}/blob/main/PRIVACY.md
      If it asks for an authorized domain, add github.com. Save.
   2. Audience > Publish app > Confirm. The status turns to "In production"."""

SIGN_IN_TIPS = """\
  A browser tab opens. Google will say "Google hasn't verified this app": it is your own app,
  so choose Continue (or Advanced > Go to ... ). Then allow access and close the tab."""


def ask(prompt, choices=None, default=""):
    """Ask until the answer is one of choices; Enter takes the default."""
    while True:
        a = input(f"{prompt} ").strip().strip('"') or default
        if choices is None or a.lower() in choices:
            return a.lower() if choices else a
        print(f"  Please answer one of: {', '.join(choices)}")


def yes(prompt, default=True):
    return ask(f"{prompt} [{'Y/n' if default else 'y/N'}]", ["y", "n", "yes", "no"], "y" if default else "n")[0] == "y"


def step(n, title):
    print(f"\n== Step {n}/{STEPS}: {title} ==")


def newest_client_json(folder=None):
    folder = folder or Path.home() / "Downloads"
    files = sorted(folder.glob("client_secret*.json"), key=lambda p: p.stat().st_mtime) if folder.is_dir() else []
    return files[-1] if files else None


def schedule_command(every, platform=sys.platform, python=Path(sys.executable), script=HERE / "tidyinbox.py"):
    """What runs a sweep every hour or day: a schtasks argv on Windows, else a crontab line."""
    if platform == "win32":
        quiet = python.with_name("pythonw.exe")  # pythonw: no window pops up at each run
        exe = quiet if quiet.exists() else python
        return ["schtasks", "/create", "/tn", "tidyinbox", "/sc", every.upper(), "/f",
                "/tr", f'"{exe}" "{script}" sweep --apply']
    when = "0 * * * *" if every == "hourly" else "0 9 * * *"
    return f'{when} "{python}" "{script}" sweep --apply'


def schedule(every):
    cmd = schedule_command(every)
    if isinstance(cmd, list):
        r = subprocess.run(cmd, capture_output=True, text=True)
        print("  " + (r.stdout or r.stderr).strip())
        if r.returncode == 0:
            print("  It runs while you are logged in. To stop it: schtasks /delete /tn tidyinbox /f")
    else:
        print("  Add this line with `crontab -e` (your key store must be reachable from cron):")
        print(f"    {cmd}")


def sign_in():
    found = newest_client_json()
    while True:
        path = Path(ask(f"  Path to the downloaded client JSON{f' [{found}]' if found else ''}:",
                        default=str(found) if found else "")).expanduser()
        if path.is_file():
            break
        print(f"  No file at {path}.")
    print(SIGN_IN_TIPS)
    ti.auth(str(path))
    if yes(f"  Delete {path.name} now? It holds your app's secret; sign-ins from now on reuse the stored copy."):
        path.unlink()


def run_wizard():
    print("tidyinbox setup. Enter takes the [default]; Ctrl+C stops at any time.")
    mode = "1"
    if ti.stored_key() and yes("You are already signed in. Skip to the rules?"):
        start = 4
    else:
        start = 1

    if start == 1:
        step(1, "your own Google app (once, about 10 minutes)")
        print(GOOGLE_STEPS)
        if yes("  Open the Google Cloud console now?"):
            webbrowser.open("https://console.cloud.google.com/apis/library/gmail.googleapis.com")
        input("  Press Enter once the client JSON is downloaded... ")

        step(2, "how long the key lasts")
        print(KEY_CHOICE)
        mode = ask("  Choose 1 or 2 [1]:", ["1", "2"], "1")
        if mode == "2":
            print(PUBLISH_STEPS)
            input("  Press Enter once the app is In production (if Google refused, it simply stays weekly)... ")

        step(3, "sign in")
        sign_in()

    step(4, "your rules")
    if not ti.RULES.exists():
        shutil.copy(HERE / "rules.example.toml", ti.RULES)
        print(f"  Created {ti.RULES} from the example: Gmail's own categories go to labels under Sorted/.")
    print(f"  Edit {ti.RULES.name} any time: each rule is a Gmail search, testable in Gmail's search box.")
    rules = ti.load_rules(ti.RULES)
    gm = ti.connect()
    if yes("  See who sends the mail that would stay in the inbox?", default=False):
        ti.senders(gm, rules)

    step(5, "a dry run, then the real thing")
    ti.sweep(gm, rules, apply=False)
    if yes("  Move them now? Nothing is deleted, and `undo LABEL` puts mail back.", default=False):
        ti.sweep(gm, rules, apply=True)

    step(6, "keep it sorted")
    every = {"1": "hourly", "2": "daily", "3": None}[
        ask("  Sort new mail: 1) every hour  2) every day  3) only when I run it [1]:", ["1", "2", "3"], "1")]
    if every:
        schedule(every)

    print("\nDone. The inbox keeps what matches no rule; the rest waits under its label in Gmail's left menu.")
    print("  Put a label back:  python tidyinbox.py undo Sorted/Promotions")
    if mode == "1":
        print("  Weekly sign-in:    python tidyinbox.py auth")
