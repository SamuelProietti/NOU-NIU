"""Chat with the same safety + clinical + Barcelona logic in PowerShell."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pinecone import Pinecone

from clinical_engine import handle_incoming
from extract_clinical_data import extract_all

load_dotenv()
extract_all(force=False)

LOCAL_FROM = os.getenv("LOCAL_TEST_FROM", "whatsapp:+local-demo")
DB_PATH = Path(__file__).resolve().parent / "nouniu_memoria.db"


def load_or_create_user(phone: str):
    conn = sqlite3.connect(DB_PATH)
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
    cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    if not row:
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute(
            '''INSERT INTO users (phone, start_date, interactions, history, profile, last_message)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (phone, today, 0, json.dumps([]), json.dumps({}), datetime.now().isoformat()),
        )
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
        row = cursor.fetchone()
    return conn, cursor, row


async def main() -> None:
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    index = pc.Index("nouniu-db")

    print("=" * 60)
    print("NOUNIU local tester  |  same logic as /whatsapp")
    print("Type your message and press Enter.")
    print("Commands:  /reset  /quit")
    print("=" * 60)

    conn, cursor, user_data = load_or_create_user(LOCAL_FROM)

    while True:
        try:
            user_message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not user_message:
            continue
        if user_message.lower() in {"/quit", "/exit", "salir"}:
            print("Bye.")
            break
        if user_message.lower() == "/reset":
            cursor.execute("DELETE FROM users WHERE phone = ?", (LOCAL_FROM,))
            conn.commit()
            conn, cursor, user_data = load_or_create_user(LOCAL_FROM)
            print("Session reset.")
            continue

        history = json.loads(user_data[3] or "[]")
        history.append({"role": "user", "content": user_message})
        history = history[-8:]
        interactions = (user_data[2] or 0) + 1

        turn = await handle_incoming(
            client,
            index,
            user_message,
            LOCAL_FROM,
            history,
            user_data[4],
        )
        output = turn["output_message"]
        history.append({"role": "assistant", "content": output})
        cursor.execute(
            '''UPDATE users SET interactions = ?, history = ?, profile = ?, last_message = ?
               WHERE phone = ?''',
            (
                interactions,
                json.dumps(history, ensure_ascii=False),
                json.dumps(turn["profile"], ensure_ascii=False),
                datetime.now().isoformat(),
                LOCAL_FROM,
            ),
        )
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE phone = ?", (LOCAL_FROM,))
        user_data = cursor.fetchone()
        print(f"\nNouniu:\n{output}")

    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
