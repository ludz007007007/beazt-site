"""NFAHub reseller API client (https://nfahub.cc/api/reseller/v2).

BEAZT acts as a reseller: a paid order triggers ``buy()`` for the tier's
NFAHub variant, and the returned account credentials are stored as the
buyer's Key and emailed to them.

API surface (bearer auth, amounts in EUR cents):
    GET  /me                  account + approval status
    GET  /balance             EUR balance and history
    GET  /catalog             products, variantId, priceCents, live stock
    GET  /keys                activation keys + status
    GET  /orders              purchase history
    GET  /order?id=...        order status and account credentials
    POST /buy                 purchase a variant
    POST /order-warranty      warranty check {"id": ..., "index": 0}

Errors: 401 invalid key - 403 access denied - 404 unknown order -
409 balance/stock/order conflict - 429 too many requests -
503 temporarily unavailable.

The exact /buy and /order response schemas are not published, so response
parsing is deliberately liberal (``extract_credentials``/``iter_variants``)
and every failure logs the raw body server-side for diagnosis. Credentials
never end up in logs or buyer-facing error messages.
"""

import logging

import requests

logger = logging.getLogger(__name__)


class NFAHubError(RuntimeError):
    """NFAHub API failure with the HTTP status attached.

    ``detail`` is safe to show admins (status + short reason) but callers
    must still keep it out of buyer-facing checkout responses.
    """

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# Node keys whose value holds (a list of) credential strings, and keys that
# make up a "login:password" line. Ordered by specificity. "Weak" keys are
# only accepted when their value looks like an actual credential line.
_CREDENTIAL_KEYS = (
    "credentials", "credential", "account_credentials", "combo",
    "account_string", "login_string", "key", "keys", "code", "token",
)
_WEAK_CREDENTIAL_KEYS = ("content", "text", "account_details", "details", "value")
_IDENTITY_KEYS = ("email", "username", "user", "login", "mail")
_SECRET_KEYS = ("password", "passwd", "pass")
# Nodes to descend into when nothing above matched (response envelopes).
_CONTAINER_KEYS = ("data", "order", "result", "accounts", "account",
                   "items", "item", "products", "product", "variants",
                   "keys", "keys_data")

import re as _re

# email:password (the dominant NFA account format) found anywhere in a JSON dump.
_EMAIL_COMBO_RE = _re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}:[^\s\"',:]{1,128}"
)
# username:password without an email; rejects URLs (no ://) and stray junk.
_COMBO_RE = _re.compile(r"(?<!\S)([A-Za-z0-9._@-]{2,64}):([^\s:\"',/][^\s:\"',]{0,127})")
_PROTOCOL_RE = _re.compile(r"://")


def _looks_like_combo(line):
    """A credential line: 'user:pass' (never a URL, never prose)."""
    if not line or len(line) > 200 or _PROTOCOL_RE.search(line):
        return False
    user, _, pw = line.partition(":")
    return bool(user and pw and " " not in line and user.lower() not in ("http", "https", "ftp"))


def _weak_value_ok(val):
    """Weak keys only count when every line looks like a credential/token."""
    if not isinstance(val, str) or not val.strip():
        return False
    lines = [ln.strip() for ln in val.splitlines() if ln.strip()]
    return bool(lines) and all(
        _looks_like_combo(ln) or _re.fullmatch(r"[A-Za-z0-9_\-]{10,}", ln) for ln in lines
    )


def extract_credentials(payload):
    """Pull account credential strings out of an arbitrary API payload.

    Handles the shapes NFAHub plausibly returns (documented schemas do not
    pin the exact fields): a bare string, a list of strings, a dict with a
    credentials-ish field (multiline allowed), identity + password fields
    joined as ``identity:password``, generic content/text fields that hold
    credential lines, and — as a last resort — an email:password scan of the
    whole payload. Returns a de-duplicated list; never raises.
    """
    out = []

    def _add_text(text):
        for line in str(text).splitlines():
            line = line.strip()
            if line and line not in out:
                out.append(line)

    def _first_str(node, keys):
        for key in keys:
            val = node.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None

    def _walk(node):
        if isinstance(node, str):
            _add_text(node)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if not isinstance(node, dict):
            return

        for key in _CREDENTIAL_KEYS:
            if key in node:
                val = node[key]
                if isinstance(val, (str, list, dict)):
                    _walk(val)
                    return

        for key in _WEAK_CREDENTIAL_KEYS:
            val = node.get(key)
            if isinstance(val, str) and _weak_value_ok(val):
                _add_text(val)
                return

        identity = _first_str(node, _IDENTITY_KEYS)
        secret = _first_str(node, _SECRET_KEYS)
        if identity and secret:
            line = f"{identity}:{secret}"
            if line not in out:
                out.append(line)
            return

        for key in _CONTAINER_KEYS:
            if key in node and isinstance(node[key], (list, dict)):
                _walk(node[key])
                return

    _walk(payload)

    if not out and payload is not None:
        # Last resort: scan the raw payload text for credential-looking
        # strings. Email combos first (highest confidence), then generic
        # user:pass pairs that are not URLs.
        import json as _json
        try:
            blob = payload if isinstance(payload, str) else _json.dumps(payload)
        except (TypeError, ValueError):
            blob = str(payload)
        for match in _EMAIL_COMBO_RE.findall(blob):
            if match not in out:
                out.append(match)
        if not out:
            for user, pw in _COMBO_RE.findall(blob):
                line = f"{user}:{pw}"
                if _looks_like_combo(line) and line not in out:
                    out.append(line)
    return out


def iter_variants(catalog):
    """Flatten a /catalog response into variant dicts.

    Yields dicts with ``variant_id``, ``name``, ``price_cents`` and
    ``stock`` (any of them possibly None). Tolerates nested
    product->variants shapes and flat variant lists; fields are matched
    across camelCase/snake_case spellings.
    """
    _ID_KEYS = ("variantId", "variant_id", "id")
    _NAME_KEYS = ("name", "title", "label")
    _PRICE_KEYS = ("priceCents", "price_cents", "price")
    _STOCK_KEYS = ("stock", "stockCount", "stock_count", "quantity", "inStock")

    def _pick(node, keys):
        for key in keys:
            if key in node and node[key] is not None:
                return node[key]
        return None

    def _walk(node, parent_name, found):
        if isinstance(node, list):
            for item in node:
                _walk(item, parent_name, found)
            return
        if not isinstance(node, dict):
            return

        name = _pick(node, _NAME_KEYS) or parent_name
        vid = _pick(node, _ID_KEYS)
        price = _pick(node, _PRICE_KEYS)
        if vid is not None and (price is not None or name != parent_name):
            try:
                price_cents = int(price) if price is not None else None
            except (TypeError, ValueError):
                price_cents = None
            stock = _pick(node, _STOCK_KEYS)
            found.append({
                "variant_id": str(vid),
                "name": str(name) if name else None,
                "price_cents": price_cents,
                "stock": stock if isinstance(stock, int) else None,
            })

        for key in _CONTAINER_KEYS + ("variants_list", "variant_list", "children"):
            if key in node and isinstance(node[key], (list, dict)):
                _walk(node[key], name, found)

    found = []
    _walk(catalog, None, found)
    return found


class NFAHub:
    """Thin reseller API client. One instance per request; not thread-safe."""

    BASE = "https://nfahub.cc/api/reseller/v2"
    TIMEOUT = 20
    RETRIES = 2

    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or ""
        self.base = (base_url or self.BASE).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _request(self, method, path, **kwargs):
        url = f"{self.base}/{path.lstrip('/')}"
        kwargs.setdefault("timeout", self.TIMEOUT)
        resp = None
        last_exc = None
        for attempt in range(self.RETRIES + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code < 500 and resp.status_code != 429:
                    return resp
                # 429/5xx: retry briefly, then surface the last response.
                if attempt < self.RETRIES:
                    logger.warning("NFAHub %s %s -> %s (attempt %d/%d)",
                                   method, path, resp.status_code,
                                   attempt + 1, self.RETRIES + 1)
                    resp = None
                    import time
                    time.sleep(1)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.RETRIES:
                    logger.warning("NFAHub request failed (attempt %d/%d): %s",
                                   attempt + 1, self.RETRIES + 1, exc)
                else:
                    break
        if resp is not None:
            return resp
        raise NFAHubError(f"NFAHub request failed after retries: {last_exc}")

    @staticmethod
    def _raise_for_status(resp, context):
        """Map the documented error codes onto NFAHubError."""
        if 200 <= resp.status_code < 300:
            return
        detail = {
            401: "invalid API key",
            403: "access denied",
            404: "not found",
            409: "balance/stock/order conflict",
            429: "rate limited",
            503: "temporarily unavailable",
        }.get(resp.status_code, f"HTTP {resp.status_code}")
        logger.error("NFAHub %s failed: HTTP %s — body=%s",
                     context, resp.status_code, resp.text[:500])
        raise NFAHubError(f"NFAHub {context}: {detail}", status=resp.status_code)

    # -- Status ------------------------------------------------------------
    def me(self):
        resp = self._request("GET", "/me")
        self._raise_for_status(resp, "me")
        return resp.json()

    def balance(self):
        resp = self._request("GET", "/balance")
        self._raise_for_status(resp, "balance")
        return resp.json()

    # -- Catalog -----------------------------------------------------------
    def catalog(self):
        resp = self._request("GET", "/catalog")
        self._raise_for_status(resp, "catalog")
        return resp.json()

    # -- Keys / orders -------------------------------------------------------
    def keys(self):
        resp = self._request("GET", "/keys")
        self._raise_for_status(resp, "keys")
        return resp.json()

    def orders(self):
        resp = self._request("GET", "/orders")
        self._raise_for_status(resp, "orders")
        return resp.json()

    def order(self, order_id):
        resp = self._request("GET", "/order", params={"id": order_id})
        self._raise_for_status(resp, "order")
        return resp.json()

    def order_warranty(self, order_id, index=0):
        resp = self._request("POST", "/order-warranty",
                             json={"id": str(order_id), "index": int(index)})
        self._raise_for_status(resp, "order-warranty")
        return resp.json()

    # -- Purchasing ----------------------------------------------------------
    def buy(self, variant_id, quantity=1):
        """Purchase ``quantity`` of a variant; returns the parsed JSON body.

        Sends both camelCase and snake_case keys — the undocumented /buy
        contract may expect either. Raises NFAHubError on any non-2xx (409
        covers insufficient balance and out-of-stock). Callers should run the
        result through ``extract_credentials`` — and treat an empty result as
        a failure, never inventing keys.
        """
        vid = str(variant_id)
        resp = self._request("POST", "/buy", json={
            "variantId": vid, "variant_id": vid,
            "quantity": max(1, int(quantity)),
        })
        self._raise_for_status(resp, "buy")
        try:
            return resp.json()
        except ValueError:
            logger.error("NFAHub buy returned non-JSON body: %s", resp.text[:500])
            raise NFAHubError("NFAHub buy: non-JSON response", status=resp.status_code)
