import hashlib
import hmac
import json
import os
import platform
import tempfile
import time
import unittest

from lamparo_lantern import LANTERN_VERSION, handle, load_keys, normalize_name
from lamparo_lantern.asgi import lantern as asgi_lantern
from lamparo_lantern.wsgi import lantern as wsgi_lantern

SECRET = "a" * 40
ENV = {"LAMPARO_KEY_09887C4F": "k_09887c4f:" + SECRET, "PATH": "/usr/bin"}
NOW = 1_800_000_000


def sign(secret, path, key_id, ts, nonce):
    return hmac.new(secret.encode(), "\n".join(["GET", path, key_id, str(ts), nonce]).encode(), hashlib.sha256).hexdigest()


def headers_for(**over):
    h = {"x-lamparo-key-id": "k_09887c4f", "x-lamparo-timestamp": str(NOW), "x-lamparo-nonce": "abcdefgh12345678"}
    h.update({k.replace("_", "-"): v for k, v in over.items()})
    if "x-lamparo-signature" not in h:
        h["x-lamparo-signature"] = sign(SECRET, "/lamparo", h["x-lamparo-key-id"], h["x-lamparo-timestamp"], h["x-lamparo-nonce"])
    return {k: v for k, v in h.items() if v is not None}


class LanternTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        with open(os.path.join(self.root, "requirements.txt"), "w") as handle_:
            handle_.write("# deps\nDjango==4.2.30\nsetuptools>=60 ; python_version >= '3.9'\n-r other.txt\n")

    def call(self, over=None, **extra):
        headers = headers_for(**(over or {}))
        return handle("GET", "/lamparo", lambda n: headers.get(n), root=self.root, env=ENV, now=NOW, **extra)

    def test_a_signed_request_gets_the_facts_signed_back(self):
        status, headers, body = self.call()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Lamparo-Signature"], hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest())
        payload = json.loads(body)
        self.assertEqual(payload["probe_version"], LANTERN_VERSION)
        self.assertEqual(payload["key_id"], "k_09887c4f")
        self.assertEqual(payload["facts"]["runtime"]["name"], "python")
        self.assertEqual(payload["facts"]["runtime"]["version"], platform.python_version())
        names = [p["name"] for p in payload["facts"]["packages"]]
        self.assertIn("setuptools", names, "Les distributions installées, par leurs métadonnées.")
        self.assertEqual(names, sorted(names))
        setuptools = next(p for p in payload["facts"]["packages"] if p["name"] == "setuptools")
        self.assertTrue(setuptools["direct"], "requirements.txt le nomme : direct, malgré le marqueur d'environnement.")
        self.assertEqual(payload["errors"], [])
        self.assertNotIn("cms", payload["facts"])

    def test_unsigned_mis_signed_stale_foreign_or_non_get_requests_get_a_bare_404(self):
        cases = [
            self.call({"x_lamparo_signature": "deadbeef"}),
            self.call({"x_lamparo_signature": None}),
            self.call({"x_lamparo_key_id": "k_unknown1"}),
            self.call({"x_lamparo_timestamp": str(NOW - 301)}),
            self.call({"x_lamparo_nonce": "short"}),
            handle("POST", "/lamparo", lambda n: headers_for().get(n), root=self.root, env=ENV, now=NOW),
            handle("GET", "/lamparo", lambda n: headers_for().get(n), root=self.root, env={}, now=NOW),
            handle("GET", "/other", lambda n: headers_for().get(n), root=self.root, env=ENV, now=NOW),
        ]
        for status, headers, body in cases:
            self.assertEqual(status, 404)
            self.assertEqual(body, b"")
            self.assertNotIn("X-Lamparo-Signature", headers)

    def test_keys_come_from_the_environment_only_ten_at_most_malformed_ignored(self):
        env = {"LAMPARO_KEY": "k_plain:" + SECRET, "LAMPARO_KEY_A": "k_aaaa:" + SECRET, "LAMPARO_KEY_A2": "k_aaaa:" + SECRET, "LAMPARO_KEY_BAD": "nope", "OTHER": "k_xxxx:" + SECRET}
        for i in range(12):
            env["LAMPARO_KEY_N%d" % i] = "k_n%d:%s" % (i, SECRET)
        keys = load_keys(env)
        self.assertEqual(len(keys), 10)
        ids = [k["id"] for k in keys]
        self.assertIn("k_plain", ids)
        self.assertIn("k_aaaa", ids)
        self.assertNotIn("k_xxxx", ids)

    def test_names_are_normalised_like_pypi_does(self):
        self.assertEqual(normalize_name("Django"), "django")
        self.assertEqual(normalize_name("typing_extensions"), "typing-extensions")
        self.assertEqual(normalize_name("zope.interface"), "zope-interface")

    def test_the_wsgi_adapter_answers_from_the_environ(self):
        app = wsgi_lantern(root=self.root)
        os.environ.update(ENV)
        try:
            headers = headers_for(x_lamparo_timestamp=str(int(__import__("time").time())))
            environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/lamparo", "QUERY_STRING": "x=1"}
            environ.update({"HTTP_" + k.upper().replace("-", "_"): v for k, v in headers.items()})
            captured = {}

            def start_response(status, response_headers):
                captured["status"] = status
                captured["headers"] = dict(response_headers)

            body = b"".join(app(environ, start_response))
            self.assertEqual(captured["status"], "200 OK")
            self.assertEqual(json.loads(body)["facts"]["runtime"]["name"], "python")
            self.assertEqual(captured["headers"]["Content-Length"], str(len(body)))
            body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": "/lamparo"}, start_response))
            self.assertEqual(captured["status"], "404 Not Found")
            self.assertEqual(body, b"")
        finally:
            for k in ENV:
                os.environ.pop(k, None)

    def test_the_asgi_adapter_answers_from_the_scope_with_the_mounted_path(self):
        import asyncio

        app = asgi_lantern(root=self.root)
        os.environ.update(ENV)
        try:
            headers = headers_for(x_lamparo_timestamp=str(int(__import__("time").time())))
            scope = {"type": "http", "method": "GET", "root_path": "/lamparo", "path": "", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
            sent = []

            async def receive():
                return {"type": "http.request"}

            async def send(message):
                sent.append(message)

            asyncio.run(app(scope, receive, send))
            self.assertEqual(sent[0]["status"], 200)
            self.assertEqual(json.loads(sent[1]["body"])["facts"]["runtime"]["name"], "python")
            sent.clear()
            asyncio.run(app({"type": "http", "method": "GET", "path": "/lamparo", "headers": []}, receive, send))
            self.assertEqual(sent[0]["status"], 404)
            self.assertEqual(sent[1]["body"], b"")
        finally:
            for k in ENV:
                os.environ.pop(k, None)


    def test_the_mounts_hand_the_path_the_platform_signed(self):
        """Audit du 25/09/2026, n° 9 : DispatcherMiddleware donne SCRIPT_NAME=/lamparo et PATH_INFO vide ; Starlette
        donne root_path=/lamparo avec path=/lamparo (ASGI récent) ou path vide (ancien) ; un montage redirige parfois
        vers /lamparo/. Dans tous les cas, c'est « /lamparo » qui est vérifié."""
        from lamparo_lantern.wsgi import lantern as wsgi_lantern
        from lamparo_lantern.asgi import lantern as asgi_lantern, Lantern
        import asyncio, inspect
        # Les adaptateurs lisent les clés dans os.environ et l'heure dans time.time() : on signe pour maintenant.
        os.environ.update(ENV)
        headers = headers_for(x_lamparo_timestamp=str(int(time.time())))
        environ = {"REQUEST_METHOD": "GET", "SCRIPT_NAME": "/lamparo", "PATH_INFO": "", "wsgi.url_scheme": "http"}
        environ.update({"HTTP_" + k.upper().replace("-", "_"): v for k, v in headers.items()})
        statuses = []
        body = b"".join(wsgi_lantern(root=self.root)(environ, lambda status, hdrs: statuses.append(status)))
        self.assertEqual(["200 OK"], statuses, "WSGI monté : SCRIPT_NAME + PATH_INFO vide = /lamparo, signé tel quel.")
        self.assertIn(b'"probe_version"', body)
        for scope_path in ("/lamparo", "", "/lamparo/"):
            scope = {"type": "http", "method": "GET", "root_path": "/lamparo", "path": scope_path, "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
            sent = []
            async def send(message):
                sent.append(message)
            asyncio.run(asgi_lantern(root=self.root)(scope, None, send))
            self.assertEqual(200, sent[0]["status"], "ASGI, path=%r" % scope_path)
        self.assertIsInstance(asgi_lantern(), Lantern)
        self.assertFalse(inspect.isfunction(asgi_lantern()), "Une instance : Starlette la pose sur une Route sans l'envelopper.")

    def test_a_signature_that_is_not_hex_is_a_bare_404_not_an_error(self):
        headers = headers_for()
        headers["x-lamparo-signature"] = "é" * 64
        status, _, body = handle("GET", "/lamparo", lambda n: headers.get(n), root=self.root, env=ENV, now=NOW)
        self.assertEqual((404, b""), (status, body))

    def test_the_response_echoes_the_request_nonce_inside_the_signed_body(self):
        headers = headers_for()
        status, _, body = handle("GET", "/lamparo", lambda n: headers.get(n), root=self.root, env=ENV, now=NOW)
        self.assertEqual(200, status)
        self.assertEqual(headers["x-lamparo-nonce"], json.loads(body)["nonce"], "Audit n° 6 : la réponse est liée à la requête.")

if __name__ == "__main__":
    unittest.main()
