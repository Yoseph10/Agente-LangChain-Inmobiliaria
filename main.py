"""
Canal CLI: conversación con el agente por terminal
Adapta la entrada/salida de la terminal al agente compartido.
Para el canal Chatwoot ver main_chatwoot.py.

Versión del agente (env AGENT_VERSION):
    python main.py                    # v1: agent.py (loop manual, 1 ronda)
    AGENT_VERSION=2 python main.py    # v2: agent_v2.py (create_agent, multironda)

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import uuid

from dotenv import load_dotenv, find_dotenv

# Cargar .env ANTES de leer AGENT_VERSION, para que también se pueda definir ahí
load_dotenv(find_dotenv())

AGENT_VERSION = os.getenv("AGENT_VERSION", "1").strip()

if AGENT_VERSION == "2":
    from agent_v2 import chat_con_agente, tools
else:
    from agent import chat_con_agente, tools


def main():
    print("=" * 60)
    print("🤖 AlphaBot — Agente de Alpha State Assessoria Imobiliária")
    print(f"⚙️  Orquestador: v{AGENT_VERSION} "
          f"({'create_agent (multironda)' if AGENT_VERSION == '2' else 'loop manual (1 ronda)'})")
    print("=" * 60)
    print("🔧 Tools disponibles:")
    for t in tools:
        print(f"   - {t.name}")
    print("💾 Historial: PostgreSQL")

    # Menú de sesión
    print("\nOpciones de sesión:")
    print("  1. Nueva conversación")
    print("  2. Continuar sesión existente (pegar UUID)")

    opcion = input("\nElige (1/2): ").strip()

    if opcion == "2":
        session_id = input("Pega el UUID de la sesión: ").strip()
        try:
            uuid.UUID(session_id)
        except ValueError:
            print("⚠️ UUID inválido. Creando nueva sesión...")
            session_id = str(uuid.uuid4())
    else:
        session_id = str(uuid.uuid4())

    print(f"\n📝 Session ID: {session_id}")
    print("   (Guarda este ID para continuar después)")
    print("✅ El agente consulta la base de conocimiento, el inventario de")
    print("   departamentos (Google Sheets), internet y la fecha/hora")
    print("Escribe 'salir' para terminar.\n")

    while True:
        usuario = input("Tú: ").strip()

        if usuario.lower() in ['salir', 'exit', 'quit']:
            print(f"\n💾 Tu sesión está guardada.")
            print(f"   UUID: {session_id}")
            print("👋 ¡Hasta luego!")
            break

        if not usuario:
            continue

        try:
            respuesta = chat_con_agente(usuario, session_id)
            print(f"\n🤖 AlphaBot: {respuesta}\n")
        except Exception as e:
            print(f"\n❌ Error: {e}\n")


if __name__ == "__main__":
    main()
