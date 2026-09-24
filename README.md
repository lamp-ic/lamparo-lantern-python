# lamparo-lantern

The lantern for Python: a read-only, signed view that tells [lamparo](https://lamparo.app) what the site knows
about itself — the Python version and the installed distributions with their versions. Zero dependency,
Python 3.9 or later. Same protocol as the PHP and Node lanterns.

It never writes, never imports anything from a request, collects a closed list of facts, and answers a bare
`404` to any request that is not signed with the site's key. Without a key it stays silent: a staging copy
never talks.

## Install

```sh
pip install lamparo-lantern
```

## Django

`urls.py`:

```python
from django.urls import path
from lamparo_lantern.django import lantern

urlpatterns = [
    path("lamparo", lantern()),
    # ...
]
```

## WSGI (Flask, or any WSGI server)

```python
from lamparo_lantern.wsgi import lantern
from werkzeug.middleware.dispatcher import DispatcherMiddleware

app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/lamparo": lantern()})
```

The route must answer at `https://your-site/lamparo`. Give it the site's key from lamparo, as an environment
variable named after the key — never in the code, never in git:

```
LAMPARO_KEY_09887C4F=k_09887c4f:…
```

In systemd (`Environment=`), Docker (`environment:`), gunicorn (`--env`), or the host's configuration variables.

## What it reads

- `runtime`: `python`, its version, the OS family;
- `packages`: the installed distributions (`importlib.metadata`), each with its exact version, and whether
  `requirements.txt` at the project root names it (`direct`).

Nothing else: no settings, no environment, no data. The whole code is in `src/lamparo_lantern/__init__.py`,
short enough to read before you add it.

## Licence

MIT — lamp (lamp-ic.fr).
