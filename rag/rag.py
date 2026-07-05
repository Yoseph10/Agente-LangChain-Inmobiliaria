"""
Ingesta RAG: indexa la base de conocimiento en Qdrant
Carga los documentos de rag/data/ (.pdf / .md / .txt), los trocea con
RecursiveCharacterTextSplitter, genera embeddings (text-embedding-ada-002,
el MISMO modelo que usa la tool buscar_datapath) y los sube a la colección
Qdrant del agente. Crea la colección si no existe.

Uso:
    python rag/rag.py            # agrega los documentos a la colección
    python rag/rag.py --reset    # BORRA la colección y la recrea desde cero
                                 # (útil para eliminar contenido viejo)

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import sys
import glob

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# Raíz del proyecto (este archivo vive en rag/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(BASE_DIR, "rag", "data")

# ============================================
# CONFIGURACIÓN Y VALIDACIÓN DE ENTORNO
# ============================================
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "alpha-state-conocimiento")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not QDRANT_URL:
    raise ValueError("❌ Falta QDRANT_URL en .env")
if not QDRANT_API_KEY:
    raise ValueError(
        "❌ Falta QDRANT_API_KEY en .env "
        "(mismo valor que QDRANT__SERVICE__API_KEY en tu servidor Qdrant)"
    )
if not OPENAI_API_KEY:
    raise ValueError("❌ Falta OPENAI_API_KEY en .env (necesaria para los embeddings)")

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

# MISMO modelo de embeddings que la tool buscar_datapath (tools/Base_de_conocimiento.py):
# si difieren, la búsqueda del agente no encontrará estos vectores.
EMBEDDING_MODEL = "text-embedding-ada-002"
EMBEDDING_DIM = 1536  # dimensión de text-embedding-ada-002

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


# ============================================
# 1. CARGA DE DOCUMENTOS
# ============================================
def _limpiar_texto_pdf(texto: str) -> str:
    """Normaliza el texto extraído del PDF: pypdf suele dejar espacios múltiples
    y saltos de línea entre palabras (texto justificado). Se colapsa todo el
    whitespace a espacios simples; el splitter corta luego por oraciones."""
    return " ".join(texto.split())


def _cargar_pdf(ruta: str) -> list[Document]:
    """Lee un PDF con pypdf: un Document por página, con metadata de origen y página."""
    import pypdf

    reader = pypdf.PdfReader(ruta)
    nombre = os.path.basename(ruta)
    paginas = [
        Document(
            page_content=_limpiar_texto_pdf(pagina.extract_text() or ""),
            metadata={"source": nombre, "page": i + 1},
        )
        for i, pagina in enumerate(reader.pages)
    ]
    total_chars = sum(len(p.page_content) for p in paginas)
    print(f"   📄 Cargado: {nombre} ({len(paginas)} páginas, {total_chars} caracteres)")
    return paginas


def cargar_documentos() -> list[Document]:
    """Lee todos los .pdf, .md y .txt de rag/data/ como Documents con metadata."""
    rutas_pdf = sorted(glob.glob(os.path.join(DOCS_DIR, "*.pdf")))
    rutas_texto = sorted(
        glob.glob(os.path.join(DOCS_DIR, "*.md"))
        + glob.glob(os.path.join(DOCS_DIR, "*.txt"))
    )
    if not rutas_pdf and not rutas_texto:
        raise ValueError(f"❌ No hay documentos .pdf/.md/.txt en {DOCS_DIR}")

    documentos = []
    for ruta in rutas_pdf:
        documentos.extend(_cargar_pdf(ruta))
    for ruta in rutas_texto:
        with open(ruta, "r", encoding="utf-8") as f:
            contenido = f.read()
        documentos.append(
            Document(page_content=contenido, metadata={"source": os.path.basename(ruta)})
        )
        print(f"   📄 Cargado: {os.path.basename(ruta)} ({len(contenido)} caracteres)")
    return documentos


# ============================================
# 2. COLECCIÓN: CREAR / RESETEAR
# ============================================
def preparar_coleccion(client: QdrantClient) -> None:
    """Crea la colección si no existe; con --reset la borra y recrea (pide confirmación)."""
    existe = client.collection_exists(QDRANT_COLLECTION)

    if "--reset" in sys.argv and existe:
        confirmacion = input(
            f"⚠️  Vas a BORRAR la colección '{QDRANT_COLLECTION}' completa. "
            "Escribe 'borrar' para confirmar: "
        ).strip().lower()
        if confirmacion != "borrar":
            print("   Operación cancelada. No se borró nada.")
            sys.exit(0)
        client.delete_collection(QDRANT_COLLECTION)
        print(f"   🗑️  Colección '{QDRANT_COLLECTION}' eliminada.")
        existe = False

    if not existe:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        print(f"   🆕 Colección '{QDRANT_COLLECTION}' creada ({EMBEDDING_DIM} dims, cosine).")


# ============================================
# 3. INGESTA: SPLIT + EMBEDDINGS + UPSERT
# ============================================
def ingestar() -> None:
    print("=" * 60)
    print("📚 Ingesta RAG → Qdrant")
    print("=" * 60)
    print(f"   Servidor: {QDRANT_URL}")
    print(f"   Colección: {QDRANT_COLLECTION}")
    print(f"   Embeddings: {EMBEDDING_MODEL}")

    # port=None: usa el puerto de la URL o el estándar del esquema (443 en https).
    # Sin esto, qdrant-client fuerza el puerto 6333 aunque la URL sea https
    # (detrás del proxy de Easypanel el servicio escucha en 443).
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, port=None)
    preparar_coleccion(client)

    print("\n1️⃣  Cargando documentos...")
    documentos = cargar_documentos()

    print("\n2️⃣  Troceando en chunks...")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        add_start_index=True,
        # Además de los separadores por defecto, corta por viñetas y fin de oración
        # (clave para PDFs, donde la limpieza elimina los saltos de línea).
        separators=["\n\n", "\n", "● ", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documentos)
    print(f"   ✂️  {len(documentos)} documento(s) → {len(chunks)} chunks")

    print("\n3️⃣  Generando embeddings y subiendo a Qdrant...")
    embedding_model = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    vectorstore = QdrantVectorStore(
        client=client,
        collection_name=QDRANT_COLLECTION,
        embedding=embedding_model,
    )
    ids = vectorstore.add_documents(documents=chunks)
    print(f"   ⬆️  {len(ids)} vectores subidos a '{QDRANT_COLLECTION}'")

    print("\n4️⃣  Verificando con una búsqueda de prueba...")
    consulta_prueba = "¿Cuál es la multa por pago atrasado?"
    resultados = vectorstore.similarity_search(consulta_prueba, k=1)
    if resultados:
        print(f"   🔍 '{consulta_prueba}'")
        print(f"   ✅ Recuperado: {resultados[0].page_content[:150]}...")
    else:
        print("   ⚠️  La búsqueda de prueba no devolvió resultados. Revisa la colección.")

    print("\n✅ Ingesta completada.")


if __name__ == "__main__":
    ingestar()
