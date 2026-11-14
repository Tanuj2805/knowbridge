# ruff: noqa: E501 - email HTML reads best one element per line
"""Account emails: the 6-digit code emails and the "you already have an account" notice.

Built as table-based HTML with inline styles: that's what Gmail, Outlook and phone mail apps all
render the same way. Each email also has a plain-text version. The app's name comes from APP_NAME.
"""

from dataclasses import dataclass
from html import escape, unescape

from app.config import get_settings

ACCENT = "#2563eb"
INK = "#0f172a"
MUTED = "#475569"
FAINT = "#94a3b8"
RULE = "#e2e8f0"
PAPER = "#f1f5f9"


@dataclass
class Email:
    subject: str
    text: str
    html: str


def _shell(*, preheader: str, heading: str, body_html: str, footer: str) -> str:
    app = escape(get_settings().app_name)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light only">
<title>{escape(heading)}</title>
</head>
<body style="margin:0;padding:0;background:{PAPER};-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{PAPER};">
  <tr><td align="center" style="padding:32px 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
      <tr><td style="padding:0 4px 18px 4px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
          <td style="width:30px;height:30px;background:{ACCENT};border-radius:8px;text-align:center;vertical-align:middle;
                     color:#ffffff;font-weight:700;font-size:15px;line-height:30px;">{app[:1].upper()}</td>
          <td style="padding-left:10px;font-size:17px;font-weight:700;color:{INK};letter-spacing:-0.2px;">{app}</td>
        </tr></table>
      </td></tr>
      <tr><td style="background:#ffffff;border:1px solid {RULE};border-radius:14px;overflow:hidden;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr><td style="height:4px;background:{ACCENT};font-size:0;line-height:0;">&nbsp;</td></tr>
          <tr><td style="padding:32px 32px 30px 32px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
            <h1 style="margin:0 0 12px 0;font-size:22px;line-height:1.3;font-weight:700;color:{INK};letter-spacing:-0.3px;">{escape(heading)}</h1>
            {body_html}
          </td></tr>
        </table>
      </td></tr>
      <tr><td style="padding:20px 8px 0 8px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
                     font-size:12px;line-height:1.6;color:{FAINT};text-align:center;">
        {footer}<br>Sent by {app}. This is an automatic email; replies aren't read.
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def _p(text: str) -> str:
    return f'<p style="margin:0 0 16px 0;font-size:15px;line-height:1.6;color:{MUTED};">{text}</p>'


def _code_box(code: str, minutes: int) -> str:
    digits = "".join(
        f'<td style="width:44px;height:54px;background:{PAPER};border:1px solid {RULE};border-radius:10px;'
        f'text-align:center;vertical-align:middle;font-family:\'SFMono-Regular\',Menlo,Consolas,monospace;'
        f'font-size:28px;font-weight:700;color:{INK};">{d}</td>'
        + ('<td style="width:8px;font-size:0;">&nbsp;</td>' if i < len(code) - 1 else "")
        for i, d in enumerate(code)
    )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 10px 0;">'
        f'<tr>{digits}</tr></table>'
        f'<p style="margin:0 0 22px 0;font-size:13px;color:{FAINT};">This code works for {minutes} minutes and '
        f'only once.</p>'
    )


def code_email(*, purpose: str, name: str, code: str, minutes: int) -> Email:
    """purpose: "verify" (finish signing up) or "reset" (set a new password)."""
    app = get_settings().app_name
    who = escape(name.split()[0]) if name.strip() else "there"
    if purpose == "verify":
        subject = f"{code} is your {app} code"
        heading = "Confirm your email"
        intro = f"Hi {who}, enter this code in {escape(app)} to finish creating your account."
        why = "If you didn't sign up, you can ignore this email: no account is created without the code."
    else:
        subject = f"{code} is your {app} password reset code"
        heading = "Reset your password"
        intro = f"Hi {who}, someone asked to reset the password for your {escape(app)} account. Enter this code to choose a new one."
        why = "If this wasn't you, ignore this email: your password stays as it is."
    body = (
        _p(intro)
        + _code_box(code, minutes)
        + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td style="border-top:1px solid {RULE};padding-top:18px;font-size:13px;line-height:1.6;color:{MUTED};">'
        f'{why}<br><strong style="color:{INK};">Never share this code.</strong> {escape(app)} will never ask you '
        f'for it by phone, chat or email.</td></tr></table>'
    )
    text = (f"{heading}\n\n{unescape(intro)}\n\nYour code: {code}\n"
            f"It works for {minutes} minutes and only once.\n\n{why}\n"
            f"Never share this code. {app} will never ask you for it.")
    return Email(subject, text, _shell(preheader=f"Your code is {code}. It works for {minutes} minutes.",
                                       heading=heading, body_html=body,
                                       footer=f"You received this because this address was entered in {escape(app)}."))


def already_registered_email(*, name: str) -> Email:
    app = get_settings().app_name
    who = escape(name.split()[0]) if name.strip() else "there"
    heading = "You already have an account"
    intro = (f"Hi {who}, someone (hopefully you) tried to create a {escape(app)} account with this email, but you "
             f"already have one.")
    advice = "Sign in as usual. If you've forgotten your password, choose <strong>Forgot password?</strong> on the sign-in page."
    body = _p(intro) + _p(advice) + _p("If this wasn't you, ignore this email: nothing has changed.")
    text = (f"{heading}\n\nSomeone tried to create a {app} account with this email, but you already have one. "
            "Sign in as usual, or use 'Forgot password?' on the sign-in page.\n\nIf this wasn't you, ignore this email.")
    return Email(f"You already have a {app} account", text,
                 _shell(preheader="Sign in, or reset your password if you've forgotten it.", heading=heading,
                        body_html=body, footer=f"You received this because this address was entered in {escape(app)}."))
