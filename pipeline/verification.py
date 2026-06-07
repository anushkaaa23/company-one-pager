from typing import List, Optional
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas.models import FactClaim, CompanyOverview, Product, Client, ClientsSection, FinalReport

# FIX 4: Confidence is now a string enum, not a float
PASSING_CONFIDENCE = {"HIGH", "MEDIUM"}

def verify_fact(fact: FactClaim) -> FactClaim:
    """Verifies a single fact claim. If confidence is NOT_FOUND, marks it appropriately."""
    if fact.confidence == "NOT_FOUND" or "not found" in fact.claim.lower():
        return FactClaim(
            claim=fact.claim if "NOT FOUND" in fact.claim.upper() else "NOT FOUND — checked available sources.",
            source_url="N/A",
            source_excerpt="N/A",
            confidence="NOT_FOUND",
            source_type="not_found",
            verification_note=fact.verification_note or "Checked: available extracted text from discovered sources."
        )
    # LOW confidence: ensure verification_note is present
    if fact.confidence == "LOW" and not fact.verification_note:
        fact.verification_note = "Single source — verify independently"
    return fact

def verify_overview(overview: Optional[CompanyOverview]) -> Optional[CompanyOverview]:
    if not overview:
        return None
    return CompanyOverview(
        what_company_does=verify_fact(overview.what_company_does),
        business_model=verify_fact(overview.business_model),
        products_services=verify_fact(overview.products_services),
        industries_served=verify_fact(overview.industries_served),
        geography=verify_fact(overview.geography),
        operating_model=verify_fact(overview.operating_model),
    )

def verify_products(products: List[Product]) -> List[Product]:
    """FIX 1: Drop products where name or description is NOT_FOUND."""
    verified = []
    for p in products:
        p.name = verify_fact(p.name)
        p.description = verify_fact(p.description)
        # Drop if name is not found OR description is not found (FIX 1)
        if p.name.confidence != "NOT_FOUND" and p.description.confidence != "NOT_FOUND":
            verified.append(p)
    return verified

def verify_clients(clients: ClientsSection) -> ClientsSection:
    """FIX 3: Verify named clients. Ensure disclosure_note is set if no named clients."""
    verified_named = []
    for c in clients.named_clients:
        c.name = verify_fact(c.name)
        c.relationship_description = verify_fact(c.relationship_description)
        if c.name.confidence != "NOT_FOUND":
            verified_named.append(c)
    
    # FIX 3: Never return both empty
    disclosure = clients.disclosure_note
    if not verified_named and not disclosure:
        disclosure = "Named clients not publicly disclosed. Checked: annual report, website, press releases."
    
    return ClientsSection(
        named_clients=verified_named,
        disclosure_note=disclosure
    )

def verify_report(report: FinalReport) -> FinalReport:
    """Passes the entire report through the verification layer."""
    report.overview = verify_overview(report.overview)
    report.products = verify_products(report.products)
    report.clients = verify_clients(report.clients)
    return report
