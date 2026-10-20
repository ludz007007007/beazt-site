"""Lightweight SMTP mailer (stdlib only — no extra dependency).

Config is sourced from Settings via :func:`config.get_mailer_config`, so SMTP
credentials can be updated from the admin Settings page without a redeploy.
If SMTP is not configured, :func:`send_email` logs a notice and returns
``False`` without raising — key assignment must never break because email
delivery failed.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_email(to_address, subject, html_body, text_body=None):
    """Send a transactional email.

    Returns ``True`` on success, ``False`` on any failure (including
    "SMTP not configured"). Never raises — callers can ignore the result.
    """
    from config import get_mailer_config

    cfg = get_mailer_config()
    host = cfg.get("smtp_host", "").strip()
    if not host:
        logger.warning("Email not sent (SMTP not configured) — would have sent '%s' to %s", subject, to_address)
        return False

    from_email = cfg.get("from_email", "").strip() or "no-reply@beazt.local"
    from_name = cfg.get("from_name", "").strip()
    port = int(cfg.get("smtp_port", 587) or 587)
    user = cfg.get("smtp_user", "").strip()
    password = cfg.get("smtp_pass", "").strip()
    use_tls = bool(cfg.get("use_tls", True))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    sender = f"{from_name} <{from_email}>" if from_name else from_email
    msg["From"] = sender
    msg["To"] = to_address
    msg.attach(MIMEText(text_body or html_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if use_tls:
            server = smtplib.SMTP(host, port, timeout=20)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.ehlo()
        if user:
            server.login(user, password)
        server.sendmail(from_email, [to_address], msg.as_string())
        server.quit()
        logger.info("Email sent '%s' to %s", subject, to_address)
        return True
    except Exception as exc:  # noqa: BLE001 - email failures must not break key assignment
        logger.exception("Failed to send email '%s' to %s: %s", subject, to_address, exc)
        return False


def notify_key_assigned(user, order, product, tier, keys, site_url=""):
    """Email a buyer their newly-assigned license key(s).

    ``keys`` is a list of ``Key`` rows (or dicts with ``key_value`` /
    ``expires_at``). Builds a branded HTML email with the key(s), product,
    expiry, loader link and Discord, then sends via :func:`send_email`.

    Returns ``True`` if the email was sent, ``False`` otherwise. Never raises.
    """
    try:
        if not user or not getattr(user, "email", None):
            return False
        if not keys:
            return False

        product_name = product.name if product else "BEAZT"
        tier_label = tier.label if tier else ""
        duration_days = tier.duration_days if tier else None
        discord_url = ""
        if product and getattr(product, "visibility", None) == "private":
            from config import get_discord_config
            discord_url = get_discord_config().get("private_url", "")
        if not discord_url and product:
            from config import get_discord_config
            discord_url = get_discord_config().get("public_url", "")

        loader_url = product.loader_url if (product and getattr(product, "loader_url", None)) else ""
        buyer_notes = product.buyer_notes if (product and getattr(product, "buyer_notes", None)) else ""

        rows_html = ""
        rows_text = ""
        for k in keys:
            kv = k.key_value if hasattr(k, "key_value") else k.get("key_value", "")
            exp = k.expires_at if hasattr(k, "expires_at") else k.get("expires_at")
            exp_str = exp.strftime("%d %b %Y, %H:%M UTC") if exp else "Lifetime"
            rows_html += f"""
              <tr>
                <td style="padding:12px 14px;background:#0f1729;border:1px solid #1f2a4a;border-radius:8px;font-family:ui-monospace,Consolas,monospace;font-size:14px;letter-spacing:.5px;color:#7c3aed;">{kv}</td>
                <td style="padding:12px 14px;color:#94a3b8;font-size:13px;">{exp_str}</td>
              </tr>"""
            rows_text += f"  • {kv}  (expires {exp_str})\n"

        my_keys_url = (site_url.rstrip("/") + "/my-keys") if site_url else "/my-keys"
        loader_block_html = ""
        if loader_url:
            loader_block_html = f"""
              <a href="{loader_url}" style="display:inline-block;background:#7c3aed;color:#fff;text-decoration:none;padding:11px 20px;border-radius:8px;font-weight:700;font-size:14px;margin-top:14px;">Download Loader</a>"""
        discord_block_html = ""
        if discord_url:
            discord_block_html = f"""
              <a href="{discord_url}" style="display:inline-block;background:#182344;color:#eaf0ff;text-decoration:none;padding:11px 20px;border-radius:8px;font-weight:600;font-size:14px;margin-top:14px;margin-left:8px;border:1px solid #1f2a4a;">Join Discord</a>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0b1020;font-family:Inter,system-ui,Segoe UI,Arial,sans-serif;color:#eaf0ff;">
  <div style="max-width:560px;margin:0 auto;padding:28px 20px;">
    <div style="font-size:20px;font-weight:800;letter-spacing:.06em;color:#fff;margin-bottom:6px;">BEAZT</div>
    <div style="height:3px;width:60px;background:linear-gradient(90deg,#7c3aed,#06b6d4);border-radius:2px;margin-bottom:22px;"></div>

    <h1 style="font-size:22px;margin:0 0 8px;color:#fff;">Your key is ready</h1>
    <p style="color:#94a3b8;font-size:15px;line-height:1.6;margin:0 0 22px;">
      Hi {user.username}, your license for <strong style="color:#eaf0ff;">{product_name}</strong>{(' — ' + tier_label) if tier_label else ''} has been assigned.
      Find your key(s) below and activate them in the loader.
    </p>

    <table style="width:100%;border-collapse:separate;border-spacing:0 8px;">
      <thead><tr><th style="text-align:left;color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.08em;padding:0 14px 4px;">License Key</th><th style="text-align:left;color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.08em;padding:0 14px 4px;">Expires</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>

    {loader_block_html}{discord_block_html}

    <a href="{my_keys_url}" style="display:inline-block;color:#06b6d4;text-decoration:none;font-size:14px;margin-top:18px;">View on My Keys &rarr;</a>

    {('<div style="margin-top:22px;padding:14px 16px;background:#121a33;border:1px solid #1f2a4a;border-radius:10px;color:#94a3b8;font-size:13px;line-height:1.6;">' + buyer_notes.replace('\n', '<br>') + '</div>') if buyer_notes else ''}

    <p style="color:#475569;font-size:12px;line-height:1.6;margin-top:26px;border-top:1px solid #1f2a4a;padding-top:16px;">
      Before running: install <a href="https://www.guru3d.com/download/rtss-rivatuner-statistics-server-download/" style="color:#06b6d4;">RivaTuner Statistics Server</a> and temporarily disable antivirus real-time protection. If you didn't make this purchase, please ignore this email.
    </p>
  </div>
</body></html>"""

        text = (
            f"BEAZT — Your key is ready\n\n"
            f"Hi {user.username}, your license for {product_name}"
            f"{(' — ' + tier_label) if tier_label else ''} has been assigned.\n\n"
            f"Key(s):\n{rows_text}\n"
            + (f"Download loader: {loader_url}\n" if loader_url else "")
            + (f"Discord: {discord_url}\n" if discord_url else "")
            + f"\nView on My Keys: {my_keys_url}\n"
        )

        subject = f"Your {product_name} license key is ready"
        return send_email(user.email, subject, html, text_body=text)
    except Exception as exc:  # noqa: BLE001
        logger.exception("notify_key_assigned failed: %s", exc)
        return False
