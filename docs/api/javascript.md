
---

# 📄 `docs/api/javascript.md`

```md
# KreyAI API v1 — JavaScript (Node.js)

---

## Install (future SDK)

```bash
npm install kreyai

import { KreyAI } from "kreyai";

const client = new KreyAI({
  apiKey: process.env.KREYAI_API_KEY
});

const result = await client.transcribe({
  file: "./audio.mp3",
  language: "auto",
  format: "text"
});

console.log(result.text);
