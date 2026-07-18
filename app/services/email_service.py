# app/services/email_service.py

import os
import httpx
from html import escape
from urllib.parse import urlencode

from app.constants import VERIFICATION_CODE_TTL_MINUTES
from app.security.job_tokens import JobTokenConfig, mint_job_token

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")
FROM_EMAIL = "KreyAI <noreply@kreyai.com>"
INTERNAL_ORDER_NOTIFICATION_EMAILS = [
    email.strip()
    for email in os.getenv(
        "INTERNAL_ORDER_NOTIFICATION_EMAILS",
        "support@kreyai.com",
    ).split(",")
    if email.strip()
]
INTERNAL_SALES_NOTIFICATION_EMAILS = [
    email.strip()
    for email in os.getenv(
        "INTERNAL_SALES_NOTIFICATION_EMAILS",
        "support@kreyai.com",
    ).split(",")
    if email.strip()
]

RESEND_URL = "https://api.resend.com/emails"


# -------------------------------------------------
# Internal helper
# -------------------------------------------------

async def _send_email(to_email: str, subject: str, html: str):
    if not RESEND_API_KEY:
        print("⚠️ RESEND_API_KEY not set — skipping email send")
        return

    payload = {
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(RESEND_URL, json=payload, headers=headers)

        if response.status_code not in (200, 201):
            print("❌ Resend error:", response.status_code, response.text)
        else:
            print(f"📧 Email sent to {to_email}")


async def _send_emails(to_emails: list[str], subject: str, html: str):
    if not to_emails:
        print("ℹ️ No internal notification recipients configured")
        return

    if not RESEND_API_KEY:
        print("⚠️ RESEND_API_KEY not set — skipping email send")
        return

    payload = {
        "from": FROM_EMAIL,
        "to": to_emails,
        "subject": subject,
        "html": html,
    }

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(RESEND_URL, json=payload, headers=headers)

        if response.status_code not in (200, 201):
            print("❌ Resend error:", response.status_code, response.text)
        else:
            print(f"📧 Internal notification sent to {', '.join(to_emails)}")


# -------------------------------------------------
# Verification Email
# -------------------------------------------------

async def send_verification_email(to_email: str, job_id: str, code: str):

    query = urlencode({"job": job_id, "email": to_email, "code": code})
    verification_link = (
        f"{FRONTEND_BASE_URL}/verify"
        f"?{query}"
    )

    html_content = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; line-height:1.6; color:#111;">
      <h2>Verify your email</h2>
      <p>Please verify your email address to continue your transcription request.</p>

      <p>
        <a href="{verification_link}" 
           style="background:#111; color:#fff; padding:12px 20px; 
                  text-decoration:none; border-radius:6px; 
                  font-weight:500; display:inline-block;">
          Verify Email
        </a>
      </p>

      <p>Or enter this verification code manually:</p>
      <p style="font-size:22px; font-weight:600; letter-spacing:3px;">
        {code}
      </p>

      <p style="font-size:13px; color:#777;">
        This code is valid for {VERIFICATION_CODE_TTL_MINUTES} minutes.
      </p>

      <p style="font-size:13px; color:#777;">
        Job ID: {job_id}
      </p>
    </div>
    """

    await _send_email(
        to_email,
        "Verify your email — KreyAI",
        html_content,
    )


def _build_job_access_link(job_id: str) -> str | None:
    secret = os.getenv("JOB_TOKEN_SECRET", "")
    if len(secret) < 16:
        return None

    ttl = int(os.getenv("JOB_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))
    token = mint_job_token(JobTokenConfig(secret=secret, ttl_seconds=ttl), job_id=job_id)
    return f"{FRONTEND_BASE_URL}/jobs/{job_id}?t={token}"

# -------------------------------------------------
# Completion Email
# -------------------------------------------------

async def send_completion_email(email: str, job_id: str, *, language: str | None = None):
    from app.storage.backend import get_storage

    storage = get_storage()

    txt = storage.get_download_url(job_id, "transcript.txt")
    docx = storage.get_download_url(job_id, "transcript.docx")
    srt = storage.get_download_url(job_id, "transcript.srt")
    vtt = storage.get_download_url(job_id, "transcript.vtt")
    html = storage.get_download_url(job_id, "transcript.html")
    job_page_link = _build_job_access_link(job_id)

    job_page_section = ""
    if job_page_link:
        job_page_section = f"""
      <p>
        You can also reopen your job page here:
        <a href="{job_page_link}">View job page</a>
      </p>
        """

    html_content = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; line-height:1.6; color:#111;">
      <h2>Your transcription is ready</h2>

      <p>Your job <strong>{job_id}</strong> has completed successfully.</p>

      <p>Download your files below:</p>

      <ul>
        <li><a href="{txt}">Download TXT</a></li>
        <li><a href="{docx}">Download DOCX</a></li>
        <li><a href="{srt}">Download SRT</a></li>
        <li><a href="{vtt}">Download VTT</a></li>
        <li><a href="{html}">Download HTML (Podcast / Website)</a></li>
      </ul>

      {job_page_section}

      <p style="font-size:13px; color:#777;">
        These download links remain available for 7 days.
      </p>

      <p style="font-size:13px; color:#777;">
        After that period, files are scheduled for automatic deletion from active storage.
      </p>

      <p style="font-size:13px; color:#777;">
        KreyAI does not keep customer files for later operational retrieval after that period. If you need access
        again after 7 days, please submit a new job.
      </p>

      <p style="font-size:13px; color:#777;">
        If you want your files removed sooner, use the delete option on your job page. Once deleted, download links
        stop working immediately and a new request is required if you need the files again.
      </p>

      <p>Thank you for using KreyAI.</p>
    </div>
    """

    await _send_email(
        email,
        f"Your KreyAI transcription is ready — {job_id}",
        html_content,
    )


async def send_job_access_email(email: str, job_id: str):
    job_page_link = _build_job_access_link(job_id)
    if not job_page_link:
        print("⚠️ JOB_TOKEN_SECRET not set — skipping job access email")
        return

    html_content = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; line-height:1.6; color:#111;">
      <h2>Your KreyAI job link</h2>

      <p>Use the link below to reopen your job page for <strong>{job_id}</strong>.</p>

      <p>
        <a href="{job_page_link}"
           style="background:#111; color:#fff; padding:12px 20px;
                  text-decoration:none; border-radius:6px;
                  font-weight:500; display:inline-block;">
          Open job page
        </a>
      </p>

      <p style="font-size:13px; color:#777;">
        This link expires automatically based on your job access token settings.
      </p>
    </div>
    """

    await _send_email(
        email,
        f"Your KreyAI job link — {job_id}",
        html_content,
    )


async def send_credit_purchase_confirmation_email(
    *,
    email: str,
    pack_name: str,
    credits_minutes: int,
    balance_minutes: int,
    amount_total_cents: int | None = None,
):
    amount_line = ""
    if isinstance(amount_total_cents, int) and amount_total_cents > 0:
        amount_line = f"""
      <p style="font-size:13px; color:#777;">
        Charged: ${amount_total_cents / 100:.2f}
      </p>
        """

    html_content = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; line-height:1.6; color:#111;">
      <h2>Your KreyAI credits are ready</h2>

      <p>We received your purchase successfully and added credits to your account.</p>

      <ul>
        <li><strong>Pack:</strong> {pack_name}</li>
        <li><strong>Minutes added:</strong> {credits_minutes}</li>
        <li><strong>Current balance:</strong> {balance_minutes} minutes</li>
      </ul>

      {amount_line}

      <p>
        You can review your balance any time on the
        <a href="{billing_url}">billing page</a>.
      </p>

      <p>Thank you for using KreyAI.</p>
    </div>
    """

    await _send_email(
        email,
        "Your KreyAI minutes are available",
        html_content,
    )


async def send_dekk_license_email(
    *,
    email: str,
    plan_name: str,
    license_key: str,
    amount_total_cents: int | None = None,
):
    amount_line = ""
    if isinstance(amount_total_cents, int) and amount_total_cents > 0:
        amount_line = f"""
      <p style="font-size:13px; color:#777;">
        Charged: ${amount_total_cents / 100:.2f}
      </p>
        """

    dekk_url = f"{FRONTEND_BASE_URL}/dekk"

    html_content = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; line-height:1.6; color:#111;">
      <h2>Your Dekk license key</h2>

      <p>Thank you for purchasing <strong>{plan_name}</strong>.</p>

      <p>
        Copy this license key, open Dekk, and choose <strong>License</strong> in the app window.
        You can also use <strong>Help &gt; Activate License</strong> from the macOS menu bar.
      </p>

      <pre style="white-space:pre-wrap;background:#f4f6fb;border:1px solid #d9def1;border-radius:8px;padding:12px;font-size:13px;line-height:1.5;">{license_key}</pre>

      {amount_line}

      <p>
        Download and release information is available on the
        <a href="{dekk_url}">Dekk page</a>.
      </p>

      <p>If you need help, reply to this email or contact <a href="mailto:support@kreyai.com">support@kreyai.com</a>.</p>

      <p style="font-size:13px; color:#777;">
        Keep this email for your records. KreyAI Dekk verifies license keys locally on your device.
      </p>
    </div>
    """

    await _send_email(
        email,
        "Your Dekk license key — KreyAI",
        html_content,
    )


async def send_atelier_license_email(
    *,
    email: str,
    plan_name: str,
    license_key: str,
    amount_total_cents: int | None = None,
):
    amount_line = ""
    if isinstance(amount_total_cents, int) and amount_total_cents > 0:
        amount_line = f"""
      <p style="font-size:13px; color:#777;">
        Charged: ${amount_total_cents / 100:.2f}
      </p>
        """

    atelier_url = f"{FRONTEND_BASE_URL}/atelier"

    html_content = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; line-height:1.6; color:#111;">
      <h2>Your aTelier license key</h2>

      <p>Thank you for purchasing <strong>{plan_name}</strong>.</p>

      <p>Copy this license key and paste it into aTelier from <strong>Settings &gt; License</strong>:</p>

      <pre style="white-space:pre-wrap;background:#f4f6fb;border:1px solid #d9def1;border-radius:8px;padding:12px;font-size:13px;line-height:1.5;">{license_key}</pre>

      {amount_line}

      <p>
        Download and release information is available on the
        <a href="{atelier_url}">aTelier page</a>.
      </p>

      <p>If you need help, reply to this email or contact <a href="mailto:support@kreyai.com">support@kreyai.com</a>.</p>

      <p style="font-size:13px; color:#777;">
        Keep this email for your records. aTelier verifies license keys locally on your device.
      </p>
    </div>
    """

    await _send_email(
        email,
        "Your aTelier license key — KreyAI",
        html_content,
    )


async def send_internal_license_sale_email(
    *,
    product_name: str,
    plan_name: str,
    customer_email: str,
    amount_total_cents: int | None,
    stripe_session_id: str,
    license_id: str,
):
    amount = "Not reported"
    if isinstance(amount_total_cents, int) and amount_total_cents >= 0:
        amount = f"${amount_total_cents / 100:.2f}"

    safe_product = escape(product_name)
    safe_plan = escape(plan_name)
    safe_email = escape(customer_email)
    safe_session = escape(stripe_session_id)
    safe_license_id = escape(license_id)

    html_content = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; line-height:1.6; color:#111;">
      <h2>New {safe_product} license sale</h2>

      <p>A paid checkout produced a new license.</p>

      <ul>
        <li><strong>Product:</strong> {safe_product}</li>
        <li><strong>Plan:</strong> {safe_plan}</li>
        <li><strong>Customer:</strong> {safe_email}</li>
        <li><strong>Amount:</strong> {amount}</li>
        <li><strong>Stripe session:</strong> {safe_session}</li>
        <li><strong>License ID:</strong> {safe_license_id}</li>
      </ul>

      <p style="font-size:13px; color:#777;">
        The license key is intentionally excluded from this internal notification.
      </p>
    </div>
    """

    await _send_emails(
        INTERNAL_SALES_NOTIFICATION_EMAILS,
        f"New {product_name} license sale — {plan_name}",
        html_content,
    )


async def send_files_deleted_email(email: str, job_id: str):
    html_content = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; line-height:1.6; color:#111;">
      <h2>Your KreyAI files were deleted</h2>

      <p>The uploaded media and generated outputs for job <strong>{job_id}</strong> were deleted from active storage at your request.</p>

      <p style="font-size:13px; color:#777;">
        All download links for this job will no longer work.
      </p>

      <p style="font-size:13px; color:#777;">
        If you need those files again, please submit a new request.
      </p>

      <p>Thank you for using KreyAI.</p>
    </div>
    """

    await _send_email(
        email,
        f"Your KreyAI files were deleted — {job_id}",
        html_content,
    )


async def send_internal_new_order_email(
    *,
    job_id: str,
    customer_email: str,
    language: str,
    speaker_mode: str,
    processing_tier: str,
    execution_lane: str,
    worker_job_name: str,
    file_path: str,
    size_bytes: int,
    content_type: str,
):
    file_name = os.path.basename(file_path) if file_path else "Unknown file"
    size_mb = f"{(size_bytes / (1024 * 1024)):.1f} MB" if size_bytes else "Unknown size"

    html_content = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; line-height:1.6; color:#111;">
      <h2>New KreyAI order received</h2>

      <p>A new transcription order has been uploaded and queued for processing.</p>

      <ul>
        <li><strong>Job ID:</strong> {job_id}</li>
        <li><strong>Customer email:</strong> {customer_email}</li>
        <li><strong>Language:</strong> {language}</li>
        <li><strong>Speaker mode:</strong> {speaker_mode}</li>
        <li><strong>Processing tier:</strong> {processing_tier}</li>
        <li><strong>Execution lane:</strong> {execution_lane}</li>
        <li><strong>Worker job:</strong> {worker_job_name}</li>
        <li><strong>File name:</strong> {file_name}</li>
        <li><strong>File size:</strong> {size_mb}</li>
        <li><strong>Content type:</strong> {content_type}</li>
      </ul>

      <p style="font-size:13px; color:#777;">
        Storage path: {file_path}
      </p>
    </div>
    """

    await _send_emails(
        INTERNAL_ORDER_NOTIFICATION_EMAILS,
        f"New KreyAI order — {job_id}",
        html_content,
    )
