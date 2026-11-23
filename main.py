import os
import sqlite3
import json
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Response, HTTPException, Query
from twilio.rest import Client
from openai import AsyncOpenAI
from pinecone import Pinecone
from sync_events import sync_to_pinecone
from clinical_engine import handle_incoming

# 1. Load environment variables
load_dotenv()

app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "Nouniu is awake and running"}

# 2. Secret route for cron-job.org to trigger the Pinecone update
@app.get("/trigger-sync")
def trigger_pinecone_sync(token: str = Query(None)):
    if token != "samuel2026": 
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        sync_to_pinecone()
        return {"status": "success", "message": "Pinecone updated successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 3. Initialize APIs
client_openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index("nouniu-db")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# 4. Persistent Memory (SQLite - Now in English)
conn = sqlite3.connect('nouniu_memoria.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        phone TEXT PRIMARY KEY,
        start_date TEXT,
        interactions INTEGER,
        history TEXT,
        profile TEXT,
        last_message TEXT 
    )
''')
conn.commit()

WELCOME_TRIGGERS = {"hi", "hello", "hey", "hola", "ciao", "bonjour", "menu", "start"}

WELCOME_TEXT = (
    "🪹 *Hi! I'm Nouniu, your new nest in Barcelona.*\n"
    "How can I help you settle in today?\n\n"
    "*1* — 🤝 *Meet community* (Free local events & civic centers)\n"
    "*2* — 🗣️ *Learn language* (Free Catalan & Spanish courses)\n"
    "*3* — 🫂 *I need to talk* (24/7 confidential emotional grounding)\n\n"
    "💬 _Reply 1, 2, or 3 — or just write freely in any language!_"
)

MENU_SHORTCUTS = {
    "1": "What specific free events, workshops, or civic centers are in Barcelona to meet people?",
    "2": "Where can I find free Catalan and Spanish courses like CPNL or language exchanges in Barcelona?",
    "3": "I need to talk to someone right now, I'm feeling overwhelmed settling into Barcelona.",
}


@app.post("/whatsapp")
async def whatsapp_webhook(Body: str = Form(""), From: str = Form("")):
    user_message = Body.strip()
    clean_cmd = user_message.lower().rstrip("!.?, ")
    current_time = datetime.now().isoformat()
    today_date = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("SELECT * FROM users WHERE phone = ?", (From,))
    user_data = cursor.fetchone()

    if not user_data:
        cursor.execute(
            '''INSERT INTO users (phone, start_date, interactions, history, profile, last_message)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (From, today_date, 0, json.dumps([]), json.dumps({}), current_time),
        )
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE phone = ?", (From,))
        user_data = cursor.fetchone()

    # 5A. Instant reset + welcome menu for Loom retakes ("reset") or greetings ("hi", "menu")
    if clean_cmd in {"reset", "/reset"} or clean_cmd in WELCOME_TRIGGERS or not user_message:
        ai_memory_text = (
            "I greeted the user with the Nouniu menu: "
            "1) Meet community, 2) Learn language, 3) I need to talk."
        )
        # If "reset" is typed, wipe profile & history completely; on "hi"/"menu", clear active ficha/crisis lock cleanly
        new_history = json.dumps([{"role": "assistant", "content": ai_memory_text}])
        new_profile = json.dumps({}) if clean_cmd in {"reset", "/reset"} else (user_data[4] or json.dumps({}))

        cursor.execute(
            '''UPDATE users SET interactions = 1, history = ?, profile = ?, last_message = ?
               WHERE phone = ?''',
            (new_history, new_profile, current_time, From),
        )
        conn.commit()

        print(f"[MODE] {'session_reset' if clean_cmd in {'reset', '/reset'} else 'welcome_menu'}")
        print("[DB/RAG] used=False reason=welcome_menu")
        try:
            twilio_client.messages.create(from_=TWILIO_NUMBER, to=From, body=WELCOME_TEXT)
        except Exception as e:
            print(f"❌ Twilio error: {e}")
        return Response(content="", status_code=200)

    # 5B. Expand 1 / 2 / 3 shortcuts while still letting free-text flow naturally
    effective_message = MENU_SHORTCUTS.get(clean_cmd, user_message)

    # 5C. Safety gate + clinical PAP / Barcelona RAG
    interactions = user_data[2] + 1
    recent_history = json.loads(user_data[3] or "[]")
    recent_history.append({"role": "user", "content": effective_message})
    recent_history = recent_history[-8:]
    raw_profile = user_data[4]

    turn = await handle_incoming(
        client_openai,
        index,
        effective_message,
        From,
        recent_history,
        raw_profile,
    )
    output_message = turn["output_message"]
    recent_history.append({"role": "assistant", "content": output_message})

    cursor.execute(
        '''UPDATE users
           SET interactions = ?, history = ?, profile = ?, last_message = ?
           WHERE phone = ?''',
        (
            interactions,
            json.dumps(recent_history),
            json.dumps(turn["profile"], ensure_ascii=False),
            current_time,
            From,
        ),
    )
    conn.commit()

    # 6. Send via Twilio
    try:
        twilio_client.messages.create(from_=TWILIO_NUMBER, to=From, body=output_message)
    except Exception as e:
        print(f"❌ Twilio error: {e}")

    return Response(content="", status_code=200)