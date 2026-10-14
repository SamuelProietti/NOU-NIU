import os
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

# Cargar las variables de entorno desde el archivo .env
load_dotenv()

# 1. Conectar los sistemas usando las claves seguras del .env
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index("nouniu-db")

# 2. El dato que queremos que Nouniu aprenda
texto_info = (
    "Aprender catalán gratis: El CPNL (Consorci per a la Normalització Lingüística) "
    "ofrece cursos gratuitos de nivel básico (Ep! y Bàsic 1, 2, 3) para recién llegados "
    "a Barcelona. Las inscripciones suelen ser en septiembre, enero y abril."
)

print("🧠 Traduciendo el texto a matemáticas (OpenAI)...")
# 3. Convertir el texto en los 1536 números vectoriales
respuesta_embed = client.embeddings.create(
    input=texto_info,
    model="text-embedding-3-small"
)
vector_numeros = respuesta_embed.data[0].embedding

print("💾 Guardando en la caja fuerte...")
# 4. Subir a Pinecone con su texto original (Metadata)
index.upsert(
    vectors=[
        {
            "id": "cpnl_info_01", 
            "values": vector_numeros, 
            "metadata": {"texto": texto_info, "categoria": "idioma"}
        }
    ]
)

print("✅ ¡Dato inyectado con éxito en la memoria de Nouniu!")