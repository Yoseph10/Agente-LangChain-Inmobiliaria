# Reglas del proyecto — Agente IA Multi-Tool (LangChain + Qdrant)

## REGLA OBLIGATORIA: Documentación de LangChain primero

**Antes de generar, modificar, refactorizar o depurar CUALQUIER código de LangChain, DEBES consultar la documentación oficial de LangChain a través del MCP `docs-langchain` disponible en la sesión.** No respondas desde memoria.

Aplica esta regla siempre que el trabajo involucre:
- Imports de `langchain`, `langchain_core`, `langchain_community`, `langchain_openai`, `langchain_qdrant`, `langchain_postgres`, `langchain_tavily`, `langgraph` o `langsmith`.
- Crear o cambiar: chains, agentes, retrievers, tools (`@tool`), memoria/historial, vector stores, embeddings, RAG, grafos, o el binding de tools (`bind_tools`, `init_chat_model`).
- El usuario pide construir, refactorizar, actualizar o corregir código LangChain.

### Cómo cumplirla
1. Usa las herramientas del MCP `docs-langchain` para buscar/leer la doc relevante:
   - `search_docs_by_lang_chain` para buscar por tema.
   - `query_docs_filesystem_docs_by_lang_chain` para leer las páginas encontradas.
2. Prefiere lo que devuelva el MCP por encima del conocimiento previo (las APIs de LangChain cambian con frecuencia).
3. Verifica nombres de paquetes, firmas y patrones actuales **antes** de escribir el código.
4. Cita/menciona brevemente la página consultada al proponer el código.
5. Si la doc del MCP contradice el código existente del proyecto, indícalo en lugar de asumir.

> Esta regla equivale a la skill `langchain-docs-first`; el MCP a usar es `docs-langchain`.

## Arquitectura del proyecto

Este proyecto sigue la convención modular documentada en la skill **`langchain-modular-agent`**
(`.claude/skills/langchain-modular-agent/SKILL.md`). Aplícala por defecto:
config del modelo en `model_config/`, prompt en `prompt/`, memoria en `conversation_history/`,
tools en `tools/`, y el ensamblado en el orquestador `agente_*.py`.

## Modelo LLM

Modelo por defecto del proyecto: **gpt-4.1** (ver `model_config/model_config.yaml`), acorde a la
preferencia global (skill `default-llm-model`).
