"""
ASGI (FastAPI, Starlette, Quart, un serveur nu) : une application à monter sur /lamparo —
    from lamparo_lantern.asgi import lantern
    app.mount("/lamparo", lantern())
Montée, l'application voit root_path=/lamparo et path vide : c'est le chemin complet qui est signé.
"""
from typing import Optional

from . import handle


def lantern(root: Optional[str] = None):
    async def app(scope, receive, send):
        if scope.get("type") != "http":
            return
        raw = {name.decode("latin-1").lower(): value.decode("latin-1") for name, value in scope.get("headers") or []}
        path = (scope.get("root_path") or "") + (scope.get("path") or "")
        status, headers, body = handle(scope.get("method", ""), path or "/", lambda name: raw.get(name.lower()), root=root)
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()] + [(b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})

    return app
