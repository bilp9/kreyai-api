# app/services/email_service.py
import os
import httpx

RESEND_API_KEY = os.getenv("RESEND_API_KEY")

FROM_EMAIL = "KreyAI <noreply@kreyai.com>"


async def send_verification_email(to_email: str, job_id: str, code: str):
    """
    Sends verification email using Resend.
    """

    if not RESEND_API_KEY:
        print("⚠️ RESEND_API_KEY not set — skipping email send")
        print(f"Verification code for {to_email}: {code}")
        return

    url = "https://api.resend.com/emails"

    html_content = f"""
    <h2>KreyAI Email Verification</h2>
    <p>Your Job ID: <strong>{job_id}</strong></p>
    <p>Your verification code:</p>
    <h1>{code}</h1>
    <p>Enter this code to begin transcription.</p>
    """

    payload = {
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": "Verify your KreyAI job",
        "html": html_content,
    }

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            print("❌ Resend error:", response.text)
        else:
            print("📧 Verification email sent")
