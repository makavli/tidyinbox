import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path, PurePosixPath
from unittest.mock import MagicMock, patch

import tidyinbox as ti
import wizard

KEEP = "is:starred"
RULES = {"keep": KEEP, "bucket": [
    {"label": "Sorted/Junk", "query": "from:junk.example"},
    {"label": "Sorted/Promotions", "query": "category:promotions"},
    {"label": "Sorted/Social", "query": "category:social"},
]}


def q(query):
    return f"in:inbox ({query}) -({KEEP})"


class FakeGmail:
    def __init__(self, results, labels=None):
        self.results, self.lab, self.created, self.calls = results, dict(labels or {}), [], []

    def ids(self, q=None, label_id=None, limit=None):
        return list(self.results.get(q or label_id, []))[:limit]

    def labels(self):
        return {k.lower(): v for k, v in self.lab.items()}

    def create_label(self, name):
        self.created.append(name)
        self.lab[name] = "id-" + name
        return self.lab[name]

    def inbox_total(self):
        return 10

    def headers(self, i):
        return {"From": f"Someone <{'Boss' if i == 'm9' else 'pal'}@Example.com>", "Subject": f"subject {i}"}

    def modify(self, ids, add, remove):
        self.calls.append((ids, add, remove))


def fake():
    # m2 matches Junk and Promotions; Social matches nothing
    return FakeGmail({q("from:junk.example"): ["m1", "m2"], q("category:promotions"): ["m2", "m3"]})


def quiet(fn, *a, **kw):
    with redirect_stdout(io.StringIO()) as out:
        fn(*a, **kw)
    return out.getvalue()


class Logic(unittest.TestCase):
    def test_first_bucket_wins_and_keep_is_excluded(self):
        self.assertEqual(ti.plan(fake(), RULES),
                         [("Sorted/Junk", ["m1", "m2"]), ("Sorted/Promotions", ["m3"]), ("Sorted/Social", [])])

    def test_no_keep_means_no_exclusion(self):
        gm = FakeGmail({"in:inbox (x)": ["a"]})
        self.assertEqual(ti.plan(gm, {"bucket": [{"label": "L", "query": "x"}]}), [("L", ["a"])])

    def test_dry_run_changes_nothing(self):
        gm = fake()
        out = quiet(ti.sweep, gm, RULES, False)
        self.assertEqual((gm.calls, gm.created), ([], []))
        self.assertIn("3 of 10", out)

    def test_apply_creates_parents_first_and_leaves_inbox(self):
        gm = fake()
        quiet(ti.sweep, gm, RULES, True)
        self.assertEqual(gm.created, ["Sorted", "Sorted/Junk", "Sorted/Promotions"])  # Social is empty: no label
        self.assertEqual(gm.calls, [(["m1", "m2"], ["id-Sorted/Junk"], ["INBOX"]),
                                    (["m3"], ["id-Sorted/Promotions"], ["INBOX"])])

    def test_senders_counts_only_mail_that_stays(self):
        gm = fake()
        gm.results["in:inbox -(from:junk.example) -(category:promotions) -(category:social)"] = ["m8", "m9", "m10"]
        out = quiet(ti.senders, gm, RULES)
        self.assertIn("2  pal@example.com", out)
        self.assertIn("1  boss@example.com", out)
        self.assertIn("newest 3 messages", out)

    def test_label_names_match_any_case(self):
        gm = FakeGmail({"in:inbox (x)": ["a"]}, labels={"Sorted": "S", "Sorted/Junk": "J"})
        quiet(ti.sweep, gm, {"bucket": [{"label": "sorted/junk", "query": "x"}]}, True)
        self.assertEqual((gm.created, gm.calls), ([], [(["a"], ["J"], ["INBOX"])]))

    def test_undo_puts_mail_back(self):
        gm = FakeGmail({"L1": ["a", "b"]}, labels={"Sorted/Junk": "L1"})
        quiet(ti.undo, gm, "Sorted/Junk")
        self.assertEqual(gm.calls, [(["a", "b"], ["INBOX"], ["L1"])])
        with self.assertRaises(SystemExit):
            ti.undo(gm, "Nope")


class Rules(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "rules.toml")
            p.write_text(text, encoding="utf-8")
            return ti.load_rules(p)

    def test_example_file_loads(self):
        self.assertTrue(ti.load_rules(Path(__file__).with_name("rules.example.toml"))["bucket"])

    def test_bad_rules_are_refused(self):
        for text in ["", 'bucket = "x"\n', '[[bucket]]\nlabel = "L"\n', '[[bucket]]\nlabel = ""\nquery = "x"\n',
                     '[[bucket]]\nlabel = "Sorted/"\nquery = "x"\n', '[[bucket]]\nlabel = " L"\nquery = "x"\n',
                     'keep = 1\n[[bucket]]\nlabel = "L"\nquery = "x"\n']:
            with self.subTest(text=text), self.assertRaises(SystemExit):
                self.load(text)

    def test_missing_file_is_refused(self):
        with self.assertRaises(SystemExit):
            ti.load_rules(Path("no-such-rules.toml"))


class Api(unittest.TestCase):
    def test_ids_follows_pages(self):
        svc = MagicMock()
        svc.users().messages().list.return_value.execute.side_effect = [
            {"messages": [{"id": "a"}], "nextPageToken": "t"}, {"messages": [{"id": "b"}]}]
        self.assertEqual(ti.Gmail(svc).ids(q="x"), ["a", "b"])
        self.assertEqual(svc.users().messages().list.call_args.kwargs["pageToken"], "t")

    def test_ids_stops_at_limit(self):
        svc = MagicMock()
        svc.users().messages().list.return_value.execute.side_effect = [
            {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "t"}, {"messages": [{"id": "c"}]}]
        self.assertEqual(ti.Gmail(svc).ids(q="x", limit=1), ["a"])

    def test_modify_chunks_by_1000(self):
        svc = MagicMock()
        ti.Gmail(svc).modify([str(i) for i in range(2500)], ["L"], ["INBOX"])
        sizes = [len(c.kwargs["body"]["ids"]) for c in svc.users().messages().batchModify.call_args_list]
        self.assertEqual(sizes, [1000, 1000, 500])

    def test_labels_skip_system_labels(self):
        svc = MagicMock()
        svc.users().labels().list.return_value.execute.return_value = {"labels": [
            {"name": "TRASH", "id": "TRASH", "type": "system"}, {"name": "Sorted", "id": "L1", "type": "user"}]}
        self.assertEqual(ti.Gmail(svc).labels(), {"sorted": "L1"})


class Auth(unittest.TestCase):
    def test_sign_in_again_reuses_the_saved_app(self):
        keyring, flowmod = MagicMock(), MagicMock()
        keyring.get_password.return_value = json.dumps({"client_id": "cid", "client_secret": "cs", "refresh_token": "old"})
        creds = flowmod.InstalledAppFlow.from_client_config.return_value.run_local_server.return_value
        creds.client_id, creds.client_secret, creds.refresh_token = "cid", "cs", "new"
        mods = {"keyring": keyring, "google_auth_oauthlib": MagicMock(), "google_auth_oauthlib.flow": flowmod}
        with patch.dict(sys.modules, mods):
            quiet(ti.auth)
        config = flowmod.InstalledAppFlow.from_client_config.call_args.args[0]["installed"]
        self.assertEqual((config["client_id"], config["client_secret"]), ("cid", "cs"))
        self.assertEqual(json.loads(keyring.set_password.call_args.args[2])["refresh_token"], "new")

    def test_a_crafted_client_file_cannot_change_googles_endpoints(self):
        keyring, flowmod = MagicMock(), MagicMock()
        creds = flowmod.InstalledAppFlow.from_client_config.return_value.run_local_server.return_value
        creds.client_id, creds.client_secret, creds.refresh_token = "cid", "cs", "tok"
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "client_secret_evil.json")
            f.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "cs",
                                                   "auth_uri": "https://evil.example/auth",
                                                   "token_uri": "https://evil.example/token"}}))
            with patch.dict(sys.modules, {"keyring": keyring, "google_auth_oauthlib": MagicMock(),
                                          "google_auth_oauthlib.flow": flowmod}):
                quiet(ti.auth, str(f))
                Path(d, "bad.json").write_text("[]")
                with self.assertRaises(SystemExit):
                    ti.auth(str(Path(d, "bad.json")))
        call = flowmod.InstalledAppFlow.from_client_config.call_args
        self.assertEqual({k: call.args[0]["installed"][k] for k in ti.GOOGLE_URIS}, ti.GOOGLE_URIS)
        self.assertTrue(call.kwargs["autogenerate_code_verifier"])

    def test_headers_lose_control_characters(self):
        gm = FakeGmail({"in:inbox (x)": ["a"]})
        gm.headers = lambda i: {"From": "Evil <e@x.example>\x1b]52;c;cGF3bmVk\x07", "Subject": "hi\x1b[2J"}
        out = quiet(ti.sweep, gm, {"bucket": [{"label": "L", "query": "x"}]}, False)
        self.assertNotIn("\x1b", out)
        self.assertIn("hi", out)

    def test_sign_in_again_without_a_saved_key_says_run_setup(self):
        keyring = MagicMock()
        keyring.get_password.return_value = None
        with patch.dict(sys.modules, {"keyring": keyring, "google_auth_oauthlib": MagicMock(),
                                      "google_auth_oauthlib.flow": MagicMock()}):
            with self.assertRaises(SystemExit) as e:
                ti.auth()
        self.assertIn("setup", e.exception.code)


class Wizard(unittest.TestCase):
    def test_ask_repeats_until_a_valid_choice(self):
        with patch("builtins.input", side_effect=["x", "", "2"]):
            self.assertEqual(quiet_value(wizard.ask, "pick", ["1", "2"]), "2")

    def test_schedule_command_per_platform(self):
        py = Path("C:/venv/Scripts/python.exe")
        win = wizard.schedule_command("hourly", "win32", py, Path("C:/app/tidyinbox.py"))
        self.assertEqual(win[:7], ["schtasks", "/create", "/tn", "tidyinbox", "/sc", "HOURLY", "/f"])
        self.assertTrue(win[-1].endswith('"C:\\app\\tidyinbox.py" sweep --apply') or win[-1].endswith(
            '"C:/app/tidyinbox.py" sweep --apply'))
        cron = wizard.schedule_command("daily", "linux", PurePosixPath("/v/bin/python"),
                                       PurePosixPath("/app/tidyinbox.py"))
        self.assertEqual(cron, '0 9 * * * "/v/bin/python" "/app/tidyinbox.py" sweep --apply')

    def test_newest_client_json(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(wizard.newest_client_json(Path(d)))
            Path(d, "client_secret_1.json").write_text("{}")
            self.assertEqual(wizard.newest_client_json(Path(d)).name, "client_secret_1.json")

    def test_full_run_signs_in_dry_runs_applies_on_yes_and_schedules(self):
        with tempfile.TemporaryDirectory() as d:
            secret = Path(d, "client_secret_x.json")
            secret.write_text("{}")
            answers = ["n",            # open the console? no
                       "",             # Enter after downloading
                       "",             # key mode: default 1 (weekly)
                       str(secret),    # path to the client JSON
                       "",             # delete the JSON? default yes
                       "",             # senders? default no
                       "y",            # move them now? yes
                       "1"]            # every hour
            with patch("builtins.input", side_effect=answers), \
                    patch.object(ti, "RULES", Path(d, "rules.toml")), \
                    patch.object(ti, "stored_key", return_value=None), \
                    patch.object(ti, "auth") as auth, patch.object(ti, "connect") as connect, \
                    patch.object(ti, "sweep") as sweep, patch.object(ti, "senders") as senders, \
                    patch.object(wizard, "newest_client_json", return_value=None), \
                    patch.object(wizard, "schedule") as schedule:
                out = quiet(wizard.run_wizard)
                self.assertTrue(Path(d, "rules.toml").exists())  # copied from the example
                self.assertFalse(secret.exists())  # deleted after sign-in
            auth.assert_called_once_with(str(secret))
            senders.assert_not_called()
            self.assertEqual([c.kwargs["apply"] for c in sweep.call_args_list], [False, True])
            schedule.assert_called_once_with("hourly")
            self.assertIn("Weekly sign-in", out)
            connect.assert_called_once()

    def test_signed_in_user_skips_to_rules_and_can_decline_everything(self):
        with tempfile.TemporaryDirectory() as d:
            answers = ["", "", "", "3"]  # skip to rules: yes; senders: no; move: no; schedule: never
            with patch("builtins.input", side_effect=answers), \
                    patch.object(ti, "RULES", Path(d, "rules.toml")), \
                    patch.object(ti, "stored_key", return_value={"client_id": "c"}), \
                    patch.object(ti, "auth") as auth, patch.object(ti, "connect"), \
                    patch.object(ti, "sweep") as sweep, patch.object(wizard, "schedule") as schedule:
                quiet(wizard.run_wizard)
            auth.assert_not_called()
            self.assertEqual([c.kwargs["apply"] for c in sweep.call_args_list], [False])
            schedule.assert_not_called()


def quiet_value(fn, *a):
    with redirect_stdout(io.StringIO()):
        return fn(*a)


if __name__ == "__main__":
    unittest.main()
