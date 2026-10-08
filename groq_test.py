from dotenv import load_dotenv
load_dotenv()

import os
from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
try:
    resp = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[{"role": "user", "content": "say ok"}],
        max_tokens=5
    )
    print(resp.choices[0].message.content)
except Exception as e:
    print("ERROR:", e)