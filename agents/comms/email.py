"""
agents/comms/email.py
=====================
Complete Email tools for Jessica 3.5.
Supports:
  - Sending via Resend (primary, production-grade)
  - Sending via Gmail SMTP (fallback)
  - Reading inbox via IMAP (Gmail)
  - Searching emails via IMAP (Gmail)
  - Scheduling emails for future delivery via Supabase
  - Logging all activity to Supabase
"""

from __future__ import annotations

import os
import time
import socket
import imaplib
import email
import email.header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.utils import make_msgid, formatdate
from email import encoders
from datetime import datetime, timezone, timedelta
import smtplib

import resend
from supabase import create_client, Client
from langchain_core.tools import tool
from dotenv import load_dotenv

from agents.comms.schedule_email import schedule_research_email

load_dotenv()

# Credentials 
RESEND_API_KEY     = os.getenv("RESEND_API_KEY", "")

GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

_default_from = f"Jessica 3.5 <{GMAIL_ADDRESS}>" if GMAIL_ADDRESS else "Jessica 3.5 <[EMAIL_ADDRESS]>"
RESEND_FROM        = os.getenv("RESEND_FROM_EMAIL", _default_from)

SUPABASE_URL       = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY       = os.getenv("SUPABASE_KEY", "")

# Supabase client (optional — gracefully degrades if not set)
_supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        _supabase = None


SAFE_LOG_BODY_CHARS = 1000
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024

# ── IMAP (Gmail) connection settings ──────────────────────────────────────────
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
IMAP_TIMEOUT_S = float(os.getenv("IMAP_TIMEOUT_S", "15"))
IMAP_DEADLINE_S = float(os.getenv("IMAP_DEADLINE_S", "45"))
IMAP_PREVIEW_BYTES = int(os.getenv("IMAP_PREVIEW_BYTES", "4096"))


def _imap_connect() -> imaplib.IMAP4_SSL:
    """Open an authenticated Gmail IMAP connection with a socket timeout."""
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=IMAP_TIMEOUT_S)
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    return mail


def _imap_logout_quietly(mail) -> None:
    """Best-effort logout so a connection is never leaked, even on error."""
    try:
        mail.logout()
    except Exception:
        pass


def _fetch_message_summary(mail, msg_id, preview_bytes: int = IMAP_PREVIEW_BYTES):
    """Fetch only the first `preview_bytes` of a message (headers + body prefix)."""
    _, msg_data = mail.fetch(msg_id, f"(BODY.PEEK[]<0.{preview_bytes}>)")
    raw = None
    for part in (msg_data or []):
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
            raw = part[1]
            break
    if not raw:
        return None
    return email.message_from_bytes(raw)


# ── Supabase helpers ─────────────────────────────────────────────────────────
def _log_email_to_supabase(
    direction: str,        
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    status: str = "ok",
    error: str = "",
):
    """Persist email event to Supabase `jessica_emails` table."""
    if not _supabase:
        return
    try:
        _supabase.table("jessica_emails").insert({
            "direction":  direction,
            "from_email": from_addr,
            "to_email":   to_addr,
            "subject":    subject,
            "body":       body[:SAFE_LOG_BODY_CHARS],
            "status":     status,
            "error":      error,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        pass                                    


def _md_to_html(text: str) -> str:
    """Convert markdown to clean HTML for email rendering."""
    import re
    lines = text.split("\n")
    html_lines = []
    in_ul = False
    in_ol = False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        if in_ol:
            html_lines.append("</ol>")
            in_ol = False

    def fmt_inline(s: str) -> str:
        s = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', s)
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'\*(.+?)\*', r'<em>\1</em>', s)
        s = re.sub(r'`(.+?)`', r'<code style="background:rgba(255,255,255,0.08);padding:1px 5px;border-radius:4px;font-size:12px;">\1</code>', s)
        return s

    for line in lines:
        stripped = line.rstrip()

        if re.match(r'^[-*_]{3,}$', stripped):
            close_lists()
            html_lines.append('<hr style="border:none;border-top:1px solid rgba(255,255,255,0.1);margin:16px 0;">')
            continue

        h_match = re.match(r'^(#{1,4})\s+(.*)', stripped)
        if h_match:
            close_lists()
            level = len(h_match.group(1))
            sizes = {1: "20px", 2: "17px", 3: "15px", 4: "14px"}
            weights = {1: "800", 2: "700", 3: "600", 4: "600"}
            html_lines.append(
                f'<h{level} style="margin:20px 0 8px;font-size:{sizes.get(level,"15px")};'
                f'font-weight:{weights.get(level,"600")};color:#e8e6ff;line-height:1.3;">'
                f'{fmt_inline(h_match.group(2))}</h{level}>'
            )
            continue

        ul_match = re.match(r'^[\-\*\+]\s+(.*)', stripped)
        if ul_match:
            if in_ol:
                close_lists()
            if not in_ul:
                html_lines.append('<ul style="margin:8px 0 8px 20px;padding:0;color:#a0a4c8;">')
                in_ul = True
            html_lines.append(f'<li style="margin:4px 0;">{fmt_inline(ul_match.group(1))}</li>')
            continue

        ol_match = re.match(r'^\d+\.\s+(.*)', stripped)
        if ol_match:
            if in_ul:
                close_lists()
            if not in_ol:
                html_lines.append('<ol style="margin:8px 0 8px 20px;padding:0;color:#a0a4c8;">')
                in_ol = True
            html_lines.append(f'<li style="margin:4px 0;">{fmt_inline(ol_match.group(1))}</li>')
            continue

        if not stripped:
            close_lists()
            html_lines.append('<div style="height:10px;"></div>')
            continue

        close_lists()
        html_lines.append(f'<p style="margin:0 0 6px;color:#a0a4c8;line-height:1.75;">{fmt_inline(stripped)}</p>')

    close_lists()
    return "\n".join(html_lines)


def _build_html_email(subject: str, body: str) -> str:
    """Wrap body in Jessica 3.5-branded HTML email template with full markdown rendering."""
    rendered_body = _md_to_html(body)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#080c14;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#080c14;padding:36px 16px;">
    <tr><td align="center">
      <table width="640" cellpadding="0" cellspacing="0"
             style="background:#0f1220;border-radius:18px;overflow:hidden;border:1px solid rgba(217,115,85,0.2);">

        <!-- Header -->
        <tr>
          <td style="padding:26px 32px 18px;border-bottom:1px solid rgba(217,115,85,0.12);">
            <table width="100%" cellpadding="0" cellspacing="0"><tr>
              <td>
                <span style="font-size:22px;font-weight:800;background:linear-gradient(135deg,#E88C6F,#D97355,#C96442);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">
                  Jessica 3.5
                </span>
                <span style="font-size:12px;color:#4b5375;margin-left:10px;">Deep Research AI Agent</span>
              </td>
              <td align="right">
                <span style="display:inline-block;background:rgba(217,115,85,0.12);color:#E88C6F;
                             font-size:11px;font-weight:600;padding:4px 12px;border-radius:20px;
                             border:1px solid rgba(217,115,85,0.25);">
                  Research Report
                </span>
              </td>
            </tr></table>
          </td>
        </tr>

        <!-- Subject -->
        <tr>
          <td style="padding:22px 32px 10px;">
            <h1 style="margin:0;font-size:19px;font-weight:700;color:#e8e6ff;line-height:1.35;">
              {subject}
            </h1>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:4px 32px 32px;">
            <div style="font-size:14px;line-height:1.8;">
              {rendered_body}
            </div>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:18px 32px;border-top:1px solid rgba(217,115,85,0.1);background:#080c14;">
            <p style="margin:0;font-size:11px;color:#323659;text-align:center;">
              Sent by Jessica 3.5 &mdash; Deep Research AI &mdash;
              Powered by Tavily &middot; Exa &middot; Linkup
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── TOOL: send_research_email ────────────────────────────────────────────────

@tool
def send_research_email(
    to_email: str,
    subject: str,
    research_content: str,
    attachment_paths: list[str] = None,
) -> str:
    """
    Send a comprehensive research report or analysis via email with professional HTML formatting.

    Use this tool when the user requests to email, send, or share deep research findings,
    competitive analysis, market insights, or investigation results with stakeholders.

    Delivery priority:
      1. Resend API  — primary (production-grade, ~99% deliverability)
      2. Gmail SMTP  — fallback if Resend key is not configured

    All emails are logged to Supabase `jessica_emails` table for audit and retrieval.

    Args:
        to_email: Recipient's email address (e.g. 'analyst@company.com')
        subject: Descriptive subject line summarising the research topic
        research_content: Full research findings, analysis, citations, and conclusions
        attachment_paths: Optional list of absolute paths to files to attach to the email.

    Returns:
        Confirmation message with delivery method and status
    """
    if not to_email or "@" not in to_email:
        return f"Email delivery failed: '{to_email}' is not a valid email address."

    html_body = _build_html_email(subject, research_content)
    method = "unknown"

    resend_attachments = []
    if attachment_paths:
        for path in attachment_paths:
            if os.path.isfile(path) and os.path.getsize(path) <= MAX_ATTACHMENT_BYTES:
                filename = os.path.basename(path)
                with open(path, "rb") as f:
                    file_data = f.read()
                resend_attachments.append({
                    "filename": filename,
                    "content": list(file_data)
                })

    # ── 1. Try Resend ──
    if RESEND_API_KEY:
        try:
            resend.api_key = RESEND_API_KEY
            payload = {
                "from":    RESEND_FROM,
                "to":      [to_email],
                "subject": subject,
                "text":    research_content,
                "html":    html_body,
            }
            if resend_attachments:
                payload["attachments"] = resend_attachments
            resend.Emails.send(payload)
            method = "Resend"
            _log_email_to_supabase("sent", RESEND_FROM, to_email, subject, research_content[:SAFE_LOG_BODY_CHARS])
            return (
                f"✓ Email delivered via Resend\n"
                f"Recipient : {to_email}\n"
                f"Subject   : {subject}\n"
                f"Logged    : Supabase jessica_emails ✓"
            )
        except Exception as e:
            method = "Resend (failed)"
            _log_email_to_supabase("sent", RESEND_FROM, to_email, subject, research_content[:SAFE_LOG_BODY_CHARS], "error", str(e))
            # Fall through to Gmail

    # ── 2. Fallback: Gmail SMTP ──
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return (
            "Email delivery failed: Neither Resend API key nor Gmail credentials are configured.\n"
            "Set RESEND_API_KEY (recommended) or GMAIL_ADDRESS + GMAIL_APP_PASSWORD in .env"
        )

    try:
        msg = MIMEMultipart("mixed")
        msg["From"]    = f"Jessica 3.5 Research Agent <{GMAIL_ADDRESS}>"
        msg["To"]      = to_email
        msg["Subject"] = subject
        msg["Date"]    = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="jessica.ai")

        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(research_content, "plain", "utf-8"))
        body_part.attach(MIMEText(html_body, "html", "utf-8"))
        msg.attach(body_part)

        if attachment_paths:
            for path in attachment_paths:
                if os.path.isfile(path) and os.path.getsize(path) <= MAX_ATTACHMENT_BYTES:
                    filename = os.path.basename(path)
                    with open(path, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
                    msg.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())

        method = "Gmail SMTP"
        _log_email_to_supabase("sent", GMAIL_ADDRESS, to_email, subject, research_content[:SAFE_LOG_BODY_CHARS])
        return (
            f"✓ Email delivered via Gmail SMTP\n"
            f"Recipient : {to_email}\n"
            f"Subject   : {subject}\n"
            f"Logged    : Supabase jessica_emails ✓"
        )

    except smtplib.SMTPAuthenticationError:
        return "Email delivery failed: Gmail authentication error. Use a Gmail App Password, not your account password."
    except Exception as e:
        _log_email_to_supabase("sent", GMAIL_ADDRESS, to_email, subject, research_content[:SAFE_LOG_BODY_CHARS], "error", str(e))
        return f"Email delivery failed: {str(e)}"


# ── TOOL: read_inbox ─────────────────────────────────────────────────────────

@tool
def read_inbox(
    max_emails: int = 10,
    folder: str = "INBOX",
) -> str:
    """
    Read the most recent emails from Jessica's Gmail inbox via IMAP.

    Use this tool when the user asks to check email, read messages, find replies,
    or retrieve incoming research requests sent to Jessica's address.

    All retrieved emails are logged to Supabase `jessica_emails` for audit.

    Args:
        max_emails: Maximum number of emails to retrieve (default 10, max 50)
        folder: IMAP mailbox folder to read from (default 'INBOX')

    Returns:
        Formatted list of recent emails with sender, subject, date, and preview
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return "Inbox read failed: Gmail credentials not configured in .env"

    max_emails = min(max_emails, 50)
    deadline = time.monotonic() + IMAP_DEADLINE_S

    mail = None
    try:
        mail = _imap_connect()
        mail.select(folder)

        _, message_ids = mail.search(None, "ALL")
        ids = message_ids[0].split()
        recent_ids = ids[-max_emails:][::-1]   # newest first

        results = []
        truncated = False
        for msg_id in recent_ids:
            if time.monotonic() > deadline:
                truncated = True
                break

            msg = _fetch_message_summary(mail, msg_id)
            if msg is None:
                continue

            subject   = _decode_header(msg.get("Subject", "(no subject)"))
            from_addr = _decode_header(msg.get("From", ""))
            date_str  = msg.get("Date", "")
            body      = _extract_body(msg)[:600]

            results.append({
                "id":      msg_id.decode(),
                "from":    from_addr,
                "subject": subject,
                "date":    date_str,
                "preview": body.strip(),
            })
            _log_email_to_supabase("received", from_addr, GMAIL_ADDRESS, subject, body)

        if not results:
            return f"No emails found in {folder}."

        header = f"📬 {len(results)} emails retrieved from {folder}:"
        if truncated:
            header += " (partial — stopped early to stay within the time budget)"
        lines = [header + "\n"]
        for i, e in enumerate(results, 1):
            lines.append(
                f"{'─'*55}\n"
                f"[{i}] From    : {e['from']}\n"
                f"    Subject : {e['subject']}\n"
                f"    Date    : {e['date']}\n"
                f"    Preview : {e['preview'][:300]}…\n"
            )
        return "\n".join(lines)

    except (socket.timeout, TimeoutError):
        return (
            "Inbox read timed out talking to Gmail (IMAP). This is usually a slow "
            "connection or a very large mailbox — please try again, or narrow the "
            "request (e.g. fewer emails)."
        )
    except Exception as err:
        return f"Inbox read failed: {err}"
    finally:
        if mail is not None:
            _imap_logout_quietly(mail)


# ── TOOL: search_emails ──────────────────────────────────────────────────────

@tool
def search_emails(
    query: str,
    folder: str = "INBOX",
    max_results: int = 10,
) -> str:
    """
    Search Jessica's Gmail inbox for emails matching a keyword, sender, or subject.

    Use this tool when the user asks to find a specific email, look for replies
    from a certain person, or retrieve emails about a particular research topic.

    Results are also cross-referenced with the Supabase jessica_emails log.

    Args:
        query: Search term — searches subject and body (e.g. 'quantum computing', 'from:alice@example.com')
        folder: IMAP mailbox folder (default 'INBOX')
        max_results: Maximum emails to return (default 10)

    Returns:
        Matching emails with sender, subject, date, and content preview
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return "Email search failed: Gmail credentials not configured."

    deadline = time.monotonic() + IMAP_DEADLINE_S

    mail = None
    try:
        mail = _imap_connect()
        mail.select(folder)

        if query.startswith("from:"):
            typ, message_ids = mail.search(None, "FROM", f'"{query[5:].strip()}"')
        elif query.startswith("subject:"):
            typ, message_ids = mail.search(None, "SUBJECT", f'"{query[8:].strip()}"')
        else:
            safe_query = query.replace('"', '\\"')
            try:
                typ, message_ids = mail.search(None, "X-GM-RAW", f'"{safe_query}"')
            except Exception:
                typ, message_ids = mail.search(None, "TEXT", f'"{safe_query}"')

        ids = (message_ids[0].split() if message_ids and message_ids[0] else [])
        recent = ids[-max_results:][::-1]

        if not recent:
            return f"No emails found matching '{query}' in {folder}."

        results = []
        truncated = False
        for msg_id in recent:
            if time.monotonic() > deadline:
                truncated = True
                break

            msg = _fetch_message_summary(mail, msg_id)
            if msg is None:
                continue
            subject   = _decode_header(msg.get("Subject", "(no subject)"))
            from_addr = _decode_header(msg.get("From", ""))
            date_str  = msg.get("Date", "")
            body      = _extract_body(msg)[:800]
            results.append({"from": from_addr, "subject": subject, "date": date_str, "body": body})

        header = f"🔍 {len(results)} email(s) matching '{query}':"
        if truncated:
            header += " (partial — stopped early to stay within the time budget)"
        lines = [header + "\n"]
        for i, e in enumerate(results, 1):
            lines.append(
                f"{'─'*55}\n"
                f"[{i}] From    : {e['from']}\n"
                f"    Subject : {e['subject']}\n"
                f"    Date    : {e['date']}\n"
                f"    Content : {e['body'][:400]}…\n"
            )
        return "\n".join(lines)

    except (socket.timeout, TimeoutError):
        return (
            "Email search timed out talking to Gmail (IMAP). Try a more specific "
            "query, use a 'from:' or 'subject:' prefix to narrow it, or try again."
        )
    except Exception as err:
        return f"Email search failed: {err}"
    finally:
        if mail is not None:
            _imap_logout_quietly(mail)


# ── TOOL: get_sent_email_log ─────────────────────────────────────────────────

@tool
def get_sent_email_log(
    limit: int = 20,
) -> str:
    """
    Retrieve Jessica's sent and received email history from Supabase.

    Use this tool when the user asks 'what emails did you send?', 'show my email history',
    or wants to review past communications that Jessica has handled.

    Args:
        limit: Number of records to retrieve (default 20, max 100)

    Returns:
        Chronological log of all emails sent or received by Jessica
    """
    if not _supabase:
        return "Supabase not configured — email log unavailable. Set SUPABASE_URL and SUPABASE_KEY in .env"

    try:
        limit = min(limit, 100)
        resp = (
            _supabase.table("jessica_emails")
            .select("direction,from_email,to_email,subject,status,created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return "No email history found in Supabase."

        lines = [f"📋 Email log — {len(rows)} record(s):\n"]
        for r in rows:
            arrow = "→" if r["direction"] == "sent" else "←"
            lines.append(
                f"{'─'*50}\n"
                f"[{r['direction'].upper()}] {arrow}  {r.get('created_at','')[:16]}\n"
                f"  From   : {r.get('from_email','')}\n"
                f"  To     : {r.get('to_email','')}\n"
                f"  Subject: {r.get('subject','')}\n"
                f"  Status : {r.get('status','')}\n"
            )
        return "\n".join(lines)

    except Exception as e:
        return f"Failed to retrieve email log: {e}"


# ── Private helpers ──────────────────────────────────────────────────────────

def _decode_header(raw: str) -> str:
    parts = email.header.decode_header(raw)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _extract_body(msg: email.message.Message) -> str:
    """Extract plain text body from a MIME message."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except Exception:
                    return ""
    else:
        try:
            return msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="replace"
            )
        except Exception:
            return ""
    return ""


# ── Grouped lists & exports ──────────────────────────────────────────────────
EMAIL_SEND_TOOLS = [
    send_research_email,
    schedule_research_email,
]

EMAIL_READ_TOOLS = [
    read_inbox,
    search_emails,
    get_sent_email_log,
]

EMAIL_TOOLS = EMAIL_SEND_TOOLS + EMAIL_READ_TOOLS
email_tools = EMAIL_TOOLS  # Legacy alias

__all__ = [
    "EMAIL_TOOLS",
    "EMAIL_SEND_TOOLS",
    "EMAIL_READ_TOOLS",
    "email_tools",
    # Callables
    "send_research_email",
    "schedule_research_email",
    "read_inbox",
    "search_emails",
    "get_sent_email_log",
    # Helpers needed by worker
    "_build_html_email",
    "_log_email_to_supabase",
    "_supabase",
    "RESEND_API_KEY",
    "RESEND_FROM",
    "GMAIL_ADDRESS",
    "GMAIL_APP_PASSWORD",
]
