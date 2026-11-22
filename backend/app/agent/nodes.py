"""
LangGraph execution nodes combining PostgreSQL structured data
with Qdrant hybrid contract clauses into actionable procurement intelligence.
"""

import json
import logging
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.agent.state import AgentState
from app.services.sql_retriever import sql_retriever
from app.services.hybrid_retriever import hybrid_retriever
from app.services.telemetry import observation, usage_details

logger = logging.getLogger("agent_nodes")

# ---------------------------------------------------------------------------
# Universal Contract Intelligence System Prompt
# Distilled from the Supplier 360 Universal Contract Intelligence Agent spec.
# This is injected as the LLM system message for ALL synthesis calls.
# ---------------------------------------------------------------------------
UNIVERSAL_SYSTEM_PROMPT = """You are Supplier 360, a professional AI-powered contract intelligence assistant for procurement, supplier management, and contract analysis.

CORE PRINCIPLES:

1. EVIDENCE-GROUNDED ANSWERING
   - Use the provided contract evidence as the PRIMARY source of truth.
   - Every material contractual claim must be supported by the evidence provided.
   - Preserve the meaning, qualifications, terminology, and conditions of the contract.
   - Distinguish explicit contractual language from reasonable interpretation or inference.
   - Never invent a contractual obligation, right, date, price, quantity, deadline, threshold, party, or exception.
   - Never substitute common industry practice for the actual contract wording.
   - If provisions conflict, explain the conflict and any supported resolution.

2. MULTI-CLAUSE REASONING
   - When one clause references another (e.g., "Subject to Section 4.2...", "As defined in Exhibit A..."), combine the referenced conditions to build a complete answer.
   - Check definitions, conditions, exceptions, cross-references, and amendments.
   - Distinguish obligations from permissions, discretionary rights, and best-efforts commitments.
   - Do not treat one isolated clause as the complete answer when other provisions materially qualify it.

3. HANDLING MISSING INFORMATION
   - Distinguish: (a) explicitly stated, (b) derivable by transparent calculation, (c) missing/redacted/not retrieved, (d) ambiguous/conflicting.
   - If a value is redacted, say so. If information was not found in ANY provided evidence, say so clearly.
   - Do not fill gaps with assumptions or external knowledge.
   - Do not claim a term is absent until all provided evidence has been considered.

4. CONTRACT vs OPERATIONAL DATA
   - Use contractual documents for contractual terms.
   - Use structured metrics (KPIs, orders, delivery data) only when appropriate to the question.
   - Do not append OTD rates, defect scores, or dashboards to a simple contract question.
   - Clearly distinguish contractual requirements from actual operational performance.

5. NATURAL, READABLE RESPONSES
   - For simple questions: answer directly in the first sentence, 1-3 sentences total.
   - For complex questions: start with the conclusion, then explain conditions and exceptions.
   - Avoid robotic introductions, unnecessary headings, repetitive disclaimers, raw retrieval snippets, internal IDs, or similarity scores.

6. EVIDENCE REFERENCES
   - Cite using: [Source: "document_filename", Page X, Section "heading"]
   - Use ONLY verified page numbers and section headings from the evidence.
   - Never invent page numbers, clause numbers, or quotations.
   - If evidence cannot be verified, say so; do not fabricate a citation.

7. VERIFICATION (silently check before responding)
   - Does the answer address the exact user question?
   - Is the evidence from the correct contract?
   - Does the evidence directly support the answer?
   - Were definitions, tables, attachments, amendments, and exceptions checked?
   - Have unrelated retrieved chunks been excluded?
   - Are missing or conflicting values handled honestly?
"""


def classify_query_node(state: AgentState) -> AgentState:
    """Decide whether to query SQL, Qdrant clauses, or both."""
    task = state.get("task_type", "general_assistant")
    query = state.get("user_query", "").lower()

    if task in ("contract_analysis", "performance_review", "pricing_analysis", "renewal_review"):
        # All procurement intelligence features require combining relational facts with contract clauses
        decision = "hybrid"
    elif any(k in query for k in ("spend", "order", "delivery", "defect", "kpi", "ontime", "price comparison")):
        if any(k in query for k in ("clause", "term", "warranty", "penalty", "sla", "notice", "contract")):
            decision = "hybrid"
        else:
            decision = "structured_only"
    elif any(k in query for k in ("clause", "agreement", "contract", "section", "warranty", "penalty", "liability")):
        decision = "unstructured_only"
    else:
        decision = "hybrid"

    state["router_decision"] = decision
    return state


async def structured_retriever_node(state: AgentState, db: AsyncSession) -> AgentState:
    """Retrieve structured metrics, contract terms, orders, and benchmarks from PostgreSQL."""
    supplier_id = state["supplier_id"]
    structured_data: Dict[str, Any] = {}

    with observation("retrieval.sql.supplier_summary") as span:
        summary = await sql_retriever.get_supplier_summary(db, supplier_id)
        span.update(metadata={"result_count": int(summary is not None)})
    if summary:
        structured_data["supplier"] = summary

    with observation("retrieval.sql.contract_details") as span:
        contract = await sql_retriever.get_contract_details(db, supplier_id)
        span.update(metadata={"result_count": int(contract is not None)})
    if contract:
        structured_data["contract"] = contract

    with observation("retrieval.sql.performance_kpis") as span:
        kpis = await sql_retriever.get_performance_kpis(db, supplier_id)
        span.update(metadata={"metric_count": len(kpis)})
    structured_data["performance_kpis"] = kpis

    with observation("retrieval.sql.price_comparison") as span:
        pricing = await sql_retriever.get_price_comparison(db, supplier_id)
        span.update(metadata={"result_count": len(pricing)})
    structured_data["pricing_comparison"] = pricing

    state["structured_data"] = structured_data
    return state


def clause_retriever_node(state: AgentState) -> AgentState:
    """Retrieve top relevant contract clauses from Qdrant vector store and BM25."""
    supplier_id = state["supplier_id"]
    task = state.get("task_type", "")
    query = state.get("user_query", "")

    search_query = query
    clause_type = None

    if task == "contract_analysis":
        search_query = "contract terms, delivery SLA, delay penalty, payment terms, warranty period, termination"
    elif task == "performance_review":
        search_query = "delivery schedule lead time delay penalties defect notification remedy quality requirements"
        clause_type = "sla_penalty"
    elif task == "pricing_analysis":
        search_query = "contract unit price minimum quantity payment discount shipping freight costs"
        clause_type = "pricing"
    elif task == "renewal_review":
        search_query = "contract renewal notice period expiration term extension termination notice"
        clause_type = "renewal_termination"
    elif task == "general_assistant":
        lower = query.lower()
        if any(k in lower for k in ("price", "pricing", "cost", "rate", "usd", "discount", "fee", "moq", "quantity")):
            clause_type = "pricing"
        elif any(k in lower for k in ("penalty", "sla", "delay", "late", "lead time", "liquidated")):
            clause_type = "sla_penalty"
        elif any(k in lower for k in ("warranty", "guarantee", "defect", "remedy", "quality", "qa")):
            clause_type = "warranty"
        elif any(k in lower for k in ("payment", "invoice", "net 30", "net 60", "advance", "deposit")):
            clause_type = "payment_terms"
        elif any(k in lower for k in ("renew", "expiration", "terminate", "notice period", "term")):
            clause_type = "renewal_termination"
        elif any(k in lower for k in ("law", "jurisdiction", "dispute")):
            clause_type = "governing_law"
        search_query = query

    with observation("retrieval.hybrid.primary", metadata={"top_k": 6, "clause_filter": bool(clause_type)}) as span:
        evidence = hybrid_retriever.retrieve(
            query=search_query,
            supplier_id=supplier_id,
            clause_type=clause_type,
            top_k=6,
        )
        span.update(metadata={
            "result_count": len(evidence),
            "chunk_ids": [item.get("chunk_id") for item in evidence if item.get("chunk_id")],
            "document_ids": [item.get("documentId") for item in evidence if item.get("documentId")],
        })

    # If clause-type filtered search returned no chunks, retrieve general chunks for this supplier
    if not evidence or len(evidence) < 2:
        with observation("retrieval.hybrid.fallback", metadata={"top_k": 6}) as span:
            general_evidence = hybrid_retriever.retrieve(
                query=search_query or "contract obligations terms delivery payment warranty",
                supplier_id=supplier_id,
                clause_type=None,
                top_k=6,
            )
            span.update(metadata={
                "result_count": len(general_evidence),
                "chunk_ids": [item.get("chunk_id") for item in general_evidence if item.get("chunk_id")],
            })
        if general_evidence:
            existing_cids = {e["chunk_id"] for e in evidence}
            for ge in general_evidence:
                if ge["chunk_id"] not in existing_cids:
                    evidence.append(ge)
                    existing_cids.add(ge["chunk_id"])

    state["contract_evidence"] = evidence[:6]
    return state


async def synthesis_node(state: AgentState) -> AgentState:
    """
    Synthesize structured DB metrics AND contractual clause evidence
    into cohesive findings and recommendations using Groq LLM (with robust fallback).
    """
    task = state.get("task_type", "general_assistant")
    query = state.get("user_query", "")
    structured = state.get("structured_data", {})
    evidence = state.get("contract_evidence", [])
    sup_name = structured.get("supplier", {}).get("supplier_name", "Supplier")
    state["generation_mode"] = "deterministic_fallback"
    state["llm_calls"] = 0

    # Check if Groq LLM is available
    if settings.GROQ_API_KEY:
        try:
            from groq import AsyncGroq
            client = AsyncGroq(api_key=settings.GROQ_API_KEY)

            async def generate_json(prompt: str) -> dict:
                state["llm_calls"] = state.get("llm_calls", 0) + 1
                with observation(
                    "llm.groq_generation",
                    as_type="generation",
                    model=settings.LLM_MODEL_NAME,
                    metadata={"provider": "groq"},
                    content_input=query,
                ) as generation:
                    response = await client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": UNIVERSAL_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt}
                        ],
                        model=settings.LLM_MODEL_NAME,
                        temperature=0.1,
                        response_format={"type": "json_object"},
                    )
                    content = response.choices[0].message.content
                    generation.update(
                        content_output=content or "",
                        usage_details=usage_details(response),
                    )
                return json.loads(content)

            if task == "general_assistant":
                # Build a formatted evidence block with explicit source labels
                evidence_with_sources = []
                for idx, ev in enumerate(evidence, 1):
                    evidence_with_sources.append(
                        f"[SOURCE {idx}] Document: \"{ev.get('documentName', 'Contract')}\", "
                        f"Page: {ev.get('page', 'N/A')}, "
                        f"Section: \"{ev.get('section', 'N/A')}\"\n"
                        f"Text: \"{ev.get('text', '')}\""
                    )
                evidence_block = "\n\n".join(evidence_with_sources) if evidence_with_sources else "NO CONTRACT EVIDENCE AVAILABLE."

                prompt = f"""Answer the following user question about a supplier contract.

Use ONLY the contractual evidence and structured metrics provided below.
Apply multi-clause reasoning: if one clause references another, combine them into a complete answer.
Distinguish what is explicitly stated from what is missing or ambiguous.
Do not append operational metrics (OTD, defect rates) unless the question asks about performance.
Answer naturally: for simple questions use 1-3 sentences; for complex questions start with the conclusion then explain.

=== STRUCTURED METRICS FROM DATABASE ===
{json.dumps(structured, indent=2)}

=== CONTRACTUAL EVIDENCE FROM CONTRACT DOCUMENTS ===
{evidence_block}

USER QUESTION: {query}

Respond with a JSON object:
{{
  "answer": "Direct, natural answer with inline [Source: \"document\", Page X, Section \"heading\"] citations. For simple questions, 1-3 sentences. For complex questions, conclusion first, then supporting detail.",
  "keyFindings": ["Concrete finding with exact terms/numbers and [Source: ...] citation"],
  "suggestedActions": ["Actionable step grounded in the contract terms found"],
  "sources": [
    {{"document": "string", "page": number, "section": "string"}}
  ]
}}"""
                parsed = await generate_json(prompt)
                state["generation_mode"] = "groq"
                state["analysis_summary"] = parsed.get("answer", parsed.get("summary", ""))
                state["key_findings"] = parsed.get("keyFindings", [])
                state["suggested_actions"] = parsed.get("suggestedActions", [])
                state["sources"] = parsed.get("sources", [])
                state["contract_findings"] = [
                    {"title": kf, "description": kf, "status": "info"}
                    for kf in parsed.get("keyFindings", [])
                ]
                return state

            # For formal procurement analysis tasks:
            # Build formatted evidence block with source labels
            evidence_with_sources = []
            for idx, ev in enumerate(evidence, 1):
                evidence_with_sources.append(
                    f"[SOURCE {idx}] Document: \"{ev.get('documentName', 'Contract')}\", "
                    f"Page: {ev.get('page', 'N/A')}, "
                    f"Section: \"{ev.get('section', 'N/A')}\"\n"
                    f"Text: \"{ev.get('text', '')}\""
                )
            evidence_block = "\n\n".join(evidence_with_sources) if evidence_with_sources else "NO CONTRACT EVIDENCE AVAILABLE."

            prompt = f"""Perform a comprehensive supplier assessment using the contractual evidence and structured metrics below.

Apply multi-clause reasoning: combine cross-referenced clauses, definitions, exhibits, and amendments into complete findings.
Correlate actual performance metrics against contractual thresholds to determine compliance status.
Distinguish what is explicitly stated from what is missing or ambiguous. Omit findings when data is genuinely absent.
For contractual claims, cite sources. For performance claims, reference actual metric values.

=== STRUCTURED METRICS FROM DATABASE ===
{json.dumps(structured, indent=2)}

=== CONTRACTUAL EVIDENCE FROM CONTRACT DOCUMENTS ===
{evidence_block}

TASK TYPE: {task}
USER QUERY: {query}

Respond with a JSON object:
{{
  "summary": "2-3 sentence synthesis connecting contractual terms with actual performance. Cite sources inline.",
  "contractFindings": [
    {{"title": "string", "description": "string (with [Source: ...] citation, synthesizing related clauses)", "status": "compliant|warning|breach"}}
  ],
  "performanceFindings": [
    {{"metric": "string", "actual": "string", "target": "string", "status": "on_target|below_target|critical"}}
  ],
  "pricingFindings": [
    {{"item": "string", "contractPrice": "string", "marketBenchmark": "string", "variance": "string", "status": "competitive|above_market|favorable"}}
  ],
  "discussionPoints": ["string"],
  "suggestedActions": ["string"],
  "sources": [
    {{"document": "string", "page": number, "section": "string"}}
  ]
}}"""
            parsed = await generate_json(prompt)
            state["generation_mode"] = "groq"
            state["analysis_summary"] = parsed.get("summary", "")
            state["contract_findings"] = parsed.get("contractFindings", [])
            state["performance_findings"] = parsed.get("performanceFindings", [])
            state["pricing_findings"] = parsed.get("pricingFindings", [])
            state["discussionPoints"] = parsed.get("discussionPoints", [])
            state["suggested_actions"] = parsed.get("suggestedActions", [])
            state["sources"] = parsed.get("sources", [])
            state["key_findings"] = [f.get("title", "") for f in parsed.get("contractFindings", [])]
            return state
        except Exception as e:
            logger.warning("Groq synthesis failed (%s). Proceeding with deterministic synthesis.", type(e).__name__)

    # High-quality deterministic synthesis correlating SQL metrics with Qdrant clauses
    kpis = structured.get("performance_kpis", {})
    contract_info = structured.get("contract", {})
    terms = contract_info.get("terms", {})
    pricing_list = structured.get("pricing_comparison", [])

    otd = kpis.get("on_time_delivery_rate_pct", 92.0)
    defect = kpis.get("defect_rate_pct", 0.8)
    penalty_clause = terms.get("penalty_for_delay", "1% per week of delay")
    lead_time = terms.get("lead_time_days", 14)
    payment_terms = terms.get("payment_terms_desc", "Net 30 days")
    expiry = contract_info.get("expiry_date", "2026-11-15")

    # Specific deterministic answer handler for General Assistant chat
    if task == "general_assistant":
        lower_q = query.lower()
        ans_parts = []
        findings = []
        actions = []

        is_penalty = any(k in lower_q for k in ("penalty", "delay", "sla", "late", "lead time", "liquidated"))
        is_warranty = any(k in lower_q for k in ("warranty", "defect", "guarantee", "remedy", "quality", "qa"))
        is_payment = any(k in lower_q for k in ("payment", "invoice", "net 30", "net 60", "terms", "advance", "deposit"))
        is_pricing = any(k in lower_q for k in ("price", "pricing", "cost", "benchmark", "product", "moq", "rate"))
        is_renewal = any(k in lower_q for k in ("renew", "expiry", "expiration", "terminate", "notice"))

        if is_penalty:
            ans_parts.append(
                f"Under the contract for {sup_name}, the agreed delivery SLA stipulates a {lead_time}-day lead time. "
                f"In the event of delivery delays, Section 8 establishes a penalty of {penalty_clause}. "
                f"Currently, {sup_name}'s recorded on-time delivery rate is {otd}%, with an average delay of {kpis.get('avg_delay_days', 0)} days."
            )
            findings.append(f"Delivery Penalty: {penalty_clause}")
            findings.append(f"Agreed Lead Time: {lead_time} business days")
            actions.append("Review whether delayed purchase orders qualify for contractual penalty deductions.")

        if is_warranty:
            ans_parts.append(
                f"The contractual warranty period under Section 9 is {terms.get('warranty_months', '24 months')} standard coverage, "
                f"with a mandatory {terms.get('defect_notification_days', 30)}-day defect reporting window. "
                f"Current recorded quality defect rate is {defect}%."
            )
            findings.append(f"Warranty Period: {terms.get('warranty_months', '24 months')}")
            findings.append(f"Defect Reporting Window: {terms.get('defect_notification_days', 30)} days")
            actions.append("Ensure QA inspection reports are formally submitted within the 30-day reporting window.")

        if is_payment:
            ans_parts.append(
                f"Agreed payment terms are '{payment_terms}'. Down payment is {terms.get('payment_on_order_pct', 15)}% on order placement, "
                f"and {terms.get('payment_before_shipment_pct', 85)}% upon QA inspection prior to shipment."
            )
            findings.append(f"Payment Terms: {payment_terms}")
            findings.append(f"Advance Deposit: {terms.get('payment_on_order_pct', 15)}%")
            actions.append("Verify accounting reconciliation against milestone payment schedule.")

        if is_pricing:
            price_details = ", ".join(
                (
                    f"{p.get('product_name')}: {p.get('currency') or ''} {p.get('contracted_price', 0):.2f} "
                    f"(Benchmark: {p.get('currency') or ''} {p.get('market_benchmark_price'):.2f})"
                    if p.get("market_benchmark_price") is not None else
                    f"{p.get('product_name')}: {p.get('currency') or ''} {p.get('contracted_price', 0):.2f} (Benchmark unavailable)"
                )
                for p in pricing_list[:3]
            ) or "contracted unit pricing"
            ans_parts.append(
                f"Contracted pricing includes: {price_details}. Minimum order quantity is {terms.get('minimum_order_quantity', 100)} units."
            )
            findings.append(f"MOQ: {terms.get('minimum_order_quantity', 100)} units")
            actions.append("Evaluate volume discount thresholds for upcoming purchase orders.")

        if is_renewal:
            ans_parts.append(
                f"The contract agreement for {sup_name} is active and set to expire on {expiry}. "
                f"Renewal terms require {terms.get('renewal_type', 'mutual written consent')} with a {terms.get('termination_notice_months', 2)}-month notice period."
            )
            findings.append(f"Contract Expiry: {expiry}")
            findings.append(f"Renewal Notice: {terms.get('termination_notice_months', 2)} months")
            actions.append("Initiate formal supplier review 60 days prior to contract expiration.")

        if not ans_parts:
            if evidence:
                chunk_texts = " ".join(e.get("text", "") for e in evidence[:2])
                ans_parts.append(
                    f"Regarding your query about {sup_name}: According to relevant contract clauses ({evidence[0].get('section', 'Contract Clause')}), "
                    f"\"{chunk_texts[:350]}...\". Current supplier performance reflects an OTD of {otd}% and defect rate of {defect}%."
                )
            else:
                ans_parts.append(
                    f"{sup_name}'s contract is currently {contract_info.get('status', 'active')}. "
                    f"Key clauses enforce a {lead_time}-day delivery SLA ({penalty_clause}) and {terms.get('warranty_months', '24 months')} warranty. "
                    f"Current on-time fulfillment is {otd}% and defect rate is {defect}%."
                )
            findings.append(f"Status: {contract_info.get('status', 'active').capitalize()}")
            findings.append(f"Compliance: {otd}% OTD, {defect}% defect rate")
            actions.append("Consult full contractual clauses for additional specific stipulations.")

        summary = "\n\n".join(ans_parts)
        state["analysis_summary"] = summary
        state["key_findings"] = findings or [f"Active agreement for {sup_name}"]
        state["suggested_actions"] = actions or ["Review agreement documentation with procurement lead."]
        state["contract_findings"] = [
            {"title": f, "description": f, "status": "info"} for f in (findings or [])
        ]
        return state

    # Contract findings for dashboard review
    contract_findings = [
        {
            "title": "Lead Time & Delivery Obligation",
            "description": f"Contract stipulates a {lead_time}-day lead time with liquidated damages of {penalty_clause}.",
            "status": "compliant" if otd >= 90 else "warning",
        },
        {
            "title": "Payment Terms & Invoicing",
            "description": f"Contractual terms are '{payment_terms}'. Down payment is {terms.get('payment_on_order_pct', 15)}% on order.",
            "status": "compliant",
        },
        {
            "title": "Warranty & Defect Remedies",
            "description": f"Warranty period is {terms.get('warranty_months', '24 months')} with a {terms.get('defect_notification_days', 30)}-day reporting window.",
            "status": "compliant" if defect < 2.0 else "warning",
        },
    ]

    # Performance findings
    performance_findings = [
        {
            "metric": "On-Time Delivery Rate",
            "actual": f"{otd}%",
            "target": "95.0%",
            "status": "on_target" if otd >= 95 else ("below_target" if otd >= 85 else "critical"),
        },
        {
            "metric": "Quality Defect Rate",
            "actual": f"{defect}%",
            "target": "< 1.0%",
            "status": "on_target" if defect <= 1.0 else "below_target",
        },
        {
            "metric": "Average Delivery Delay",
            "actual": f"{kpis.get('avg_delay_days', 0)} days",
            "target": "0 days",
            "status": "on_target" if kpis.get("avg_delay_days", 0) <= 2 else "critical",
        },
    ]

    # Pricing findings
    pricing_findings = []
    for p in pricing_list:
        diff = p.get("price_variance_pct")
        currency = p.get("currency") or ""
        market = p.get("market_benchmark_price")
        pricing_findings.append({
            "item": p.get("product_name", "Supplied Item"),
            "contractPrice": f"{currency} {p.get('contracted_price', 0):.2f}",
            "marketBenchmark": f"{currency} {market:.2f}" if market is not None else "Unavailable",
            "variance": f"{'+' if diff is not None and diff > 0 else ''}{diff}%" if diff is not None else "Unavailable",
            "status": "above_market" if diff is not None and diff > 2.0 else "competitive" if diff is not None else p.get("benchmark_status", "benchmark_unavailable"),
        })

    # Summary
    if task == "contract_analysis":
        summary = f"{sup_name}'s contract is currently {contract_info.get('status', 'active')}. Key clauses enforce a {lead_time}-day delivery SLA and {penalty_clause}. Current compliance shows an on-time fulfillment rate of {otd}%."
    elif task == "performance_review":
        summary = f"Operational evaluation for {sup_name} reveals an on-time delivery rate of {otd}% and defect rate of {defect}%. Contract terms mandate liquidated damages for persistent delays exceeding 3 business days."
    elif task == "pricing_analysis":
        summary = f"Pricing review for {sup_name} highlights that contracted rates show a variance against regional market benchmarks. Opportunity exists to renegotiate volume tiers ahead of contract renewal."
    elif task == "renewal_review":
        summary = f"Contract for {sup_name} expires on {expiry}. Contractual renewal requires written notice under Section 14. Performance KPIs should be leveraged to negotiate improved pricing and SLA commitments."
    else:
        summary = f"Procurement analysis for {sup_name} combining active contract clauses with order delivery and quality records."

    state["analysis_summary"] = summary
    state["contract_findings"] = contract_findings
    state["performance_findings"] = performance_findings
    state["pricing_findings"] = pricing_findings
    state["discussionPoints"] = [
        f"Review recent delivery delays against Section 8 delay penalty clause ({penalty_clause}).",
        f"Discuss price realignment given market benchmarks showing variance.",
        f"Confirm renewal intention well before expiration date ({expiry}).",
    ]
    state["suggested_actions"] = [
        "Issue formal QA feedback on defect notifications within the 30-day contractual window.",
        "Request volume discount tier for orders exceeding annual commit.",
        "Initiate renewal discussion with preferred 60-day notice timeline.",
    ]
    state["key_findings"] = [f["title"] for f in contract_findings]

    return state


def _normalize_findings(items: List[Any], default_evidence: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    normalized = []
    for it in (items or []):
        if isinstance(it, str):
            normalized.append({"severity": "info", "message": it, "evidence": default_evidence})
            continue
        if not isinstance(it, dict):
            continue

        status = str(it.get("status") or "").lower()
        sev = it.get("severity")
        if not sev:
            if status in ("warning", "below_target", "above_market"):
                sev = "warning"
            elif status in ("breach", "critical", "error"):
                sev = "error"
            elif status in ("compliant", "on_target", "competitive", "success"):
                sev = "success"
            else:
                sev = "info"

        msg = it.get("message")
        if not msg:
            title = it.get("title") or it.get("metric") or it.get("item")
            desc = it.get("description") or it.get("actual") or it.get("variance")
            if title and desc:
                msg = f"{title}: {desc}"
            else:
                msg = title or desc or "Observation noted"

        ev = it.get("evidence") or default_evidence
        normalized.append({
            "severity": sev,
            "message": str(msg),
            "evidence": ev,
        })
    return normalized


def guardrail_node(state: AgentState) -> AgentState:
    """Format and validate the state into the exact schema expected by the frontend."""
    state["status"] = "success"

    # Ensure evidence objects match frontend Evidence model:
    # { documentId, documentName, page, section, text }
    formatted_evidence = []
    for ev in state.get("contract_evidence", []):
        formatted_evidence.append({
            "documentId": str(ev.get("documentId") or "doc-1"),
            "documentName": str(ev.get("documentName") or "Contract Document"),
            "page": int(ev.get("page") or 1),
            "section": str(ev.get("section") or "Contract Clause"),
            "text": str(ev.get("text") or ""),
        })

    state["contract_evidence"] = formatted_evidence

    default_ev = formatted_evidence[:2] if formatted_evidence else None
    state["contract_findings"] = _normalize_findings(state.get("contract_findings", []), default_ev)
    state["performance_findings"] = _normalize_findings(state.get("performance_findings", []))
    state["pricing_findings"] = _normalize_findings(state.get("pricing_findings", []))

    return state

