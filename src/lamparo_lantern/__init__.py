"""
lamparo — la lanterne, pour Python
---------------------------------------------------------------------------
Une vue en lecture seule, signée, qui dit à lamparo ce que le site sait de lui-même : la version de Python et les
paquets installés, avec leurs versions. Aucune dépendance. Même protocole que les lanternes PHP et Node.

LA CLÉ N'EST PAS DANS LE CODE. Elle vient de l'environnement, dans une variable nommée d'après la clé —
LAMPARO_KEY_09887C4F pour la clé k_09887c4f, valeur « identifiant:secret » — dans l'environnement du service
(systemd, Docker, gunicorn) ou les variables de l'hébergeur. Sans clé, la lanterne répond 404 : une préproduction
ne parle jamais.

PRINCIPES NON NÉGOCIABLES :
  1. LECTURE SEULE ABSOLUE — n'écrit jamais, ne modifie jamais rien.
  2. AUCUNE EXÉCUTION DYNAMIQUE — rien d'importé ni d'évalué depuis une entrée.
  3. LISTE BLANCHE — ne collecte que les faits énumérés dans collect().
  4. MUETTE SANS SIGNATURE — toute requête invalide reçoit un 404 vide.

MIT — lamp (lamp-ic.fr). Publiée sur PyPI : pip install lamparo-lantern
"""
import hashlib
import hmac
import json
import os
import platform
import re
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from typing import Callable, Dict, List, Optional, Tuple

LANTERN_VERSION = "0.2.1"
# Tolérance d'horloge, en secondes.
MAX_SKEW = 300
# Plus de clés que ça, ce n'est plus un site partagé : c'est une erreur de configuration.
MAX_KEYS = 10
# Les distributions installées d'une application se comptent en dizaines ; au-delà, on coupe et on le dit.
MAX_PACKAGES = 500
# Un requirements.txt pèse quelques kilo-octets ; au-delà d'un méga-octet on ne le lit pas.
MAX_MANIFEST_BYTES = 1048576

_KEY_NAME = re.compile(r"^LAMPARO_KEY(_[A-Za-z0-9]+)?$")
_KEY_VALUE = re.compile(r"^\s*([A-Za-z0-9_]{4,32}):([A-Za-z0-9]{32,128})\s*$")
_SIGNATURE = re.compile(r"^[0-9a-fA-F]{64}$")
_NONCE = re.compile(r"^[A-Za-z0-9]{8,64}$")
_TIMESTAMP = re.compile(r"^[0-9]{1,12}$")
# Un nom de distribution, tel que PEP 503 le normalise : minuscules, un seul tiret entre les mots.
_NAME = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$")

Response = Tuple[int, Dict[str, str], bytes]


# ---------------------------------------------------------------------------
# Les clés : l'environnement, jamais le code. Une variable par compte lamparo qui surveille le site.
# ---------------------------------------------------------------------------

def load_keys(env: Dict[str, str]) -> List[Dict[str, str]]:
    keys: List[Dict[str, str]] = []
    seen = set()
    for name in sorted(env):
        value = env[name]
        if not isinstance(value, str) or not _KEY_NAME.match(name):
            continue
        match = _KEY_VALUE.match(value)
        if match is None or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        keys.append({"id": match.group(1), "secret": match.group(2)})
        if len(keys) >= MAX_KEYS:
            break
    return keys


# ---------------------------------------------------------------------------
# Authentification HMAC — chaîne canonique (séparateur \n) : GET \n {path} \n {key_id} \n {timestamp} \n {nonce}
# ---------------------------------------------------------------------------

def _hmac(secret: str, data: str) -> str:
    return hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()


def authenticate(keys: List[Dict[str, str]], method: str, path: str, header: Callable[[str], Optional[str]], now: int) -> Optional[Dict[str, str]]:
    if method != "GET":
        return None
    key_id = header("x-lamparo-key-id")
    timestamp = header("x-lamparo-timestamp")
    nonce = header("x-lamparo-nonce")
    signature = header("x-lamparo-signature")
    if not key_id or not timestamp or not nonce or not signature:
        return None
    key = next((k for k in keys if k["id"] == key_id), None)
    if key is None or not _TIMESTAMP.match(timestamp) or abs(now - int(timestamp)) > MAX_SKEW or not _NONCE.match(nonce):
        return None
    # Une signature qui n'est pas soixante-quatre chiffres hexadécimaux n'est pas une signature : 404, pas une erreur.
    if not _SIGNATURE.match(signature):
        return None
    canonical = "\n".join(["GET", path, key_id, timestamp, nonce])
    return key if hmac.compare_digest(_hmac(key["secret"], canonical), signature.lower()) else None


# ---------------------------------------------------------------------------
# La collecte : une liste blanche, rien d'autre.
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def collect(root: str, errors: List[Dict[str, str]]) -> Dict[str, object]:
    return {
        "runtime": {
            "name": "python",
            "version": platform.python_version(),
            "env": None,
            "os": sys.platform,
        },
        "packages": read_packages(root, errors),
    }


def read_packages(root: str, errors: List[Dict[str, str]]) -> List[Dict[str, object]]:
    """
    Les distributions installées, par leurs métadonnées, avec leur version exacte ; celles que requirements.txt nomme
    à la racine du projet sont dites directes. Rien n'est importé : les métadonnées se lisent comme du texte.
    """
    direct = _read_requirements(root, errors)
    seen: Dict[str, str] = {}
    for dist in metadata.distributions():
        try:
            raw = dist.metadata["Name"]
            version = dist.version
        except Exception:  # une distribution abîmée ne fait pas taire la lanterne
            continue
        if not raw or not version:
            continue
        name = normalize_name(raw)
        if not _NAME.match(name) or name in seen:
            continue
        seen[name] = version
    names = sorted(seen)
    if len(names) > MAX_PACKAGES:
        errors.append({"scope": "packages", "reason": "packages truncated"})
        names = names[:MAX_PACKAGES]
    return [{"name": name, "version": seen[name], "direct": name in direct if direct is not None else None} for name in names]


def _read_requirements(root: str, errors: List[Dict[str, str]]) -> Optional[set]:
    path = os.path.join(root, "requirements.txt")
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size > MAX_MANIFEST_BYTES:
        errors.append({"scope": "packages", "reason": "requirements.txt too large"})
        return None
    names = set()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.split("#", 1)[0].strip()
                if not line or line.startswith("-"):
                    continue
                match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
                if match:
                    names.add(normalize_name(match.group(1)))
    except OSError:
        errors.append({"scope": "packages", "reason": "requirements.txt unreadable"})
        return None
    return names


# ---------------------------------------------------------------------------
# Entrée
# ---------------------------------------------------------------------------

def not_found() -> Response:
    """Réponse indistinguable d'une route inexistante : on ne confirme jamais l'existence de la lanterne."""
    return 404, {"Content-Type": "text/html; charset=utf-8"}, b""


def respond(payload: Dict[str, object], secret: str) -> Response:
    """La réponse est signée avec le même secret : la plateforme sait que c'est bien la lanterne qui parle."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return 200, {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex, nofollow",
        "X-Lamparo-Signature": _hmac(secret, body),
    }, body.encode("utf-8")


def handle(method: str, path: str, header: Callable[[str], Optional[str]], root: Optional[str] = None, env: Optional[Dict[str, str]] = None, now: Optional[int] = None) -> Response:
    """Traite une requête décrite de façon neutre ; les adaptateurs (django, wsgi) font le reste."""
    # Un montage rend parfois « /lamparo/ » pour « /lamparo » : c'est le même chemin, et c'est lui qui est signé.
    path = path.rstrip("/") or "/"
    key = authenticate(load_keys(env if env is not None else dict(os.environ)), method, path, header, now if now is not None else int(time.time()))
    if key is None:
        return not_found()
    errors: List[Dict[str, str]] = []
    facts = collect(root or os.getcwd(), errors)
    return respond({
        "probe_version": LANTERN_VERSION,
        "key_id": key["id"],
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "nonce": header("x-lamparo-nonce"),
        "facts": facts,
        "errors": errors,
    }, key["secret"])
