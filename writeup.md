# Project Write-Up: System Reflection & Trade-Offs

## What Didn't Work

1. **Scraping Tables from Unstructured PDFs**: Initially, the plan was to parse Annual Reports to dynamically extract complex financial tables. However, parsing massive 300-page PDF blobs into context windows frequently resulted in distorted layouts and hallucinated values when the LLM attempted to reconstruct tabular data. I realized that for deterministic financial data, leaning on a trusted API (`yfinance`) was vastly superior to pure extraction.
2. **DuckDuckGo for Specific Image Logos**: Attempting to grab product images and client logos purely through text-based search snippets proved unreliable. A dedicated Image Search API or programmatic scraping of the company's `/media` or `/investors` page would be required to consistently attach verifiable product imagery without guessing.
3. **Handling Cloudflare/Bot-Protection**: Relying purely on standard HTTP requests (`requests` and `trafilatura`) often resulted in `403 Forbidden` errors on official corporate sites. 

## The Trade-Offs

### 1. Cost vs. Extraction Depth
Processing entire annual reports or all indexed pages of a company website is extremely token-heavy. The current system limits extraction to the top 3 discovered sources and truncates text chunks.
**Trade-off**: This drastically reduces latency and API costs, but risks missing long-tail client names or niche product lines hidden deep in a 200-page PDF. Given the directive that a hallucinated datapoint is a failure, sacrificing completeness for speed and cost is the correct move here—what *is* extracted is heavily verified, even if some edge-case data is missed.

### 2. Latency vs. Accuracy
The pipeline currently runs sequentially: Entity Resolution -> Search -> Download -> Extraction -> Verification.
**Trade-off**: While this takes a few seconds to run, it ensures high accuracy because the search queries are dynamically informed by the initial Entity Resolution phase. Running all searches in parallel initially could improve speed but would lead to higher noise if the canonical website or ticker was slightly misinterpreted.

### 3. Strict Typing vs. Flexibility
By forcing the LLM to output Pydantic schemas where every field must be a `FactClaim` (enforcing a `confidence` score and a `source_excerpt`), I traded away conversational flexibility. 
**Trade-off**: The system will flat out refuse to write a flowing paragraph for the "Business Model" if it can't find it, opting to rigidly return "Not found in available sources." While this reads less like a human analyst's prose, it guarantees 100% adherence to the core hallucination-prevention constraints.

## What I'd Build Next

1. **RAG / Vector Database Ingestion**: Instead of naive text chunking, I would build an async worker to ingest all discovered PDFs (SEC filings, Annual Reports) into a local FAISS or ChromaDB vector store. The extraction layer would then query this database for specific vectors ("key customers", "revenue margins") rather than relying on massive context windows.
2. **Headless Browser Scraping**: Replace `requests/trafilatura` with `Playwright`. This would easily bypass Cloudflare blocks and allow the system to wait for dynamic JavaScript tables to render on Investor Relations pages.
3. **Confidence Feedback Loop**: Implement a multi-agent debate step where an independent "Critic" LLM checks the generated `FactClaim` against the `source_excerpt`. If the Critic finds that the claim is an over-extrapolation of the excerpt, it explicitly downgrades the confidence score below the `0.5` threshold before the final output is compiled.
