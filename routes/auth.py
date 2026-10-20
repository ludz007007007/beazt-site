from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse
from models import db, User, PasswordResetToken
from utils import mailer
from utils.passwords import password_error
from utils.tokens import RESET_TOKEN_TTL, generate_reset_token, verify_reset_token, hash_token

auth_bp = Blueprint("auth", __name__)


def _safe_next(target):
    """Only allow same-site relative redirect targets (VAL-AUTH-004).

    Rejects absolute URLs (any scheme), protocol-relative `//evil.com`,
    backslash tricks, and non-`/`-rooted paths. Returns None when unsafe.
    """
    if not target or not target.startswith("/"):
        return None
    if target.startswith("//") or target.startswith("/\\") or target.startswith("\\"):
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    return target


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.my_keys"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=bool(request.form.get("remember")))
            next_page = _safe_next(request.args.get("next"))
            return redirect(next_page or url_for("main.my_keys"))

        flash("Invalid username or password.", "error")

    return render_template("login.html")


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("main.my_keys"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if not username or len(username) < 3:
            errors.append("Username must be at least 3 characters.")
        if not email or "@" not in email:
            errors.append("Please enter a valid email address.")
        pw_error = password_error(password)
        if pw_error:
            errors.append(pw_error)
        if password != confirm:
            errors.append("Passwords do not match.")
        if User.query.filter_by(username=username).first():
            errors.append("Username already taken.")
        if User.query.filter_by(email=email).first():
            errors.append("Email already registered.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("signup.html")

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        try:
            from utils.kv_store import backup_everything
            backup_everything()
        except Exception:
            pass

        login_user(user)
        # Welcome flash points at the first steps (VAL-AUTH-002 / VAL-CROSS-003).
        flash(
            "Welcome to BEAZT. Your account is ready — pick a product and your "
            "key appears in your account the moment payment is confirmed.",
            "success",
        )
        # Honor the product-page return path: the signup links carry ?next=,
        # and the form posts back to the same URL, so it survives here too.
        next_page = _safe_next(request.args.get("next"))
        return redirect(next_page or url_for("main.my_keys"))

    return render_template("signup.html")


def _reset_email(user, reset_url):
    """Build the (subject, html, text) reset email. Compact, SIGNAL-toned."""
    subject = "Reset your BEAZT password"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0b0d10;font-family:Inter,system-ui,Segoe UI,Arial,sans-serif;color:#f4f1ea;">
  <div style="max-width:520px;margin:0 auto;padding:28px 20px;">
    <div style="font-size:20px;font-weight:800;letter-spacing:.08em;color:#f4f1ea;">BEAZT</div>
    <div style="height:3px;width:60px;background:#e8a33d;border-radius:2px;margin-bottom:22px;"></div>
    <h1 style="font-size:20px;margin:0 0 8px;color:#f4f1ea;">Password reset requested</h1>
    <p style="color:#b7b3a8;font-size:14px;line-height:1.6;margin:0 0 20px;">
      Hi {user.username}, use the button below to set a new BEAZT password.
      The link expires in one hour and can only be used once.
    </p>
    <a href="{reset_url}" style="display:inline-block;background:#e8a33d;color:#0b0d10;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:700;font-size:14px;">Choose a new password</a>
    <p style="color:#8a867c;font-size:12px;line-height:1.6;margin-top:22px;border-top:1px solid #23262c;padding-top:16px;">
      If the button does not work, open this link: {reset_url}<br>
      Didn't request this? You can ignore the email — your password stays unchanged.
    </p>
  </div>
</body></html>"""
    text = (
        f"BEAZT — Reset your password\n\n"
        f"Hi {user.username}, open the link below to set a new password. "
        f"It expires in one hour and can only be used once.\n\n"
        f"{reset_url}\n\n"
        f"Didn't request this? Ignore the email — your password stays unchanged.\n"
    )
    return subject, html, text


@auth_bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    """Request a password-reset email (VAL-AUTH-003).

    The response is identical for registered and unregistered addresses (no
    account enumeration). A valid request mints a single-use, HMAC-signed
    token (hash stored only) and emails the link. Email failures — including
    "SMTP not configured" — are soft: the confirmation state still renders.
    """
    if current_user.is_authenticated:
        return redirect(url_for("main.my_keys"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first() if email else None
        if user:
            token = generate_reset_token(user.id)
            db.session.add(PasswordResetToken(
                token_hash=hash_token(token),
                user_id=user.id,
                expires_at=datetime.utcnow() + RESET_TOKEN_TTL,
            ))
            db.session.commit()
            reset_url = (
                request.url_root.rstrip("/")
                + url_for("auth.reset_password", token=token)
            )
            subject, html, text = _reset_email(user, reset_url)
            # Soft-fail: mailer.send_email never raises and returns False when
            # SMTP is unconfigured — logged there, never surfaced here.
            mailer.send_email(user.email, subject, html, text_body=text)
        return render_template("forgot.html", requested=True)

    return render_template("forgot.html", requested=False)


def _load_reset_token(token):
    """Validate a reset token end to end.

    Returns ``(user, row, error)`` — error is ``"invalid"``, ``"expired"``,
    ``"used"`` or ``None``. Checks signature + TTL (stateless), then the
    issued single-use row (hash match, not yet used, not expired), then that
    the embedded user still exists.
    """
    user_id, error = verify_reset_token(token)
    if error == "invalid" or user_id is None:
        return None, None, "invalid"
    row = PasswordResetToken.query.filter_by(token_hash=hash_token(token)).first()
    if row is None or row.user_id != user_id:
        return None, None, "invalid"
    if row.used_at is not None:
        return None, row, "used"
    if row.expires_at and datetime.utcnow() >= row.expires_at:
        return None, row, "expired"
    user = db.session.get(User, user_id)
    if user is None:
        return None, row, "invalid"
    return user, row, None


@auth_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Set a new password with a reset token (VAL-AUTH-004).

    Valid completion consumes the token (single use), updates the password,
    backs up the KV store (same contract as signup/profile) and sends the
    user to the login page with a success flash.
    """
    if current_user.is_authenticated:
        return redirect(url_for("main.my_keys"))

    user, row, error = _load_reset_token(token)
    if error:
        # Distinguish "expired" for honest copy; anything malformed or spent
        # gets the generic invalid state (no details leaked to an attacker).
        state = error if error == "expired" else "invalid"
        return render_template("reset.html", state=state), 400

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        pw_error = password_error(password)
        if pw_error:
            errors.append(pw_error)
        elif password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("reset.html", state="form"), 400

        user.set_password(password)
        row.used_at = datetime.utcnow()
        db.session.commit()
        # KV-restore safety: restore_users_to_db() re-applies backed-up
        # password hashes on boot — persist this change immediately.
        try:
            from utils.kv_store import backup_everything
            backup_everything()
        except Exception:
            pass

        flash("Password updated. Sign in with your new password.", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset.html", state="form")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.index"))
