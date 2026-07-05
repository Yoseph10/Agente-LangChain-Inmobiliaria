"""
Tool: Base de Conocimiento (RAG con Qdrant)
Permite buscar información en la base de conocimientos de la inmobiliaria
Alpha State (políticas de alquiler, boletos, multas, FAQ).

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
from dotenv import load_dotenv, find_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_core.tools import tool
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

load_dotenv(find_dotenv())

# ============================================
# CONFIGURACIÓN DE QDRANT
# ============================================
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "alpha-state-conocimiento")

if not QDRANT_URL:
    raise ValueError(
        "❌ Falta QDRANT_URL en .env (URL de tu instancia Qdrant, ej. https://qdrant.midominio.com)"
    )
if not QDRANT_API_KEY:
    raise ValueError(
        "❌ Falta QDRANT_API_KEY en .env "
        "(mismo valor que QDRANT__SERVICE__API_KEY en tu servidor Qdrant)"
    )

embedding_model = OpenAIEmbeddings(model="text-embedding-ada-002")

# Conexión perezosa: QdrantVectorStore valida que la colección exista al crearse,
# así que se conecta recién en la primera búsqueda (permite arrancar el agente
# antes de la primera ingesta con rag/rag.py).
_vectorstore = None


def _get_vectorstore() -> QdrantVectorStore:
    global _vectorstore
    if _vectorstore is None:
        # port=None: usa el puerto de la URL o el estándar del esquema (443 en https);
        # sin esto qdrant-client fuerza el 6333 aunque la URL sea https.
        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, port=None)
        if not client.collection_exists(QDRANT_COLLECTION):
            raise ValueError(
                f"La colección '{QDRANT_COLLECTION}' no existe en Qdrant. "
                "Ejecuta primero la ingesta: python rag/rag.py"
            )
        _vectorstore = QdrantVectorStore(
            client=client,
            collection_name=QDRANT_COLLECTION,
            embedding=embedding_model,
        )
    return _vectorstore


# ============================================
# FUNCIÓN INTERNA DE BÚSQUEDA
# ============================================
def buscar_en_base_conocimiento_interno(query: str, top_k: int = 5) -> str:
    """
    Función interna de búsqueda RAG con Qdrant.

    Args:
        query: Consulta de búsqueda
        top_k: Número de documentos a retornar

    Returns:
        str: Información encontrada formateada
    """
    try:
        docs = _get_vectorstore().similarity_search(query, k=top_k)

        if not docs:
            return "No encontré información relevante en la base de conocimientos."

        contexto = "Información encontrada:\n\n"
        for i, doc in enumerate(docs, 1):
            contexto += f"[{i}]\n{doc.page_content}\n\n"

        return contexto

    except Exception as e:
        return f"Error al buscar: {str(e)}"


# ============================================
# TOOL EXPORTABLE
# ============================================
@tool
def buscar_datapath(consulta: str) -> str:
    """
    Busca información en la base de conocimientos de Alpha State Assessoria Imobiliária.
    Usa esta herramienta cuando el usuario pregunte sobre:
    - Políticas de alquiler y composición del boleto (alquiler neto, IPTU, SANASA, seguro de incendio, gastos bancarios)
    - Multas e intereses por pago atrasado, reajuste anual del contrato
    - Documentación y garantías necesarias para alquilar un inmueble
    - Responsabilidad de reparaciones (propietario vs inquilino)
    - Datos de contacto y dirección de la inmobiliaria

    NO uses esta herramienta para:
    - Disponibilidad y precios de departamentos (usa buscar_departamentos_alquiler)
    - Búsquedas generales en internet (usa buscar_internet)

    Args:
        consulta: La pregunta o tema a buscar
    """
    print(f"   🔍 Buscando: '{consulta}'")
    resultado = buscar_en_base_conocimiento_interno(consulta)
    return resultado
