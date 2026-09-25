"""
ASGI (FastAPI, Starlette, Quart, un serveur nu) : une application à poser sur /lamparo —
    from lamparo_lantern.asgi import lantern
    app.add_route("/lamparo", lantern())          # une route exacte, sans redirection
    app.mount("/lamparo", lantern())              # ou un montage : « /lamparo/ » est accepté comme « /lamparo »
Selon la version d'ASGI, `path` contient déjà `root_path` ou non : les deux formes donnent le chemin complet.
"""
from typing import Optional

from . import handle


class Lantern:
    """Une application ASGI. Une instance, pas une fonction : Starlette la monte telle quelle sur une Route."""

    def __init__(self, root: Optional[str] = None):
        self.root = root

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return
        raw = {name.decode("latin-1").lower(): value.decode("latin-1") for name, value in scope.get("headers") or []}
        root_path = scope.get("root_path") or ""
        path = scope.get("path") or ""
        full = path if (root_path and path.startswith(root_path)) else root_path + path
        status, headers, body = handle(scope.get("method", ""), full or "/", lambda name: raw.get(name.lower()), root=self.root)
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()] + [(b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})


def lantern(root: Optional[str] = None) -> Lantern:
    return Lantern(root)
