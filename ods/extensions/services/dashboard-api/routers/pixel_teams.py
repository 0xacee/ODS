"""Owner-authenticated agent teams using the existing retained Pixel transport."""
import asyncio
import json
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from security import verify_api_key
from pixel_chat_results import owner_namespace
from pixel_agent_teams import TeamManager, TeamStore, TeamConflict
from routers import pixel

router = APIRouter(prefix="/api/pixel/agents", tags=["pixel"])
_manager = None


class TeamStart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chat_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    task: str = Field(min_length=1, max_length=8000)
    count: int | None = Field(default=None, ge=1, le=6)
    context: str = Field(default="", max_length=1800)
    mode: Literal['team', 'goal'] = 'team'


class TeamList(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chat_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


class TeamIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    team_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class TeamAnswer(TeamIdentity):
    agent_id: str = Field(pattern=r"^[0-5]$")
    answers: dict[str, str] = Field(min_length=1, max_length=3)


class TeamRetry(TeamIdentity):
    agent_id: str = Field(pattern=r"^[0-5]$")


class _Subscription:
    async def is_disconnected(self):
        return False


async def _run(owner, agent):
    # Internal team receipts use a separate namespace, never a credential or a
    # browser-supplied child session ID. Normal runtime policy still applies.
    # A healthy gateway alone does not prove the selected inference backend is
    # alive. Check before every worker, including read-only recovery attempts.
    for attempt in range(3):
        if agent.get('stop_requested'):
            yield {'_done':True,'_state':'cancelled'}
            return
        host_status=await pixel._host_model_status()
        issue=pixel._model_readiness_issue_from_status(host_status) or await pixel._local_inference_issue(host_status)
        if issue is None:
            break
        yield {'runtime_wait':True}
        if attempt==2:
            yield {'error':{'code':'model_unavailable'}}
            yield {'_done':True,'_state':'interrupted'}
            return
        await asyncio.sleep(2 ** attempt)
    yield {'runtime_wait':False}
    if agent.get('stop_requested'):
        yield {'_done':True,'_state':'cancelled'}
        return
    body = pixel.ChatStreamRequest(chat_id=agent["chat_id"], request_id=agent["request_id"], messages=agent["messages"])
    response = await pixel._retained_chat_stream(_Subscription(), body, owner)
    buffered = ""
    async for chunk in response.body_iterator:
        buffered += chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
        while "\n" in buffered:
            line, buffered = buffered.split("\n", 1)
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                continue
            value = json.loads(raw)
            if isinstance(value, dict):
                yield value
    identity = (owner_namespace(owner), agent["chat_id"], agent["request_id"])
    row = pixel._result_state(pixel._chat_results(), identity)
    yield {"_done": True, "_state": row["state"] if row else "unknown"}


async def _cancel(owner, agent):
    identity = (owner_namespace(owner), agent["chat_id"], agent["request_id"])
    row = pixel._result_state(pixel._chat_results(), identity)
    if row is None or row["state"] in {"complete", "cancelled"}:
        return True
    if row["state"] == "interrupted":
        activity = await pixel.pixel_chat_activity(pixel.ChatCancelRequest(chat_id=agent["chat_id"]))
        if activity["state"] == "terminal":
            return True
        result = await pixel.pixel_chat_cancel(pixel.ChatCancelRequest(chat_id=agent["chat_id"]), owner)
        return result["aborted"]
    result = await pixel.pixel_chat_cancel(pixel.ChatCancelRequest(chat_id=agent["chat_id"], request_id=agent["request_id"]), owner)
    if result["aborted"]:
        return True
    activity = await pixel.pixel_chat_activity(pixel.ChatCancelRequest(chat_id=agent["chat_id"]))
    return activity["state"] == "terminal"


def manager():
    global _manager
    if _manager is None:
        _manager = TeamManager(TeamStore(Path(os.environ.get("ODS_DATA_DIR", "/data")) / "pixel-agent-teams"), _run, _cancel)
    return _manager


@router.post("/start")
async def start(body: TeamStart, owner: str = Depends(verify_api_key)):
    if not body.task.strip():
        raise HTTPException(422, "Describe the team's task")
    if pixel._pixel_config() is None:
        raise HTTPException(503, "Portal is not enabled")
    try:
        return manager().start(owner_namespace(owner), body.chat_id, body.request_id, body.task.strip(), body.count, body.context, body.mode)
    except TeamConflict as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/list")
async def listing(body: TeamList, owner: str = Depends(verify_api_key)):
    return {"teams": manager().list(owner_namespace(owner), body.chat_id)}


@router.post("/stop")
async def stop(body: TeamIdentity, owner: str = Depends(verify_api_key)):
    result = await manager().stop(owner_namespace(owner), body.team_id)
    if result is None:
        raise HTTPException(404, "Team not found")
    return result


@router.post("/answer")
async def answer(body: TeamAnswer, owner: str = Depends(verify_api_key)):
    try:
        result = manager().answer(owner_namespace(owner), body.team_id, body.agent_id, body.answers)
    except TeamConflict as exc:
        raise HTTPException(409, str(exc)) from None
    if result is None:
        raise HTTPException(404, "Team not found")
    return result


@router.post('/retry')
async def retry(body: TeamRetry, owner: str = Depends(verify_api_key)):
    try:
        result = manager().retry(owner_namespace(owner), body.team_id, body.agent_id)
    except TeamConflict as exc:
        raise HTTPException(409,str(exc)) from None
    if result is None:
        raise HTTPException(404,'Team not found')
    return result
