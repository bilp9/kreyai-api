# app/services/email_service.py

import os
import httpx

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")
FROM_EMAIL = "KreyAI <noreply@kreyai.com>"

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


# -------------------------------------------------
# Verification Email
# -------------------------------------------------

async def send_verification_email(to_email: str, job_id: str, code: str):

    verification_link = (
        f"{FRONTEND_BASE_URL}/verify"
        f"?job={job_id}&email={to_email}&code={code}"
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
        Job ID: {job_id}
      </p>
    </div>
    """

    await _send_email(
        to_email,
        "Verify your email — KreyAI",
        html_content,
    )

# -------------------------------------------------
# Completion Email
# -------------------------------------------------

async def send_completion_email(email: str, job_id: str):
    from app.storage.backend import get_storage

    storage = get_storage()

    txt = storage.get_download_url(job_id, "transcript.txt")
    docx = storage.get_download_url(job_id, "transcript.docx")
    srt = storage.get_download_url(job_id, "transcript.srt")
    vtt = storage.get_download_url(job_id, "transcript.vtt")
    html = storage.get_download_url(job_id, "transcript.html")

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

      <p style="font-size:13px; color:#777;">
        Note: These links expire in 7 days.
      </p>

      <p>Thank you for using KreyAI.</p>
    </div>
    """

    await _send_email(
        email,
        f"Your KreyAI transcription is ready — {job_id}",
        html_content,
    )