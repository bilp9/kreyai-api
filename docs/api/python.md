
---

# 📄 `docs/api/python.md`

```md
# KreyAI API v1 — Python Usage

> This is client-side example code.
> You do not run this inside KreyAI’s backend.

---

## Install (future SDK)

```bash
pip install kreyai

from kreyai import Client

client = Client(api_key="YOUR_API_KEY")

result = client.transcribe(
    file_path="audio.mp3",
    language="auto",
    format="text"
)

print(result.text)
