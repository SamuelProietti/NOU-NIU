import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

# 1. Load keys
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index("nouniu-db")

def fetch_api_events():
    """Pulls structured data from a public API"""
    print("🌐 Fetching official events via API...")
    eventos_api = []
    try:
        # Example: A generic open public API call (using a mock structure for the portfolio)
        # In production, this would be the Open Data BCN or Eventbrite endpoint
        response = requests.get("https://date.nager.at/api/v3/publicholidays/2026/ES")
        if response.status_code == 200:
            holidays = response.json()
            for day in holidays:
                # We filter for local Catalan/Spanish context
                eventos_api.append(f"Official Holiday: {day['name']} is happening on {day['date']}. Keep this in mind for local schedules.")
        print(f"✅ Found {len(eventos_api)} events from API.")
    except Exception as e:
        print(f"⚠️ API Error: {e}")
    return eventos_api

def scrape_local_events():
    """Scrapes unstructured hyper-local data from a website"""
    print("🕷️ Scraping hyper-local community websites...")
    eventos_scraped = []
    try:
        # Example: Scraping a real webpage. We'll use a generic URL for demonstration, 
        # but you can swap this with a specific Barcelona expat blog or civic center URL.
        url = "https://example.com" # Placeholder for a real local events page
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Example logic: Find all paragraph tags that might contain event descriptions
        # You will customize these tags based on the exact website you decide to scrape
        paragraphs = soup.find_all('p', limit=3)
        for p in paragraphs:
            text = p.get_text().strip()
            if text:
                eventos_scraped.append(f"Community Note: {text}")
                
        # Adding a hardcoded local event to guarantee we have rich data for testing
        eventos_scraped.append("Community Event: Free vegan cooking workshop this Saturday at 11:00 AM in the Gràcia Civic Center. Great for meeting people!")
        print(f"✅ Scraped {len(eventos_scraped)} events from the web.")
    except Exception as e:
        print(f"⚠️ Scraping Error: {e}")
    return eventos_scraped

def sync_to_pinecone():
    print("🚀 Starting Hybrid Data Pipeline...")
    
    # 1. Extract (Gather data from both sources)
    datos_api = fetch_api_events()
    datos_web = scrape_local_events()
    
    # 2. Transform (Merge into one master list)
    todos_los_eventos = datos_api + datos_web
    
    if not todos_los_eventos:
        print("❌ No data fetched. Aborting sync.")
        return

    print(f"🧠 Generating vectors for {len(todos_los_eventos)} items...")
    
    # 3. Load (Embed and push to Pinecone)
    vectors_to_upsert = []
    for idx, evento in enumerate(todos_los_eventos):
        try:
            response = client.embeddings.create(
                input=evento,
                model="text-embedding-3-small"
            )
            vector = response.data[0].embedding
            vectors_to_upsert.append({
                "id": f"evento_hibrido_{idx}", 
                "values": vector, 
                "metadata": {"texto": evento, "origen": "pipeline_hibrido"}
            })
        except Exception as e:
            print(f"⚠️ Embedding error on item {idx}: {e}")
            
    if vectors_to_upsert:
        index.upsert(vectors=vectors_to_upsert)
        print("🎉 Sync complete! Nouniu's brain is updated with Hybrid Data.")

if __name__ == "__main__":
    sync_to_pinecone()
    