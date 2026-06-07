# Company One-Pager Generator

This repository contains a production-ready AI pipeline designed to generate fully sourced, accurate, and hallucination-free company one-pagers based on minimal input (Company Name). 

The system prioritizes **factual traceability** above all else. Every generated claim is strictly coupled to a source URL and a confidence score. If a datapoint cannot be verified, the system aggressively defaults to `"Not found in available sources."`

## 1. Setup & Running the Code

### Prerequisites
- Python 3.9+
- A Google API Key (Required for structured extraction via `gemini-1.5-flash`)

### Installation
```bash
# Clone the repository
git clone <repository-url>
cd company-one-pager

# Create and activate a virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration
Create a `.env` file in the root directory and add your API key:
```bash
GOOGLE_API_KEY=your_google_api_key_here
```

### Running the API
Start the FastAPI server:
```bash
python app/main.py
```
*The server will start on `http://localhost:8000`.*

### Generating a Report
In a new terminal window, send a POST request with the company name.

**Example 1: Bharat Forge Limited**
```bash
curl -X POST "http://localhost:8000/generate" \
     -H "Content-Type: application/json" \
     -d '{"company_name": "Bharat Forge Limited", "ticker": "BHARATFORG"}'
```

**Example 2: Brakes India Private Limited**
```bash
curl -X POST "http://localhost:8000/generate" \
     -H "Content-Type: application/json" \
     -d '{"company_name": "Brakes India Private Limited"}'
```

The system will stream logs to your console and save the resulting highly structured Markdown and JSON reports in the `outputs/` directory.

---

## 2. Architecture Overview

The system is built as a highly modular Python pipeline exposed via a FastAPI backend. It explicitly separates the reasoning steps to enforce strict fact-checking boundaries.

1. **Entity Resolution** (`pipeline/entity_resolution.py`): Infers canonical tickers, website URLs, and company types using DuckDuckGo search combined with LLM evaluation.
2. **Source Discovery** (`pipeline/discovery.py`): Crawls the web for high-trust sources, strictly categorizing and prioritizing SEC/Exchange filings, Annual Reports, and official company domains. It assigns an initial `trust_score` to domains.
3. **Extraction** (`pipeline/extraction.py`): 
   - Uses `trafilatura` to parse raw HTML/PDF text from the highest-trusted domains.
   - Uses `yfinance` to fetch strict numerical financial data (bypassing LLM hallucination for numbers entirely). 
   - Uses `LangChain` combined with `Pydantic` to ensure qualitative facts are extracted into rigid `FactClaim` schemas.
4. **Verification Layer** (`pipeline/verification.py`): The core anti-hallucination mechanism. It processes all extracted facts, enforcing a strict confidence threshold (`0.5`). Any unsupported claims are aggressively replaced with `"Not found in available sources."`
5. **Generation** (`pipeline/generation.py`): Compiles the surviving verified facts into a beautifully structured Markdown document.

---

## 3. Self-Evaluation: System Limits & Honesty

I ran the system against the two required benchmarks: the data-rich **Bharat Forge Limited** and the data-sparse **Brakes India Private Limited**. You can view the full outputs in the `/evaluation` directory.

### How Good Is It?
The system performs exceptionally well at **not inventing data**. By forcing the LLM to map every output to a Pydantic `FactClaim` (which requires an exact `source_excerpt` string), the model is heavily discouraged from guessing. 

For **Bharat Forge (Data-Rich)**:
- The system correctly identifies the ticker, fetches real numerical values via `yfinance`, and extracts highly specific product lines (e.g., ATAGS artillery systems) directly sourced to news and annual reports.
- It is highly useful for an analyst needing a quick, reliable overview.

For **Brakes India (Data-Sparse)**:
- The system correctly handles the lack of public filings.
- Because it is unlisted, the `yfinance` integration legitimately returns empty frames. The pipeline explicitly catches this and renders a table filled with `"Not publicly available"`.
- It successfully identifies the company's core operations via its primary website but refuses to hallucinate specific revenue sizes or unverified clients.

### Where Does It Break?
1. **Deeper Context Processing**: Currently, to save on token costs and latency, the system only passes the truncated text of the top 3 highest-rated search results to the LLM. If a specific client name is buried on page 40 of a 300-page Annual Report PDF, the system will likely miss it and report `"Not found in available sources"`. 
2. **Dynamic Corporate Sites**: The reliance on standard HTTP requests (`requests`/`trafilatura`) means the system will break and fail to extract text if an official company site is heavily protected by Cloudflare. 
3. **Granular Financials**: By hard-coding `yfinance` to prevent LLM hallucination, the system explicitly breaks if an analyst wants non-standard metrics (like "Customer Acquisition Cost" or specific segment revenue margins) that aren't available in standard Yahoo Finance ticker tables.

*(For a deeper dive into architectural trade-offs, please see `writeup.md`)*
