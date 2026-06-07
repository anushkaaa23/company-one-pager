import requests
import trafilatura
import yfinance as yf
from bs4 import BeautifulSoup
from typing import List, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas.models import FactClaim, CompanyOverview, Product, Client, ClientsSection, FinancialYear
from pipeline.llm_helper import invoke_with_retry

def _url_variants(url: str) -> List[str]:
    """Generate alternate URL variants to try when the primary URL fails."""
    from urllib.parse import urlparse
    variants = [url]
    parsed = urlparse(url)
    host = parsed.hostname or ""
    
    # Try stripping www
    if host.startswith("www."):
        bare = url.replace("://www.", "://", 1)
        variants.append(bare)
    else:
        # Try adding www
        www = url.replace("://", "://www.", 1)
        variants.append(www)
    
    # Try http if https
    if url.startswith("https://"):
        for v in list(variants):
            variants.append(v.replace("https://", "http://", 1))
    
    return variants

def extract_text_from_url(url: str) -> str:
    """Download and extract raw text from a URL using Playwright (HTML) or requests (PDF)."""
    import io
    import pdfplumber
    from playwright.sync_api import sync_playwright
    
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    
    last_exception = None
    
    for variant_url in _url_variants(url):
        try:
            # Try requests first to easily detect and handle PDFs
            try:
                response = requests.get(variant_url, timeout=10, headers=headers, stream=True)
                if response.status_code == 200:
                    content_type = response.headers.get("content-type", "").lower()
                    if "application/pdf" in content_type or variant_url.lower().endswith(".pdf"):
                        content = response.content
                        with pdfplumber.open(io.BytesIO(content)) as pdf:
                            text = "\n".join(page.extract_text() or "" for page in pdf.pages[:20])
                        if text.strip():
                            if variant_url != url:
                                print(f"  (fetched PDF via alternate URL: {variant_url})")
                            return text[:40000]
                        continue
            except Exception:
                # If requests fails (e.g. 403), we still want to try Playwright
                pass
                
            # If it's a regular webpage, use Playwright to handle JS rendering
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                try:
                    page.goto(variant_url, timeout=20000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)  # brief wait for dynamic content
                    text = page.evaluate("document.body.innerText")
                    if text and len(text.strip()) > 100:
                        if variant_url != url:
                            print(f"  (fetched via alternate URL: {variant_url})")
                        return text[:40000]
                finally:
                    browser.close()
                    
        except Exception as e:
            last_exception = e
            continue
            
    # If all variants failed, raise an exception to be caught by the main pipeline
    error_msg = f"{type(last_exception).__name__}: {str(last_exception)}" if last_exception else "Empty response"
    raise Exception(error_msg)

def extract_financials(ticker: Optional[str]) -> List[FinancialYear]:
    """Fetch financial data from yfinance if a ticker is available."""
    if not ticker:
        return []
    
    def try_fetch(t):
        try:
            ticker_obj = yf.Ticker(t)
            if ticker_obj.financials is not None and not ticker_obj.financials.empty:
                is_inr = False
                if t.endswith('.NS') or t.endswith('.BO'):
                    is_inr = True
                else:
                    try:
                        info = ticker_obj.info
                        if info:
                            country = info.get('country', '').lower()
                            currency = info.get('currency', '').upper()
                            exchange = info.get('exchange', '').upper()
                            if country == 'india' or currency == 'INR' or exchange in ['NSI', 'BSE', 'NSE']:
                                is_inr = True
                    except:
                        pass
                return ticker_obj.financials, ticker_obj.balance_sheet, is_inr
        except Exception:
            pass
        return None, None, False

    financials, balance_sheet, is_inr = try_fetch(ticker)
    if financials is None:
        financials, balance_sheet, is_inr = try_fetch(f"{ticker}.NS")
        if financials is None:
            financials, balance_sheet, is_inr = try_fetch(f"{ticker}.BO")
            if financials is None:
                return []
                
    try:
        years_data = []
        for col in financials.columns[:4]:  # Last 4 years
            year = col.year
            rev = financials.loc["Total Revenue", col] if "Total Revenue" in financials.index else None
            net_inc = financials.loc["Net Income", col] if "Net Income" in financials.index else None
            ebitda = financials.loc["EBITDA", col] if "EBITDA" in financials.index else None
            
            ebitda_margin = None
            if ebitda and rev and rev != 0:
                ebitda_margin = f"{(ebitda / rev) * 100:.1f}%"
                
            debt = balance_sheet.loc["Total Debt", col] if (balance_sheet is not None and "Total Debt" in balance_sheet.index) else None
            
            def fmt(val):
                if val is None or str(val).lower() == 'nan':
                    return "NOT FOUND — not in available financial data"
                if is_inr:
                    return f"₹{val / 10000000:,.1f} Cr"
                return f"${val / 1000000:,.1f}M"
                
            years_data.append(FinancialYear(
                year=year,
                revenue=fmt(rev),
                ebitda=fmt(ebitda),
                ebitda_margin=ebitda_margin or "NOT FOUND — not in available financial data",
                net_income=fmt(net_inc),
                debt=fmt(debt)
            ))
            
        return years_data
    except Exception as e:
        print(f"Error fetching financials for {ticker}: {e}")
        return []

# ─── FIX 2 + FIX 4 + FIX 5 + FIX 6 ──────────────────────────────────────────
OVERVIEW_SYSTEM_PROMPT = """You are a senior financial analyst AI tasked with extracting VERIFIED facts only.

RULES (non-negotiable):
1. Extract ONLY from the provided context text. Never use prior knowledge.
2. Confidence levels: HIGH = verbatim in annual report/10-K/filing. MEDIUM = credible secondary source (Reuters, Bloomberg, ET, analyst note, press release). LOW = single unverified source (add verification_note: "Single source — verify independently"). NOT_FOUND = could not be verified.
3. For business_model: Read DEEPER than the opening paragraph. Look for: how revenue is earned, who it sells to (OEMs/consumers/enterprises), sales channel (direct/dealer/distributor), manufacturing model (in-house/outsourced/JV), domestic vs export split. Only mark NOT_FOUND after checking all of those angles in the text.
4. For industries_served: Check segment notes, end-market descriptions. This should almost never be NOT_FOUND for a listed company.
5. If a field is truly NOT_FOUND, write: "NOT FOUND — [specific sections you checked in the provided text]". This is the honest answer.
6. Never write a plausible-sounding guess. An honest gap beats a fabricated answer every time.
7. CONFLICT RESOLUTION: If two sources give different figures for the same field (e.g. plant count), do NOT silently pick one. Flag it explicitly: "Source conflict: [source A] states X, [source B] states Y. Unresolved — verify against latest company disclosure."
"""

def extract_overview(company_name: str, context: str, source_url: str, source_type: str) -> CompanyOverview:
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    
    user_prompt = "Company: {company_name}\nSource URL: {source_url}\nSource Type: {source_type}\n\nContext Text:\n{context}"

    prompt = ChatPromptTemplate.from_messages([
        ("system", OVERVIEW_SYSTEM_PROMPT),
        ("user", user_prompt)
    ])
    
    chain = prompt | llm.with_structured_output(CompanyOverview)
    try:
        return invoke_with_retry(chain, {
            "company_name": company_name,
            "source_url": source_url,
            "source_type": source_type,
            "context": context
        })
    except Exception as e:
        print(f"Failed to extract overview from {source_url}: {e}")
        return None

# ─── PRODUCT EXTRACTION FROM DEDICATED PRODUCT PAGES ─────────────────────────
PRODUCT_PAGE_SYSTEM_PROMPT = """You are a senior financial analyst AI extracting SPECIFIC product information from a company's product/services page.

PRODUCT RULES (strict):
1. Extract ONLY specifically named products or services (e.g. "Finacle", "EdgeVerve AssistEdge", "McCormick Tractors", "NIA Platform").
2. NEVER list generic category names like "consulting", "digital services", "automotive", "forgings" as products.
3. Each product MUST have ALL of:
   - name: The specific, named product or service line
   - description: One sentence — what it does AND who buys it
   - industry_served: Which industry or customer segment it targets
4. If you cannot find a description for a named product, DO NOT include it.
5. If ONLY category names are available (no specific named products), return an EMPTY list.
6. For IT companies: Named service lines (e.g. "Infosys BPM", "Cobalt Cloud") count as products.

CONFIDENCE RULES:
- HIGH = found on the company's own website (product page, solutions page).
- MEDIUM = found in credible news, press release, or analyst note.
- LOW = single unverified source. Add verification_note: "Single source — verify independently".

SOURCE TRACKING:
- Set source_url to the EXACT page URL where the product was found.
- Set source_excerpt to the verbatim text snippet that names/describes the product.

HONESTY:
- Never guess. A gap is better than a fabrication.
- If only 1-2 products can be found, that is an honest answer. Do not pad with categories.
"""

class ProductExtractionContainer(BaseModel):
    products: List[Product]

def extract_products_from_product_pages(
    company_name: str,
    product_contexts: list,  # List of {"url": str, "text": str, "label": str}
) -> List[Product]:
    """Extract structured products from dedicated product page contexts.

    Args:
        company_name: The company name.
        product_contexts: List of dicts with url, text, label from product_discovery.

    Returns:
        List of Product objects with source URLs pointing to the exact product page.
    """
    if not product_contexts:
        return []

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

    # Combine all product page texts with clear source annotations
    combined = "\n\n".join([
        f"─── Source: {ctx['url']} ({ctx['label']}) ───\n{ctx['text'][:6000]}"
        for ctx in product_contexts
    ])

    prompt = ChatPromptTemplate.from_messages([
        ("system", PRODUCT_PAGE_SYSTEM_PROMPT),
        ("user", (
            "Company: {company_name}\n\n"
            "Product Page Content:\n{context}\n\n"
            "Extract every specifically named product or service you can find. "
            "Set source_url to the exact page URL for each product."
        ))
    ])

    chain = prompt | llm.with_structured_output(ProductExtractionContainer)
    try:
        res = invoke_with_retry(chain, {
            "company_name": company_name,
            "context": combined,
        })
        return res.products
    except Exception as e:
        print(f"Failed to extract products from product pages: {e}")
        return []


# ─── FALLBACK: PRODUCTS FROM GENERAL CONTEXT ─────────────────────────────────
PRODUCTS_FALLBACK_SYSTEM_PROMPT = """You are a senior financial analyst AI. The company's product pages could not be found.
Extract any SPECIFIC, named products or services you can find in the provided general context text.

RULES:
1. Only extract specifically named products (e.g. "Finacle", "Crankshaft for CV engines"), NOT categories.
2. Each product needs a name, description (what it does + who buys it), and industry_served.
3. If only categories are found, return an EMPTY list — do not fabricate product names.
4. Set confidence to MEDIUM (since this is from general context, not a dedicated product page).
"""

def extract_products_fallback(company_name: str, context: str, source_url: str, source_type: str) -> List[Product]:
    """Fallback: try to extract products from general context (overview text)."""
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

    prompt = ChatPromptTemplate.from_messages([
        ("system", PRODUCTS_FALLBACK_SYSTEM_PROMPT),
        ("user", "Company: {company_name}\nSource URL: {source_url}\nSource Type: {source_type}\n\nContext Text:\n{context}")
    ])

    chain = prompt | llm.with_structured_output(ProductExtractionContainer)
    try:
        res = invoke_with_retry(chain, {
            "company_name": company_name,
            "source_url": source_url,
            "source_type": source_type,
            "context": context,
        })
        return res.products
    except Exception as e:
        print(f"Failed to extract products (fallback) from {source_url}: {e}")
        return []


# ─── CLIENT EXTRACTION (separated from products) ─────────────────────────────
CLIENTS_SYSTEM_PROMPT = """You are a senior financial analyst AI tasked with extracting VERIFIED client information only.

CLIENT RULES:
- Check in order: "Customers" section, MD&A (often names top customers), press releases for order wins/supply agreements, website case studies.
- For auto-component companies: OEM relationships (Tata, Maruti, Cummins, Daimler etc.) often appear in annual reports or press releases.
- If named clients are found → list them with relationship description and source.
- If named clients are NOT publicly available after checking all sources → set disclosure_note to: "Named clients not publicly disclosed. Verified customer segments: [list the sectors you did find, with source]"
- NEVER return both named_clients empty AND disclosure_note empty. One of them must always be populated.

CONFIDENCE RULES:
- HIGH = verbatim in annual report, 10-K, exchange filing.
- MEDIUM = credible secondary source (Reuters, Bloomberg, ET, analyst note, press release).
- LOW = single unverified source. Add verification_note: "Single source — verify independently".
- NOT_FOUND = cannot be verified.

HONESTY:
- Never fill a gap with a plausible-sounding guess.
- A claim you cannot source → NOT_FOUND with reason.
"""

def extract_clients(company_name: str, context: str, source_url: str, source_type: str) -> ClientsSection:
    """Extract client information from general context."""
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

    user_prompt = "Company: {company_name}\nSource URL: {source_url}\nSource Type: {source_type}\n\nContext Text:\n{context}"
    


    prompt = ChatPromptTemplate.from_messages([
        ("system", CLIENTS_SYSTEM_PROMPT),
        ("user", user_prompt)
    ])

    chain = prompt | llm.with_structured_output(ClientsSection)
    try:
        return invoke_with_retry(chain, {
            "company_name": company_name,
            "source_url": source_url,
            "source_type": source_type,
            "context": context,
        })
    except Exception as e:
        print(f"Failed to extract clients from {source_url}: {e}")
        return ClientsSection(
            named_clients=[],
            disclosure_note="Named clients not publicly disclosed. Checked: annual report, website, press releases."
        )
