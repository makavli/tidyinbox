"""tidyinbox: sort a Gmail inbox into labels and keep only what matters in it."""
import argparse
import json
import sys
import tomllib
from collections import Counter
from email.utils import parseaddr
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]  # this scope cannot delete mail for good
KEY = ("tidyinbox", "gmail")  # the entry in the OS key store (Windows Credential Manager, macOS Keychain...)
RULES = Path(__file__).with_name("rules.toml")
SAMPLES = 3
RETRIES = 6  # the client retries 429, 5xx and 403 rate-limit answers with growing waits (Gmail caps units per minute)
NOT_SIGNED_IN = "Not signed in. Run: python tidyinbox.py setup"
GOOGLE_URIS = {"auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}


def clean(text):
    """Header text written by strangers, minus control characters that could drive the terminal."""
    return "".join(c for c in text if c.isprintable())


class NeedsSignIn(SystemExit):
    """An exit the user fixes by signing in again; the scheduled task offers to do it."""


class Gmail:
    """The only code that talks to the Gmail API."""

    def __init__(self, svc):
        self.m = svc.users().messages()
        self.l = svc.users().labels()

    def ids(self, q=None, label_id=None, limit=None):
        out, token = [], None
        while True:
            kw = {"userId": "me", "maxResults": 500}
            if q:
                kw["q"] = q
            if label_id:
                kw["labelIds"] = [label_id]
            if token:
                kw["pageToken"] = token
            page = self.m.list(**kw).execute(num_retries=RETRIES)
            out += [m["id"] for m in page.get("messages", [])]
            token = page.get("nextPageToken")
            if not token or (limit and len(out) >= limit):
                return out[:limit]

    def labels(self):
        # user labels only, so a rule can never file mail under TRASH or SPAM; Gmail names are case-insensitive
        found = self.l.list(userId="me").execute(num_retries=RETRIES)["labels"]
        return {l["name"].lower(): l["id"] for l in found if l["type"] == "user"}

    def create_label(self, name):
        return self.l.create(userId="me", body={"name": name}).execute(num_retries=RETRIES)["id"]

    def inbox_total(self):
        return self.l.get(userId="me", id="INBOX").execute(num_retries=RETRIES)["messagesTotal"]

    def headers(self, msg_id):
        msg = self.m.get(userId="me", id=msg_id, format="metadata",
                         metadataHeaders=["From", "Subject"]).execute(num_retries=RETRIES)
        return {x["name"]: x["value"] for x in msg["payload"]["headers"]}

    def modify(self, ids, add, remove):
        # shortcut: moves messages, not threads; a mixed thread can stay half in the inbox, use threads.modify if that shows up
        for i in range(0, len(ids), 1000):  # batchModify takes at most 1000 ids
            body = {"ids": ids[i:i + 1000], "addLabelIds": add, "removeLabelIds": remove}
            self.m.batchModify(userId="me", body=body).execute(num_retries=RETRIES)


def load_rules(path):
    if not path.exists():
        sys.exit(f"No rules file at {path}. Run setup, or copy rules.example.toml to rules.toml.")
    rules = tomllib.loads(path.read_text(encoding="utf-8"))
    buckets = rules.get("bucket", [])

    def good(b):
        label, query = (b.get("label"), b.get("query")) if isinstance(b, dict) else (None, None)
        return (isinstance(label, str) and isinstance(query, str) and query.strip()
                and all(p and p == p.strip() for p in label.split("/")))

    if not isinstance(buckets, list) or not buckets or not all(good(b) for b in buckets) \
            or not isinstance(rules.get("keep", ""), str):
        sys.exit(f"{path}: needs at least one [[bucket]], each with a query and a label like Sorted/Junk "
                 "(no empty parts, no edge spaces); keep must be text.")
    return rules


def plan(gm, rules):
    """[(label, ids)] in rule order; a message goes to the first bucket it matches."""
    keep = rules.get("keep", "").strip()
    seen, out = set(), []
    for b in rules["bucket"]:
        q = f"in:inbox ({b['query']})" + (f" -({keep})" if keep else "")
        ids = [i for i in gm.ids(q=q) if i not in seen]
        seen.update(ids)
        out.append((b["label"], ids))
    return out


def ensure_labels(gm, names):
    have = gm.labels()
    for name in names:
        parts = name.split("/")
        for n in range(1, len(parts) + 1):  # parents first, so Gmail shows them nested
            sub = "/".join(parts[:n])
            if sub.lower() not in have:
                have[sub.lower()] = gm.create_label(sub)
    return have


def sweep(gm, rules, apply):
    moves = plan(gm, rules)
    for label, ids in moves:
        print(f"{len(ids):6}  -> {label}")
        for i in ids[:SAMPLES]:
            h = gm.headers(i)
            print(f'          {clean(h.get("From", "?"))} | {clean(h.get("Subject", ""))}')
    moved = sum(len(ids) for _, ids in moves)
    if not apply:
        print(f"Dry run: {moved} of {gm.inbox_total()} inbox messages would move. "
              "Nothing changed; add --apply to move them.")
        return
    labels = ensure_labels(gm, [label for label, ids in moves if ids])  # all labels exist before any mail moves
    for label, ids in moves:
        if ids:
            gm.modify(ids, [labels[label.lower()]], ["INBOX"])
    print(f"Moved {moved} messages; {gm.inbox_total()} stay in the inbox.")


def senders(gm, rules, scan=300, top=30):
    """Who sends the mail that would stay: the list to grow junk and buckets from."""
    # one search for what no bucket takes, newest first; mail that keep holds back is left out
    q = "in:inbox " + " ".join(f"-({b['query']})" for b in rules["bucket"])
    stay = gm.ids(q=q, limit=scan)
    counts = Counter(clean(parseaddr(gm.headers(i).get("From", ""))[1].lower()) or "?" for i in stay)
    print(f"Top senders in the newest {len(stay)} messages that would stay in the inbox:")
    for addr, n in counts.most_common(top):
        print(f"{n:6}  {addr}")


def undo(gm, label):
    lid = gm.labels().get(label.lower())
    if not lid:
        sys.exit(f"No label named {label!r}.")
    ids = gm.ids(label_id=lid)
    gm.modify(ids, ["INBOX"], [lid])
    print(f"Put {len(ids)} messages from {label} back in the inbox.")


def stored_key():
    import keyring

    raw = keyring.get_password(*KEY)
    return json.loads(raw) if raw else None


def auth(secret_file=None):
    """Sign in and store the key. Without a file, reuse the Google app saved at the first sign-in."""
    import keyring
    from google_auth_oauthlib.flow import InstalledAppFlow

    if secret_file:
        try:
            info = json.loads(Path(secret_file).read_text(encoding="utf-8"))["installed"]
        except (OSError, ValueError, KeyError, TypeError):
            info = None
    else:
        info = stored_key()
        if not info:
            sys.exit(NOT_SIGNED_IN)
    if not isinstance(info, dict) or not all(isinstance(info.get(k), str) and info[k] for k in ("client_id", "client_secret")):
        sys.exit(f"{secret_file or 'The saved key'} is not a Desktop-app client JSON from Google Cloud.")
    # only the app's id and secret come from the file; the endpoints are Google's own, so a planted file
    # cannot route the sign-in code elsewhere
    client = {"client_id": info["client_id"], "client_secret": info["client_secret"], **GOOGLE_URIS}
    flow = InstalledAppFlow.from_client_config({"installed": client}, SCOPES, autogenerate_code_verifier=True)  # PKCE
    creds = flow.run_local_server(port=0, prompt="consent")  # consent again, so Google always returns a refresh token
    if not creds.refresh_token:
        sys.exit("Google sent no refresh token; sign in again.")
    keyring.set_password(*KEY, json.dumps(
        {"client_id": creds.client_id, "client_secret": creds.client_secret, "refresh_token": creds.refresh_token}))
    print("Signed in. The key is in the OS key store" + (
        f". Delete {secret_file} now: it holds your app's secret and is no longer needed." if secret_file else "."))


def connect():
    from google.auth.exceptions import RefreshError, TransportError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    saved = stored_key()
    if not saved:
        sys.exit(NOT_SIGNED_IN)
    creds = Credentials.from_authorized_user_info(saved, SCOPES)
    try:
        creds.refresh(Request())
    except RefreshError:
        raise NeedsSignIn("Google refused the saved key (expired or revoked). Sign in again: python tidyinbox.py auth")
    except TransportError:
        # without a console (the scheduled task) stay quiet: the next run tries again
        sys.exit("Could not reach Google. Check the connection and try again." if sys.stdout else 0)
    return Gmail(build("gmail", "v1", credentials=creds, cache_discovery=False))


def logout():
    import keyring

    try:
        keyring.delete_password(*KEY)
    except keyring.errors.PasswordDeleteError:
        pass
    print("Key removed. To cut access on Google's side too: https://myaccount.google.com/permissions")


def main(argv=None):
    if sys.stdout:  # None under pythonw (the scheduled task); print() is then a no-op
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # accents and emoji survive a redirect to a log
    p = argparse.ArgumentParser(prog="tidyinbox", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="step-by-step setup: Google app, sign-in, rules, first sort, schedule")
    a = sub.add_parser("auth", help="sign in (again) and store the key")
    a.add_argument("client_secret", nargs="?", help="the OAuth client JSON from Google Cloud (only the first time)")
    s = sub.add_parser("sweep", help="sort the inbox (dry run unless --apply)")
    s.add_argument("--apply", action="store_true", help="really move the mail")
    s.add_argument("--rules", type=Path, default=RULES)
    t = sub.add_parser("senders", help="top senders of the mail that would stay (to tune the rules)")
    t.add_argument("--rules", type=Path, default=RULES)
    u = sub.add_parser("undo", help="put a label's mail back in the inbox")
    u.add_argument("label")
    sub.add_parser("logout", help="delete the stored key")
    args = p.parse_args(argv)

    if args.cmd == "setup":
        import wizard

        try:
            wizard.run_wizard()
        except (KeyboardInterrupt, EOFError):
            sys.exit("\nStopped. Run setup again to carry on.")
    elif args.cmd == "auth":
        auth(args.client_secret)
    elif args.cmd == "sweep":
        rules = load_rules(args.rules)
        sweep(connect(), rules, args.apply)
    elif args.cmd == "senders":
        rules = load_rules(args.rules)
        senders(connect(), rules)
    elif args.cmd == "undo":
        undo(connect(), args.label)
    else:
        logout()


def run(argv=None):
    """main(), plus a message box for what needs the user when there is no console (the Windows task)."""
    try:
        main(argv)
    except SystemExit as e:
        if sys.stdout is not None or not isinstance(e.code, str) or sys.platform != "win32":
            raise
        import ctypes

        box = ctypes.windll.user32.MessageBoxW
        if isinstance(e, NeedsSignIn):
            if box(None, f"{e.code}\n\nSign in again now?", "tidyinbox", 0x34) == 6:  # 0x34 = Yes/No + warning; 6 = Yes
                auth()
                return
        else:
            box(None, e.code, "tidyinbox", 0x30)
        raise


if __name__ == "__main__":
    run()
