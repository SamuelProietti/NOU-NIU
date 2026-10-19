import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone
from datetime import datetime

# 1. Cargar llaves
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index("nouniu-db")

def fetch_api_events():
    """1. Recolector Oficial: API del Ayuntamiento (Fiestas Mayores, cultura cívica)"""
    print("🏛️ Extrayendo agenda oficial del Ayuntamiento...")
    eventos_api = []
    url = "https://opendata-ajuntament.barcelona.cat/data/api/action/datastore_search"
    parametros = {"resource_id": "877ccf66-9106-4ae2-be51-95a9f6469e4c", "limit": 3000}

    try:
        response = requests.get(url, params=parametros)
        response.raise_for_status()
        eventos = response.json().get("result", {}).get("records", [])
        
        fecha_hoy = datetime.now()
        eventos_vigentes = []
        for evento in eventos:
            fecha_fin_str = evento.get("end_date", "")
            if fecha_fin_str:
                try:
                    fecha_fin = datetime.strptime(fecha_fin_str[:10], "%Y-%m-%d")
                    if fecha_fin >= fecha_hoy:
                        eventos_vigentes.append(evento)
                except ValueError:
                    continue
        
        for evento in eventos_vigentes[:5]:
            titulo = evento.get("name", "Evento Oficial")
            fecha_inicio = evento.get("start_date", "Sin fecha")[:10]
            distrito = evento.get("addresses_district_name", "Barcelona")
            eventos_api.append(f"Evento oficial del Ayuntamiento: '{titulo}'. Inicia el {fecha_inicio} en {distrito}.")
            
        print(f"✅ API: {len(eventos_api)} eventos oficiales encontrados.")
    except Exception as e:
        print(f"⚠️ Error en API: {e}")
    return eventos_api

def scrape_resident_advisor():
    """2. Recolector de Clubbing: Resident Advisor (Electrónica, Techno, House)"""
    print("🪩 Extrayendo fiestas de electrónica de Resident Advisor...")
    eventos_ra = []
    try:
        url = "https://ra.co/events/es/barcelona"
        # Usamos headers para simular que somos un navegador real y que no nos bloqueen
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # RA usa etiquetas h3 para los nombres de los eventos/DJs
        titulos = soup.find_all('h3', limit=5)
        for t in titulos:
            texto = t.get_text().strip()
            if texto and len(texto) > 3:
                eventos_ra.append(f"Fiesta de música electrónica en Barcelona: '{texto}'. Ideal para clubbing.")
                
        print(f"✅ RA: {len(eventos_ra)} fiestas encontradas.")
    except Exception as e:
        print(f"⚠️ Error en RA: {e}")
    return eventos_ra

def scrape_actividades():
    """3. Recolector Local: Time Out Barcelona (Mercadillos, talleres, planes)"""
    print("🎨 Extrayendo actividades locales y cultura de Time Out...")
    eventos_act = []
    try:
        url = "https://www.timeout.es/barcelona/es/que-hacer"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extraemos los titulares de los planes de la semana
        articulos = soup.find_all('h3', limit=5)
        for art in articulos:
            texto = art.get_text().strip()
            if texto and len(texto) > 5:
                eventos_act.append(f"Actividad recomendada en la ciudad: '{texto}'. Buen plan para el fin de semana.")
                
        print(f"✅ Time Out: {len(eventos_act)} actividades encontradas.")
    except Exception as e:
        print(f"⚠️ Error en Actividades: {e}")
    return eventos_act

def sync_to_pinecone():
    print("🚀 Iniciando Pipeline Híbrido Definitivo...")
    print("🧹 Vaciando la memoria antigua de Pinecone...")
    index.delete(delete_all=True)
    
    # Ejecutamos los tres recolectores
    datos_api = fetch_api_events()
    datos_clubbing = scrape_resident_advisor()
    datos_locales = scrape_actividades()
    
    # Unificamos todo en una sola lista maestra
    todos_los_eventos = datos_api + datos_clubbing + datos_locales
    
    if not todos_los_eventos:
        print("❌ No se obtuvieron datos de ninguna fuente. Abortando.")
        return

    print(f"🧠 Generando vectores para {len(todos_los_eventos)} elementos combinados...")
    
    vectors_to_upsert = []
    for idx, evento in enumerate(todos_los_eventos):
        try:
            response = client.embeddings.create(input=evento, model="text-embedding-3-small")
            vectors_to_upsert.append({
                "id": f"evento_bcn_{idx}", 
                "values": response.data[0].embedding, 
                "metadata": {"texto": evento, "origen": "pipeline_definitivo"}
            })
        except Exception as e:
            print(f"⚠️ Error generando embedding en elemento {idx}: {e}")
            
    if vectors_to_upsert:
        index.upsert(vectors=vectors_to_upsert)
        print("🎉 ¡Sincronización completada! El cerebro de Nouniu ahora tiene datos del Ayuntamiento, Resident Advisor y Time Out.")

if __name__ == "__main__":
    sync_to_pinecone()
    