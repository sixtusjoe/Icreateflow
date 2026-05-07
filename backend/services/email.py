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
        header_inner = (
            f'<div class="header-inner">'
            f'<img src="{logo_url}" alt="{site_name}" style="height:36px;width:auto;display:block;">'
            f'<span class="header-name">{site_name}</span>'
            f'</div>'
        )
    else:
        header_inner = f'<span class="header-name">{site_name}</span>'

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
    plats = ", ".join(p.capitalize() for p in platform_list) if platform_list else "connected platforms"
    html = await _html_wrap_cfg(f"""
      <p>Hi,</p>
      <p>Reminder: <strong>{artist_name}</strong> has a post scheduled in approximately 1 hour.</p>
      <p><strong>Time:</strong> {scheduled_time}<br>
         <strong>Platforms:</strong> {plats}</p>
      <p>Make sure the variation accounts are connected and tokens are valid.</p>
    """)
    text = (
        f"Reminder: {artist_name} has a post scheduled in ~1 hour at {scheduled_time}.\n"
        f"Platforms: {plats}"
    )
    await send_email(to_email, f"{site_name} — Upcoming post: {artist_name}", html, text)


async def send_post_result_email(
    to_email: str,
    artist_name: str,
    results: list[dict],
    unsubscribe_url: str | None = None,
) -> None:
    """Send a post success/failure summary email.

    results: list of {platform, variation_name, status, error}
    """
    cfg = await _get_smtp_cfg()
    site_name = cfg.get("site_name", "iCreateFlow") or "iCreateFlow"
    rows = ""
    for r in results:
        icon = "✓" if r.get("status") == "posted" else "✗"
        color = "#16a34a" if r.get("status") == "posted" else "#dc2626"
        err = f" — {r['error'][:120]}" if r.get("error") else ""
        rows += (
            f"<tr>"
            f"<td style='padding:6px 12px;color:{color};font-weight:700'>{icon}</td>"
            f"<td style='padding:6px 0'>{r.get('platform','').capitalize()}</td>"
            f"<td style='padding:6px 12px;color:#666'>{r.get('variation_name','')}</td>"
            f"<td style='padding:6px 0;color:{color};font-size:13px'>{err}</td>"
            f"</tr>"
        )
    html = await _html_wrap_cfg(f"""
      <p>Here's the posting summary for <strong>{artist_name}</strong>:</p>
      <table style='width:100%;border-collapse:collapse'>
        <tr style='background:#f5f5f5;font-size:12px;color:#666'>
          <th style='padding:6px 12px;text-align:left'></th>
          <th style='padding:6px 0;text-align:left'>Platform</th>
          <th style='padding:6px 12px;text-align:left'>Variation</th>
          <th style='padding:6px 0;text-align:left'>Note</th>
        </tr>
        {rows}
      </table>
    """)
    failed = [r for r in results if r.get("status") != "posted"]
    if failed:
        text = f"Post summary for {artist_name}: {len(results)-len(failed)} posted, {len(failed)} failed.\n"
        text += "\n".join(f"✗ {r.get('platform')} ({r.get('variation_name')}): {r.get('error','')}" for r in failed)
    else:
        text = f"Post summary for {artist_name}: all {len(results)} posts succeeded."
    await send_email(
        to_email,
        f"{site_name} — Post results: {artist_name}",
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
