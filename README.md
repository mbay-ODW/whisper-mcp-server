# whisper-mcp-server

> MCP-Server für den selbst gehosteten [whisper-service](https://github.com/mbay-ODW/whisper-service). Liest und manipuliert Transkriptions-Jobs aus Claude.ai / Claude Desktop / Claude Cowork.

## Warum

Aus Claude-Cowork-Sandboxen erreichst du `*.bay-ram.de` nicht direkt — die Bash-Egress-Regeln blocken alles außer GitHub und Paket-Registries. Der MCP-Kanal (Claude → Anthropic Gateway → MCP-Server) läuft jedoch außerhalb der Sandbox, dadurch funktioniert dieser Server problemlos.

## Tools

| Tool | Zweck |
|---|---|
| `whisper_list_jobs` | Recent Jobs mit Status, Dateiname, Dauer |
| `whisper_get_job` | Voll-Details inkl. Transkript + Segmente |
| `whisper_get_transcript_text` | Nur reiner Text (für LLM-Kontext) |
| `whisper_search_transcripts` | Substring-Suche über alle fertigen Transkripte |
| `whisper_transcribe_from_url` | Audio von HTTPS-URL pullen → transkribieren lassen |
| `whisper_cancel_job` · `whisper_retry_job` · `whisper_delete_job` | Job-Lifecycle |
| `whisper_list_models` | Verfügbare Whisper-Modelle |

## Auth (identisch zu hero-mcp / paperless-mcp / …)

1. **Statischer Bearer** (`MCP_API_KEY`) — für Claude Desktop / direkte Clients
2. **JWT via Authelia OIDC Introspection** — für Claude.ai

## Deploy

```bash
docker compose up -d
```

Env-Vars siehe [.env.example](./.env.example).

Traefik-Routing wird über einen File-Provider gesetzt (`whisper-mcp.bay-ram.de`).

## Local dev

```bash
pip install -e .
MCP_TRANSPORT=stdio WHISPER_URL=https://whisper.example.com \
  WHISPER_BEARER=… whisper-mcp-server
```
