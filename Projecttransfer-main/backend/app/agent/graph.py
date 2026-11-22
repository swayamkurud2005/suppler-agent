"""
LangGraph procurement workflow graph assembling the classification,
retrieval, synthesis, and guardrail nodes.
"""

import logging
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.agent.state import AgentState
from app.agent.nodes import (
    classify_query_node,
    structured_retriever_node,
    clause_retriever_node,
    synthesis_node,
    guardrail_node,
)
from app.services.telemetry import observation, request_trace

logger = logging.getLogger("agent_graph")


class ProcurementWorkflow:
    """Executes the stateful multi-step procurement workflow."""

    async def execute(
        self,
        supplier_id: str,
        task_type: str,
        user_query: str,
        db: AsyncSession,
        trace_metadata: Dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> Dict[str, Any]:
        """Run all workflow nodes with error resilience."""
        state: AgentState = {
            "supplier_id": supplier_id,
            "task_type": task_type,
            "user_query": user_query,
            "structured_data": {},
            "contract_evidence": [],
            "status": "processing",
        }

        # This workflow is currently a direct sequence of Python nodes, so each
        # existing stage is traced explicitly without changing its execution order.
        with request_trace(
            "supplier360.procurement_request",
            content_input=user_query,
            metadata={"task_type": task_type, **(trace_metadata or {})},
            session_id=session_id,
            as_type="agent",
        ) as trace:
            with observation("agent.classify_route", as_type="chain", metadata={"task_type": task_type}):
                state = classify_query_node(state)

            with observation("retrieval.structured_sql", as_type="retriever", metadata={"retriever": "sql"}):
                state = await structured_retriever_node(state, db)

            with observation(
                "retrieval.contract_hybrid",
                as_type="retriever",
                metadata={"retriever": "dense_bm25_rrf", "top_k": 6},
            ):
                state = clause_retriever_node(state)

            with observation(
                "agent.answer_generation",
                metadata={"configured_model": settings.LLM_MODEL_NAME},
            ):
                state = await synthesis_node(state)

            with observation("agent.guardrail_normalization", as_type="guardrail"):
                state = guardrail_node(state)

            evidence = state.get("contract_evidence", [])
            trace.update(
                content_output=state.get("analysis_summary", ""),
                metadata={
                    "generation_mode": state.get("generation_mode", "deterministic_fallback"),
                    "model_name": settings.LLM_MODEL_NAME if state.get("generation_mode") == "groq" else None,
                    "llm_calls": state.get("llm_calls", 0),
                    "tool_calls": 0,
                    "retrieved_chunk_count": len(evidence),
                    "chunk_ids": [item.get("chunk_id") for item in evidence if item.get("chunk_id")],
                    "document_ids": [item.get("documentId") for item in evidence if item.get("documentId")],
                    "reranker_used": False,
                    "agent_steps": ["classify_route", "structured_sql", "contract_hybrid", "answer_generation", "guardrail_normalization"],
                    "status": state.get("status", "success"),
                },
            )
            state["trace_id"] = trace.trace_id

        return state


procurement_workflow = ProcurementWorkflow()
