import io
import json
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from packages.core.config import settings
from packages.services.fact_service import FactService

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

def main():
    print("=" * 70)
    print("PHASE 2 MIGRATION: DRY-RUN EXECUTION ON LIVE DATABASE")
    print("=" * 70)
    print(f"Target DB URL: {settings.database_url}")

    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()

    try:
        fact_svc = FactService(session)
        result = fact_svc.migrate_business_brains_and_knowledge_to_facts(dry_run=True)

        print("\n1. SOURCE TABLE COUNTS:")
        for tbl, cnt in result["source_table_counts"].items():
            print(f"   - {tbl}: {cnt} rows")

        print(f"\n2. TOTAL FACTS GENERATED IN DRY-RUN: {result['migrated_facts_count']}")

        print("\n3. RESULTING TOPIC BREAKDOWN:")
        for topic, count in sorted(result["rows_per_resulting_topic"].items(), key=lambda x: x[1], reverse=True):
            print(f"   - {topic}: {count} facts")

        print("\n4. 10 SAMPLE MAPPINGS (BEFORE -> AFTER):")
        for idx, sample in enumerate(result["sample_mappings"][:10], 1):
            print(f"\n--- Sample {idx} (Source: {sample['source_table']} -> {sample['source_field']}) ---")
            print("  [BEFORE]:")
            print("   ", json.dumps(sample["before"], ensure_ascii=False, indent=4).replace("\n", "\n    "))
            print("  [AFTER - FACT RECORD]:")
            print("   ", json.dumps(sample["after"], ensure_ascii=False, indent=4).replace("\n", "\n    "))

        print(f"\n5. SKIPPED / MALFORMED ROWS SUMMARY:")
        print(f"   Total skipped/malformed occurrences: {result['skipped_or_malformed_count']}")
        print("   Sample reasons:")
        for s in result["skipped_or_malformed_samples"][:10]:
            print(f"   - Table: {s.get('source_table')}, Tenant: {s.get('tenant_id')}, Field: {s.get('source_field')}, Reason: {s.get('reason')}")

    finally:
        session.close()

if __name__ == "__main__":
    main()
