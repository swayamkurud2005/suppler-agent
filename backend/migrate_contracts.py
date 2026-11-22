"""
Database migration script: Add document_data and document_filename columns
to the contracts table in Neon PostgreSQL, then backfill existing contracts
from local disk files.
"""
import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, r"d:\Supplier_360-main\Supplier_360-main\backend")

async def migrate():
    from app.core.database import engine
    from sqlalchemy import text

    async with engine.begin() as conn:
        # Add columns if they don't exist
        await conn.execute(text("""
            ALTER TABLE contracts ADD COLUMN IF NOT EXISTS document_data BYTEA;
        """))
        await conn.execute(text("""
            ALTER TABLE contracts ADD COLUMN IF NOT EXISTS document_filename VARCHAR(500);
        """))
        print("✅ Columns added (or already exist)")

        # Check existing contracts
        rows = await conn.execute(text("""
            SELECT contract_id, document_path, document_filename,
                   CASE WHEN document_data IS NOT NULL THEN TRUE ELSE FALSE END as has_data
            FROM contracts
        """))
        contracts = rows.fetchall()
        print(f"📋 Found {len(contracts)} contracts in database")

        backfilled = 0
        for row in contracts:
            cid, doc_path, doc_filename, has_data = row
            print(f"  Contract {cid}: path={doc_path}, filename={doc_filename}, has_cloud_data={has_data}")

            # Backfill from local disk if cloud data is missing
            if not has_data and doc_path and os.path.isfile(doc_path):
                with open(doc_path, "rb") as f:
                    file_bytes = f.read()
                fname = os.path.basename(doc_path)
                await conn.execute(
                    text("UPDATE contracts SET document_data = :data, document_filename = :fname WHERE contract_id = :cid"),
                    {"data": file_bytes, "fname": fname, "cid": cid}
                )
                print(f"    ✅ Backfilled {len(file_bytes)} bytes for {cid} ({fname})")
                backfilled += 1
            elif has_data:
                print(f"    ✓ Already has cloud data")
            else:
                print(f"    ⚠ No local file to backfill from")

        print(f"\n✅ Migration complete. Backfilled {backfilled} contracts.")

asyncio.run(migrate())
