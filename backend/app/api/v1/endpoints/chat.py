"""
Chat Sessions API — persistent conversation history for the Supplier AI Assistant.
Supports creating, listing, loading, renaming, and deleting chat sessions,
as well as sending messages within a session (with AI response persistence).
"""

import logging
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, func, desc

from app.core.database import get_db
from app.models.models import ChatSession, ChatMessage, Supplier
from app.schemas.schemas import APIResponse
from app.agent.graph import procurement_workflow

logger = logging.getLogger("chat_api")

router = APIRouter()


class CreateSessionRequest(BaseModel):
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    title: Optional[str] = None


class SendMessageRequest(BaseModel):
    message: str
    supplier_id: Optional[str] = None


class RenameSessionRequest(BaseModel):
    title: str


@router.get("/sessions", response_model=APIResponse)
async def list_sessions(
    supplier_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List all chat sessions, optionally filtered by supplier_id, ordered by most recent."""
    stmt = select(ChatSession).order_by(desc(ChatSession.updated_at))
    if supplier_id:
        stmt = stmt.where(ChatSession.supplier_id == supplier_id)

    result = await db.execute(stmt)
    sessions = result.scalars().all()

    data = [
        {
            "session_id": s.session_id,
            "supplier_id": s.supplier_id,
            "supplier_name": s.supplier_name,
            "title": s.title,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            "is_active": s.is_active,
            "message_count": s.message_count,
        }
        for s in sessions
    ]
    return APIResponse(status="success", data=data)


@router.post("/sessions", response_model=APIResponse)
async def create_session(
    req: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat session."""
    session = ChatSession(
        supplier_id=req.supplier_id,
        supplier_name=req.supplier_name,
        title=req.title or "New Chat",
        is_active=True,
        message_count=0,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return APIResponse(
        status="success",
        data={
            "session_id": session.session_id,
            "supplier_id": session.supplier_id,
            "supplier_name": session.supplier_name,
            "title": session.title,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "is_active": session.is_active,
            "message_count": session.message_count,
        },
        message="Chat session created",
    )


@router.get("/sessions/{session_id}/messages", response_model=APIResponse)
async def get_session_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Load all messages for a chat session."""
    # Verify session exists
    session = (
        await db.execute(select(ChatSession).where(ChatSession.session_id == session_id))
    ).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    data = {
        "session": {
            "session_id": session.session_id,
            "supplier_id": session.supplier_id,
            "supplier_name": session.supplier_name,
            "title": session.title,
        },
        "messages": [
            {
                "message_id": m.message_id,
                "role": m.role,
                "content": m.content,
                "key_findings": m.key_findings,
                "evidence": m.evidence,
                "suggested_actions": m.suggested_actions,
                "timestamp": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }
    return APIResponse(status="success", data=data)


@router.post("/sessions/{session_id}/messages", response_model=APIResponse)
async def send_message(
    session_id: str,
    req: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a user message, get AI response, persist both.
    Includes conversation history context for multi-turn coherence.
    """
    # Verify session exists
    session = (
        await db.execute(select(ChatSession).where(ChatSession.session_id == session_id))
    ).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    # 1. Resolve supplier_id dynamically
    supplier_id = req.supplier_id or session.supplier_id

    # If supplier_id not set, check if user message mentions any supplier in the database
    all_suppliers_res = await db.execute(select(Supplier))
    all_suppliers = all_suppliers_res.scalars().all()

    if not supplier_id and all_suppliers:
        msg_lower = req.message.lower()
        matched_sup = None
        for sup in all_suppliers:
            if sup.supplier_id.lower() in msg_lower or sup.supplier_name.lower() in msg_lower:
                matched_sup = sup
                break
            name_words = [
                w for w in sup.supplier_name.lower().replace(",", "").replace(".", "").split()
                if len(w) > 3 and w not in ("ltd", "inc", "corp", "corporation", "company", "supplies", "components", "solutions", "products", "manufacturing")
            ]
            if any(w in msg_lower for w in name_words):
                matched_sup = sup
                break

        if matched_sup:
            supplier_id = matched_sup.supplier_id
            session.supplier_id = matched_sup.supplier_id
            session.supplier_name = matched_sup.supplier_name
        else:
            # A contract answer must never be silently grounded in an unrelated
            # supplier's agreement. The UI asks the user to select a supplier.
            raise HTTPException(
                status_code=400,
                detail="Select a supplier or name one in the message before asking a contract question.",
            )
    elif supplier_id and not session.supplier_name and all_suppliers:
        for sup in all_suppliers:
            if sup.supplier_id == supplier_id:
                session.supplier_name = sup.supplier_name
                break

    # Save user message
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=req.message,
    )
    db.add(user_msg)

    # Load recent conversation history for context (last 10 messages)
    history_stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(10)
    )
    history_result = await db.execute(history_stmt)
    history_msgs = list(reversed(history_result.scalars().all()))

    # Build conversation context string for LLM synthesis (clean, turn-based)
    conversation_context = ""
    if history_msgs:
        context_parts = []
        for hm in history_msgs[-8:]:  # Last 8 messages for context window
            role_label = "User" if hm.role == "user" else "Assistant"
            context_parts.append(f"{role_label}: {hm.content}")
        conversation_context = "\n".join(context_parts)

    # Get AI response via existing procurement workflow with clean query and separated conversation history
    try:
        result = await procurement_workflow.execute(
            supplier_id=supplier_id,
            task_type="general_assistant",
            user_query=req.message,
            conversation_history=conversation_context,
            db=db,
        )

        ai_content = result.get("analysis_summary", "I could not process your request. Please try again.")
        key_findings = result.get("key_findings", [])
        evidence = result.get("contract_evidence", [])
        suggested_actions = result.get("suggested_actions", [])
    except Exception as e:
        logger.exception("AI assistant query failed")
        ai_content = "I encountered an error while processing your request. Please try again."
        key_findings = []
        evidence = []
        suggested_actions = []

    # Save assistant message
    assistant_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=ai_content,
        key_findings=key_findings,
        evidence=evidence,
        suggested_actions=suggested_actions,
    )
    db.add(assistant_msg)

    # Update session title (auto-title from first user message) and timestamp
    if session.message_count == 0 or session.title == "New Chat":
        # Auto-generate title from first message
        title = req.message[:60].strip()
        if len(req.message) > 60:
            title += "..."
        session.title = title

    session.message_count = (session.message_count or 0) + 2
    session.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(assistant_msg)

    return APIResponse(
        status="success",
        data={
            "role": "assistant",
            "content": ai_content,
            "keyFindings": key_findings,
            "evidence": evidence,
            "suggestedActions": suggested_actions,
            "timestamp": assistant_msg.created_at.isoformat() if assistant_msg.created_at else datetime.utcnow().isoformat(),
            "session_id": session_id,
            "session_title": session.title,
            "supplier_id": session.supplier_id,
            "supplier_name": session.supplier_name,
        },
    )


@router.patch("/sessions/{session_id}", response_model=APIResponse)
async def rename_session(
    session_id: str,
    req: RenameSessionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Rename a chat session."""
    session = (
        await db.execute(select(ChatSession).where(ChatSession.session_id == session_id))
    ).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    session.title = req.title
    session.updated_at = datetime.utcnow()
    await db.commit()

    return APIResponse(status="success", data={"session_id": session_id, "title": req.title})


@router.delete("/sessions/{session_id}", response_model=APIResponse)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a chat session and all its messages."""
    session = (
        await db.execute(select(ChatSession).where(ChatSession.session_id == session_id))
    ).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    # Delete messages first
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    # Delete session
    await db.delete(session)
    await db.commit()

    return APIResponse(status="success", data={"session_id": session_id}, message="Chat session deleted")
