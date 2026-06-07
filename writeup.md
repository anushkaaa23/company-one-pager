# Project Write-Up: System Reflection & Trade-Offs

## What Didn't Work

1. **Scraping Tables from Unstructured PDFs**
This was the first thing that broke badly. The plan was to parse Annual Reports and extract financial tables directly, but feeding 300-page PDF blobs into a context window consistently produced distorted layouts and hallucinated numbers — the LLM would confidently reconstruct a table that didn't quite exist. Switching to `yfinance` for deterministic financial data was an easy decision in hindsight, but it took a few bad outputs to get there.

2. **DuckDuckGo for Product Images and Logos**
Text-based search snippets are just not reliable enough for this. Without a dedicated Image Search API or direct scraping of the company's `/media` page, attaching verifiable product imagery consistently isn't possible. I dropped this rather than ship something that guesses.

3. **Cloudflare / Bot Protection**
Standard HTTP requests (`requests`, `trafilatura`) hit `403 Forbidden` walls on a surprising number of official corporate sites. Playwright handles most of it, but some pages are genuinely inaccessible without more aggressive workarounds I wasn't willing to build yet.

---

## The Trade-Offs

### 1. Cost vs. Extraction Depth
The system caps extraction at the top 3 sources and truncates text chunks. This means long-tail client names or niche products buried deep in a 200-page PDF will get missed. That's a real gap — but given that a hallucinated datapoint is a worse outcome than a missing one, I'd make this trade-off again. Speed and verified accuracy over completeness.

### 2. Latency vs. Accuracy
The pipeline runs sequentially: Entity Resolution → Search → Download → Extraction → Verification. It's slower than running searches in parallel, but the accuracy benefit is real — each step is informed by what came before it. Parallelizing early would introduce noise if the ticker or canonical website was slightly misresolved at the start, and that error compounds downstream.

### 3. Strict Typing vs. Flexibility
Forcing every output into a Pydantic `FactClaim` schema — with a mandatory confidence score and verbatim source excerpt — means the system sometimes reads stiffly. It won't write a flowing business model paragraph if it can't find the source. That's a deliberate choice and I think the right one, but it does make the output feel more like a structured database entry than an analyst's note.

---

## What I'd Build Next

**RAG / Vector Database Ingestion** is the highest-priority fix. Right now the system does naive text chunking, which is why facts buried deep in Annual Reports get missed. Building an async worker to ingest discovered PDFs into a FAISS or ChromaDB vector store — and querying it for specific concepts like "key customers" or "segment margins" — would meaningfully close that gap without blowing up token costs.

After that, a **Confidence Feedback Loop**: a second "Critic" LLM that checks each `FactClaim` against its `source_excerpt` and flags over-extrapolations before final output. It's a smaller change but would catch the kind of subtle drift — where the claim is *technically* supported by the excerpt but slightly overstates it — that the current verification layer misses.
