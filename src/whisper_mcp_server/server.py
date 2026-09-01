"""Whisper MCP Server — MCP-Tools für den selbst gehosteten Whisper-Service.

Auth-Architektur (identisch zu hero-mcp):
  1. Statischer Bearer (MCP_API_KEY) → Claude Desktop / direkte API-Clients
  2. Bearer JWT → Authelia OIDC Introspection → Claude.ai
"""

import json
import logging
import os
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)

from . import client  # noqa: E402

server = Server(
    "whisper-mcp-server",
    instructions=(
        "MCP-Server für den selbst gehosteten Whisper-Transkriptions-Service.\n\n"
        "Use cases:\n"
        "- Recent Jobs auflisten / Status prüfen → whisper_list_jobs\n"
        "- Transkript-Text fürs LLM-Kontextfenster holen → whisper_get_transcript_text\n"
        "- Inhaltliche Suche über alle Done-Jobs → whisper_search_transcripts\n"
        "- Audio von HTTPS-URL transkribieren lassen (GitHub-Gist, Release, …)"
        " → whisper_transcribe_from_url. So funktioniert Upload aus Cowork-Sandbox,"
        " die nur GitHub erreicht: Audio auf GitHub legen, URL übergeben.\n"
        "- Jobs verwalten: cancel / retry / delete."
    ),
)


# ---------------------------------------------------------------------------
# Tool-Definitionen
# ---------------------------------------------------------------------------


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="whisper_list_jobs",
            description=(
                "Listet die letzten Transkriptions-Jobs (neueste zuerst) mit Status, "
                "Dateiname, Dauer und Modell. Optional Anzahl begrenzen."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "Maximalanzahl Jobs (Default 20)",
                    }
                },
            },
        ),
        types.Tool(
            name="whisper_get_job",
            description=(
                "Vollständige Details zu einem Job inkl. Transkript-Text und "
                "Zeitstempel-Segmenten."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "UUID des Jobs"}
                },
                "required": ["job_id"],
            },
        ),
        types.Tool(
            name="whisper_get_transcript_text",
            description=(
                "Liefert NUR den reinen Transkript-Text eines Jobs ohne Meta — "
                "optimal um ihn in den LLM-Kontext zu laden."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "UUID des Jobs"}
                },
                "required": ["job_id"],
            },
        ),
        types.Tool(
            name="whisper_search_transcripts",
            description=(
                "Sucht (case-insensitive Substring) über alle fertigen Transkripte. "
                "Gibt Treffer mit Snippet zurück. Geeignet zum Auffinden bestimmter "
                "Notizen, Themen oder Stichwörter."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff (Substring, case-insensitive)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "Maximalanzahl Treffer (Default 20)",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="whisper_transcribe_from_url",
            description=(
                "Lädt eine Audio-Datei von einer HTTPS-URL und schickt sie an "
                "den Whisper-Service. Gibt die Job-ID zurück — danach mit "
                "whisper_get_job auf Status pollen.\n\n"
                "Workflow für Claude-Cowork-Sandbox: Audio in einen GitHub-Gist "
                "oder ein Release uploaden (das geht aus der Sandbox), dann hier "
                "die Raw-URL einsetzen. Der MCP-Server pullt die Datei und "
                "reicht sie an whisper-service durch."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Direkter HTTPS-Download-Link zur Audio-Datei",
                    },
                    "model": {
                        "type": "string",
                        "description": (
                            "Whisper-Modell (z.B. large-v3, medium, small, base). "
                            "Default = Server-Default."
                        ),
                    },
                    "initial_prompt": {
                        "type": "string",
                        "description": "Optionales Fachvokabular für bessere Erkennung",
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "Optionaler Dateiname (sonst aus URL abgeleitet). "
                            "Endung sollte zum Audio-Format passen: "
                            "m4a, mp3, wav, ogg, flac, webm, mp4."
                        ),
                    },
                },
                "required": ["url"],
            },
        ),
        types.Tool(
            name="whisper_cancel_job",
            description="Bricht einen laufenden oder wartenden Job ab.",
            inputSchema={
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        ),
        types.Tool(
            name="whisper_retry_job",
            description="Startet einen fehlgeschlagenen oder abgebrochenen Job neu.",
            inputSchema={
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        ),
        types.Tool(
            name="whisper_delete_job",
            description="Löscht einen Job permanent (inkl. Audiodatei falls noch vorhanden).",
            inputSchema={
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        ),
        types.Tool(
            name="whisper_list_models",
            description=(
                "Liefert die Liste der verfügbaren Whisper-Modelle "
                "(built-in + Custom-HuggingFace) plus das Default-Modell."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# ---------------------------------------------------------------------------
# Tool-Handler
# ---------------------------------------------------------------------------


@server.call_tool()
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent]:
    try:
        result = await _dispatch(name, arguments or {})
    except Exception as exc:
        result = {"error": str(exc), "tool": name}
    return [
        types.TextContent(
            type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
        )
    ]


async def _dispatch(name: str, args: dict[str, Any]) -> Any:
    if name == "whisper_list_jobs":
        return await client.list_jobs(limit=args.get("limit"))
    if name == "whisper_get_job":
        return await client.get_job(args["job_id"])
    if name == "whisper_get_transcript_text":
        job = await client.get_job(args["job_id"])
        return {
            "id": job.get("id"),
            "filename": job.get("filename"),
            "duration": job.get("duration"),
            "language": job.get("language"),
            "text": job.get("full_text") or "",
        }
    if name == "whisper_search_transcripts":
        return await client.search_transcripts(
            args["query"], limit=args.get("limit", 20)
        )
    if name == "whisper_transcribe_from_url":
        return await client.transcribe_from_url(
            url=args["url"],
            model=args.get("model"),
            initial_prompt=args.get("initial_prompt"),
            filename=args.get("filename"),
        )
    if name == "whisper_cancel_job":
        return await client.cancel_job(args["job_id"])
    if name == "whisper_retry_job":
        return await client.retry_job(args["job_id"])
    if name == "whisper_delete_job":
        return await client.delete_job(args["job_id"])
    if name == "whisper_list_models":
        return await client.list_models()
    raise ValueError(f"Unbekanntes Tool: {name}")


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------


def main() -> None:
    import asyncio

    if os.getenv("MCP_TRANSPORT", "stdio") == "sse":
        _run_sse()
    else:
        asyncio.run(mcp.server.stdio.run_server(server))


def _run_sse() -> None:
    """SSE + Streamable-HTTP transport mit Dual-Auth (statisch + OIDC)."""
    import contextlib
    from collections.abc import AsyncIterator

    import httpx as _httpx
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.routing import Mount, Route

    mcp_api_key = os.getenv("MCP_API_KEY", "")
    oidc_introspection_url = os.getenv("OIDC_INTROSPECTION_URL", "")
    oidc_client_id = os.getenv("OIDC_CLIENT_ID", "")
    oidc_client_secret = os.getenv("OIDC_CLIENT_SECRET", "")

    # Refuse to start rather than serve everything unauthenticated: an empty
    # MCP_API_KEY is the image default, so a forgotten env var used to be enough to
    # open the server to anyone. Failing loudly at startup is the only variant of
    # this that cannot go unnoticed.
    if not mcp_api_key and not all(
        (oidc_introspection_url, oidc_client_id, oidc_client_secret)
    ):
        raise RuntimeError(
            "[auth] Neither MCP_API_KEY nor a complete OIDC triple "
            "(OIDC_INTROSPECTION_URL + OIDC_CLIENT_ID + OIDC_CLIENT_SECRET) is set. "
            "Refusing to start."
        )

    async def _is_authorized(request: Request) -> tuple[bool, str | None]:
        auth = request.headers.get("Authorization", "")
        if not auth:
            return False, "no_header"

        # 1. Statischer Bearer (Claude Desktop)
        if mcp_api_key and auth == f"Bearer {mcp_api_key}":
            return True, None

        if not auth.startswith("Bearer "):
            return False, "invalid_token"

        # 2. JWT via Authelia OIDC Introspection (Claude.ai)
        if oidc_introspection_url and oidc_client_id and oidc_client_secret:
            jwt_token = auth[7:]
            try:
                async with _httpx.AsyncClient() as http:
                    resp = await http.post(
                        oidc_introspection_url,
                        data={"token": jwt_token},
                        auth=(oidc_client_id, oidc_client_secret),
                        timeout=5.0,
                    )
                    data = resp.json()
                    if data.get("active", False):
                        return True, None
                    return False, "invalid_token"
            except Exception as e:
                logging.error("Introspection fehlgeschlagen: %s", e)
                return False, "invalid_token"
        return False, "invalid_token"

    def _unauthorized(reason: str | None) -> Response:
        """RFC-6750-konformes 401 (siehe hero-mcp Erklärung)."""
        if reason == "invalid_token":
            www = (
                'Bearer realm="whisper-mcp", error="invalid_token", '
                'error_description="The access token expired or is invalid"'
            )
            return Response(
                "Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": www},
            )
        return Response("Unauthorized", status_code=401)

    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        ok, reason = await _is_authorized(request)
        if not ok:
            return _unauthorized(reason)
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )
        return Response()

    async def handle_messages(scope, receive, send):
        """The /messages/ endpoint carries the client's JSON-RPC calls for an SSE
        session, so it needs the same check as every other route -- mounting
        SseServerTransport.handle_post_message directly bypasses _is_authorized."""
        req = Request(scope, receive=receive)
        ok, reason = await _is_authorized(req)
        if not ok:
            await _unauthorized(reason)(scope, receive, send)
            return
        await sse.handle_post_message(scope, receive, send)

    class _AlreadySent(Response):
        def __init__(self) -> None:
            super().__init__(content=b"", status_code=200)

        async def __call__(self, scope, receive, send):  # noqa: D401
            return

    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
    )

    async def handle_streamable_http(request: Request):
        ok, reason = await _is_authorized(request)
        if not ok:
            return _unauthorized(reason)
        await session_manager.handle_request(
            request.scope, request.receive, request._send
        )
        return _AlreadySent()

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            logging.info("StreamableHTTPSessionManager started")
            yield
            logging.info("StreamableHTTPSessionManager stopping")

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_streamable_http, methods=["POST"]),
            Route("/mcp", endpoint=handle_streamable_http, methods=["POST"]),
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=handle_messages),
        ],
        lifespan=lifespan,
    )

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
