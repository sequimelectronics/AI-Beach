# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Job 09, part A: snapshots for the operator only, message retention, and optional HTTPS.
(The launcher's Windows/POSIX clean-up is tested in test_cleanup.LauncherTests.)

Against a temporary data directory with a fake clock. The engine side of the snapshot fix (a
patched Clawblox refusing the spectator token) is shown live by scripts/snapshot_live.py.
"""

from __future__ import annotations

import random
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach import tls  # noqa: E402
from beach.core import SANDCHAT, Beach, BeachError  # noqa: E402

try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False


class FakeClock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hardening-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(9))
        self.admin_tok = self.beach.ensure_admin()
        self.sandy, self.sandy_tok = self.beach.add_participant("Sandy", "agent")
        self.coral, self.coral_tok = self.beach.add_participant("Coral", "person")

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)


# A1 ------------------------------------------------------------------ snapshots: operator only

class SnapshotPatchTests(unittest.TestCase):
    def test_the_patch_refuses_anything_but_the_operator_token(self):
        patch = (ROOT / "patches" / "clawblox-snapshot-operator-only.patch").read_text()
        self.assertIn("MIT", patch)
        self.assertIn("https://github.com/nacloos/clawblox", patch)
        added = "\n".join(line for line in patch.splitlines() if line.startswith("+"))
        removed = "\n".join(line for line in patch.splitlines() if line.startswith("-"))
        self.assertIn("FORBIDDEN", added)
        self.assertIn("operator_token_matches", patch)
        self.assertIn("require_spectator_access", removed)    # the spectator path is gone from /snapshot

    def test_nothing_of_ours_reads_snapshots(self):
        # The bridge, the adapter and the scripts use /spectate and /observe, never /snapshot.
        hits = []
        for path in list(ROOT.glob("beach/**/*.py")) + list(ROOT.glob("adapters/**/*.py")) + \
                list(ROOT.glob("scripts/*.py")) + list(ROOT.glob("worlds/**/*.js")) + list(ROOT.glob("worlds/**/*.lua")):
            if "vendor" in path.parts or path.name == "snapshot_live.py":
                continue
            if "/snapshot" in path.read_text(errors="replace"):
                hits.append(str(path.relative_to(ROOT)))
        self.assertEqual(hits, [])


# A4 ------------------------------------------------------------------------ message retention

class RetentionTests(Case):
    def say(self, who, text):
        return self.beach.post(who.id, SANDCHAT, text)

    def text_of(self, mid):
        return self.beach.db.one("SELECT text, deleted FROM messages WHERE id = ?", (mid,))

    def test_default_is_90_days_and_old_messages_go(self):
        b = self.beach
        self.assertEqual(b.setting("message_retention_days"), 90)
        b.join(self.sandy.id, SANDCHAT)
        b.join(self.coral.id, SANDCHAT)
        old = self.say(self.sandy, "an old line about the tide")["id"]
        self.clock.advance(60 * 86400)
        middle = self.say(self.coral, "a line from two months ago")["id"]
        self.clock.advance(31 * 86400)
        new = self.say(self.sandy, "a fresh line")["id"]
        older = b.db.one("SELECT COUNT(*) AS n FROM messages WHERE created_at < ?", (self.clock.t - 90 * 86400,))["n"]
        self.assertEqual(older, 3)                               # the old line, and the two arrivals before it
        self.assertEqual(b.sweep_retention(), 3)
        row = self.text_of(old)
        self.assertIsNone(row["text"])
        self.assertEqual(row["deleted"], 1)
        self.assertFalse(b.db.q("SELECT 1 FROM witnesses WHERE message_id = ?", (old,)))
        self.assertEqual(self.text_of(middle)["text"], "a line from two months ago")
        self.assertEqual(self.text_of(new)["text"], "a fresh line")
        audit = b.audit()
        self.assertEqual(audit[-1]["what"], "retention")
        self.assertEqual(audit[-1]["admin"], "the Beach")
        self.assertIn("removed 3 messages older than 90 days", audit[-1]["detail"])
        self.assertEqual(b.sweep_retention(), 0)                 # nothing left to do: no new audit row
        self.assertEqual(len(b.audit()), len(audit))

    def test_the_text_is_gone_from_the_file(self):
        b = self.beach
        b.join(self.sandy.id, SANDCHAT)
        self.say(self.sandy, "zqxj-unique-marker-1234")
        self.clock.advance(91 * 86400)
        b.sweep_retention()
        b.db.close()
        raw = b"".join(p.read_bytes() for p in Path(self.dir).glob("beach.db*"))
        self.assertNotIn(b"zqxj-unique-marker-1234", raw)
        self.beach = Beach(self.dir, clock=self.clock)          # for tearDown

    def test_admin_deletions_stay_in_the_audit_trail(self):
        b = self.beach
        b.join(self.sandy.id, SANDCHAT)
        mid = self.say(self.sandy, "deleted by the keeper")["id"]
        admin = b.authenticate(self.admin_tok)
        b.delete_message(admin, mid)
        self.clock.advance(200 * 86400)
        b.sweep_retention()
        whats = [a["what"] for a in b.audit()]
        self.assertIn("delete_message", whats)                   # never trimmed

    def test_forever_keeps_everything(self):
        b = self.beach
        b.update_settings({"message_retention_days": None})
        b.join(self.sandy.id, SANDCHAT)
        mid = self.say(self.sandy, "kept forever")["id"]
        self.clock.advance(3650 * 86400)
        self.assertEqual(b.sweep_retention(), 0)
        self.assertEqual(self.text_of(mid)["text"], "kept forever")

    def test_upkeep_runs_it_and_the_setting_is_checked(self):
        b = self.beach
        b.update_settings({"message_retention_days": 7})
        b.join(self.sandy.id, SANDCHAT)
        mid = self.say(self.sandy, "a week and a day")["id"]
        self.clock.advance(8 * 86400)
        b.tick()
        self.assertIsNone(self.text_of(mid)["text"])
        for bad in (0, -3, 1.5, "90", True):
            with self.assertRaises(BeachError):
                b.update_settings({"message_retention_days": bad})

    def test_keeper_page_shows_it(self):
        js = (ROOT / "beach" / "web" / "keeper.js").read_text()
        self.assertIn("message_retention_days", js)
        self.assertIn("Keep messages forever", js)


# A3 ------------------------------------------------------------------------------------ HTTPS

class TlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="tls-"))
        cls.names = tls.wanted_names("https://192.168.1.20:8766", ["beach.lan"])
        cls.cert, cls.key, cls.ca = tls.ensure(cls.dir, cls.names, log=lambda m: None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def handshake(self, cert: Path, key: Path, server_name: str) -> None:
        """A real TLS handshake over loopback: a server with `cert`, a client that trusts only the CA."""
        srv_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        srv_ctx.load_cert_chain(str(cert), str(key))
        cli_ctx = ssl.create_default_context(cafile=str(self.ca))
        listener = socket.create_server(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        errors = []

        def serve():
            try:
                conn, _ = listener.accept()
                with srv_ctx.wrap_socket(conn, server_side=True) as s:
                    s.sendall(b"ok")
            except (ssl.SSLError, OSError) as e:
                errors.append(e)
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
                with cli_ctx.wrap_socket(raw, server_hostname=server_name) as s:
                    self.assertEqual(s.recv(2), b"ok")
        finally:
            t.join(5)
            listener.close()

    def test_names(self):
        for n in ("localhost", "127.0.0.1", "::1", "192.168.1.20", "beach.lan"):
            self.assertIn(n, self.names)

    def test_a_browser_that_trusts_the_ca_accepts_the_beach(self):
        for name in ("localhost", "127.0.0.1", "192.168.1.20", "beach.lan"):
            self.handshake(self.cert, self.key, name)

    def test_the_wrong_name_is_refused(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(self.cert, self.key, "elsewhere.lan")

    def test_the_ca_cannot_vouch_for_a_public_site(self):
        # Even with the CA's private key, a certificate for a public name is refused (name constraints).
        ca_key = tls.RSAKey.from_der(tls._unpem((self.dir / "tls" / "beach-ca.key").read_text()))
        key, der = tls.make_leaf(["www.example.com"], ca_key, tls.ca_name())
        bad_cert, bad_key = self.dir / "bad.pem", self.dir / "bad.key"
        bad_cert.write_text(tls._pem("CERTIFICATE", der) + self.ca.read_text())
        bad_key.write_text(tls._pem("RSA PRIVATE KEY", key.private_der()))
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(bad_cert, bad_key, "www.example.com")

    def test_kept_across_starts_and_renewed_for_new_names(self):
        ca_before = self.ca.read_text()
        leaf_before = self.cert.read_text()
        tls.ensure(self.dir, self.names, log=lambda m: None)
        self.assertEqual(self.cert.read_text(), leaf_before)            # same names: nothing remade
        tls.ensure(self.dir, self.names + ["10.0.0.7"], log=lambda m: None)
        self.assertEqual(self.ca.read_text(), ca_before)                # a private address: same CA
        self.assertNotEqual(self.cert.read_text(), leaf_before)         # ...a new certificate for it
        tls.ensure(self.dir, self.names, log=lambda m: None)            # back as it was, for other tests

    def test_private_keys_are_private(self):
        import os
        import stat
        if os.name == "nt":
            self.skipTest("POSIX permissions")
        for k in ("beach.key", "beach-ca.key"):
            mode = stat.S_IMODE((self.dir / "tls" / k).stat().st_mode)
            self.assertEqual(mode, 0o600)


class HttpsSettingTests(Case):
    def test_off_by_default_and_checked(self):
        b = self.beach
        self.assertFalse(b.setting("https"))
        self.assertEqual(b.setting("https_port"), 8766)
        b.update_settings({"https": True, "https_names": ["Beach.LAN", "192.168.1.9"]})
        self.assertEqual(b.setting("https_names"), ["beach.lan", "192.168.1.9"])
        for bad in ({"https": "yes"}, {"https_port": 70000}, {"https_names": ["not a name!"]},
                    {"https_cert": "/no/such/file.pem"}):
            with self.assertRaises(BeachError):
                b.update_settings(bad)

    @unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
    def test_ca_download_and_status(self):
        from beach.app import create_app
        admin = {"Authorization": f"Bearer {self.admin_tok}"}
        plain = TestClient(create_app(self.beach, upkeep_interval=None, serving={"http": "http://127.0.0.1:8765"}))
        self.assertEqual(plain.get("/beach-ca.pem").status_code, 404)       # not serving its own CA
        st = plain.get("/admin/https", headers=admin).json()
        self.assertFalse(st["setting"])
        self.assertFalse(st["restart_needed"])
        tls.ensure(Path(self.dir), tls.wanted_names(None, []), log=lambda m: None)
        own = TestClient(create_app(self.beach, upkeep_interval=None,
                                    serving={"http": "http://127.0.0.1:8765", "https": "https://127.0.0.1:8766",
                                             "own_ca": True}))
        r = own.get("/beach-ca.pem")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"BEGIN CERTIFICATE", r.content)
        self.assertNotIn(b"PRIVATE", r.content)
        self.assertEqual(r.headers["content-type"], "application/x-x509-ca-cert")
        self.assertEqual(own.get("/admin/https", headers={"Authorization": f"Bearer {self.coral_tok}"}).status_code, 403)
        self.assertTrue(own.get("/admin/https", headers=admin).json()["restart_needed"])   # setting off, HTTPS on


if __name__ == "__main__":
    unittest.main()
