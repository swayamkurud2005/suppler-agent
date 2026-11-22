"""
End-to-end integration tests for:
1. Persistent Chat Sessions & Chat History (/api/chat/sessions, /api/chat/sessions/{id}/messages)
2. Available documents listing (/api/suppliers/available-documents)
3. Extraction from already-uploaded/existing contracts without re-uploading (/api/suppliers/extract-from-existing)
"""

import asyncio
import os
import sys

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import ensure_active_engine, async_session_factory
from app.db.seed import init_tables
from app.services.supplier_extractor import supplier_extractor
from app.models.models import ChatSession, ChatMessage, Contract, Supplier
from sqlalchemy import select, delete


async def run_all_tests():
    print("=" * 60)
    print("RUNNING CHAT HISTORY & AUTO-EXTRACT INTEGRATION TESTS")
    print("=" * 60)

    # Step 1: Ensure DB tables exist
    await ensure_active_engine()
    await init_tables()
    print("✅ Step 1: Database initialized and tables verified.")

    async with async_session_factory() as db:
        # Step 2: Test Available Documents
        docs = await supplier_extractor.get_available_documents(db)
        print(f"✅ Step 2: Found {len(docs)} available documents in system.")
        assert len(docs) > 0, "Expected at least one available contract document"
        first_doc = docs[0]
        print(f"   Sample document: {first_doc['filename']} ({first_doc['displayName']})")

        # Step 3: Test Extract from Existing Document without re-uploading
        print("✅ Step 3: Testing extraction from existing document...")
        extracted = await supplier_extractor.extract_from_existing_document(
            db=db,
            document_name=first_doc['filename'],
            contract_id=first_doc.get('contractId'),
        )
        assert extracted is not None, "Extraction result was None"
        assert "supplier_name" in extracted, "Missing supplier_name in extraction"
        assert extracted.get("is_existing_document") is True, "Expected is_existing_document=True"
        print(f"   Extracted Supplier: {extracted['supplier_name']['value']} (Confidence: {extracted['supplier_name']['confidence']})")
        print(f"   Category: {extracted['category']['value']}")
        print(f"   Location: {extracted['location']['value']}")
        print(f"   Evidence Source: {extracted['supplier_name']['source']}")

        # Step 4: Test Chat Sessions Persistence
        print("✅ Step 4: Testing Chat Session creation & message persistence...")
        # Clean test sessions
        await db.execute(delete(ChatSession).where(ChatSession.title.ilike("%TEST_SESSION%")))
        await db.commit()

        # Create new chat session
        test_session = ChatSession(
            supplier_id="SUP-001",
            supplier_name="ABC Components",
            title="TEST_SESSION_Contract_Query",
            is_active=True,
            message_count=0,
        )
        db.add(test_session)
        await db.commit()
        await db.refresh(test_session)
        sid = test_session.session_id
        print(f"   Created session: {sid} (Title: {test_session.title})")

        # Save user message
        msg1 = ChatMessage(
            session_id=sid,
            role="user",
            content="What are the agreed payment terms and penalty clauses for ABC Components?",
        )
        db.add(msg1)

        # Save assistant message with evidence
        msg2 = ChatMessage(
            session_id=sid,
            role="assistant",
            content="According to the contract for ABC Components, the payment terms are Net 30 days with a 15% advance deposit. Delivery delay incurs a 1% per week penalty.",
            key_findings=["Payment Terms: Net 30 days", "Delay Penalty: 1% per week"],
            evidence=[{"documentName": "Supply Agreement.pdf", "page": 4, "section": "Section 8 - Payment & Penalties"}],
            suggested_actions=["Review PO delivery dates against contractual SLA."],
        )
        db.add(msg2)
        test_session.message_count = 2
        await db.commit()

        # Step 5: Verify Session Retrieval & Messages
        loaded_msgs = (
            await db.execute(
                select(ChatMessage).where(ChatMessage.session_id == sid).order_by(ChatMessage.created_at)
            )
        ).scalars().all()
        assert len(loaded_msgs) == 2, f"Expected 2 messages, got {len(loaded_msgs)}"
        assert loaded_msgs[0].role == "user"
        assert loaded_msgs[1].role == "assistant"
        assert len(loaded_msgs[1].key_findings) == 2
        print(f"✅ Step 5: Retrieved {len(loaded_msgs)} messages from session {sid} with evidence and key findings.")

        # Step 6: Test Rename Session
        test_session.title = "TEST_SESSION_Updated_Title"
        await db.commit()
        refreshed = (await db.execute(select(ChatSession).where(ChatSession.session_id == sid))).scalars().first()
        assert refreshed.title == "TEST_SESSION_Updated_Title"
        print(f"✅ Step 6: Session renamed successfully to '{refreshed.title}'.")

        # Step 7: Clean up test session
        await db.execute(delete(ChatMessage).where(ChatMessage.session_id == sid))
        await db.execute(delete(ChatSession).where(ChatSession.session_id == sid))
        await db.commit()
        print("✅ Step 7: Test cleanup completed.")

    print("\n" + "=" * 60)
    print("ALL INTEGRATION TESTS PASSED SUCCESSFULLY! 🚀")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
