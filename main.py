import os
import sqlite3
import json
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Response
from twilio.rest import Client
from openai import AsyncOpenAI
from pinecone import Pinecone

# 1. Load environment variables
load_dotenv()

app = FastAPI()
@app.get("/")
def health_check():
    return {"status": "Nouniu está despierto y funcionando"}

# 2. Initialize APIs
client_openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index("nouniu-db")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# 3. Persistent Memory (SQLite)
conn = sqlite3.connect('nouniu_memoria.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS usuarios (
        telefono TEXT PRIMARY KEY,
        fecha_inicio TEXT,
        interacciones INTEGER,
        historial TEXT,
        perfil TEXT,
        ultimo_mensaje TEXT 
    )
''')
conn.commit()

@app.post("/whatsapp")
async def whatsapp_webhook(Body: str = Form(""), From: str = Form("")):
    mensaje_usuario = Body.strip()
    ahora = datetime.now().isoformat()
    
    # 4. State Management
    cursor.execute("SELECT * FROM usuarios WHERE telefono = ?", (From,))
    usuario = cursor.fetchone()
    
    if not usuario:
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        cursor.execute('''
            INSERT INTO usuarios (telefono, fecha_inicio, interacciones, historial, perfil, ultimo_mensaje)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (From, fecha_hoy, 1, json.dumps([]), json.dumps({}), ahora))
        conn.commit()
        
        mensaje_salida = (
            "🪹 *Hi! I'm Nouniu, your new nest in Barcelona.*\n"
            "_(Feel free to reply in English, Español, Français, Italiano, or any language!)_\n\n"
            "How can I help you settle in today?\n\n"
            "🤝 *1. Meet the Community* (Local groups, making friends)\n"
            "🗣️ *2. Language & Culture* (Free courses, local customs)\n"
            "🫂 *3. I need a break* (Feeling overwhelmed? Let's take a breath)"
        )
    
    else:
        interacciones = usuario[2] + 1
        historial_reciente = json.loads(usuario[3])
        historial_reciente.append({"role": "user", "content": mensaje_usuario})
        historial_reciente = historial_reciente[-4:]
        
        # A. RAG: Proactive Background Search
        try:
            busqueda_hibrida = f"{mensaje_usuario} upcoming local events cultural activities Barcelona"
            respuesta_embed = await client_openai.embeddings.create(
                input=busqueda_hibrida,
                model="text-embedding-3-small"
            )
            resultados = index.query(vector=respuesta_embed.data[0].embedding, top_k=1, include_metadata=True)
            info_recuperada = resultados['matches'][0]['metadata']['texto'] if resultados['matches'] else "No specific local data found."
        except Exception as e:
            print(f"⚠️ Pinecone error: {e}")
            info_recuperada = "Database offline."

        # B. THE MASTER PROMPT
        prompt_sistema = f"""
        You are Nouniu, an empathetic local companion for expats in Barcelona. Your goal is to help them integrate, discover the culture, and support their emotional wellbeing.
        
        CRITICAL RULES:
        1. STRICT LANGUAGE MATCHING: You MUST detect the language of the user's very last message and reply EXCLUSIVELY in that exact same language. If they wrote in English, reply in English. If Spanish, reply in Spanish. NEVER mix languages.
        2. LOCAL CONTEXT: Use this provided local database context: {info_recuperada}
        3. WHATSAPP FORMATTING: People read on small screens. Keep paragraphs extremely short (1-2 sentences max). Use *bold text* for key places or concepts. NEVER output large blocks of text.
        4. CURATION OVER VOLUME: You are a local curator, not Google. NEVER give long lists of 5-10 places. Always suggest a maximum of 1 or 2 highly tailored, specific options.
        5. BOUNDARIES: You are a supportive companion, not a lawyer or a medical doctor. If asked about complex legal processes, advise them to consult official services.
        6. EMPATHY FIRST: If the user expresses sadness, loneliness, or frustration, first validate their feelings naturally before offering solutions.
        7. PROACTIVE PUSH: NEVER end with a closed statement. ALWAYS offer 2 distinct options at the end: one real-world event using [LOCAL CONTEXT], and one low-effort wellness/conversational choice. Ensure your final sentence is complete.
        """
        
        # C. Generate AI Response with FAILSAFE
        mensajes_para_ia = [{"role": "system", "content": prompt_sistema}] + historial_reciente
        
        try:
            # Added max_tokens to ensure the model doesn't get cut off mid-sentence
            respuesta_ia = await client_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=mensajes_para_ia,
                max_tokens=300
            )
            mensaje_salida = respuesta_ia.choices[0].message.content
            historial_reciente.append({"role": "assistant", "content": mensaje_salida})
            
            cursor.execute('''
                UPDATE usuarios
                SET interacciones = ?, historial = ?, ultimo_mensaje = ?
                WHERE telefono = ?
            ''', (interacciones, json.dumps(historial_reciente), ahora, From))
            conn.commit()
            
        except Exception as e:
            print(f"⚠️ OpenAI error: {e}")
            mensaje_salida = (
                "⚠️ *Technical Break*\n"
                "I am having a brief moment finding my words, but I am still here for you!\n\n"
                "While I reconnect, here are some reliable offline resources:\n"
                "📞 Emergencies: 112\n"
                "🏥 Medical Help (CatSalut): 061\n"
                "🌐 City Hall Info: 010\n\n"
                "I will be fully back online shortly. 💙"
            )

    # 5. Send via Twilio
    try:
        twilio_client.messages.create(from_=TWILIO_NUMBER, to=From, body=mensaje_salida)
    except Exception as e:
        print(f"❌ Twilio error: {e}")

    return Response(content="", status_code=200)