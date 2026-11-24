# tidyinbox

Sort your Gmail inbox into labels and keep only what matters in it. tidyinbox runs on your own machine, talks only to Google, and never deletes mail.

You write the rules as plain Gmail searches. A message that matches a rule gets that rule's label (Gmail's folders) and leaves the inbox. Whatever matches no rule stays: that is your important mail.

```
     12  -> Sorted/Junk
            Deals Daily <promo@example.com> | 70% off today only
    340  -> Sorted/Promotions
     85  -> Sorted/Social
    210  -> Sorted/Updates
Dry run: 647 of 702 inbox messages would move. Nothing changed; add --apply to move them.
```

## Quick start

You need Python 3.11+ and a Gmail account.

```bash
git clone https://github.com/makavli/tidyinbox.git
cd tidyinbox
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # macOS/Linux: .venv/bin/pip
.venv/Scripts/python tidyinbox.py setup             # macOS/Linux: .venv/bin/python
```

`setup` walks you through six steps:

1. **Your own Google app.** It's free and takes about 10 minutes, once. The wizard lists each click in the Google Cloud console and can open the console for you.
2. **How long the key lasts.**
   - *Weekly sign-in*: simplest. Google expires the key every 7 days, and signing in again takes two clicks.
   - *Permanent key*: you publish your app. Google asks for a home page and a privacy policy link, and this project's [README](README.md) and [PRIVACY.md](PRIVACY.md) can serve.
3. **Sign in** in the browser. The key goes into your OS key store (Windows Credential Manager, macOS Keychain, Secret Service on Linux), never into a file. The wizard then offers to delete the downloaded JSON.
4. **Your rules.** It creates `rules.toml` from the example (Gmail's own categories) and can show who sends the mail that would stay.
5. **A dry run, then the real thing.** You see the counts and samples first, and nothing moves without your yes.
6. **Keep it sorted.** Every hour, every day, or only when you run it. On Windows the wizard creates the scheduled task, which runs with no window. On macOS/Linux it prints the `crontab` line.

## Commands

```bash
python tidyinbox.py setup             # the guided setup; run it again any time
python tidyinbox.py sweep             # dry run: what would move, nothing changes
python tidyinbox.py sweep --apply     # really move it
python tidyinbox.py senders           # top senders of what would stay: ideas for new rules
python tidyinbox.py undo Sorted/Promotions   # put a label's mail back in the inbox
python tidyinbox.py auth              # sign in again (the weekly sign-in)
python tidyinbox.py logout            # delete the stored key
```

`undo` returns everything that carries the label, including mail you labelled by hand. Fix the rule before the next sweep, or that mail moves again.

## Rules

```toml
keep = 'is:starred OR from:(your-bank.example OR tax-office.example)'   # never leaves the inbox

[[bucket]]
label = "Sorted/Junk"
query = 'from:(spammer@example.com OR junk.example)'

[[bucket]]
label = "Sorted/Promotions"
query = "category:promotions"
```

- Buckets run top to bottom, and a message goes to the first one it matches. Put buckets for whole senders (shops, a marketplace, GitHub) before the categories.
- `keep` wins over every bucket. Star a message to keep it in the inbox for good.
- A label with a `/` shows nested in Gmail (`Sorted/Junk` sits under `Sorted`).
- Real spam already lands in Gmail's own **Spam** folder, and tidyinbox leaves it alone.
- Test any query in Gmail's search box first.

## When the key expires (weekly sign-in)

On Windows, the scheduled sort shows a box: *"Sign in again now?"* Choose **Yes**, and a browser tab signs you in again. Without the box, run `python tidyinbox.py auth`. It reuses the app from your first sign-in, so the downloaded JSON is only needed once.

If the network is down, the scheduled sort stays quiet and the next run tries again.

## Safety

- The key lives in your OS key store and is never written to a file by tidyinbox.
- It asks Google for the `gmail.modify` scope. That scope can move and label mail but **cannot delete it for good**. Google's consent screen also lists composing and sending, because no narrower scope can move mail. tidyinbox never sends.
- It reads only headers: From and Subject of a few samples, and the From of up to 300 messages for `senders`. Searches run on Google's side, and bodies are never downloaded.
- The downloaded `client_secret*.json` holds your app's secret. The wizard offers to delete it after sign-in, since later sign-ins reuse the copy in the key store. Sign-in always talks to Google's own addresses, whatever the file says.
- `rules.toml` and `client_secret*.json` are git-ignored.
- To cut access completely, run `python tidyinbox.py logout`, then remove the app at <https://myaccount.google.com/permissions>.

See [PRIVACY.md](PRIVACY.md).

## Limits

- The message box is Windows only. On macOS/Linux, a cron job that cannot sign in fails, and cron's own mail or log carries the error. On Linux, cron may not reach the desktop key store at all.
- It moves messages, not whole threads. A conversation that mixes sorted and unsorted mail can stay half in the inbox.

## Develop

```bash
bash check.sh    # unit tests (fake Gmail, no network) + the real libraries load
```

## License

MIT
