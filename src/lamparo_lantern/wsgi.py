"""
WSGI (Flask, Bottle, un serveur nu) : une application à monter sur /lamparo —
    from lamparo_lantern.wsgi import lantern
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/lamparo": lantern()})
Monté, SCRIPT_NAME vaut /lamparo et PATH_INFO est vide ; à la racine, PATH_INFO vaut /lamparo. Dans les deux cas
c'est « /lamparo » qui est signé, barre finale ou pas.
"""
from typing import Optional

from . import handle


def lantern(root: Optional[str] = None):
    def app(environ, start_response):
        # Sous un montage (DispatcherMiddleware), SCRIPT_NAME porte le préfixe et PATH_INFO est vide : le chemin
        # complet est « /lamparo », sans barre finale ajoutée — c'est lui que la plateforme a signé.
        path = ((environ.get("SCRIPT_NAME") or "") + (environ.get("PATH_INFO") or "")) or "/"
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
