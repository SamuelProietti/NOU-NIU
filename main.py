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
    cursor.execute("SELECT * FROM users WHERE phone = ?", (From,))
    user_data = cursor.fetchone()
    
    if not user_data:
        # First time user
        today_date = datetime.now().strftime("%Y-%m-%d")
        cursor.execute('''
            INSERT INTO users (phone, start_date, interactions, history, profile, last_message)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (From, today_date, 1, json.dumps([]), json.dumps({}), current_time))
        conn.commit()
        
        output_message = (
            "🪹 *Hi! I'm Nouniu, your new nest in Barcelona.*\n"
            "_(Feel free to reply in English, Español, Français, Italiano, or any language!)_\n\n"
            "How can I help you settle in today?\n\n"
            "🤝 *1. Meet the Community* (Local events, underground parties, plans)\n"
            "🗣️ *2. Language & Culture* (Practice Spanish/Catalan with me)\n"
            "🫂 *3. I need a break* (Feeling overwhelmed? Let's take a breath)"
        )
    
    else:
        # Returning user
        interactions = user_data[2] + 1
        recent_history = json.loads(user_data[3])
        recent_history.append({"role": "user", "content": user_message})
        recent_history = recent_history[-6:] # Keep last 6 messages for better context during roleplay
        
        # A. RAG: Proactive Background Search for Events
        try:
            hybrid_search = f"{user_message} upcoming local events cultural activities clubbing Barcelona"
            embed_response = await client_openai.embeddings.create(
                input=hybrid_search,
                model="text-embedding-3-small"
            )
            results = index.query(vector=embed_response.data[0].embedding, top_k=1, include_metadata=True)
            retrieved_info = results['matches'][0]['metadata']['texto'] if results['matches'] else "No specific local data found."
        except Exception as e:
            print(f"⚠️ Pinecone error: {e}")
            retrieved_info = "Database offline."

        # B. THE MASTER PROMPT (Dual-Brain)
        system_prompt = f"""
        You are Nouniu, an empathetic local companion and language tutor for expats in Barcelona.

        CURRENT LOCAL DATA (Events/Activities): {retrieved_info}

        YOUR TWO MODES:

        1. LOCAL COMPANION MODE (Default)
        - If the user wants to socialize, mentions "1", or asks for plans, use the CURRENT LOCAL DATA. Suggest 1 or 2 specific events (e.g., an underground techno party or Time Out activity). Speak like an insider friend ("I heard there's a cool party...").
        - Empathy First: Validate feelings of loneliness or frustration warmly before suggesting plans.
        - Match their language exactly (e.g., if they speak Italian, reply in Italian).

        2. LANGUAGE TUTOR MODE (If user selects "2", "Language", or asks to practice)
        - Step 1: If not specified, ask which language they want to practice (Spanish or Catalan) AND their level (Beginner, Intermediate, Advanced).
        - Step 2: Once level is known, immediately start a practical daily-life role-play (e.g., ordering coffee at a 'forn de pa', buying a metro ticket, or talking to a bartender). 
        - Step 3: During the role-play, gently correct their grammar in brackets [Correction: ...] and then reply IN CHARACTER to continue the scene. Do not break character to give long grammar lectures.

        CRITICAL RULES FOR ALL MODES:
        - WHATSAPP FORMATTING: Keep paragraphs extremely short (1-2 sentences). Use *bold* for emphasis. Use natural emojis.
        - PROACTIVE PUSH: Never end with a closed statement. Always end by asking a question, offering a choice, or passing the turn in the role-play to keep the conversation flowing.
        """
        
        # C. Generate AI Response with FAILSAFE
        ai_messages = [{"role": "system", "content": system_prompt}] + recent_history
        
        try:
            ai_response = await client_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=ai_messages,
                max_tokens=300
            )
            output_message = ai_response.choices[0].message.content
            recent_history.append({"role": "assistant", "content": output_message})
            
            # Save updated state to English database
            cursor.execute('''
                UPDATE users
                SET interactions = ?, history = ?, last_message = ?
                WHERE phone = ?
            ''', (interactions, json.dumps(recent_history), current_time, From))
            conn.commit()
            
        except Exception as e:
            print(f"⚠️ OpenAI error: {e}")
            output_message = (
                "⚠️ *Technical Break*\n"
                "I am having a brief moment finding my words, but I am still here for you!\n\n"
                "While I reconnect, here are some reliable offline resources:\n"
                "📞 Emergencies: 112\n"
                "🏥 Medical Help (CatSalut): 061\n"
                "🌐 City Hall Info: 010\n\n"
                "I will be fully back online shortly. 💙"
            )

    # 6. Send via Twilio
    try:
        twilio_client.messages.create(from_=TWILIO_NUMBER, to=From, body=output_message)
    except Exception as e:
        print(f"❌ Twilio error: {e}")

    return Response(content="", status_code=200)