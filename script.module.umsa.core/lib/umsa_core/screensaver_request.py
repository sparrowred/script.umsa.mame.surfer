"""Versioned launch request for manual screensaver starts.

The frontend encodes the request (``encode_request``) and passes the token as
the single ``RunScript`` argument; the screensaver decodes and validates it
(``decode_request``). Both add-ons share this module through Core, so neither
imports the other. Kodi-free.
"""

import base64
import binascii
import json
import re

MAX_ARGUMENT_LENGTH = 4096
MODES = frozenset(("videos", "cross", "slide", "wall"))
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_art_types(art_types):
    """Raise ValueError unless ``art_types`` is None or a short list of names."""

    if art_types is not None and (
        not isinstance(art_types, list)
        or len(art_types) > 64
        or any(not isinstance(item, str) or not item or len(item) > 64
               for item in art_types)
    ):
        raise ValueError("Invalid artwork type list")


def encode_request(mode, art_types=None):
    """Encode a validated launch request as one shell-safe argument."""

    if mode not in MODES:
        raise ValueError("Unsupported screensaver mode")
    _validate_art_types(art_types)
    payload = json.dumps(
        {"v": 1, "mode": mode, "art_types": art_types},
        separators=(",", ":"),
    ).encode("utf-8")
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    if len(token) > MAX_ARGUMENT_LENGTH:
        raise ValueError("Screensaver request is too large")
    return token


def decode_request(arguments):
    """Decode and validate a single versioned launch argument."""

    if len(arguments) != 1:
        raise ValueError("Expected one screensaver request argument")
    token = arguments[0]
    if (
        not isinstance(token, str)
        or not token
        or len(token) > MAX_ARGUMENT_LENGTH
        or not _TOKEN_PATTERN.fullmatch(token)
    ):
        raise ValueError("Invalid screensaver request encoding")
    try:
        payload = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        request = json.loads(payload.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Malformed screensaver request") from error
    if (
        not isinstance(request, dict)
        or request.get("v") != 1
        or request.get("mode") not in MODES
    ):
        raise ValueError("Unsupported screensaver request")
    art_types = request.get("art_types")
    _validate_art_types(art_types)
    return {"mode": request["mode"], "art_types": art_types}
