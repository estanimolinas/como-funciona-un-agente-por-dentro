# coderag-mcp frontend

A local-only React+Vite+TypeScript UI for coderag-mcp, showing a live
"x-ray" of the orchestrator's tool calls, tool results, and streamed
answer as it works.

## Prerequisites

Node 20.19+ or 22.12+ (required by `vite`'s `engines` field).

The backend must already be running on `http://localhost:8000` (see the
root `README.md`'s Quickstart — `uvicorn coderag_mcp.api.main:app`).

## Setup

```bash
cd frontend
npm install
npm run dev
```

Open the printed local URL (typically `http://localhost:5173`). The dev
server proxies `/ask` and `/ask/stream` requests to the backend, so no
CORS configuration is needed.

If the backend has `CODERAG_API_KEY` set, click "Add API key (optional)"
on the form and paste it in — it's saved to your browser's local storage
so you don't need to re-enter it each time.

## Testing

```bash
npm test
```
