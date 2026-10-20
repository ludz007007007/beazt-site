import requests
import logging
import re
import time

logger = logging.getLogger(__name__)


class ChairFBIRateLimitError(RuntimeError):
    """Raised when the ChairFBI API responds 429 rate_limit_exceeded.

    Carries ``available_in`` (seconds until the per-token limit resets, per
    the API's ``availableIn`` field). Callers should degrade gracefully
    rather than sleep-and-retry inside a request thread.
    """

    def __init__(self, message, available_in=None):
        super().__init__(message)
        self.available_in = available_in


class ChairFBI:
    BASE = "https://access.chairfbi.com"
    TIMEOUT = 15
    RETRIES = 2
    BALANCE_KEYS = ("balance", "credits", "credit", "funds", "amount", "total", "money", "wallet")
    BALANCE_CONTAINERS = ("data", "store", "result", "account", "wallet")

    def __init__(self, api_token=None, base_url=None):
        self.token = api_token
        self.base = base_url or self.BASE
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method, path, **kwargs):
        url = f"{self.base.rstrip('/')}/{path.lstrip('/')}"
        kwargs.setdefault("timeout", self.TIMEOUT)
        kwargs.setdefault("headers", self.headers)

        resp = None
        for attempt in range(self.RETRIES + 1):
            try:
                resp = requests.request(method, url, **kwargs)
                if resp.status_code == 429:
                    # Rate limit: 100 req/min per token. The API tells us how
                    # long until the window resets ("availableIn"); retrying
                    # sooner would just burn more of the budget. Never
                    # sleep-and-retry inside a request thread — surface it.
                    available_in = None
                    try:
                        available_in = resp.json().get("availableIn")
                    except Exception:
                        pass
                    logger.warning(
                        "ChairFBI rate limit hit on %s %s (availableIn=%s)",
                        method, path, available_in,
                    )
                    raise ChairFBIRateLimitError(
                        f"ChairFBI rate limit exceeded — retry in {available_in or 'a few'} seconds",
                        available_in=available_in,
                    )
                if resp.status_code < 500:
                    return resp
                if attempt < self.RETRIES:
                    logger.warning("ChairFBI 5xx error (attempt %d/%d), retrying...", attempt + 1, self.RETRIES + 1)
                    time.sleep(1)
            except ChairFBIRateLimitError:
                raise
            except requests.RequestException as e:
                if attempt < self.RETRIES:
                    logger.warning("ChairFBI request failed (attempt %d/%d): %s", attempt + 1, self.RETRIES + 1, e)
                    time.sleep(1)
                else:
                    raise
        if resp is None:
            raise requests.RequestException("ChairFBI request failed after retries")
        return resp

    # -- Status --
    def get_cheats(self):
        """GET /api/status - returns cheat availability list [{id, name, active, price_type}]"""
        resp = self._request("GET", "/api/status")
        resp.raise_for_status()
        return resp.json()

    def get_cheat_bases(self):
        """GET /api/status-bases - returns cheat base status list [{id, name, enabled, status}]"""
        resp = self._request("GET", "/api/status-bases")
        resp.raise_for_status()
        return resp.json()

    # -- Store --
    def get_store_info(self):
        """GET /api/store - returns store info including balance"""
        resp = self._request("GET", "/api/store")
        resp.raise_for_status()
        return resp.json()

    def get_balance(self):
        """Returns the exact balance from /api/store as a float.

        No scaling or unit conversion is applied: the number shown in
        admin is precisely the number the ChairFBI API returned.
        Handles nested payloads ({data: {balance}}), numeric strings,
        and European decimal commas ("12,50"). Returns None when the
        payload carries no parseable amount.
        """
        store = self.get_store_info()
        return self.parse_balance(store)

    @classmethod
    def _coerce_amount(cls, value):
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            # European decimal comma ("12,50" -> "12.50"). When both
            # separators are present the commas are thousands separators.
            if "," in text and "." not in text:
                text = text.replace(",", ".")
            else:
                text = text.replace(",", "")
            cleaned = re.sub(r"[^0-9.\-]", "", text)
            if not cleaned or cleaned in ("-", ".", "-."):
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    @classmethod
    def _find_amount(cls, payload, depth=0):
        if depth > 3 or payload is None:
            return None
        if isinstance(payload, list):
            for item in payload:
                found = cls._find_amount(item, depth + 1)
                if found is not None:
                    return found
            return None
        if isinstance(payload, dict):
            for key in cls.BALANCE_KEYS:
                if key in payload:
                    amount = cls._coerce_amount(payload.get(key))
                    if amount is not None:
                        return amount
            for key in cls.BALANCE_CONTAINERS:
                if key in payload:
                    found = cls._find_amount(payload.get(key), depth + 1)
                    if found is not None:
                        return found
            return None
        return cls._coerce_amount(payload)

    @classmethod
    def _find_raw(cls, payload, depth=0):
        """Same search as _find_amount but returns the untouched raw value."""
        if depth > 3 or payload is None:
            return None
        if isinstance(payload, list):
            for item in payload:
                found = cls._find_raw(item, depth + 1)
                if found is not None:
                    return found
            return None
        if isinstance(payload, dict):
            for key in cls.BALANCE_KEYS:
                if key in payload and payload.get(key) is not None and not isinstance(payload.get(key), bool):
                    return payload.get(key)
            for key in cls.BALANCE_CONTAINERS:
                if key in payload:
                    found = cls._find_raw(payload.get(key), depth + 1)
                    if found is not None:
                        return found
            return None
        return payload

    @classmethod
    def parse_balance(cls, payload):
        amount = cls._find_amount(payload)
        if amount is None:
            logger.warning("ChairFBI /api/store returned no parseable balance: %r", payload)
            return None
        # Exact passthrough: never scale, round, or otherwise transform the
        # API value. What ChairFBI returns is what admin displays.
        return float(amount)

    def get_balance_report(self):
        """Single /api/store call returning parsed value AND raw payload.

        Returns {"value": float|None, "raw": <untouched API value>,
        "payload": <full /api/store JSON>} so admin templates can display
        the exact figure ChairFBI returned alongside the parsed number.
        """
        store = self.get_store_info()
        return {
            "value": self.parse_balance(store),
            "raw": self._find_raw(store),
            "payload": store,
        }

    # -- Cheats (paginated) --
    def list_cheats(self, page=1, per_page=50, sort=None, filter_str=None):
        """GET /api/cheats - paginated cheat list with meta"""
        params = {"page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
        if filter_str:
            params["filter"] = filter_str
        resp = self._request("GET", "/api/cheats", params=params)
        resp.raise_for_status()
        return resp.json()

    def update_cheats(self, cheats, name=None, active=None, custom_menu=None,
                      override_spoofer=None, disable_for_update=None):
        """PUT /api/cheats - update store cheat settings.

        ``cheats`` is an array of cheat IDs. ``disable_for_update`` requires
        ``active=False`` (per API docs it sets disabled_at on editable cheats).
        """
        payload = {"cheats": [int(c) for c in cheats]}
        if name is not None:
            payload["name"] = name
        if active is not None:
            payload["active"] = active
        if custom_menu is not None:
            payload["custom_menu"] = custom_menu
        if override_spoofer is not None:
            payload["override_spoofer"] = override_spoofer
        if disable_for_update is not None:
            payload["disable_for_update"] = disable_for_update
        resp = self._request("PUT", "/api/cheats", json=payload)
        resp.raise_for_status()
        return resp.json()

    # -- Keys --
    def create_key(self, cheat_id, days, notes=None, prefix=None, amount=1):
        """POST /api/keys - creates keys, returns {balance, keys: [string]}"""
        payload = {"cheat": int(cheat_id), "amount": amount, "days": days}
        if prefix:
            payload["prefix"] = prefix
        if notes:
            payload["notes"] = notes
        resp = self._request("POST", "/api/keys", json=payload)
        resp.raise_for_status()
        return resp.json()

    def list_keys(self, page=1, per_page=50, cheat_id=None, sort=None, filter_str=None):
        """GET /api/keys - paginated key list with meta.data"""
        params = {"page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
        if filter_str:
            params["filter"] = filter_str
        resp = self._request("GET", "/api/keys", params=params)
        resp.raise_for_status()
        return resp.json()

    def update_keys(self, keys, hwid=None, freezed=None, locked=None, vouche=None, notes=None):
        """PUT /api/keys - update keys (hwid reset, freeze, lock, vouche).

        ``keys`` accepts key IDs (int) or loader_keys (str), per the API schema.
        """
        payload = {"keys": keys}
        if hwid is not None:
            payload["hwid"] = hwid
        if freezed is not None:
            payload["freezed"] = freezed
        if locked is not None:
            payload["locked"] = locked
        if vouche is not None:
            payload["vouche"] = vouche
        if notes is not None:
            payload["notes"] = notes
        resp = self._request("PUT", "/api/keys", json=payload)
        resp.raise_for_status()
        return resp.json()

    def revoke_key(self, key_id):
        """Lock a key via PUT /api/keys"""
        return self.update_keys(keys=[key_id], locked=True)

    def delete_keys(self, keys):
        """POST /api/keys-delete - delete UNUSED keys (refunds the balance).

        ``keys`` accepts key IDs (int) or loader_keys (str). For STARTED keys
        use request_key_deletion() instead — the API requires admin approval.
        Returns {deletedKeys, totalRefunded, refundDetails}.
        """
        resp = self._request("POST", "/api/keys-delete", json={"keys": keys})
        resp.raise_for_status()
        return resp.json()

    def request_key_deletion(self, keys, reason):
        """POST /api/keys-delete-request - request deletion of STARTED keys.

        Requires admin approval on the ChairFBI side. The reason must be
        specific and include proof (screenshots, transaction IDs) — vague
        reasons like "refund" are rejected automatically.
        Returns {success, message, requests: [{id, key_id, status}]}.
        """
        resp = self._request("POST", "/api/keys-delete-request",
                             json={"keys": keys, "reason": reason})
        resp.raise_for_status()
        return resp.json()

    def get_key_deletion_request(self, loader_key):
        """GET /api/key-deletion-request/{loader_key} - deletion request status.

        Works with the loader_key of an active key/pass key, or the preserved
        loader_key stored on the request after deletion.
        """
        resp = self._request("GET", f"/api/key-deletion-request/{loader_key}")
        resp.raise_for_status()
        return resp.json()

    # -- Passes --
    def list_passes(self, page=1, per_page=50, sort=None, filter_str=None):
        """GET /api/passes - paginated pass template list with meta"""
        params = {"page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
        if filter_str:
            params["filter"] = filter_str
        resp = self._request("GET", "/api/passes", params=params)
        resp.raise_for_status()
        return resp.json()

    def create_pass(self, name):
        """POST /api/passes - create a pass template (name: 4-30 chars)."""
        resp = self._request("POST", "/api/passes", json={"name": name})
        resp.raise_for_status()
        return resp.json()

    def update_pass(self, pass_id, name=None, active=None):
        """PUT /api/passes - update a pass template (name and/or active)."""
        payload = {"pass": int(pass_id)}
        if name is not None:
            payload["name"] = name
        if active is not None:
            payload["active"] = active
        resp = self._request("PUT", "/api/passes", json=payload)
        resp.raise_for_status()
        return resp.json()

    def delete_pass(self, pass_id):
        """DELETE /api/passes - delete a pass template (only if no keys exist)."""
        resp = self._request("DELETE", "/api/passes", json={"pass": int(pass_id)})
        resp.raise_for_status()
        return resp.json()

    def update_pass_cheats(self, pass_id, cheats):
        """PUT /api/passes-cheats - set the cheats associated with a pass."""
        payload = {"pass": int(pass_id), "cheats": [int(c) for c in cheats]}
        resp = self._request("PUT", "/api/passes-cheats", json=payload)
        resp.raise_for_status()
        return resp.json()

    # -- Pass Keys --
    def list_pass_keys(self, page=1, per_page=50, sort=None, filter_str=None):
        """GET /api/pass-keys - paginated pass key list with meta"""
        params = {"page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
        if filter_str:
            params["filter"] = filter_str
        resp = self._request("GET", "/api/pass-keys", params=params)
        resp.raise_for_status()
        return resp.json()

    def create_pass_key(self, pass_id, amount=1, days=7, prefix=None, notes=None):
        """POST /api/pass-keys - creates pass keys, returns {balance, keys: [string]}.

        ``days`` must be 7, 15, or 30 (API-enforced enum).
        """
        if days not in (7, 15, 30):
            raise ValueError("ChairFBI pass key days must be 7, 15, or 30")
        payload = {"pass": int(pass_id), "amount": amount, "days": days}
        if prefix:
            payload["prefix"] = prefix
        if notes:
            payload["notes"] = notes
        resp = self._request("POST", "/api/pass-keys", json=payload)
        resp.raise_for_status()
        return resp.json()

    def update_pass_keys(self, keys, hwid=None, freezed=None, locked=None, notes=None):
        """PUT /api/pass-keys - update pass keys (hwid reset, freeze, lock).

        ``keys`` accepts pass key IDs (int) or loader_keys (str).
        """
        payload = {"keys": keys}
        if hwid is not None:
            payload["hwid"] = hwid
        if freezed is not None:
            payload["freezed"] = freezed
        if locked is not None:
            payload["locked"] = locked
        if notes is not None:
            payload["notes"] = notes
        resp = self._request("PUT", "/api/pass-keys", json=payload)
        resp.raise_for_status()
        return resp.json()

    def delete_pass_keys(self, keys):
        """POST /api/pass-keys-delete - delete UNUSED pass keys."""
        resp = self._request("POST", "/api/pass-keys-delete", json={"keys": keys})
        resp.raise_for_status()
        return resp.json()

    def test_connection(self):
        try:
            resp = self._request("GET", "/api/store")
            return resp.status_code == 200, resp.json()
        except Exception as e:
            return False, str(e)
