"""
AI Analysis and Supplier Assistant API endpoints.
Connects directly to the LangGraph procurement workflow combining
structured PostgreSQL data with hybrid Qdrant contract evidence.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from fastapi import APIRouter, Depends, Body, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.schemas import APIResponse
from app.agent.graph import procurement_workflow
from app.services.telemetry import current_request_id

router = APIRouter()


class AnalysisRequest(BaseModel):
    supplier_id: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    supplierId: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    analysis_type: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    analysisType: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class AssistantMessageRequest(BaseModel):
    supplier_id: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    supplierId: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    session_id: Optional[str] = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    sessionId: Optional[str] = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def message_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must contain non-whitespace text.")
        return value


@router.post("/run", response_model=APIResponse)
@router.post("/{analysis_type}", response_model=APIResponse)
async def run_supplier_analysis(
    req: AnalysisRequest,
    response: Response,
    analysis_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Executes LangGraph agent workflow for contract, performance, pricing, or renewal analysis.
    Combines SQL relational facts with Qdrant vector evidence.
    """
    supplier_id = req.supplierId or req.supplier_id or "SUP-001"
    task = req.analysisType or req.analysis_type or analysis_type or "contract_analysis"

    result = await procurement_workflow.execute(
        supplier_id=supplier_id,
        task_type=task,
        user_query=f"Perform complete {task} evaluating supplier obligations and actual execution",
        db=db,
    )

    data = {
        "supplierId": supplier_id,
        "analysisType": task,
        "summary": result.get("analysis_summary", ""),
        "contractFindings": result.get("contract_findings", []),
        "performanceFindings": result.get("performance_findings", []),
        "pricingFindings": result.get("pricing_findings", []),
        "discussionPoints": result.get("discussionPoints", []),
        "evidence": result.get("contract_evidence", []),
        "generatedAt": datetime.now().isoformat(),
    }
    trace_id = result.get("trace_id")
    if trace_id:
        response.headers["X-Trace-ID"] = trace_id
    return APIResponse(status="success", data=data, request_id=current_request_id(), trace_id=trace_id)


@router.post("/assistant/query", response_model=APIResponse)
async def query_supplier_assistant(
    req: AssistantMessageRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Supplier AI Assistant interactive query.
    Extracts answers grounded in both SQL tables and contract evidence.
    """
    supplier_id = req.supplierId or req.supplier_id or "SUP-001"
    message = req.message

    result = await procurement_workflow.execute(
        supplier_id=supplier_id,
        task_type="general_assistant",
        user_query=message,
        db=db,
        session_id=req.sessionId or req.session_id,
        trace_metadata={
            "supplier_id": supplier_id,
            "api_route": "/analysis/assistant/query",
        },
    )

    data = {
        "role": "assistant",
        "content": result.get("analysis_summary", ""),
        "keyFindings": result.get("key_findings", []),
        "evidence": result.get("contract_evidence", []),
        "suggestedActions": result.get("suggested_actions", []),
        "timestamp": datetime.now().isoformat(),
    }
    trace_id = result.get("trace_id")
    if trace_id:
        response.headers["X-Trace-ID"] = trace_id
    return APIResponse(status="success", data=data, request_id=current_request_id(), trace_id=trace_id)
