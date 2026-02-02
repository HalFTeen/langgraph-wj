from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException

from examples.agent_system.gateway.discord_bot import DiscordConfig, DiscordGateway
from examples.agent_system.gateway.models import ApprovalRecord, ApprovalRequest, ApprovalResolution
from examples.agent_system.gateway.state_store import ApprovalStore
from examples.agent_system.graph import build_checkpointed_graph, build_initial_state
from langgraph.checkpoint.sqlite import SqliteSaver

app = FastAPI()

approval_store = ApprovalStore.empty()


def _get_discord_gateway() -> DiscordGateway:
    token = os.getenv("DISCORD_TOKEN", "")
    channel_id = os.getenv("DISCORD_CHANNEL_ID", "")
    return DiscordGateway(DiscordConfig(token=token, channel_id=channel_id))


@app.post("/approval/request", response_model=ApprovalRecord)
def request_approval(payload: ApprovalRequest) -> ApprovalRecord:
    record = approval_store.create(payload)
    discord = _get_discord_gateway()
    if discord.config.token and discord.config.channel_id:
        discord.post_approval_request(payload.thread_id, payload.summary)
    return record


@app.post("/approval/resolve", response_model=ApprovalRecord)
def resolve_approval(payload: ApprovalResolution) -> ApprovalRecord:
    record = approval_store.get(payload.thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail="approval not found")

    status = payload.decision
    updated = approval_store.resolve(
        payload.thread_id,
        status=status,
        reviewer=payload.reviewer,
        reason=payload.reason,
    )

    with SqliteSaver.from_conn_string(":memory:") as checkpointer:
        run = build_checkpointed_graph(
            checkpointer=checkpointer, interrupt_before=["executor"]
        )
        graph = run.graph
        config = run.config
        graph.invoke(build_initial_state(), config)
        graph.update_state(config, {"approval_status": status})
        graph.invoke(None, config)

    return updated
