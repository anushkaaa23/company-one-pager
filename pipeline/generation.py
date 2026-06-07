import json
from typing import Dict
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas.models import FinalReport, FactClaim, ClientsSection

def format_fact(fact: FactClaim) -> str:
    if fact.confidence == "NOT_FOUND":
        note = ""
        if fact.verification_note:
            note = f"\n> **Note**: {fact.verification_note}"
        return f"{fact.claim}{note}\n"
    
    conf_badge = {"HIGH": "🟢 HIGH", "MEDIUM": "🟡 MEDIUM", "LOW": "🔴 LOW"}.get(fact.confidence, fact.confidence)
    result = f"{fact.claim}\n> **Source**: [{fact.source_type}]({fact.source_url})\n> **Excerpt**: \"{fact.source_excerpt}\"\n> **Confidence**: {conf_badge}\n"
    if fact.confidence == "LOW" and fact.verification_note:
        result += f"> ⚠️ {fact.verification_note}\n"
    return result

def generate_markdown(report: FinalReport) -> str:
    md = f"# Company One-Pager: {report.company_name}\n\n"
    if report.ticker:
        md += f"**Ticker**: {report.ticker} | "
    if report.website:
        md += f"**Website**: [{report.website}]({report.website})\n\n"
    
    md += "---\n\n## 1. Company Overview\n\n"
    
    if report.overview:
        md += "### What the company does\n"
        md += format_fact(report.overview.what_company_does) + "\n"
        md += "### Business Model\n"
        md += format_fact(report.overview.business_model) + "\n"
        md += "### Products & Services\n"
        md += format_fact(report.overview.products_services) + "\n"
        md += "### Industries Served\n"
        md += format_fact(report.overview.industries_served) + "\n"
        md += "### Geography\n"
        md += format_fact(report.overview.geography) + "\n"
        md += "### Operating Model\n"
        md += format_fact(report.overview.operating_model) + "\n"
    else:
        md += "NOT FOUND — extraction failed for all discovered sources.\n\n"
        
    md += "---\n\n## 2. Financial Snapshot\n\n"
    
    if report.financials:
        md += "| Year | Revenue | EBITDA | EBITDA Margin | Net Income | Debt | Leverage |\n"
        md += "|---|---|---|---|---|---|---|\n"
        for fy in report.financials:
            md += f"| {fy.year} | {fy.revenue} | {fy.ebitda} | {fy.ebitda_margin} | {fy.net_income} | {fy.debt} | {fy.leverage_metric} |\n"
        md += "\n> *Source: Yahoo Finance (yfinance)*\n\n"
    else:
        md += "NOT FOUND — no financial data available via yfinance.\n\n"
        
    md += "---\n\n## 3. Products & Clients\n\n"
    
    md += "### Key Products\n"
    if report.products:
        for p in report.products:
            md += f"**{p.name.claim}**\n"
            md += format_fact(p.description) + "\n"
    else:
        md += "Specific named products not found in available sources. Only generic category names were present.\n\n"
        
    md += "### Notable Clients\n"
    if isinstance(report.clients, ClientsSection):
        if report.clients.named_clients:
            for c in report.clients.named_clients:
                md += f"**{c.name.claim}**\n"
                md += format_fact(c.relationship_description) + "\n"
        if report.clients.disclosure_note:
            md += f"\n> ℹ️ {report.clients.disclosure_note}\n\n"
    else:
        md += "NOT FOUND — no client data available.\n\n"
        
    return md

def save_report(report: FinalReport, output_dir: str = "outputs"):
    os.makedirs(output_dir, exist_ok=True)
    slug = report.company_name.lower().replace(" ", "_")
    
    # Save MD
    md_path = os.path.join(output_dir, f"{slug}_report.md")
    with open(md_path, "w") as f:
        f.write(generate_markdown(report))
        
    # Save JSON
    json_path = os.path.join(output_dir, f"{slug}_report.json")
    with open(json_path, "w") as f:
        f.write(report.model_dump_json(indent=2))
        
    return md_path, json_path
