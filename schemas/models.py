from pydantic import BaseModel, Field
from typing import List, Optional, Literal

SourceType = Literal["annual_report", "company_website", "exchange_filing", "news", "database", "not_found"]

# FIX 4: Three-level confidence instead of binary 0/1
ConfidenceLevel = Literal["HIGH", "MEDIUM", "LOW", "NOT_FOUND"]
# HIGH   → verbatim in annual report, 10-K, exchange filing, or official MCA document
# MEDIUM → credible secondary source: Reuters, Bloomberg, ET, Mint, BS, analyst note, company press release
# LOW    → single unverified source, industry database entry, or contextual inference
# NOT_FOUND → claim could not be verified after checking all available sources

class FactClaim(BaseModel):
    claim: str = Field(
        ...,
        description=(
            "The factual claim being made. "
            "If NOT_FOUND, write: 'NOT FOUND — [sections checked, e.g. annual report Business section, MD&A, website]'. "
            "NEVER write a plausible-sounding guess. An honest gap is always better than a fabricated answer."
        )
    )
    source_url: str = Field(..., description="The URL or citation source of the claim. Use 'N/A' if not found.")
    source_excerpt: str = Field(..., description="A verbatim excerpt from the source supporting the claim. Use 'N/A' if not found.")
    confidence: ConfidenceLevel = Field(
        ...,
        description=(
            "HIGH = verbatim in annual report/10-K/exchange filing. "
            "MEDIUM = credible secondary source (Reuters, Bloomberg, ET, analyst note, press release). "
            "LOW = single unverified source — must add note 'Single source — verify independently'. "
            "NOT_FOUND = could not be verified."
        )
    )
    source_type: SourceType = Field(..., description="The type of the source.")
    verification_note: Optional[str] = Field(
        None,
        description="Required for LOW confidence: write 'Single source — verify independently'. Also used for NOT_FOUND to list which sections were checked."
    )

class FinancialYear(BaseModel):
    year: int
    revenue: str = Field(default="NOT FOUND — not in available financial data")
    ebitda: str = Field(default="NOT FOUND — not in available financial data")
    ebitda_margin: str = Field(default="NOT FOUND — not in available financial data")
    net_income: str = Field(default="NOT FOUND — not in available financial data")
    debt: str = Field(default="NOT FOUND — not in available financial data")
    leverage_metric: str = Field(default="NOT FOUND — not in available financial data")

# Default minimum number of products expected before triggering fallback message.
# Configurable per-run via the pipeline.
DEFAULT_MIN_PRODUCTS = 3

# FIX 1: Products must have BOTH a specific name AND a description.
# If description cannot be found, the product must be omitted entirely.
class Product(BaseModel):
    name: FactClaim = Field(
        ...,
        description=(
            "SPECIFIC named product only (e.g. 'iPhone 16', 'Crankshaft for CV engines'). "
            "NEVER list generic category names like 'smartphones', 'forgings', 'automotive'. "
            "If only category names are found, do not create a Product entry."
        )
    )
    description: FactClaim = Field(
        ...,
        description=(
            "One sentence: what it does + who buys it. "
            "MUST be sourced from text. "
            "If this cannot be found from the source, DO NOT include this product at all."
        )
    )
    industry_served: Optional[str] = Field(
        None,
        description=(
            "Which industry or customer segment this product serves "
            "(e.g., 'Automotive OEMs', 'Enterprise IT', 'BFSI'). "
            "Extract from the same source page when available."
        )
    )

# FIX 3: Clients must never be an empty array.
# Use ClientsSection to handle the honest 'not publicly disclosed' case.
class Client(BaseModel):
    name: FactClaim = Field(..., description="Specific verified client name, sourced from annual report, press release, or credible news.")
    relationship_description: FactClaim = Field(..., description="Nature of the relationship (e.g. supply agreement, OEM customer, long-term contract).")

class ClientsSection(BaseModel):
    named_clients: List[Client] = Field(
        default=[],
        description="List of specifically named, verifiable clients. Only include if name is confirmed in a reliable source."
    )
    disclosure_note: Optional[str] = Field(
        None,
        description=(
            "If named clients are not publicly available after checking annual report Customers section, MD&A, "
            "press releases, and website case studies, write: "
            "'Named clients not publicly disclosed. Verified customer segments: [list sectors with source]'. "
            "This is an honest answer. Never leave both named_clients and disclosure_note empty."
        )
    )

class CompanyOverview(BaseModel):
    what_company_does: FactClaim
    # FIX 2: Business model must be extracted from deeper sections, not just paragraph 1
    business_model: FactClaim = Field(
        ...,
        description=(
            "How revenue is earned, who it sells to, sales channel, manufacturing model, domestic vs export split. "
            "Check: annual report Business section, MD&A, segment notes. "
            "Only mark NOT FOUND after checking all of these sections."
        )
    )
    products_services: FactClaim
    # FIX 6: Industries served should almost never be NOT FOUND for listed companies
    industries_served: FactClaim = Field(
        ...,
        description=(
            "End-markets served. For listed companies check segment notes in annual report. "
            "This should only be NOT FOUND if the company is completely opaque."
        )
    )
    geography: FactClaim
    operating_model: FactClaim

class FinalReport(BaseModel):
    company_name: str
    ticker: Optional[str] = None
    website: Optional[str] = None
    overview: Optional[CompanyOverview] = None
    financials: List[FinancialYear] = []
    financials_note: Optional[str] = Field(
        None,
        description="Note regarding availability of financial data."
    )
    products: List[Product] = []
    products_discovery_note: Optional[str] = Field(
        None,
        description=(
            "Fallback note when fewer than the minimum expected products were found. "
            "Format: 'Specific products not found on public pages. Known categories: [list from overview]'"
        )
    )
    clients: ClientsSection = Field(
        default_factory=lambda: ClientsSection(
            named_clients=[],
            disclosure_note="Named clients not publicly disclosed. Checked: annual report, website, press releases."
        )
    )

    class Config:
        json_schema_extra = {
            "example": {
                "company_name": "Acme Industries Limited",
                "ticker": "ACME",
                "website": "https://www.acme.com"
            }
        }
