"""
Debug script: Shows exactly what the retrieval pipeline fetches and passes to the LLM.
Run with: python3 debug_retrieval.py "Tata Motors Limited" --ticker TATAMOTORS --website www.tatamotors.com
"""
import sys
import os
import argparse
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from pipeline.discovery import discover_sources
from pipeline.extraction import extract_text_from_url
from pipeline.entity_resolution import resolve_entity

parser = argparse.ArgumentParser(description="Debug retrieval pipeline for any company.")
parser.add_argument("company_name", help="Full company name (e.g. 'Tata Motors Limited')")
parser.add_argument("--ticker", default=None, help="Stock ticker (e.g. 'TATAMOTORS')")
parser.add_argument("--website", default=None, help="Company website (e.g. 'www.tatamotors.com')")
args = parser.parse_args()

company_name = args.company_name
ticker = args.ticker
website = args.website

print("=" * 80)
print("STEP 1: ENTITY RESOLUTION")
print("=" * 80)
try:
    entity = resolve_entity(company_name, website, ticker)
    print(f"  Resolved name:    {entity.company_name}")
    print(f"  Resolved ticker:  {entity.ticker}")
    print(f"  Resolved website: {entity.website}")
    print(f"  Confidence:       {entity.confidence}")
except Exception as e:
    print(f"  FAILED: {e}")

print()
print("=" * 80)
print("STEP 2: SOURCE DISCOVERY")
print("=" * 80)
sources = discover_sources(company_name, website)
print(f"  Total sources discovered: {len(sources)}")
for i, s in enumerate(sources):
    print(f"\n  [{i+1}] {s.source_type} (trust: {s.trust_score})")
    print(f"      URL:     {s.url}")
    print(f"      Title:   {s.title}")
    print(f"      Snippet: {s.snippet[:120]}...")

print()
print("=" * 80)
print("STEP 3: TEXT EXTRACTION (per source)")
print("=" * 80)
context_chunks = []
for i, s in enumerate(sources[:3]):  # Same limit as main.py
    print(f"\n  --- Source [{i+1}]: {s.url} ---")
    text = extract_text_from_url(s.url)
    char_count = len(text)
    word_count = len(text.split())
    approx_tokens = int(word_count * 1.3)  # rough estimate
    
    print(f"  Characters extracted: {char_count:,}")
    print(f"  Word count:          {word_count:,}")
    print(f"  Approx tokens:       ~{approx_tokens:,}")
    print(f"  First 500 chars:")
    print(f"  {'─' * 60}")
    print(f"  {text[:500]}")
    print(f"  {'─' * 60}")
    print(f"  Last 300 chars:")
    print(f"  {'─' * 60}")
    print(f"  {text[-300:]}")
    print(f"  {'─' * 60}")
    
    if text:
        context_chunks.append({"url": s.url, "type": s.source_type, "text": text})

print()
print("=" * 80)
print("STEP 4: WHAT GETS SENT TO GEMINI")
print("=" * 80)
if context_chunks:
    combined_context = "\n\n".join([f"Source: {c['url']}\n\n{c['text'][:8000]}" for c in context_chunks])
    print(f"  Number of source chunks:     {len(context_chunks)}")
    print(f"  Combined context characters: {len(combined_context):,}")
    print(f"  Combined context words:      {len(combined_context.split()):,}")
    print(f"  Approx tokens sent to LLM:   ~{int(len(combined_context.split()) * 1.3):,}")
    print(f"\n  Truncation per source:       8,000 chars (from extract limit of 20,000)")
else:
    print("  NO TEXT EXTRACTED — LLM receives nothing useful!")

print()
print("=" * 80)
print("DIAGNOSIS")
print("=" * 80)
if not sources:
    print("  ❌ DuckDuckGo returned 0 results (rate limited).")
    print("     The pipeline fell back to guessing the homepage URL.")
elif all(s.source_type == "company_website" for s in sources):
    print("  ⚠️  Only company website found (no annual reports or filings).")
    print("     DuckDuckGo may be rate-limiting. The LLM only sees homepage text.")
    
if context_chunks:
    for c in context_chunks:
        if len(c["text"]) < 500:
            print(f"  ⚠️  Very little text from {c['url']} ({len(c['text'])} chars)")
            print(f"     This URL might be JavaScript-heavy or require login.")
        if len(c["text"]) > 5000:
            print(f"  ✅ Good text volume from {c['url']} ({len(c['text']):,} chars)")

print()
