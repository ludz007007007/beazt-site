import requests
import logging

logger = logging.getLogger(__name__)


class IvnoPayments:
    BASE = "https://app.ivno.io/api/ivno/v1"
    TIMEOUT = 30

    def __init__(self, api_key=None, api_secret=None, base_url=None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base = base_url or self.BASE

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key,
            "X-Api-Secret": self.api_secret,
        }

    def create_payment(self, amount, currency, order_id, return_url, email=None, webhook_url=None, domain=None, fee_preference=None):
        payload = {
            "amount": amount,
            "currency": currency,
            "order_id": order_id,
            "return_url": return_url,
        }
        if email:
            payload["email"] = email
        if webhook_url:
            payload["webhook_url"] = webhook_url
        if domain:
            payload["domain"] = domain
        if fee_preference:
            payload["fee_preference"] = fee_preference

        url = f"{self.base.rstrip('/')}/payments/create"
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=self.TIMEOUT)
        resp.raise_for_status()
        return resp.json()
