# AgentTrace

Backend de RAG consciente del código: indexa repositorios públicos con
chunking basado en AST (tree-sitter), genera embeddings de cada chunk con
`voyage-code-3` de Voyage AI, y los guarda en SQLite con la extensión
`sqlite-vec` (similitud coseno). Responde preguntas sobre el código, con
citas file:line, mediante un agente único (Claude Agent SDK) que combina
búsqueda semántica con lectura exacta de archivos. Se sirve tanto como API
REST (`POST /ask`) como servidor MCP (Streamable HTTP, montado en `/mcp/`),
así que se puede consultar directamente o conectar a cualquier cliente MCP
(Claude Desktop, conectores de Claude.ai, etc.).

**Estado:** REST (`POST /ask`) y MCP (`index_repo`, `search_code`,
`ask_repo`) funcionan de punta a punta, con autenticación por API key
opcional.

## Demo

[![Demo de AgentTrace](https://img.youtube.com/vi/g_o0UT6XCRw/maxresdefault.jpg)](https://youtu.be/g_o0UT6XCRw)

Recorrido en vivo del frontend local: indexado de un repo, el agente
eligiendo entre búsqueda semántica y exploración directa de archivos según
la pregunta, y el trace en vivo (dos columnas) de esa decisión mientras
sucede.

## Cómo funciona

1. **Indexar** — clona un repo público, parsea los archivos `.py` con
   tree-sitter, extrae un chunk por cada función/clase/método de nivel
   superior (no un split naive por líneas), genera el embedding de cada
   chunk con `voyage-code-3` de Voyage AI, y guarda los vectores en SQLite
   vía la extensión `sqlite-vec`. Idempotente por URL — si el repo ya está
   indexado, no hace nada.
2. **Preguntar** — un único agente (Claude Agent SDK) recibe tanto una
   herramienta de búsqueda semántica (`search_code`, sobre los chunks
   indexados) como herramientas de archivo directas (`Read`/`Grep`/`Glob`,
   sobre los archivos clonados reales) y elige, pregunta por pregunta, cuál
   usar — preguntas conceptuales tipo "cómo funciona X" tienden a la
   búsqueda semántica, preguntas de símbolo exacto tipo "qué hace la línea
   X del archivo Y" tienden a la exploración directa.
3. **Trazar** — cada llamada a herramienta, resultado, y token de la
   respuesta se transmite como un evento estructurado (`POST /ask/stream`),
   así quien llama puede ver qué método eligió el agente y por qué, no solo
   la respuesta final.

### Decisiones de diseño que vale la pena conocer

- **SQLite + `sqlite-vec` en vez de Postgres/pgvector** — el diseño
  original especificaba Postgres; se reemplazó temprano porque un vector
  store embebido en un solo archivo no necesita un servicio de base de
  datos aparte para correr ni para deployar, a costa de margen de
  escalabilidad en escrituras concurrentes que este proyecto no necesita.
- **Un solo agente, no una arquitectura de dispatcher más subagentes** —
  un diseño anterior tenía un orquestador de nivel superior despachando a
  subagentes separados (`rag-search`/`code-explorer`) vía la herramienta
  Agent. Se colapsó en un solo agente con ambas familias de herramientas
  directamente: despachar agregaba una ida y vuelta de tokens/latencia
  para una decisión que el modelo puede tomar por sí mismo.
- **La elección de herramienta es una decisión en vivo, no un pipeline
  guionado** — deliberadamente esto no es "siempre embed-search-y-después-
  generar". El agente decide por pregunta, que es también por qué existe
  el trace en vivo de la demo: el punto es hacer visible esa decisión, no
  solo la respuesta final.
- **Chunking solo para Python** — tree-sitter-python es el único chunker
  implementado; otros lenguajes caen a exploración directa de archivos
  (`Read`/`Grep`/`Glob`) sin índice semántico, algo que tanto la UI como el
  agente conocen explícitamente en vez de devolver resultados vacíos en
  silencio.

## Inspiración

Los patrones de diseño de este proyecto están inspirados en
[nanoLoop](https://github.com/ismaelfaro/nanoLoop), un harness de
ingeniería autónomo: el enfoque de seguridad default-deny/allowlist
explícita, la máquina de estados de trabajos estilo
`pending → active → done/blocked`, y el patrón de fábrica de clientes
guiado por variables de entorno. No se comparte código — nanoLoop es un
harness de agentes LangChain/DeepAgents, esto es un servicio RAG/MCP, con
stacks distintos.

## Quickstart

Requiere el CLI `claude` instalado y autenticado
(`npm i -g @anthropic-ai/claude-code && claude login`), o la variable
`ANTHROPIC_API_KEY` exportada — `POST /ask` y la herramienta MCP `ask_repo`
corren a través del Claude Agent SDK, que ejecuta ese CLI como subproceso.
Sin uno de los dos, el primer `curl /ask` va a fallar.

```bash
git clone https://github.com/estanimolinas/como-funciona-un-agente-por-dentro.git
cd como-funciona-un-agente-por-dentro
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"

cp .env.example .env
# editá .env: seteá VOYAGE_API_KEY (ver .env.example para saber dónde conseguir una)

./.venv/bin/uvicorn coderag_mcp.api.main:app --reload
```

El servidor se niega a arrancar si falta `VOYAGE_API_KEY`, con un mensaje
que indica qué falta — ver `validate_settings` en `coderag_mcp/config.py`.

Preguntale algo sobre cualquier repo público de GitHub/GitLab (lo indexa en
el primer uso):

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/pypa/sampleproject", "question": "What does this project do, and where is the package version defined?"}'
```

`POST /ask/stream` recibe el mismo body y devuelve la misma respuesta, pero
como Server-Sent Events (`data: <json>\n\n`) transmitiendo el progreso en
vivo del orquestador a medida que sucede — estado del indexado, cada
llamada a herramienta y su resultado, y la respuesta token por token — en
vez de esperar una única respuesta final.

El resto de la configuración (`CODERAG_PUBLIC_HOST`,
`CODERAG_SQLITE_DB_PATH`, `CODERAG_ALLOWED_HOSTS`, etc.) es opcional y tiene
valores por defecto razonables — ver `coderag_mcp/config.py`. Notar el
prefijo `CODERAG_`: cada setting salvo `VOYAGE_API_KEY` solo se lee de su
variable de entorno con prefijo `CODERAG_`, así una variable genérica como
`ALLOWED_HOSTS` (común en plataformas PaaS) no puede sobreescribirla por
accidente.

## Frontend (opcional)

Un frontend React local que muestra en vivo las llamadas a herramientas y
la respuesta del orquestador mientras trabaja — ver
[`frontend/README.md`](frontend/README.md) para el setup. No es necesario
para usar la API REST o MCP directamente.

## Auth

Si `CODERAG_API_KEY` está seteada, `/ask`, `/ask/stream`, y `/mcp` requieren
un header `X-API-Key` que coincida — los requests sin ese header (o con el
valor incorrecto) reciben un 401. Si `CODERAG_API_KEY` no está seteada (el
default), la autenticación está deshabilitada y se acepta cualquier
request.

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: tu-secreto-elegido" \
  -d '{"repo_url": "https://github.com/owner/repo", "question": "How does X work?"}'
```

## Servidor MCP

Un servidor MCP (transporte Streamable HTTP) está montado en `/mcp/` en la
misma app corriendo (`/mcp` sin la barra final redirige con 307 a `/mcp/`;
los clientes MCP siguen redirects automáticamente), sujeto al mismo
requisito de `X-API-Key` descripto arriba. Expone:

- `ping` — chequeo de salud trivial.
- `index_repo(repo_url)` — clona, chunkea, genera embeddings, y guarda un
  repo público de GitHub/GitLab (idempotente por URL; no hace nada si ya
  está indexado).
- `search_code(repo_url, query, top_k=5)` — búsqueda semántica sobre los
  chunks de código indexados de un repo, indexándolo primero si es la
  primera llamada.
- `ask_repo(repo_url, question)` — responde una pregunta sobre un repo
  usando el mismo agente único que usa `POST /ask`, indexándolo primero si
  hace falta.

### Usarlo como servidor MCP en Claude Code

Con el servidor corriendo (ver Quickstart arriba):

```bash
claude mcp add --transport http coderag http://localhost:8000/mcp/
```

Si `CODERAG_API_KEY` está seteada, pasala como header:

```bash
claude mcp add --transport http coderag http://localhost:8000/mcp/ \
  --header "X-Api-Key: tu-secreto-elegido"
```

Verificá que se conectó: `claude mcp list` debería mostrar `coderag` como
`✔ Connected`. Claude Code ya puede llamar a `index_repo`, `search_code`, y
`ask_repo` directamente.

## Tests

```bash
./.venv/bin/pytest -v
```
