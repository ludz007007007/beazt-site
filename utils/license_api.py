import logging
import requests

logger = logging.getLogger(__name__)


class LicenseAPI:
    """Client for the Project Infinity (CatNip) license panel API.

    Auth: the panel expects the token as a bare value in the ``Authorization``
    header (``Authorization: <token>``), so the default ``auth_scheme`` is
    ``"raw"``. Pass ``auth_scheme="bearer"`` if the panel is ever changed to
    expect ``Authorization: Bearer <token>``.

    The API backend runs over HTTP on port 3845
    (``http://panel.projectinfinity.co.za:3845``); the port-443 host is the web
    panel frontend and does not accept token auth.
    """

    BASE = "http://panel.projectinfinity.co.za:3845"
    TIMEOUT = 15

    def __init__(self, api_token=None, base_url=None, auth_scheme="raw"):
        self.token = api_token
        self.base = base_url or self.BASE
        self.auth_scheme = auth_scheme
        self.headers = self._build_headers(auth_scheme)
        # Captured for diagnostics — most recent response object.
        self.last_response = None

    def _build_headers(self, scheme):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if not self.token:
            return headers
        if scheme == "raw":
            headers["Authorization"] = self.token
        else:  # "bearer" (default)
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method, path, **kwargs):
        url = f"{self.base.rstrip('/')}/{path.lstrip('/')}"
        kwargs.setdefault("timeout", self.TIMEOUT)
        kwargs.setdefault("headers", self.headers)
        resp = requests.request(method, url, **kwargs)
        self.last_response = resp
        return resp

    def get_apps(self):
        resp = self._request("GET", "/backend/dashboard/api/v1/apps")
        resp.raise_for_status()
        return resp.json()

    def get_licenses(self, app_id):
        resp = self._request("GET", f"/backend/dashboard/api/v1/apps/{app_id}/licenses?limit=1000")
        resp.raise_for_status()
        return resp.json()

    def create_keys(self, app_id, duration_days, quantity=1):
        path = f"/backend/dashboard/api/v1/apps/{app_id}/licenses"
        body = {"duration": str(duration_days), "quantity": str(quantity)}
        resp = self._request("POST", path, json=body)
        if resp.status_code >= 400:
            logger.error("License API error %s for app %s: %s",
                         resp.status_code, app_id, resp.text[:500])
        resp.raise_for_status()
        data = resp.json()
        # Normalize various response formats into a flat list
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for fld in ("licenses", "data", "keys", "results"):
                if data.get(fld):
                    return data[fld]
            # Single-key response
            for fld in ("key", "license", "license_key"):
                if data.get(fld):
                    return [data]
        return []

    def delete_key(self, app_id, license_key):
        resp = self._request("DELETE", f"/backend/dashboard/api/v1/apps/{app_id}/licenses/{license_key}")
        resp.raise_for_status()
        return resp.json()

    def reset_hwid(self, license_key, app_id=None):
        """Reset the HWID binding for a license key.

        Uses the panel's ``PUT /licenses/reset-by-license`` endpoint with a
        ``{"license": <key>}`` body (as used by the panel's own dashboard).
        ``app_id`` is accepted for backward compatibility but unused — the
        endpoint is not app-scoped.
        """
        resp = self._request(
            "PUT",
            "/backend/dashboard/api/v1/licenses/reset-by-license",
            json={"license": license_key},
        )
        resp.raise_for_status()
        return resp.json()

    def diagnose(self):
        """Probe the panel to determine the working auth scheme.

        Tries ``get_apps`` with both ``bearer`` and ``raw`` Authorization
        formats and reports the HTTP status + truncated body for each, plus a
        recommended scheme (the first that returned 200).

        Returns a dict suitable for JSON-serialisation in the admin UI.
        """
        results = {}
        for scheme in ("bearer", "raw"):
            self.headers = self._build_headers(scheme)
            try:
                resp = self._request("GET", "/backend/dashboard/api/v1/apps")
                results[scheme] = {
                    "status": resp.status_code,
                    "body": resp.text[:1500],
                }
            except Exception as exc:  # noqa: BLE001 - diagnostics surface everything
                results[scheme] = {"status": None, "body": str(exc)[:1500]}

        recommended = None
        for scheme in ("raw", "bearer"):
            if results[scheme]["status"] == 200:
                recommended = scheme
                break
        # Restore headers to the recommended (or default) scheme.
        self.headers = self._build_headers(recommended or "raw")
        return {"schemes": results, "recommended": recommended}
