# Company One-Pager Generator

This repository contains a production-ready AI pipeline designed to generate fully sourced, accurate, and hallucination-free company one-pagers based on minimal input (Company Name).

The system prioritizes **factual traceability** above all else. Every generated claim is strictly coupled to a source URL and a confidence score. If a datapoint cannot be verified, the system aggressively defaults to `"Not found in available sources."`

---

## 1. Setup & Running the Code

### Prerequisites
- Python 3.9+
- A Google API Key (required for structured extraction via `gemini-2.5-flash`)

### Installation
```bash
# Clone the repository
git clone <repository-url>
cd company-one-pager

# Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright's Chromium browser (required for JS-rendered pages)
playwright install chromium
```

### Configuration
Copy the example env file and add your API key:
```bash
cp .env.example .env
# Then edit .env and replace with your real Google API key
```

`.env` contents:
```
GOOGLE_API_KEY=your_google_api_key_here
```

### Running the API
Start the FastAPI server:
```bash
python app/main.py
```
*The server will start on `http://localhost:8000`. Visit `http://localhost:8000/docs` for the interactive Swagger UI.*

### Generating a Report
In a new terminal window, send a POST request with the company name.

**Example 1: Listed company (with ticker)**
```bash
curl -X POST "http://localhost:8000/generate" \
     -H "Content-Type: application/json" \
     -d '{"company_name": "Bharat Forge Limited", "ticker": "BHARATFORG", "website": "https://www.bharatforge.com"}'
```

**Example 2: Unlisted private company**
```bash
curl -X POST "http://localhost:8000/generate" \
     -H "Content-Type: application/json" \
     -d '{"company_name": "Brakes India Private Limited", "website": "https://www.brakesindia.com"}'
```

**Optional parameters:**
| Parameter | Type | Description |
|---|---|---|
| `company_name` | string (required) | Full legal name of the company |
| `ticker` | string (optional) | Stock ticker (e.g. `BHARATFORG`). Enables financial data fetch. |
| `website` | string (optional) | Official company website URL |
| `min_products` | int (optional, default: 3) | Minimum products before fallback note is triggered |

The pipeline logs progress to your console and saves Markdown + JSON reports in the `outputs/` directory.

### Debugging
To inspect what the pipeline fetches for any company before running the full extraction:
```bash
python debug_retrieval.py "Tata Motors Limited" --ticker TATAMOTORS --website www.tatamotors.com
```

---

## 2. Project Structure

```
company-one-pager/
├── app/
│   └── main.py              # FastAPI server & orchestration pipeline
├── pipeline/
│   ├── entity_resolution.py # Resolves company → canonical ticker, website, type
│   ├── discovery.py         # Finds and ranks high-trust sources
│   ├── extraction.py        # Fetches text, extracts financials & facts via LLM
│   ├── product_discovery.py # Probes company website for product/service pages
│   ├── verification.py      # Anti-hallucination layer — enforces confidence rules
│   ├── generation.py        # Renders verified facts into Markdown + JSON
│   └── llm_helper.py        # Retry logic for Gemini API rate limits
├── schemas/
│   └── models.py            # Pydantic data models (FactClaim, FinalReport, etc.)
├── evaluation/              # Sample outputs for benchmark companies
├── json/                    # Structured JSON outputs for benchmark companies
├── debug_retrieval.py       # CLI tool to inspect pipeline retrieval step-by-step
├── .env.example             # Template for environment variables
├── requirements.txt         # Pinned Python dependencies
└── writeup.md               # Architectural trade-offs and design decisions
```

---

## 3. Architecture Overview

The system is a modular Python pipeline exposed via a FastAPI backend. Each step is explicitly separated to enforce strict fact-checking boundaries.

1. **Entity Resolution** (`pipeline/entity_resolution.py`): Infers canonical ticker, website URL, and company type (Public/Private) using DuckDuckGo search + LLM evaluation. Accepts user-provided hints to skip search if already known.
2. **Source Discovery** (`pipeline/discovery.py`): Builds a ranked list of high-trust sources — BSE/NSE filings, Annual Report PDFs, official company domains, and Tier-1 business news. Each source gets a `trust_score` (0–1).
3. **Extraction** (`pipeline/extraction.py`):
   - Uses **Playwright** (headless Chromium) to render JS-heavy corporate sites, with `pdfplumber` for PDF annual reports.
   - Uses **`yfinance`** to fetch numerical financial data directly — bypassing LLM hallucination for numbers entirely.
   - Uses **LangChain + Pydantic** to extract qualitative facts into rigid `FactClaim` schemas (every claim requires a `source_url`, `source_excerpt`, and `confidence` level).
4. **Product Discovery** (`pipeline/product_discovery.py`): Probes standard URL paths (`/products`, `/solutions`, `/businesses`) on the company website to find dedicated product pages before falling back to general context.
5. **Verification Layer** (`pipeline/verification.py`): The core anti-hallucination mechanism. Enforces confidence rules — any `NOT_FOUND` or unsupported claim is replaced with an honest gap message. `LOW` confidence claims are flagged with a note.
6. **Generation** (`pipeline/generation.py`): Compiles verified facts into a structured Markdown report and a machine-readable JSON file.

---

## 4. Self-Evaluation: System Limits & Honesty

Benchmark outputs are in the `/evaluation` directory and structured JSON in `/json`.

### How Good Is It?
The system excels at **not inventing data**. By forcing the LLM to populate a Pydantic `FactClaim` (requiring a verbatim `source_excerpt`), the model is structurally prevented from guessing.

For **Bharat Forge (Data-Rich, Listed)**:
- Correctly resolves ticker, fetches 4 years of real financials via `yfinance`, and extracts overview facts with HIGH confidence sourced directly to the company website.
- Highly useful for an analyst needing a quick, reliable baseline overview.

For **Brakes India (Data-Sparse, Unlisted)**:
- Correctly handles the absence of public filings — `yfinance` returns nothing for an unlisted company and the pipeline renders an honest note rather than fabricating figures.
- Successfully extracts core operations, geography, and product info from the company website with HIGH confidence.
- Refuses to hallucinate revenue figures or client names.

### Known Limitations
1. **Deep PDF Context**: The system truncates text chunks to manage token cost. Facts buried deep in a 300-page Annual Report PDF may be missed and reported as `NOT FOUND`.
2. **Cloudflare-Protected Sites**: Some corporate IR pages block standard HTTP requests. Playwright handles most cases, but aggressive bot-protection can still cause failures.
3. **Non-Standard Financials**: `yfinance` only provides standard income statement / balance sheet rows. Segment-level margins or non-GAAP metrics require a dedicated data vendor.

*(For a deeper dive into trade-offs, see [`writeup.md`](writeup.md))*
