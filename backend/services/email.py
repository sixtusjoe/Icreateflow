"""Email sending service.

Uses Python's built-in smtplib wrapped in asyncio.to_thread so it doesn't
block the event loop. Configuration is read from site_config at send time so
changes take effect immediately without a restart.

If smtp_host is not configured, all send calls are no-ops (logged but not
raised) so the rest of the app works without email configured.
"""
from __future__ import annotations

import asyncio
import smtplib
import secrets
import string
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import database as db


async def _get_smtp_cfg() -> dict:
    """Return smtp config from site_config. Returns empty dict if not set."""
    database = await db.get_db()
    try:
        cfg = await db.get_site_config(database)
    finally:
        await database.close()
    return cfg


def _build_message(
    from_email: str,
    from_name: str,
    to: str,
    subject: str,
    html: str,
    text: str,
    unsubscribe_url: str | None = None,
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = to
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(text or "", "plain"))
    msg.attach(MIMEText(html or "", "html"))
    return msg


def _send_sync(
    host: str,
    port: int,
    user: str,
    password: str,
    msg: MIMEMultipart,
    use_tls: bool,
) -> None:
    """Blocking SMTP send (runs in thread pool)."""
    if use_tls:
        server = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
        try:
            server.starttls()
        except Exception:
            pass  # Some servers don't support STARTTLS
    try:
        if user and password:
            server.login(user, password)
        server.send_message(msg)
    finally:
        server.quit()


async def send_email(
    to: str,
    subject: str,
    html: str,
    text: str = "",
    unsubscribe_url: str | None = None,
) -> None:
    """Send an email. No-op if SMTP is not configured."""
    cfg = await _get_smtp_cfg()
    host = cfg.get("smtp_host", "").strip()
    if not host:
        print(f"[email] SMTP not configured — skipping email to {to!r} ({subject!r})", flush=True)
        return

    port = int(cfg.get("smtp_port") or 587)
    user = cfg.get("smtp_user", "").strip()
    password = cfg.get("smtp_password", "").strip()
    from_email = cfg.get("smtp_from_email", user).strip() or user
    from_name = cfg.get("smtp_from_name", "iCreateFlow").strip()
    use_tls = port == 465

    msg = _build_message(from_email, from_name, to, subject, html, text, unsubscribe_url)
    try:
        await asyncio.to_thread(_send_sync, host, port, user, password, msg, use_tls)
        print(f"[email] Sent '{subject}' to {to}", flush=True)
    except Exception as exc:
        print(f"[email] Failed to send to {to!r}: {exc}", flush=True)
        raise


def generate_otp(length: int = 6) -> str:
    """Return a secure numeric OTP code."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


# ---------------------------------------------------------------------------
# Templated email helpers
# ---------------------------------------------------------------------------

_BASE_STYLE = """
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f5f5f5; margin: 0; padding: 0; }
  .wrap { max-width: 520px; margin: 40px auto; background: #fff;
          border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
  .header { background: #000; color: #fff; padding: 24px 32px; text-align: center; }
  .header-inner { display: inline-flex; align-items: center; gap: 12px; }
  .header img { height: 36px; width: auto; display: block; }
  .header-name { font-size: 18px; font-weight: 700; color: #fff; }
  .body   { padding: 28px 32px; color: #111; line-height: 1.6; }
  .code   { display: inline-block; font-size: 32px; font-weight: 700; letter-spacing: 6px;
            background: #f0f0f0; border-radius: 8px; padding: 12px 24px; margin: 16px 0; }
  .footer { padding: 16px 32px; font-size: 12px; color: #999; border-top: 1px solid #eee; text-align: center; }
  a { color: #111; }
"""


def _html_wrap(body: str, site_name: str = "iCreateFlow", logo_url: str = "") -> str:
    if logo_url:
        # Use a table so logo + name stay on one line and vertically centred
        # in all email clients (Gmail, Outlook, Apple Mail) — flexbox is not
        # reliably supported inside email rendering engines.
        header_inner = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'style="margin:0 auto;border-collapse:collapse;">'
            f'<tr>'
            f'<td style="vertical-align:middle;padding:0;">'
            f'<img src="{logo_url}" alt="" style="height:36px;width:auto;display:block;">'
            f'</td>'
            f'<td style="vertical-align:middle;padding:0 0 0 10px;">'
            f'<span style="font-size:18px;font-weight:700;color:#fff;white-space:nowrap;">{site_name}</span>'
            f'</td>'
            f'</tr>'
            f'</table>'
        )
    else:
        header_inner = f'<span style="font-size:18px;font-weight:700;color:#fff;">{site_name}</span>'

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{_BASE_STYLE}</style></head>
<body><div class="wrap">
  <div class="header">{header_inner}</div>
  <div class="body">{body}</div>
  <div class="footer">{site_name} · <a href="#">Unsubscribe</a></div>
</div></body></html>"""


async def _html_wrap_cfg(body: str) -> str:
    """Async version that fetches site_name + logo_url from site_config automatically."""
    cfg = await _get_smtp_cfg()
    site_name = cfg.get("site_name", "iCreateFlow") or "iCreateFlow"
    logo_url = cfg.get("site_logo_url", "").strip()
    return _html_wrap(body, site_name=site_name, logo_url=logo_url)


async def send_password_reset_email(to_email: str, otp_code: str) -> None:
    cfg = await _get_smtp_cfg()
    site_name = cfg.get("site_name", "iCreateFlow") or "iCreateFlow"
    html = await _html_wrap_cfg(f"""
      <p>Hi,</p>
      <p>You requested a password reset. Use the code below — it expires in <strong>15 minutes</strong>.</p>
      <div class="code">{otp_code}</div>
      <p>If you didn't request this, you can ignore this email.</p>
    """)
    text = (
        f"Your {site_name} password reset code is: {otp_code}\n"
        "It expires in 15 minutes. If you didn't request this, ignore this email."
    )
    await send_email(to_email, f"{site_name} — Password reset code", html, text)


async def send_email_change_otp(to_email: str, new_email: str, otp_code: str) -> None:
    cfg = await _get_smtp_cfg()
    site_name = cfg.get("site_name", "iCreateFlow") or "iCreateFlow"
    html = await _html_wrap_cfg(f"""
      <p>Hi,</p>
      <p>We received a request to change your {site_name} email to <strong>{new_email}</strong>.</p>
      <p>Enter this code to confirm — it expires in <strong>15 minutes</strong>.</p>
      <div class="code">{otp_code}</div>
      <p>If you didn't request this, you can ignore this email.</p>
    """)
    text = (
        f"Your {site_name} email change code is: {otp_code}\n"
        f"This will change your email to: {new_email}\n"
        "It expires in 15 minutes."
    )
    await send_email(new_email, f"{site_name} — Confirm email change", html, text)


async def send_post_reminder_email(
    to_email: str,
    artist_name: str,
    scheduled_time: str,
    platform_list: list[str],
) -> None:
    cfg = await _get_smtp_cfg()
    site_name = cfg.get("site_name", "iCreateFlow") or "iCreateFlow"
    html = await _html_wrap_cfg(f"""
      <p>Hi,</p>
      <p><strong>{artist_name}</strong> has a post going out in approximately 1 hour.</p>
      <p style="font-size:15px;color:#555;">Scheduled for <strong style="color:#111;">{scheduled_time}</strong></p>
    """)
    text = f"Reminder: {artist_name} has a post scheduled in ~1 hour at {scheduled_time}."
    await send_email(to_email, f"⏰ Upcoming post — {artist_name}", html, text)


async def send_post_result_email(
    to_email: str,
    artist_name: str,
    results: list[dict],
    unsubscribe_url: str | None = None,
    dashboard_url: str = "https://icreateflow.com/clipping",
) -> None:
    """Send a post success/failure summary email.

    results: list of {platform, variation_name, status, error}
    """
    cfg = await _get_smtp_cfg()
    site_name = cfg.get("site_name", "iCreateFlow") or "iCreateFlow"
    failed = [r for r in results if r.get("status") not in ("posted", "skipped")]
    failed_count = len(failed)

    failed_block = ""
    if failed_count:
        failed_block = f"""
      <div style="margin-top:24px;background:#fff5f5;border:1px solid #fecaca;border-radius:10px;padding:16px 20px;text-align:center;">
        <p style="margin:0;font-size:15px;color:#dc2626;font-weight:600;">
          ⚠️ {failed_count} post{"s" if failed_count > 1 else ""} failed
        </p>
        <p style="margin:8px 0 12px;font-size:13px;color:#666;">
          You can retry from your dashboard.
        </p>
        <a href="{dashboard_url}"
           style="display:inline-block;background:#dc2626;color:#fff;text-decoration:none;
                  font-size:13px;font-weight:600;padding:9px 20px;border-radius:8px;">
          View failed posts →
        </a>
      </div>"""

    html = await _html_wrap_cfg(f"""
      <div style="text-align:center;padding:8px 0 4px;">
        <div style="font-size:42px;letter-spacing:4px;margin-bottom:4px;">🎉 🎊 🎉</div>
        <h1 style="font-size:36px;font-weight:800;margin:0 0 8px;letter-spacing:1px;color:#111;">
          HURRAY!
        </h1>
        <p style="font-size:16px;color:#444;margin:0 0 4px;">
          Posts published successfully for
        </p>
        <p style="font-size:18px;font-weight:700;color:#111;margin:0;">
          {artist_name}
        </p>
      </div>
      {failed_block}
      <div style="margin-top:28px;text-align:center;">
        <a href="{dashboard_url}"
           style="display:inline-block;background:#111;color:#fff;text-decoration:none;
                  font-size:13px;font-weight:600;padding:10px 24px;border-radius:8px;">
          View dashboard →
        </a>
      </div>
    """)

    if failed_count:
        text = (
            f"HURRAY! Posts published for {artist_name}.\n"
            f"{failed_count} post(s) failed — visit your dashboard to retry: {dashboard_url}"
        )
    else:
        text = f"HURRAY! Posts published successfully for {artist_name}."

    await send_email(
        to_email,
        f"🎉 Posts published — {artist_name}",
        html,
        text,
        unsubscribe_url=unsubscribe_url,
    )


async def send_welcome_pending_email(to_email: str, name: str) -> None:
    cfg = await _get_smtp_cfg()
    site_name = cfg.get("site_name", "iCreateFlow") or "iCreateFlow"
    html = await _html_wrap_cfg(f"""
      <p>Hi {name},</p>
      <p>Thanks for signing up for <strong>{site_name}</strong>!</p>
      <p>Your account is <strong>pending admin approval</strong>. You'll receive another email
      once your account is activated and you can log in.</p>
    """)
    text = (
        f"Hi {name},\n\nThanks for signing up for {site_name}!\n"
        "Your account is pending admin approval. You'll be notified when it's activated."
    )
    await send_email(to_email, f"{site_name} — Account pending approval", html, text)
