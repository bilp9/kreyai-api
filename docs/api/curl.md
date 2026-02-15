# KreyAI API v1 — cURL Examples

Base URL:
https://api.kreyai.com

---

## Transcribe an audio file (basic)

```bash
curl -X POST https://api.kreyai.com/v1/transcribe \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Accept: application/json" \
  -F "file=@audio.mp3" \
  -F "language=auto"
