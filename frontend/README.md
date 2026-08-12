# AgentTrace

Una UI local en React+Vite+TypeScript para AgentTrace, que muestra en vivo
una "radiografía" de las llamadas a herramientas, sus resultados, y la
respuesta del orquestador mientras trabaja.

## Requisitos

Node 20.19+ o 22.12+ (requerido por el campo `engines` de `vite`).

El backend tiene que estar corriendo en `http://localhost:8000` (ver el
Quickstart del `README.md` raíz — `uvicorn coderag_mcp.api.main:app`).

## Setup

```bash
cd frontend
npm install
npm run dev
```

Abrí la URL local que imprime (típicamente `http://localhost:5173`). El
servidor de desarrollo hace proxy de `/ask` y `/ask/stream` hacia el
backend, así que no hace falta configurar CORS.

Si el backend tiene `CODERAG_API_KEY` seteada, hacé click en "Agregar API
key (opcional)" en el formulario y pegala ahí — se guarda en el
localStorage del navegador para no tener que reingresarla cada vez.

## Tests

```bash
npm test
```
