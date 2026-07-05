"""
Histórico de conversación (memoria persistente)
- Conexión a PostgreSQL (Supabase) vía psycopg
- Creación de la tabla de historial
- Recuperación del historial por sesión con PostgresChatMessageHistory

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
from urllib.parse import quote_plus

from dotenv import load_dotenv, find_dotenv
from langchain_postgres import PostgresChatMessageHistory
import psycopg

load_dotenv(find_dotenv())

# ============================================
# CONFIGURACIÓN DE BASE DE DATOS (Supabase / PostgreSQL)
# ============================================
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "postgres")

# Nombre de la tabla donde se guarda el historial de chat (configurable por env)
TABLE_NAME = os.getenv("DB_TABLE_NAME", "chat_history")

if not all([DB_USER, DB_PASSWORD, DB_HOST]):
    raise ValueError(
        "❌ Faltan variables de base de datos en .env\n"
        "Requeridas: DB_USER, DB_PASSWORD, DB_HOST"
    )

DATABASE_URL = f"postgresql://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

print(f"🔌 Conectando como: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")


# ============================================
# CREAR TABLA DE HISTORIAL
# ============================================
def crear_tabla_historial():
    """Crea la tabla de historial en PostgreSQL si no existe."""
    try:
        sync_connection = psycopg.connect(DATABASE_URL)
        PostgresChatMessageHistory.create_tables(sync_connection, TABLE_NAME)
        sync_connection.close()
    except Exception as e:
        print(f"⚠️ Nota sobre tabla: {e}")


# ============================================
# HISTÓRICO DE CONVERSACIÓN POR SESIÓN
# ============================================
def get_session_history(session_id: str) -> PostgresChatMessageHistory:
    """Devuelve el historial persistente de una sesión."""
    sync_connection = psycopg.connect(DATABASE_URL)
    return PostgresChatMessageHistory(
        TABLE_NAME,
        session_id,
        sync_connection=sync_connection,
    )
