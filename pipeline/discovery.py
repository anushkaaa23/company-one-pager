from typing import List, Dict
from pydantic import BaseModel
from langchain_community.tools import DuckDuckGoSearchResults

class DiscoveredSource(BaseModel):
    url: str
    title: str
    snippet: str
    source_type: str  # annual_report, company_website, exchange_filing, news, database
    trust_score: float # 0.0 to 1.0

def categorize_url(url: str, title: str, snippet: str, company_website: str = None) -> (str, float):
    url_lower = url.lower()
    title_lower = title.lower()
    
    # Check for regulatory filings
    if "sec.gov" in url_lower or "bseindia" in url_lower or "nseindia" in url_lower:
        return "exchange_filing", 0.95
    
    # Check for annual reports
    if "annual-report" in url_lower or "annual report" in title_lower or url_lower.endswith(".pdf"):
        return "annual_report", 0.90
        
    # Check for official company website
    if company_website and company_website.lower() in url_lower:
        return "company_website", 0.85
        
    # Tier-1 business news
    tier_1_news = ["bloomberg.com", "reuters.com", "ft.com", "wsj.com", "cnbc.com", "economictimes.indiatimes.com"]
    for news_domain in tier_1_news:
        if news_domain in url_lower:
            return "news", 0.80
            
    # Generic news or database
    if "news" in url_lower:
        return "news", 0.25
        
    return "database", 0.40

def discover_sources(company_name: str, company_website: str = None, ticker: str = None) -> List[DiscoveredSource]:
    """
    Search for high-quality sources about the company.
    """
    discovered = []
    seen_urls = set()
    
    is_private = "private" in company_name.lower() or "pvt" in company_name.lower() or (ticker is None and not company_website)
    
    # 1. Company Website
    if company_website:
        url = company_website if company_website.startswith("http") else f"https://{company_website}"
        discovered.append(DiscoveredSource(
            url=url,
            title=f"{company_name} Official Website",
            snippet="Official company website.",
            source_type="company_website",
            trust_score=0.95
        ))
        seen_urls.add(url)
        

        
    # 2. Ticker (Screener.in)
    if ticker:
        clean_ticker = ticker.split('.')[0]
        screener_url = f"https://www.screener.in/company/{clean_ticker}/"
        discovered.append(DiscoveredSource(
            url=screener_url,
            title=f"{company_name} on Screener.in",
            snippet="Financial and company details from Screener.in.",
            source_type="database",
            trust_score=0.90
        ))
        seen_urls.add(screener_url)
        
    # 3. MCA / ACMA for unlisted private companies
    if is_private:
        # MCA
        mca_url = "https://www.mca.gov.in/mcafoportal/viewCompanyMasterData.do"
        discovered.append(DiscoveredSource(
            url=mca_url,
            title="MCA Master Data",
            snippet="MCA basic data (free tier). Does NOT return financials.",
            source_type="database",
            trust_score=0.80
        ))
        seen_urls.add(mca_url)
        
        # ACMA
        acma_url = "https://www.acma.in"
        discovered.append(DiscoveredSource(
            url=acma_url,
            title="ACMA Member Profile",
            snippet="Search for company overview.",
            source_type="database",
            trust_score=0.75
        ))
        seen_urls.add(acma_url)
        
    # 4. Web Search
    from duckduckgo_search import DDGS
    
    if is_private:
        queries = [
            f'"{company_name}" site:economictimes.indiatimes.com',
            f'"{company_name}" revenue business overview',
            f'"{company_name}" annual report'
        ]
    elif not company_website and not ticker:
        queries = [
            f"{company_name} company Ltd annual report filetype:pdf",
            f"{company_name} company investor relations",
            f"{company_name} company products and clients",
            f"{company_name} company business model and operations overview"
        ]
    else:
        queries = [] # Skip search if we have sufficient direct sources for listed companies
        
    for query in queries:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
                for r in results:
                    url = r.get("href", "")
                    title = r.get("title", "")
                    snippet = r.get("body", "")
                    
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    
                    source_type, trust_score = categorize_url(url, title, snippet, company_website)
                    
                    if trust_score < 0.3:
                        continue
                        
                    discovered.append(DiscoveredSource(
                        url=url,
                        title=title,
                        snippet=snippet,
                        source_type=source_type,
                        trust_score=trust_score
                    ))
        except Exception as e:
            print(f"Error searching for query '{query}': {e}")
            
    # Sort by trust score descending
    discovered.sort(key=lambda x: x.trust_score, reverse=True)

    return discovered

def discover_targeted_sources(company_name: str, missing_fields: List[str], seen_urls: set) -> List[DiscoveredSource]:
    """
    Search specifically for missing fields.
    """
    from duckduckgo_search import DDGS
    discovered = []
    
    queries = []
    for field in missing_fields:
        clean_field = field.replace('_', ' ')
        queries.append(f'"{company_name}" {clean_field}')
        
    for query in queries:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3))
                for r in results:
                    url = r.get("href", "")
                    title = r.get("title", "")
                    snippet = r.get("body", "")
                    
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    
                    source_type, trust_score = categorize_url(url, title, snippet, "")
                    if trust_score < 0.2:
                        continue
                        
                    discovered.append(DiscoveredSource(
                        url=url,
                        title=title,
                        snippet=snippet,
                        source_type=source_type,
                        trust_score=trust_score
                    ))
        except Exception as e:
            print(f"Error searching for targeted query '{query}': {e}")
            
    discovered.sort(key=lambda x: x.trust_score, reverse=True)
    return discovered

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Discover sources for a company.")
    parser.add_argument("company_name", help="Full company name (e.g. 'Tata Motors Limited')")
    parser.add_argument("--website", default=None, help="Company website domain (e.g. 'tatamotors.com')")
    parser.add_argument("--ticker", default=None, help="Stock ticker symbol (e.g. 'TATAMOTORS')")
    args = parser.parse_args()

    sources = discover_sources(args.company_name, args.website, args.ticker)
    for s in sources:
        print(f"[{s.trust_score}] {s.source_type}: {s.url}")
