"""
End-to-end integration test for AI-Powered Supplier Onboarding Through Contract Extraction.
Tests:
1. Extract supplier from realistic contract document.
2. Field validation: confidence, evidence source, zero hallucination on missing fields.
3. Party distinction: Buyer vs Supplier.
4. Duplicate supplier detection in extraction and creation.
5. Error handling for empty / invalid files.
6. Supplier creation with contract linking & vector indexing.
"""

import asyncio
import io
from httpx import AsyncClient, ASGITransport
from app.main import app

SAMPLE_CONTRACT_TEXT = """MASTER SUPPLY AND PURCHASE AGREEMENT

This Master Supply and Purchase Agreement ("Agreement") is entered into and made effective as of 15th January 2026, by and between:

Enterprise Procurement Corporation, a corporation organized and existing under the laws of Delaware, with its principal offices located at 100 Corporate Parkway, New York, NY 10001 ("Buyer" or "Customer"),

AND

Precision Machining Dynamics Pvt Ltd, a private limited company incorporated under the laws of India, having its registered office and manufacturing facility at Plot No. 42, Hinjewadi Industrial Estate, Phase 2, Pune, Maharashtra 411057, India ("Supplier" or "Vendor").

RECITALS
WHEREAS, Buyer desires to purchase high-precision CNC machined automotive parts, and Supplier possesses the specialized manufacturing equipment, engineering expertise, and capacity to manufacture and supply such Precision Machining components;

NOW, THEREFORE, in consideration of the mutual covenants herein contained, the parties agree as follows:

1. SCOPE OF SUPPLY
Supplier shall manufacture, inspect, package, and deliver to Buyer high-precision CNC turned shafts, aerospace bracket assemblies, and specialized precision machined components in accordance with Exhibit A.

2. PRICING & PAYMENT TERMS
Unit price for contracted components shall be USD $45.00 per unit. Payment terms are Net 45 days following receipt of correct invoice and QA acceptance certificate.

3. NOTICES AND COMMUNICATION
All notices, requests, demands, and other communications under this Agreement shall be in writing and shall be deemed to have been duly given when delivered by email or certified mail to:

If to Buyer:
Attention: Legal & Procurement Department
Enterprise Procurement Corporation
100 Corporate Parkway, New York, NY 10001
Email: notices@enterpriseprocurement.com
Phone: +1-212-555-0199

If to Supplier:
Attention: Vikram Deshmukh, Managing Director
Precision Machining Dynamics Pvt Ltd
Plot No. 42, Hinjewadi Industrial Estate, Pune, India
Email: v.deshmukh@precisiondynamics.in
Phone: +91-98230-12345

4. GOVERNING LAW & ARBITRATION
This Agreement shall be governed by and construed in accordance with the laws of India.

IN WITNESS WHEREOF, the parties hereto have executed this Agreement as of the date first written above.

For Buyer:
ENTERPRISE PROCUREMENT CORP.
By: John C. Adams
Title: Chief Procurement Officer

For Supplier:
PRECISION MACHINING DYNAMICS PVT LTD
By: Vikram Deshmukh
Title: Managing Director & Authorized Signatory
"""

SAMPLE_CONTRACT_MISSING_CONTACTS = """STANDARD RAW MATERIALS SUPPLY CONTRACT

This Agreement is made between Global Manufacturing Ltd ("Buyer") and Deccan Metal Castings LLP ("Supplier"), located at GIDC Industrial Area, Ahmedabad, Gujarat, India.

Supplier agrees to supply industrial grade raw aluminium ingots and alloys under the terms hereof.

Signed for Deccan Metal Castings LLP:
By: Authorized Partner
"""


async def run_tests():
    print("==================================================================")
    print("STARTING TEST SUITE: AI-POWERED SUPPLIER ONBOARDING PIPELINE")
    print("==================================================================")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=30.0) as client:
        # TEST 1: Health check
        print("\n[TEST 1] Checking system health...")
        h = await client.get("/health")
        assert h.status_code == 200, f"Health check failed: {h.text}"
        print(f"✓ Health check status: {h.json().get('status')}")

        # TEST 2: Extract details from contract with full details
        print("\n[TEST 2] Extracting supplier details from realistic contract...")
        contract_bytes = SAMPLE_CONTRACT_TEXT.encode("utf-8")
        files = {"file": ("PrecisionMachining_Contract.txt", contract_bytes, "text/plain")}
        res = await client.post("/api/suppliers/extract-from-contract", files=files)
        assert res.status_code == 200, f"Extraction failed: {res.text}"
        data = res.json().get("data", {})

        print("✓ Extraction successful!")
        print(f"  - Supplier Name: '{data['supplier_name']['value']}' (Conf: {data['supplier_name']['confidence']}, Source: {data['supplier_name']['source']})")
        print(f"  - Category: '{data['category']['value']}' (Conf: {data['category']['confidence']}, Source: {data['category']['source']})")
        print(f"  - Location: '{data['location']['value']}' (Conf: {data['location']['confidence']}, Source: {data['location']['source']})")
        print(f"  - Contact Person: '{data['contact_person']['value']}' (Conf: {data['contact_person']['confidence']}, Source: {data['contact_person']['source']})")
        print(f"  - Contact Email: '{data['contact_email']['value']}' (Conf: {data['contact_email']['confidence']}, Source: {data['contact_email']['source']})")
        print(f"  - Contact Phone: '{data['contact_phone']['value']}' (Conf: {data['contact_phone']['confidence']}, Source: {data['contact_phone']['source']})")
        print(f"  - Document Token: '{data.get('document_token')}'")

        # Verifications
        assert "Precision" in data["supplier_name"]["value"], "Failed to identify Precision Machining as supplier"
        assert "Enterprise Procurement" not in data["supplier_name"]["value"], "Incorrectly selected Buyer as supplier!"
        assert data["category"]["value"] == "Precision Machining", f"Expected 'Precision Machining' category, got {data['category']['value']}"
        assert "Pune" in data["location"]["value"] or "India" in data["location"]["value"], "Failed to extract location"
        assert "Vikram" in data["contact_person"]["value"], "Failed to extract contact person"
        assert "v.deshmukh@precisiondynamics.in" in data["contact_email"]["value"], "Failed to extract supplier email"
        assert "98230" in data["contact_phone"]["value"], "Failed to extract supplier phone"
        assert data["supplier_name"]["confidence"] > 0.7, "Confidence too low"
        assert data["document_token"] is not None, "Missing document token for linking"
        document_token = data["document_token"]

        # TEST 3: Zero hallucination check on missing contact information
        print("\n[TEST 3] Testing zero-hallucination when contact details are missing...")
        files_missing = {"file": ("DeccanMetals_Contract.txt", SAMPLE_CONTRACT_MISSING_CONTACTS.encode("utf-8"), "text/plain")}
        res_missing = await client.post("/api/suppliers/extract-from-contract", files=files_missing)
        assert res_missing.status_code == 200
        data_missing = res_missing.json().get("data", {})

        print(f"  - Supplier Name: '{data_missing['supplier_name']['value']}'")
        print(f"  - Contact Email: {data_missing['contact_email']['value']} (Conf: {data_missing['contact_email']['confidence']})")
        print(f"  - Contact Phone: {data_missing['contact_phone']['value']} (Conf: {data_missing['contact_phone']['confidence']})")
        assert "Deccan" in data_missing["supplier_name"]["value"]
        assert data_missing["contact_email"]["value"] is None, "Hallucinated contact email when none existed!"
        assert data_missing["contact_phone"]["value"] is None, "Hallucinated contact phone when none existed!"
        print("✓ Zero-hallucination verified: missing fields remain null.")

        # TEST 4: Error handling on invalid/empty file
        print("\n[TEST 4] Testing error handling for empty / invalid files...")
        empty_files = {"file": ("empty.pdf", b"", "application/pdf")}
        res_empty = await client.post("/api/suppliers/extract-from-contract", files=empty_files)
        assert res_empty.status_code == 400
        print(f"✓ Correctly rejected empty file with HTTP 400: '{res_empty.json().get('detail')}'")

        bad_format = {"file": ("script.exe", b"binary content", "application/octet-stream")}
        res_bad = await client.post("/api/suppliers/extract-from-contract", files=bad_format)
        assert res_bad.status_code == 400
        print(f"✓ Correctly rejected unsupported file format: '{res_bad.json().get('detail')}'")

        # TEST 5: Create supplier with contract linking & vector indexing
        print("\n[TEST 5] Creating new supplier partner with document linking...")
        new_supplier_name = f"Precision Machining Dynamics Pvt Ltd"
        create_payload = {
            "name": new_supplier_name,
            "category": data["category"]["value"],
            "location": data["location"]["value"],
            "contactPerson": data["contact_person"]["value"],
            "contactEmail": data["contact_email"]["value"],
            "contactPhone": data["contact_phone"]["value"],
            "status": "active",
            "relationshipYears": 1,
            "riskScore": 20,
            "documentToken": document_token,
            "contractFileName": "PrecisionMachining_Contract.txt",
        }
        res_create = await client.post("/api/suppliers", json=create_payload)
        assert res_create.status_code == 200, f"Creation failed: {res_create.text}"
        created = res_create.json().get("data", {})
        print(f"✓ Supplier created: ID={created.get('id')}, Name='{created.get('name')}'")
        assert created.get("contract") is not None, "Contract was not linked to new supplier!"
        print(f"  - Contract linked: ID={created.get('contract', {}).get('contract_id')}, Chunks={created.get('contract', {}).get('chunks_indexed')}")

        # TEST 6: Duplicate detection on creation
        print("\n[TEST 6] Testing duplicate supplier prevention on creation...")
        res_dup = await client.post("/api/suppliers", json=create_payload)
        assert res_dup.status_code == 409, f"Expected 409 conflict on duplicate, got {res_dup.status_code}"
        print(f"✓ Duplicate prevented with HTTP 409: '{res_dup.json().get('detail')}'")

        # TEST 7: Duplicate detection in extraction
        print("\n[TEST 7] Testing duplicate detection during contract extraction...")
        res_extract_dup = await client.post("/api/suppliers/extract-from-contract", files=files)
        assert res_extract_dup.status_code == 200
        dup_data = res_extract_dup.json().get("data", {})
        assert dup_data.get("is_duplicate") is True, "Failed to flag duplicate supplier in extraction"
        print(f"✓ Duplicate supplier flagged during extraction: Existing ID={dup_data.get('existing_supplier', {}).get('id')}")

        # TEST 8: Verify new supplier is queryable in suppliers list
        print("\n[TEST 8] Verifying new supplier in suppliers list...")
        res_list = await client.get("/api/suppliers?search=Precision")
        assert res_list.status_code == 200
        found = [s for s in res_list.json().get("data", []) if "Precision" in s.get("name", "")]
        assert len(found) > 0, "New supplier not found in search list"
        print(f"✓ Verified new supplier found in list: {found[0]['id']} - {found[0]['name']}")

    print("\n==================================================================")
    print("ALL 8 END-TO-END SUPPLIER ONBOARDING TESTS PASSED (100% SUCCESS)!")
    print("==================================================================")


if __name__ == "__main__":
    asyncio.run(run_tests())
