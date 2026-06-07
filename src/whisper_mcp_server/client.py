"""Whisper-Service-Client — reine HTTP-Calls gegen die REST-API."""

import os
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

WHISPER_URL = os.getenv("WHISPER_URL", "").rstrip("/")
WHISPER_BEARER = os.getenv("WHISPER_BEARER", "")


def _check_config() -> None:
    if not WHISPER_URL or not WHISPER_BEARER:
        raise RuntimeError(
            "WHISPER_URL und WHISPER_BEARER müssen gesetzt sein. "
            "Token im Web-UI unter 'App-Tokens' erstellen."
        )


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {WHISPER_BEARER}",
        "Accept": "application/json",
    }


async def list_jobs(limit: int | None = None) -> list[dict[str, Any]]:
    _check_config()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{WHISPER_URL}/api/jobs", headers=_headers())
        resp.raise_for_status()
        jobs = resp.json()
    if limit:
        jobs = jobs[:limit]
    return jobs


async def get_job(job_id: str) -> dict[str, Any]:
    _check_config()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{WHISPER_URL}/api/jobs/{job_id}", headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def cancel_job(job_id: str) -> dict[str, Any]:
    _check_config()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{WHISPER_URL}/api/jobs/{job_id}/cancel", headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()


async def retry_job(job_id: str) -> dict[str, Any]:
    _check_config()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{WHISPER_URL}/api/jobs/{job_id}/retry", headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()


async def delete_job(job_id: str) -> dict[str, Any]:
    _check_config()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(
            f"{WHISPER_URL}/api/jobs/{job_id}/delete", headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()


async def list_models() -> dict[str, Any]:
    _check_config()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{WHISPER_URL}/api/models", headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def transcribe_from_url(
    url: str,
    model: str | None = None,
    initial_prompt: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Lädt eine Audio-Datei von einer beliebigen HTTP(S)-URL, schickt sie an
    den Whisper-Service und gibt die Job-ID zurück.

    Cowork-Workaround: aus der Sandbox erreichst du GitHub aber nicht
    bay-ram.de. Lade eine Datei in einen Gist/Release, gib die URL hier
    rein — der MCP-Server (der bay-ram.de erreicht) zieht die Datei und
    pusht sie weiter.
    """
    _check_config()
    # Filename aus URL ableiten, falls nicht angegeben
    if not filename:
        from urllib.parse import urlparse, unquote
        path = urlparse(url).path
        filename = unquote(path.rsplit("/", 1)[-1]) or "audio.bin"

    async with httpx.AsyncClient(timeout=300) as client:
        # 1) Datei pullen
        get = await client.get(url, follow_redirects=True)
        get.raise_for_status()
        audio_bytes = get.content
        content_type = get.headers.get("content-type", "application/octet-stream")

        # 2) An whisper-service weiterreichen
        form: dict[str, Any] = {}
        if model:
            form["model"] = model
        if initial_prompt:
            form["initial_prompt"] = initial_prompt
        files = {"file": (filename, audio_bytes, content_type)}
        post = await client.post(
            f"{WHISPER_URL}/api/transcribe",
            headers=_headers(),
            data=form,
            files=files,
        )
        post.raise_for_status()
        return post.json()


async def search_transcripts(
    query: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Naive Volltextsuche über alle Done-Jobs.

    Wir holen die Job-Liste, ziehen für die done-Jobs jeweils das Transkript
    und filtern lokal nach `query` (case-insensitive substring).
    """
    _check_config()
    q = query.lower().strip()
    if not q:
        return []

    async with httpx.AsyncClient(timeout=60) as client:
        # Job-Liste
        resp = await client.get(f"{WHISPER_URL}/api/jobs", headers=_headers())
        resp.raise_for_status()
        jobs = [j for j in resp.json() if j.get("status") == "done"]

        hits: list[dict[str, Any]] = []
        for job in jobs:
            if len(hits) >= limit:
                break
            detail_resp = await client.get(
                f"{WHISPER_URL}/api/jobs/{job['id']}", headers=_headers()
            )
            if detail_resp.status_code != 200:
                continue
            detail = detail_resp.json()
            text = (detail.get("full_text") or "").lower()
            if q in text:
                # Snippet um den Treffer extrahieren
                idx = text.find(q)
                start = max(0, idx - 80)
                end = min(len(text), idx + len(q) + 80)
                snippet = (detail.get("full_text") or "")[start:end]
                hits.append(
                    {
                        "id": detail["id"],
                        "filename": detail.get("filename"),
                        "created_at": detail.get("created_at"),
                        "duration": detail.get("duration"),
                        "snippet": ("…" if start > 0 else "")
                        + snippet
                        + ("…" if end < len(text) else ""),
                    }
                )
        return hits
