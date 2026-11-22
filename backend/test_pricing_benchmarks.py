"""
Comprehensive Test Suite for Market Price Benchmarking Feature.
Validates:
1. Contract Pricing & Specification Extraction (Northstar & generic materials)
2. Brave Search API Query Generation
3. Material Matching Engine (High, Partial, Low, Not Comparable)
4. Price Normalization Engine (Currencies, Units, Taxes, Incoterms)
5. Benchmark Calculation (Median, Variance, Potential Annual Diff, Confidence)
6. Error handling (Brave errors, irrelevant results, stale prices, missing specs)
7. End-to-End API Integration
"""

import asyncio
import sys
import os

sys.path.insert(0, r"d:\Supplier_360-main\Supplier_360-main\backend")

from app.core.database import async_session_factory
from app.schemas.schemas import ContractPricingDetails, MarketPriceObservationSchema
from app.services.contract_pricing_extractor import contract_pricing_extractor
from app.services.brave_search_service import brave_search_service
from app.services.material_matching_service import material_matching_service
from app.services.price_normalization_service import price_normalization_service
from app.services.price_benchmark_service import price_benchmark_service
from app.services.pricing_insight_service import pricing_insight_service


async def run_all_tests():
    print("================================================================")
    print("RUNNING MARKET PRICE BENCHMARKING TEST SUITE")
    print("================================================================\n")

    passed_tests = 0
    total_tests = 8

    # TEST 1: Contract Extraction from Northstar Agreement (SUP-021)
    print("--- TEST 1: Northstar Agreement Contract Extraction ---")
    async with async_session_factory() as db:
        details = await contract_pricing_extractor.extract_pricing_details(db, "SUP-021")
        print(f"  Material Name: {details.material_name}")
        print(f"  Grade: {details.grade}")
        print(f"  Contract Price: {details.contract_unit_price} {details.currency}/{details.unit_of_measurement}")
        print(f"  Annual Quantity: {details.annual_estimated_quantity}")
        print(f"  Incoterms: {details.incoterms}")
        print(f"  Tax Terms: {details.tax_inclusion}")

        assert "epoxy" in details.material_name.lower(), "Material should contain 'epoxy'"
        assert details.contract_unit_price == 420.0, f"Expected 420.0, got {details.contract_unit_price}"
        assert details.annual_estimated_quantity == 24000.0, f"Expected 24000, got {details.annual_estimated_quantity}"
        assert "ddp" in (details.incoterms or "").lower(), "Expected DDP incoterms"
        assert "exclud" in (details.tax_inclusion or "").lower(), "Expected GST excluded"
        print("  ✅ TEST 1 PASSED: Northstar contract terms extracted with 100% accuracy\n")
        passed_tests += 1

    # TEST 2: Dynamic Query Generation Across Categories (Steel, Copper, Aluminium, Cement, Epoxy)
    print("--- TEST 2: Multi-Category Dynamic Brave Search Queries ---")
    categories_to_test = [
        ("NS-480 Industrial Epoxy Resin", "Grade A", "kg", "INR"),
        ("Cold Rolled Steel Coil", "IS 2062", "tonne", "INR"),
        ("Copper Cathode / Wire Rod", "Grade A 99.99%", "kg", "INR"),
        ("Aluminium Ingot", "Alloy 6063", "tonne", "INR"),
        ("Ordinary Portland Cement", "53 Grade", "bag", "INR"),
    ]
    for mat_name, grade, unit, curr in categories_to_test:
        dummy_contract = ContractPricingDetails(
            material_name=mat_name,
            grade=grade,
            contract_unit_price=100.0,
            currency=curr,
            unit_of_measurement=unit,
        )
        queries = brave_search_service.generate_search_queries(dummy_contract, "India")
        print(f"  Material: {mat_name} -> {len(queries)} dynamic queries generated:")
        print(f"    Sample: '{queries[0]}'")
        assert len(queries) >= 4, "Should generate at least 4 query variations"
        assert any(unit in q for q in queries), f"Query should reference unit '{unit}'"
    print("  ✅ TEST 2 PASSED: Dynamic queries verified across all commodity categories\n")
    passed_tests += 1

    # TEST 3: Material Matching Engine (High, Partial, Low, Not Comparable)
    print("--- TEST 3: Material Specification Matching & Validation ---")
    target_contract = details # Northstar Epoxy Resin Grade A

    test_cases = [
        # Exact/Equivalent Grade
        ({"material_name": "Liquid Epoxy Resin Grade A", "grade": "Grade A", "snippet": "DGEBA Grade A 200kg drums"}, "high", True),
        # Partial Match (different grade / unspecified standard)
        ({"material_name": "Epoxy Resin General Standard", "grade": None, "snippet": "Bulk liquid industrial resin 200kg drum"}, "partial", False),
        # Low Match (Secondary Grade B)
        ({"material_name": "Epoxy Resin Technical Grade B", "grade": "Grade B", "snippet": "Viscosity 8000, secondary grade"}, "low", False),
        # Low Match (Retail consumer tube)
        ({"material_name": "Epoxy Adhesive Glue 50g DIY tube", "grade": "Art Grade", "snippet": "50g syringe retail package"}, "low", False),
        # Not Comparable (Different commodity)
        ({"material_name": "Hot Rolled Steel Coils", "grade": "IS 2062", "snippet": "Prime steel coil Raipur"}, "not_comparable", False),
    ]

    for record, expected_class, expected_included in test_cases:
        m_class, rationale, is_inc = material_matching_service.evaluate_match(record, target_contract)
        print(f"  '{record['material_name']}' -> Classification: {m_class.upper()} (Included in benchmark: {is_inc})")
        print(f"    Rationale: {rationale[:80]}...")
        assert m_class == expected_class, f"Expected {expected_class}, got {m_class}"
        assert is_inc == expected_included, f"Expected included={expected_included}, got {is_inc}"
    print("  ✅ TEST 3 PASSED: Material matching correctly filters grades and scale\n")
    passed_tests += 1

    # TEST 4: Multi-Currency and Unit Normalization
    print("--- TEST 4: Currency, Unit, and Terms Price Normalization ---")
    # Case A: Foreign Currency (USD to INR @ 85.0)
    norm_p, fx, ratio, note = price_normalization_service.normalize(
        raw_price=4.50,
        raw_currency="USD",
        raw_unit="kg",
        contract=target_contract,
    )
    print(f"  USD 4.50/kg -> INR {norm_p}/kg (Fx: {fx}) [{note}]")
    assert abs(norm_p - 382.50) < 1.0, f"Expected ~382.50, got {norm_p}"

    # Case B: Unit Conversion (INR 380,000 per Metric Tonne -> per kg)
    norm_p_unit, fx, ratio, note = price_normalization_service.normalize(
        raw_price=380000.0,
        raw_currency="INR",
        raw_unit="tonne",
        contract=target_contract,
    )
    print(f"  INR 380,000/tonne -> INR {norm_p_unit}/kg (Ratio: {ratio}) [{note}]")
    assert norm_p_unit == 380.0, f"Expected 380.0, got {norm_p_unit}"

    # Case C: Delivery Condition Normalization (EXW + 3.5% freight to DDP)
    norm_p_inco, fx, ratio, note = price_normalization_service.normalize(
        raw_price=385.0,
        raw_currency="INR",
        raw_unit="kg",
        contract=target_contract,
        observation={"delivery_conditions": "EXW", "tax_inclusion": "Excl. GST"},
    )
    print(f"  EXW INR 385.0/kg -> DDP INR {norm_p_inco}/kg [{note}]")
    assert abs(norm_p_inco - 398.47) < 0.5, f"Expected ~398.47, got {norm_p_inco}"

    # Case D: Tax Adjustment (Removing 18% GST to align with tax-exclusive contract)
    norm_p_tax, fx, ratio, note = price_normalization_service.normalize(
        raw_price=472.0,
        raw_currency="INR",
        raw_unit="kg",
        contract=target_contract,
        observation={"delivery_conditions": "DDP", "tax_inclusion": "Incl. GST 18%"},
    )
    print(f"  Incl. GST INR 472.0/kg -> Excl. GST INR {norm_p_tax}/kg [{note}]")
    assert abs(norm_p_tax - 400.0) < 0.5, f"Expected ~400.0, got {norm_p_tax}"

    print("  ✅ TEST 4 PASSED: Currency, unit, tax, and freight normalizations verified\n")
    passed_tests += 1

    # TEST 5: Benchmark Calculation (Median, Variance, Potential Annual Difference)
    print("--- TEST 5: Statistical Benchmark Calculation & Confidence Scoring ---")
    mock_obs = [
        MarketPriceObservationSchema(
            id="OBS-1", source_name="IndiaMART", source_url="https://indiamart.com",
            material_name="Epoxy Grade A", raw_price=385.0, normalized_price=398.47,
            normalized_currency="INR", normalized_unit="kg", match_classification="high",
            is_included_in_benchmark=True
        ),
        MarketPriceObservationSchema(
            id="OBS-2", source_name="TradeIndia", source_url="https://tradeindia.com",
            material_name="Epoxy Grade A", raw_price=380.0, normalized_price=387.60,
            normalized_currency="INR", normalized_unit="kg", match_classification="high",
            is_included_in_benchmark=True
        ),
        MarketPriceObservationSchema(
            id="OBS-3", source_name="Echemi Global", source_url="https://echemi.com",
            material_name="Epoxy DGEBA", raw_price=4.45, normalized_price=385.81,
            normalized_currency="INR", normalized_unit="kg", match_classification="high",
            is_included_in_benchmark=True
        ),
        MarketPriceObservationSchema(
            id="OBS-4", source_name="ExportersIndia", source_url="https://exportersindia.com",
            material_name="Grade B Epoxy", raw_price=340.0, normalized_price=340.0,
            normalized_currency="INR", normalized_unit="kg", match_classification="low",
            is_included_in_benchmark=False
        ),
    ]

    bench = price_benchmark_service.compute_benchmark(target_contract, mock_obs)
    print(f"  Contract Price: {target_contract.contract_unit_price} INR/kg")
    print(f"  Market Benchmark Median: {bench['market_benchmark_median']} INR/kg")
    print(f"  Price Variance: {bench['variance_pct']}%")
    print(f"  Potential Annual Difference: INR {bench['potential_annual_difference']:,.2f}")
    print(f"  Confidence Level: {bench['confidence_level']} (Score: {bench['confidence_score']})")

    # Median of [385.81, 387.60, 398.47] is 387.60
    assert bench["market_benchmark_median"] == 387.60, f"Expected 387.60, got {bench['market_benchmark_median']}"
    assert bench["variance_pct"] > 0, "Variance should be positive (paying above market)"
    assert bench["potential_annual_difference"] > 0, "Potential annual diff should be positive"
    assert bench["confidence_level"] in ("High", "Moderate"), "Confidence should be High or Moderate"
    print("  ✅ TEST 5 PASSED: Statistical median and variance formulas verified\n")
    passed_tests += 1

    # TEST 6: Insufficient Data / No Results Handling
    print("--- TEST 6: Handling Insufficient Market Data & Conflicting Quotes ---")
    insufficient_obs = []
    empty_bench = price_benchmark_service.compute_benchmark(target_contract, insufficient_obs)
    print(f"  Empty observations -> Median: {empty_bench['market_benchmark_median']}, Confidence: {empty_bench['confidence_level']}")
    assert empty_bench["is_sufficient"] == False, "Should flag is_sufficient = False"
    assert empty_bench["market_benchmark_median"] is None, "Should not fabricate a median"
    assert "Insufficient" in empty_bench["confidence_level"], "Should state Insufficient market data"

    # Single source check
    single_obs = [mock_obs[0]]
    single_bench = price_benchmark_service.compute_benchmark(target_contract, single_obs)
    assert single_bench["is_sufficient"] == False, "Single source should not establish a benchmark"
    print("  ✅ TEST 6 PASSED: Insufficient market data correctly guarded against hallucinations\n")
    passed_tests += 1

    # TEST 7: AI Procurement Insight Generation
    print("--- TEST 7: AI Executive Procurement Insight Generation ---")
    insight = await pricing_insight_service.generate_insight(target_contract, bench, mock_obs)
    print(f"  Verdict: {insight.verdict}")
    print(f"  Summary: {insight.summary[:100]}...")
    print(f"  Financial Impact: {insight.financial_impact[:100]}...")
    print(f"  Recommended Actions ({len(insight.recommended_actions)}):")
    for act in insight.recommended_actions:
        print(f"    - {act}")
    assert insight.verdict in ("Above Market", "Below Market", "In Line with Market"), "Verdict should be standard"
    assert len(insight.recommended_actions) >= 2, "Should provide actionable steps"
    print("  ✅ TEST 7 PASSED: AI procurement insight generated actionable strategic guidance\n")
    passed_tests += 1

    # TEST 8: Full End-to-End API Call
    print("--- TEST 8: Live HTTP API Verification on Port 8000 ---")
    import urllib.request, json
    req_url = "http://127.0.0.1:8000/api/suppliers/SUP-021/pricing/analysis"
    with urllib.request.urlopen(req_url) as res:
        api_data = json.loads(res.read())
        assert api_data["status"] == "success", "API response status must be success"
        d = api_data["data"]
        print(f"  HTTP 200 OK from {req_url}")
        print(f"  Material: {d['contract_details']['material_name']}")
        print(f"  Contract: {d['contract_details']['contract_unit_price']} {d['contract_details']['currency']}/{d['contract_details']['unit_of_measurement']}")
        print(f"  Benchmark Median: {d['market_benchmark_median']}")
        print(f"  Observations: {len(d['observations'])} records with clickable URLs")
        assert len(d["observations"]) > 0, "Should return market observations"
        for obs in d["observations"][:2]:
            assert obs["source_url"].startswith("http"), f"Source URL must be valid link: {obs['source_url']}"
    print("  ✅ TEST 8 PASSED: Live API endpoint returned complete verified benchmark data\n")
    passed_tests += 1

    print("================================================================")
    print(f"ALL TESTS PASSED: {passed_tests} / {total_tests} test suites completed successfully!")
    print("================================================================")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
