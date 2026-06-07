"""
Product Discovery Module
========================
Probes company-website URL paths to find product/service pages,
fetches their text, and returns structured results for LLM extraction.
"""

import re
from typing import List, Optional
from urllib.parse import urlparse, urljoin
from pydantic import BaseModel
from pipeline.extraction import extract_text_from_url


class ProductPageResult(BaseModel):
    url: str
    text: str
    source_label: str  # e.g. "/products", "/solutions", "screener_about"


# ── URL path templates ────────────────────────────────────────────────
# Order matters: more specific paths first.
BASE_PRODUCT_PATHS = [
    "/products",
    "/products-services",
    "/businesses",
    "/solutions",
    "/offerings",
]

IT_EXTRA_PATHS = [
    "/services",
    "/industries",
]


# ── IT-company heuristic ──────────────────────────────────────────────
_IT_KEYWORDS = re.compile(
    r"\b(information technology|IT services|software services|digital transformation"
    r"|consulting & technology|systems integration|cloud services|managed services"
    r"|technology solutions|BPO|business process outsourcing|tech services)\b",
    re.IGNORECASE,
)


def is_it_company(
    industry: Optional[str] = None,
    description: Optional[str] = None,
    company_name: Optional[str] = None,
) -> bool:
    """Heuristic: returns True when the entity looks like an IT-services firm.

    Checks the industry field first, then falls back to keyword matching
    against the company description or name.
    """
    for text in (industry, description, company_name):
        if text and _IT_KEYWORDS.search(text):
            return True
    return False


# ── Core discovery logic ──────────────────────────────────────────────

def _normalise_base(website: str) -> str:
    """Ensure the website string is a proper base URL with scheme."""
    if not website:
        return ""
    url = website.strip().rstrip("/")
    if not url.startswith("http"):
        url = f"https://{url}"
    return url


def _probe_url(base: str, path: str) -> Optional[ProductPageResult]:
    """Try to fetch text from base+path. Returns None on failure or empty text."""
    target = urljoin(base + "/", path.lstrip("/"))
    print(f"  Probing product page: {target}")
    try:
        text = extract_text_from_url(target)
        if text and len(text.strip()) > 200:
            return ProductPageResult(url=target, text=text, source_label=path)
    except Exception as e:
        print(f"  Probing failed for {target}: {e}")
    return None


def _extract_screener_about(screener_text: str) -> Optional[str]:
    """Pull the 'About' block out of a Screener.in page dump.

    Screener pages typically contain a section starting with the company's
    description paragraph right after the financials table.  We look for
    a block that starts with common preamble phrases.
    """
    if not screener_text:
        return None
    # Try to isolate the About / company description section
    markers = ["About\n", "Company overview", "About the company"]
    lower = screener_text.lower()
    for marker in markers:
        idx = lower.find(marker.lower())
        if idx != -1:
            block = screener_text[idx:idx + 3000]
            if len(block.strip()) > 100:
                return block.strip()
    # Fallback: return first 2000 chars (often contains the description)
    return screener_text[:2000].strip() if len(screener_text) > 100 else None


def discover_product_pages(
    website: str,
    company_name: str,
    industry: Optional[str] = None,
    description: Optional[str] = None,
    screener_text: Optional[str] = None,
) -> List[ProductPageResult]:
    """Probe a company website for product/service pages.

    Args:
        website:        The company's base URL (e.g. "https://www.infosys.com").
        company_name:   Canonical company name for IT heuristic.
        industry:       Industry string from entity resolution (optional).
        description:    Company description text for IT heuristic (optional).
        screener_text:  Raw text already fetched from Screener.in (optional).

    Returns:
        A list of ProductPageResult with URL + extracted text,
        ordered by discovery priority.
    """
    results: List[ProductPageResult] = []
    base = _normalise_base(website)

    if not base:
        # No website — can only check Screener
        if screener_text:
            about = _extract_screener_about(screener_text)
            if about:
                results.append(ProductPageResult(
                    url="screener.in",
                    text=about,
                    source_label="screener_about",
                ))
        return results

    # Build the list of paths to try
    paths = list(BASE_PRODUCT_PATHS)
    if is_it_company(industry=industry, description=description, company_name=company_name):
        print(f"  IT-company heuristic triggered for '{company_name}' — adding /services & /industries")
        paths.extend(IT_EXTRA_PATHS)

    # Probe each path
    for path in paths:
        result = _probe_url(base, path)
        if result:
            results.append(result)

    # Screener.in About as fallback for products (only if website paths yielded nothing)
    if not results and screener_text:
        about = _extract_screener_about(screener_text)
        if about:
            print("  Using Screener.in About section as product fallback")
            results.append(ProductPageResult(
                url="screener.in",
                text=about,
                source_label="screener_about",
            ))

    print(f"  Product discovery found {len(results)} page(s): "
          f"{[r.source_label for r in results]}")
    return results
