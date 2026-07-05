"""
Tool: Departamentos disponibles para alquilar (Google Sheets)
Lee la hoja de cálculo de departamentos en alquiler usando un Service Account
de Google Cloud (clave JSON). Solo lectura (scope readonly).

Requisitos previos:
1. Crear un Service Account en Google Cloud y descargar su clave JSON.
2. Habilitar la API "Google Sheets API" en el proyecto de Google Cloud.
3. Compartir el Google Sheet con el email del service account (permiso Lector).

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os

from dotenv import load_dotenv, find_dotenv
from langchain_core.tools import tool

import gspread

load_dotenv(find_dotenv())

# Raíz del proyecto (este archivo vive en tools/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================
# CONFIGURACIÓN DE GOOGLE SHEETS
# ============================================
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
CREDENTIALS_FILE = os.getenv(
    "GOOGLE_SHEETS_CREDENTIALS_FILE", "credentials/google-service-account.json"
)
WORKSHEET_NAME = os.getenv("GOOGLE_SHEETS_WORKSHEET", "")  # vacío = primera hoja

# Ruta de la clave JSON resuelta contra la raíz del proyecto (portable)
if not os.path.isabs(CREDENTIALS_FILE):
    CREDENTIALS_FILE = os.path.join(BASE_DIR, CREDENTIALS_FILE)

if not SPREADSHEET_ID:
    raise ValueError(
        "❌ Falta GOOGLE_SHEETS_SPREADSHEET_ID en .env\n"
        "Es el ID del Google Sheet (la parte entre /d/ y /edit de la URL)."
    )

if not os.path.exists(CREDENTIALS_FILE):
    raise ValueError(
        f"❌ No se encontró la clave JSON del service account: {CREDENTIALS_FILE}\n"
        "Descárgala desde Google Cloud (IAM > Service Accounts > Keys) y define\n"
        "GOOGLE_SHEETS_CREDENTIALS_FILE en .env (ruta relativa al proyecto o absoluta)."
    )

# Solo lectura: el agente nunca modifica la hoja
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Cliente perezoso: la clave se valida al importar, pero la conexión
# a Google se abre recién en la primera consulta.
_client = None


def _get_worksheet():
    """Devuelve la hoja de trabajo configurada (autentica en la primera llamada)."""
    global _client
    if _client is None:
        _client = gspread.service_account(filename=CREDENTIALS_FILE, scopes=_SCOPES)
    spreadsheet = _client.open_by_key(SPREADSHEET_ID)
    if WORKSHEET_NAME:
        return spreadsheet.worksheet(WORKSHEET_NAME)
    return spreadsheet.sheet1


# ============================================
# FUNCIÓN INTERNA DE LECTURA
# ============================================
def _leer_departamentos_interno(filtro: str = "") -> str:
    """
    Lee todas las filas del Google Sheet y las formatea como texto.
    La fila 1 se usa como cabecera (nombres de columna).

    Args:
        filtro: Texto opcional para filtrar filas (coincidencia en cualquier columna)

    Returns:
        str: Departamentos encontrados formateados, o mensaje de error
    """
    try:
        worksheet = _get_worksheet()
        registros = worksheet.get_all_records()  # list[dict] con la fila 1 como cabecera

        if not registros:
            return "No hay departamentos registrados en la hoja por el momento."

        filtro_norm = (filtro or "").strip().lower()
        if filtro_norm:
            registros = [
                r for r in registros
                if filtro_norm in " ".join(str(v) for v in r.values()).lower()
            ]
            if not registros:
                return (
                    f"No encontré departamentos que coincidan con '{filtro}'. "
                    "Puedes pedir la lista completa sin filtro."
                )

        respuesta = f"Departamentos disponibles para alquilar ({len(registros)}):\n\n"
        for i, registro in enumerate(registros, 1):
            respuesta += f"[{i}]\n"
            for columna, valor in registro.items():
                if str(valor).strip():
                    respuesta += f"- {columna}: {valor}\n"
            respuesta += "\n"

        return respuesta

    except Exception as e:
        return f"Error al consultar los departamentos en Google Sheets: {str(e)}"


# ============================================
# TOOL EXPORTABLE
# ============================================
@tool
def buscar_departamentos_alquiler(filtro: str = "") -> str:
    """
    Consulta los departamentos disponibles para alquilar (Google Sheets).
    Usa esta herramienta cuando el usuario pregunte sobre:
    - Departamentos, deptos o inmuebles disponibles para alquilar/rentar
    - Precios de alquiler, ubicaciones, habitaciones o características de los departamentos
    - Disponibilidad de un departamento específico

    NO uses esta herramienta para:
    - Preguntas sobre DATAPATH (usa buscar_datapath)
    - Búsquedas generales en internet (usa buscar_internet)

    Args:
        filtro: Texto opcional para filtrar (ej. distrito, precio, "2 habitaciones").
                Si está vacío, devuelve todos los departamentos disponibles.
    """
    print(f"   🏢 Consultando departamentos en alquiler (filtro: '{filtro or 'todos'}')")
    return _leer_departamentos_interno(filtro)
