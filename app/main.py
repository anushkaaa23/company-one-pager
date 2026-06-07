from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sys
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.entity_resolution import resolve_entity
from pipeline.discovery import discover_sources, discover_targeted_sources
from pipeline.extraction import (
    extract_text_from_url,
    extract_financials,
    extract_overview,
    extract_products_from_product_pages,
    extract_products_fallback,
    extract_clients,
)
from pipeline.product_discovery import discover_product_pages
from pipeline.verification import verify_report
from pipeline.generation import save_report
from schemas.models import FinalReport, CompanyOverview, FactClaim, ClientsSection, DEFAULT_MIN_PRODUCTS

app = FastAPI(title="Company One-Pager Generator")

class GenerateRequest(BaseModel):
    company_name: str
    ticker: Optional[str] = None
    website: Optional[str] = None
    min_products: int = DEFAULT_MIN_PRODUCTS  # Configurable per-request


def verify_source_content(text: str, company_name: str, ticker: Optional[str]) -> bool:
    text_lower = text.lower()
    base_name = company_name.lower().replace(" limited", "").replace(" private", "").replace(" ltd", "").replace(" pvt", "").strip()
    
    if base_name in text_lower:
        return True
    if ticker:
        clean_ticker = ticker.split('.')[0].lower()
        if clean_ticker and clean_ticker in text_lower:
            return True
            
    # Also check if pieces of the name appear AND some business words exist
    name_parts = base_name.split()
    if len(name_parts) > 1 and name_parts[0] in text_lower and ("company" in text_lower or "industry" in text_lower or "revenue" in text_lower or "business" in text_lower):
        if all(part in text_lower for part in name_parts if len(part) > 2):
            return True
            
    return False


def _extract_overview_description(overview: Optional[CompanyOverview]) -> Optional[str]:
    """Pull a text description from the overview for IT heuristic and fallback."""
    if not overview:
        return None
    parts = []
    for field_name in ("what_company_does", "business_model", "products_services", "industries_served"):
        fact = getattr(overview, field_name, None)
        if fact and fact.confidence != "NOT_FOUND":
            parts.append(fact.claim)
    return " ".join(parts) if parts else None


def _build_categories_from_overview(overview: Optional[CompanyOverview]) -> str:
    """Extract known product/service categories from the overview for fallback note."""
    if not overview or not overview.products_services:
        return "no categories identified"
    claim = overview.products_services.claim
    if "NOT FOUND" in claim.upper():
        return "no categories identified"
    return claim


@app.post("/generate", response_model=FinalReport)
def generate_report(request: GenerateRequest):
    try:
        # ── 1. Entity Resolution ──────────────────────────────────────
        print(f"Resolving entity: {request.company_name}")
        entity = resolve_entity(request.company_name, request.website, request.ticker)
        
        # ── 2. Source Discovery ────────────────────────────────────────
        print(f"Discovering sources for: {entity.company_name}")
        sources = discover_sources(entity.company_name, entity.website, entity.ticker)
        
        if not sources:
            raise HTTPException(status_code=404, detail="No reliable sources found.")
            
        # ── 3. Text Extraction from general sources ───────────────────
        print(f"Extracting data from sources...")
        context_chunks = []
        screener_text = None  # Track Screener.in text separately for product fallback

        max_chunks = 5

        for s in sources:
            if len(context_chunks) >= max_chunks:
                break
                
            try:
                text = extract_text_from_url(s.url)
            except Exception as e:
                print(f"Extraction failed for {s.url}: {e}")
                continue
                
            if text:
                if verify_source_content(text, entity.company_name, entity.ticker):
                    context_chunks.append({
                        "url": s.url,
                        "type": s.source_type,
                        "text": text
                    })
                    # Save Screener.in text for product discovery fallback
                    if "screener.in" in s.url.lower():
                        screener_text = text
                else:
                    print(f"  Discarding {s.url}: failed entity verification.")
                
        if not context_chunks:
            raise HTTPException(status_code=500, detail="Failed to extract matching text from sources.")
            
        # Aggregate context for overview and client extraction
        combined_context = "\n\n".join([f"Source: {c['url']}\n\n{c['text'][:8000]}" for c in context_chunks])
        top_source_url = context_chunks[0]['url']
        top_source_type = context_chunks[0]['type']
        
        # ── 4. Overview Extraction ────────────────────────────────────
        print("Extracting Overview...")
        overview = extract_overview(entity.company_name, combined_context, top_source_url, top_source_type)
        
        # ── 4b. Secondary Overview Extraction (Global Rule) ───────────
        missing_fields = []
        if overview:
            for field in ["what_company_does", "business_model", "products_services", "industries_served", "geography", "operating_model"]:
                val = getattr(overview, field, None)
                if val and val.confidence == "NOT_FOUND":
                    missing_fields.append(field)
                    
        has_ar_10k = any("annual" in c["url"].lower() or "10-k" in c["url"].lower() or c["url"].lower().endswith(".pdf") or c.get("type") == "sec_filing" for c in context_chunks)
        
        if missing_fields and not has_ar_10k:
            print(f"Missing fields detected: {missing_fields}. Initiating secondary targeted search...")
            seen_urls = {c["url"] for c in context_chunks}
            new_sources = discover_targeted_sources(entity.company_name, missing_fields, seen_urls)
            
            new_chunks = []
            for s in new_sources:
                if len(new_chunks) >= 2: # Fetch at least 2 more sources
                    break
                try:
                    text = extract_text_from_url(s.url)
                    if text and verify_source_content(text, entity.company_name, entity.ticker):
                        new_chunks.append({
                            "url": s.url,
                            "type": s.source_type,
                            "text": text
                        })
                except Exception as e:
                    print(f"Secondary extraction failed for {s.url}: {e}")
                    
            if new_chunks:
                context_chunks.extend(new_chunks)
                combined_context = "\n\n".join([f"Source: {c['url']}\n\n{c['text'][:8000]}" for c in context_chunks])
                print("Re-extracting Overview with expanded context...")
                overview = extract_overview(entity.company_name, combined_context, top_source_url, top_source_type)
        
        # ── 5. Financial Extraction ───────────────────────────────────
        print("Extracting Financials...")
        financials = []
        financials_note = None
        
        is_private = "private" in entity.company_name.lower() or "pvt" in entity.company_name.lower() or entity.company_type == "Private"
        if is_private or not entity.ticker:
            financials_note = f"{entity.company_name} is an unlisted private company. Financial data not available in public sources. MCA filings exist but are paywalled. No reliable figures found."
        else:
            financials = extract_financials(entity.ticker)
        
        # ── 6. Product Discovery & Extraction (NEW) ───────────────────
        print("=" * 60)
        print("PRODUCT DISCOVERY PHASE")
        print("=" * 60)

        # Get a description from the overview for IT heuristic
        overview_desc = _extract_overview_description(overview)
        overview_industry = None
        if overview and overview.industries_served and overview.industries_served.confidence != "NOT_FOUND":
            overview_industry = overview.industries_served.claim

        # 6a. Discover product pages
        print("Discovering product pages...")
        product_pages = discover_product_pages(
            website=entity.website or "",
            company_name=entity.company_name,
            industry=overview_industry,
            description=overview_desc,
            screener_text=screener_text,
        )

        # 6b. Extract products from dedicated product pages
        products = []
        if product_pages:
            print(f"Extracting products from {len(product_pages)} product page(s)...")
            product_contexts = [
                {"url": pp.url, "text": pp.text, "label": pp.source_label}
                for pp in product_pages
            ]
            products = extract_products_from_product_pages(entity.company_name, product_contexts)
            print(f"  Found {len(products)} product(s) from product pages.")

        # 6c. Fallback to general context if below minimum
        products_discovery_note = None
        if len(products) < request.min_products:
            print(f"  Below minimum ({len(products)} < {request.min_products}), trying general context fallback...")
            fallback_products = extract_products_fallback(
                entity.company_name, combined_context, top_source_url, top_source_type
            )
            # Merge: add fallback products that aren't already found
            existing_names = {p.name.claim.lower() for p in products}
            for fp in fallback_products:
                if fp.name.claim.lower() not in existing_names:
                    products.append(fp)
                    existing_names.add(fp.name.claim.lower())
            print(f"  After fallback: {len(products)} product(s) total.")

        # 6d. Set honest fallback note if still below minimum
        if len(products) < request.min_products:
            categories = _build_categories_from_overview(overview)
            products_discovery_note = (
                f"Specific products not found on public pages. "
                f"Known categories: {categories}"
            )
            print(f"  Products discovery note: {products_discovery_note}")

        print("=" * 60)

        # ── 7. Client Extraction (now separate) ───────────────────────
        print("Extracting Clients...")
        clients = extract_clients(entity.company_name, combined_context, top_source_url, top_source_type)
        
        # ── 8. Assemble Report ────────────────────────────────────────
        report = FinalReport(
            company_name=entity.company_name,
            ticker=entity.ticker,
            website=entity.website,
            overview=overview,
            financials=financials,
            financials_note=financials_note,
            products=products,
            products_discovery_note=products_discovery_note,
            clients=clients,
        )
        
        # ── 9. Verification ───────────────────────────────────────────
        print("Running Verification Layer...")
        verified_report = verify_report(report)
        
        # ── 10. Generation ─────────────────────────────────────────────
        print("Saving report...")
        save_report(verified_report, output_dir=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs"))
        
        return verified_report
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
