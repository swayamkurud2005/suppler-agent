"""
Database migration: Create price_research_runs and market_price_observations tables
in Neon PostgreSQL database if they do not already exist.
"""
import asyncio
import sys

sys.path.insert(0, r"d:\Supplier_360-main\Supplier_360-main\backend")

async def run_migration():
    from app.core.database import engine
    from sqlalchemy import text

    async with engine.begin() as conn:
        print("1. Creating price_research_runs table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS price_research_runs (
                id VARCHAR(64) PRIMARY KEY,
                supplier_id VARCHAR(64) NOT NULL REFERENCES suppliers(supplier_id) ON DELETE CASCADE,
                contract_id VARCHAR(64) REFERENCES contracts(contract_id) ON DELETE SET NULL,
                material_name VARCHAR(255) NOT NULL,
                grade VARCHAR(255),
                product_code VARCHAR(100),
                technical_characteristics TEXT,
                contract_price NUMERIC(14, 4) NOT NULL,
                contract_currency VARCHAR(10) NOT NULL DEFAULT 'INR',
                contract_unit VARCHAR(50) NOT NULL DEFAULT 'kg',
                contract_quantity NUMERIC(14, 2),
                annual_quantity NUMERIC(14, 2),
                delivery_terms VARCHAR(100),
                delivery_location VARCHAR(255),
                tax_terms VARCHAR(100),
                packaging_details VARCHAR(255),
                region VARCHAR(100) DEFAULT 'India',
                comparison_period VARCHAR(50) DEFAULT 'Current Quarter',
                market_benchmark_median NUMERIC(14, 4),
                market_min_price NUMERIC(14, 4),
                market_max_price NUMERIC(14, 4),
                market_avg_price NUMERIC(14, 4),
                variance_pct NUMERIC(8, 2),
                potential_annual_difference NUMERIC(16, 2),
                confidence_score NUMERIC(5, 2),
                confidence_level VARCHAR(50),
                ai_summary TEXT,
                ai_insight JSON,
                status VARCHAR(50) NOT NULL DEFAULT 'completed',
                error_message TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """))

        print("2. Creating indexes for price_research_runs...")
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prr_supplier ON price_research_runs(supplier_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prr_contract ON price_research_runs(contract_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prr_created ON price_research_runs(created_at);"))

        print("3. Creating market_price_observations table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_price_observations (
                id VARCHAR(64) PRIMARY KEY,
                research_run_id VARCHAR(64) NOT NULL REFERENCES price_research_runs(id) ON DELETE CASCADE,
                source_name VARCHAR(255) NOT NULL,
                source_url TEXT NOT NULL,
                material_name VARCHAR(255) NOT NULL,
                grade VARCHAR(255),
                specification TEXT,
                raw_price NUMERIC(14, 4),
                raw_currency VARCHAR(10),
                raw_unit VARCHAR(50),
                normalized_price NUMERIC(14, 4) NOT NULL,
                normalized_currency VARCHAR(10) NOT NULL,
                normalized_unit VARCHAR(50) NOT NULL,
                exchange_rate_applied NUMERIC(12, 6),
                unit_conversion_ratio NUMERIC(12, 6),
                location VARCHAR(255),
                observation_date DATE,
                price_type VARCHAR(100),
                delivery_conditions VARCHAR(100),
                tax_inclusion VARCHAR(100),
                match_classification VARCHAR(50) NOT NULL DEFAULT 'high',
                match_rationale TEXT,
                snippet TEXT,
                is_included_in_benchmark BOOLEAN DEFAULT TRUE,
                retrieved_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """))

        print("4. Creating indexes for market_price_observations...")
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_mpo_run ON market_price_observations(research_run_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_mpo_match ON market_price_observations(match_classification);"))

        print("✅ Migration completed successfully!")

if __name__ == "__main__":
    asyncio.run(run_migration())
