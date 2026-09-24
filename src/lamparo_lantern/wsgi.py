"""
WSGI (Flask, Bottle, un serveur nu) : une application à monter sur /lamparo —
    from lamparo_lantern.wsgi import lantern
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/lamparo": lantern()})
Sous un serveur qui monte l'application à la racine, PATH_INFO vaut /lamparo et c'est ce chemin qui est signé.
"""
from typing import Optional

from . import handle


def lantern(root: Optional[str] = None):
    def app(environ, start_response):
        path = (environ.get("SCRIPT_NAME") or "") + (environ.get("PATH_INFO") or "/")
        status, headers, body = handle(
            environ.get("REQUEST_METHOD", ""),
            path,
            lambda name: environ.get("HTTP_" + name.upper().replace("-", "_")),
            root=root,
        )
        reason = "OK" if status == 200 else "Not Found"
        start_response("%d %s" % (status, reason), list(headers.items()) + [("Content-Length", str(len(body)))])
        return [body]

    return app
