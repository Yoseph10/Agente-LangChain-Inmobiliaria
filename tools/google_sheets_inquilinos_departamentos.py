"""
Tool: Pagos mensuales de inquilinos/propietarios (Google Sheets)
Lee la hoja de cálculo con el desglose de gastos mensuales por departamento
(consumo de agua, servicios básicos, gestión administrativa, mantenimientos
preventivos, fondo de contingencia, redondeos y total a pagar).

Usa el mismo Service Account de Google que la tool de departamentos en
alquiler (clave completa en GOOGLE_SHEETS_SERVICE_ACCOUNT_KEY), compartido
también con este Google Sheet (permiso Lector).

Autenticación de la consulta (información confidencial):
Esta hoja contiene el monto que paga CADA inquilino/propietario, dato que
no debe ser visible para otros inquilinos. Por eso la tool exige DOS datos
que solo el propio inquilino/propietario debería conocer:
- Bloque inmobiliario (número de departamento, ej. "101")
- Responsable de Pago / Propietario (nombre tal como figura en la hoja)
Solo si ambos coinciden con la misma fila se devuelve el desglose de pago.

Estructura de la hoja: la fila 1 son encabezados de categoría (ej. "Consumo
de Agua", "Servicios Básicos") y la fila 2 tiene los nombres de columna
reales; los datos empiezan en la fila 3. Por eso se lee con _HEADER_ROW=2
(valores crudos, no get_all_records, ver _leer_registros).

Autor: Yoseph Ayala Valencia
"""

import json
import os

from dotenv import load_dotenv, find_dotenv
from langchain_core.tools import tool

import gspread

load_dotenv(find_dotenv())

# ============================================
# CONFIGURACIÓN DE GOOGLE SHEETS
# ============================================
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_INQUILINOS_SPREADSHEET_ID")
SERVICE_ACCOUNT_KEY_RAW = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT_KEY")
WORKSHEET_NAME = os.getenv("GOOGLE_SHEETS_INQUILINOS_WORKSHEET", "Hoja1")

# Fila donde viven los nombres de columna reales (la fila 1 son encabezados
# de categoría que agrupan varias columnas, ej. "Consumo de Agua")
_HEADER_ROW = 2

COLUMNA_BLOQUE = "Bloque inmobiliario"
COLUMNA_RESPONSABLE = "Responsable de Pago / Propietario"

if not SPREADSHEET_ID:
    raise ValueError(
        "❌ Falta GOOGLE_SHEETS_INQUILINOS_SPREADSHEET_ID en .env\n"
        "Es el ID del Google Sheet de pagos de inquilinos (la parte entre /d/ y /edit de la URL)."
    )

if not SERVICE_ACCOUNT_KEY_RAW:
    raise ValueError(
        "❌ Falta GOOGLE_SHEETS_SERVICE_ACCOUNT_KEY en .env\n"
        "Debe contener el JSON completo de la clave del service account "
        "(el mismo que usa buscar_departamentos_alquiler)."
    )

try:
    SERVICE_ACCOUNT_INFO = json.loads(SERVICE_ACCOUNT_KEY_RAW)
except json.JSONDecodeError as e:
    raise ValueError(
        "❌ GOOGLE_SHEETS_SERVICE_ACCOUNT_KEY no contiene un JSON válido.\n"
        "Debe ser el contenido íntegro del archivo de clave del service account."
    ) from e

# Solo lectura: el agente nunca modifica la hoja
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Cliente perezoso: la clave se valida al importar, pero la conexión
# a Google se abre recién en la primera consulta.
_client = None


def _get_worksheet():
    """Devuelve la hoja de trabajo configurada (autentica en la primera llamada)."""
    global _client
    if _client is None:
        _client = gspread.service_account_from_dict(SERVICE_ACCOUNT_INFO, scopes=_SCOPES)
    spreadsheet = _client.open_by_key(SPREADSHEET_ID)
    return spreadsheet.worksheet(WORKSHEET_NAME)


def _normalizar(valor) -> str:
    """Normaliza texto para comparar bloque/responsable sin falsos negativos
    por mayúsculas, espacios extra o números tipo '101.0'."""
    texto = str(valor).strip()
    if texto.endswith(".0") and texto[:-2].isdigit():
        texto = texto[:-2]
    return " ".join(texto.split()).casefold()


def _leer_registros(worksheet) -> list[dict]:
    """
    Lee la hoja como valores crudos y arma los registros combinando las dos
    filas de cabecera.

    No se usa `get_all_records()` porque la hoja trae columnas de la grilla
    sin nombre (celdas en blanco más allá de la última columna con datos),
    lo que gspread rechaza como "cabeceras duplicadas" (todas vacías).

    La fila 1 trae el nombre de categoría para las columnas agrupadas (ej.
    "Consumo de Agua") y la fila 2 el nombre real de cada columna dentro del
    grupo; pero columnas sueltas al final (SubTotal, Descuentos por saldos,
    Redondeo del Mes Anterior, Redondeo del Mes, Total) solo tienen nombre en
    la fila 1 (la fila 2 queda vacía porque no pertenecen a ningún grupo). Por
    eso el nombre de columna es: fila 2 si no está vacía, si no, fila 1.
    """
    valores = worksheet.get_all_values()
    if len(valores) < _HEADER_ROW:
        return []

    fila_categoria = valores[_HEADER_ROW - 2] if _HEADER_ROW >= 2 else []
    fila_columna = valores[_HEADER_ROW - 1]

    columnas = []
    for i, nombre in enumerate(fila_columna):
        nombre = nombre.strip()
        if not nombre and i < len(fila_categoria):
            nombre = fila_categoria[i].strip()
        if nombre:
            columnas.append((i, nombre))

    registros = []
    for fila in valores[_HEADER_ROW:]:
        if not any(celda.strip() for celda in fila):
            continue
        registro = {
            nombre: (fila[i] if i < len(fila) else "")
            for i, nombre in columnas
        }
        registros.append(registro)

    return registros


# ============================================
# FUNCIÓN INTERNA DE LECTURA
# ============================================
def _consultar_pago_interno(bloque_inmobiliario: str, responsable_pago: str) -> str:
    """
    Busca la fila cuyo Bloque inmobiliario y Responsable de Pago / Propietario
    coinciden EXACTAMENTE con los datos recibidos (autenticación del inquilino).

    Args:
        bloque_inmobiliario: Número de departamento/bloque (ej. "101")
        responsable_pago: Nombre del responsable de pago o propietario

    Returns:
        str: Desglose de pago formateado, o mensaje de error/"no encontré"
    """
    bloque_norm = _normalizar(bloque_inmobiliario)
    responsable_norm = _normalizar(responsable_pago)

    if not bloque_norm or not responsable_norm:
        return (
            "Para consultar tu pago mensual necesito el número de bloque inmobiliario "
            "(departamento) y el nombre del Responsable de Pago / Propietario, ya que es "
            "información confidencial exclusiva de cada inquilino/propietario."
        )

    try:
        worksheet = _get_worksheet()
        registros = _leer_registros(worksheet)

        if not registros:
            return "No hay datos de pagos registrados en la hoja por el momento."

        coincidencias = [
            r for r in registros
            if _normalizar(r.get(COLUMNA_BLOQUE, "")) == bloque_norm
            and _normalizar(r.get(COLUMNA_RESPONSABLE, "")) == responsable_norm
        ]

        if not coincidencias:
            return (
                "No encontré ningún pago que coincida con el bloque inmobiliario "
                f"'{bloque_inmobiliario}' y el responsable de pago '{responsable_pago}'. "
                "Verifica que ambos datos sean exactamente correctos; por seguridad, "
                "esta información solo se muestra si ambos coinciden."
            )

        respuesta = "Desglose de pago mensual:\n\n"
        for i, registro in enumerate(coincidencias, 1):
            respuesta += f"[{i}]\n"
            for columna, valor in registro.items():
                if str(valor).strip():
                    respuesta += f"- {columna}: {valor}\n"
            respuesta += "\n"

        return respuesta

    except Exception as e:
        return f"Error al consultar el pago del inquilino en Google Sheets: {str(e)}"


# ============================================
# TOOL EXPORTABLE
# ============================================
@tool
def buscar_pago_inquilino(bloque_inmobiliario: str, responsable_pago: str) -> str:
    """
    Consulta el desglose del pago mensual (Google Sheets) de un inquilino o
    propietario: consumo de agua, servicios básicos, gestión administrativa,
    mantenimientos preventivos, fondo de contingencia, redondeos y total a pagar.

    Información CONFIDENCIAL: solo se devuelve si AMBOS datos de identificación
    coinciden con la misma fila (autenticación). NUNCA inventes ni asumas estos
    datos por el usuario; pídeselos explícitamente si no los dio.

    Usa esta herramienta cuando el inquilino o propietario pregunte:
    - Cuánto debe pagar este mes, o el detalle/desglose de su pago o mantenimiento
    - Montos de agua, servicios básicos, mantenimiento, fondo de contingencia, etc. de SU departamento

    NO uses esta herramienta para:
    - Preguntar por los montos de OTRO departamento o inquilino (no está permitido)
    - Departamentos disponibles para alquilar (usa buscar_departamentos_alquiler)
    - Preguntas generales sobre DATAPATH/Alpha State (usa buscar_datapath)

    Args:
        bloque_inmobiliario: Número de bloque/departamento del inquilino (ej. "101")
        responsable_pago: Nombre completo del Responsable de Pago / Propietario, tal
            como el usuario lo identifica (debe coincidir con el registrado en la hoja)
    """
    print(
        f"   🧾 Consultando pago de inquilino (bloque: '{bloque_inmobiliario}', "
        f"responsable: '{responsable_pago}')"
    )
    return _consultar_pago_interno(bloque_inmobiliario, responsable_pago)
