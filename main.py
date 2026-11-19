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

@app.post("/whatsapp")
async def whatsapp_webhook(Body: str = Form(""), From: str = Form("")):
    user_message = Body.strip()
    current_time = datetime.now().isoformat()
    
    # 5. State Management
    use_welcome_template = False # Flag to trigger the Twilio buttons
    
    cursor.execute("SELECT * FROM users WHERE phone = ?", (From,))
    user_data = cursor.fetchone()
    
    if not user_data:
        today_date = datetime.now().strftime("%Y-%m-%d")
        cursor.execute('''
            INSERT INTO users (phone, start_date, interactions, history, profile, last_message)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (From, today_date, 0, json.dumps([]), json.dumps({}), current_time))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE phone = ?", (From,))
        user_data = cursor.fetchone()

        # Empty first ping: keep the existing Twilio welcome template.
        if not user_message:
            use_welcome_template = True
            ai_memory_text = "I greeted the user and gave them 3 options: 'Meet community', 'Learn language', or 'I need to talk'."
            cursor.execute(
                '''UPDATE users SET interactions = 1, history = ?, last_message = ?
                   WHERE phone = ?''',
                (json.dumps([{"role": "assistant", "content": ai_memory_text}]), current_time, From),
            )
            conn.commit()
            output_message = "" # We leave this blank because Twilio handles the template
            print("[MODE] welcome_template")
            print("[SAFETY CHECK] skipped=empty_first_contact")
            print("[FICHA STEP] none")
            print("[DB/RAG] used=False reason=welcome_template")
            try:
                twilio_client.messages.create(from_=TWILIO_NUMBER, to=From, body=output_message)
            except Exception as e:
                print(f"❌ Twilio error: {e}")
            return Response(content="", status_code=200)

    # Returning user (or first text message): safety gate + clinical / Barcelona RAG
    interactions = user_data[2] + 1
    recent_history = json.loads(user_data[3] or "[]")
    recent_history.append({"role": "user", "content": user_message})
    recent_history = recent_history[-8:]
    raw_profile = user_data[4]

    turn = await handle_incoming(
        client_openai,
        index,
        user_message,
        From,
        recent_history,
        raw_profile,
    )
    output_message = turn["output_message"]
    recent_history.append({"role": "assistant", "content": output_message})

    cursor.execute('''
        UPDATE users
        SET interactions = ?, history = ?, profile = ?, last_message = ?
        WHERE phone = ?
    ''', (
        interactions,
        json.dumps(recent_history),
        json.dumps(turn["profile"], ensure_ascii=False),
        current_time,
        From,
    ))
    conn.commit()

    # 6. Send via Twilio
    try:
        twilio_client.messages.create(from_=TWILIO_NUMBER, to=From, body=output_message)
    except Exception as e:
        print(f"❌ Twilio error: {e}")

    return Response(content="", status_code=200)
