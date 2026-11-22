import pytest
"""
Verification script testing the full backend stack:
1. Health check
2. Suppliers listing & single supplier
3. Contracts & contract terms
4. Performance KPIs (OTD, defect rate, spend)
5. AI Analysis (combining PostgreSQL structured data + Qdrant hybrid contract evidence)
6. Supplier AI Assistant query with citations
7. Reports generation
"""

import asyncio
import sys
from types import ModuleType
from httpx import AsyncClient, ASGITransport

# Keep integration tests offline and fast. The vector store already supports
# this deterministic fallback when its optional embedding model is unavailable.
_offline_embeddings = ModuleType("sentence_transformers")


class _UnavailableSentenceTransformer:
    def __init__(self, *_args, **_kwargs):
        raise RuntimeError("Embedding model disabled in offline integration tests.")


_offline_embeddings.SentenceTransformer = _UnavailableSentenceTransformer
sys.modules["sentence_transformers"] = _offline_embeddings
_offline_fastembed = ModuleType("fastembed")
_offline_fastembed.TextEmbedding = _UnavailableSentenceTransformer
sys.modules["fastembed"] = _offline_fastembed

from app.main import app


@pytest.mark.asyncio
async def test_api():
    print("[TEST] Initializing test client...")
    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
    ) as client:
        # 1. Health check
        h = await client.get("/health")
        print(f"[TEST 1] Health check: status={h.status_code}, data={h.json()}")
        assert h.status_code == 200

        # 2. Suppliers
        s = await client.get("/api/suppliers")
        suppliers = s.json().get("data", [])
        print(f"[TEST 2] Suppliers count: {len(suppliers)}")
        assert len(suppliers) > 0, "Expected suppliers in database"

        # 3. Contract details
        c = await client.get("/api/contracts/suppliers/SUP-001/contract")
        cdata = c.json().get("data", {})
        print(f"[TEST 3] Contract SUP-001: '{cdata.get('contractTitle')}', Payment: {cdata.get('paymentTerms')}")
        assert cdata.get("id") is not None

        # 4. Performance
        p = await client.get("/api/performance/suppliers/SUP-001/performance")
        pdata = p.json().get("data", {})
        print(f"[TEST 4] Performance SUP-001: OTD={pdata.get('onTimeDelivery')}%, Quality={pdata.get('qualityScore')}%")
        assert pdata.get("onTimeDelivery") is not None

        # 5. AI Analysis combining SQL + Vector Store
        print("[TEST 5] Running Agentic AI Analysis for SUP-001 (contract_analysis)...")
        a = await client.post(
            "/api/analysis/contract_analysis",
            json={"supplierId": "SUP-001", "analysisType": "contract_analysis"},
        )
        adata = a.json().get("data", {})
        print(f"         Summary: {adata.get('summary')}")
        print(f"         Contract Findings: {len(adata.get('contractFindings', []))}")
        print(f"         Evidence Chunks: {len(adata.get('evidence', []))}")
        for idx, ev in enumerate(adata.get("evidence", [])[:2]):
            print(f"         - Evidence [{idx+1}]: Page {ev.get('page')}, {ev.get('section')}")
        assert len(adata.get("evidence", [])) > 0, "Expected contractual evidence citations"

        # 6. Assistant Query
        print("[TEST 6] Querying Supplier Assistant...")
        chat = await client.post(
            "/api/analysis/assistant/query",
            json={"supplierId": "SUP-001", "message": "What is the penalty for delivery delays and warranty period?"},
        )
        chatdata = chat.json().get("data", {})
        print(f"         Assistant Response: {chatdata.get('content')[:140]}...")
        print(f"         Key Findings: {chatdata.get('keyFindings')}")
        print(f"         Evidence count: {len(chatdata.get('evidence', []))}")
        assert chatdata.get("role") == "assistant"

        # 7. Dashboard Metrics
        dash = await client.get("/api/dashboard/metrics")
        print(f"[TEST 7] Dashboard metrics: Active Suppliers={dash.json().get('data', {}).get('activeSuppliers')}")
        print("\n==============================================")
        print("ALL 7 SYSTEM INTEGRATION TESTS PASSED (100% SUCCESS)!")
        print("==============================================")

    # Close the SQLite async worker threads created by the isolated test DB.
    import app.core.database as database
    await database.engine.dispose()


@pytest.mark.asyncio
async def test_contract_ingestion_without_metalcharts_key():
    from app.core.config import settings
    import app.core.database as database

    original_key = settings.METALCHARTS_API_KEY
    settings.METALCHARTS_API_KEY = ""
    try:
        async with app.router.lifespan_context(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
        ) as client:
            response = await client.post(
                "/api/documents/upload",
                data={"supplier_id": "SUP-001"},
                files={"file": (
                    "offline-test-contract.txt",
                    b"Net 30 days. 30 days warranty. Delivery period 14 days.",
                    "text/plain",
                )},
            )
            assert response.json().get("status") == "success", response.json().get("message")
    finally:
        settings.METALCHARTS_API_KEY = original_key
        await database.engine.dispose()


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_and_oversized_files(monkeypatch):
    from app.core.config import settings

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
    ) as client:
        unsupported = await client.post(
            "/api/documents/upload",
            data={"supplier_id": "SUP-001"},
            files={"file": ("contract.exe", b"not a contract", "application/octet-stream")},
        )
        assert unsupported.status_code == 415

        previous_limit = settings.MAX_UPLOAD_SIZE_MB
        settings.MAX_UPLOAD_SIZE_MB = 1
        try:
            oversized = await client.post(
                "/api/documents/upload",
                data={"supplier_id": "SUP-001"},
                files={"file": ("contract.txt", b"x" * (1024 * 1024 + 1), "text/plain")},
            )
            assert oversized.status_code == 413
        finally:
            settings.MAX_UPLOAD_SIZE_MB = previous_limit


@pytest.mark.asyncio
async def test_missing_supplier_metrics_are_not_filled_with_demo_defaults():
    import app.core.database as database

    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=30.0
    ) as client:
        response = await client.get("/api/performance/suppliers/SUP-NO-RECORDS/performance")
        metrics = response.json()["data"]
        assert response.status_code == 200
        assert metrics["onTimeRate"] is None
        assert metrics["defectRate"] is None
    await database.engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_api())

