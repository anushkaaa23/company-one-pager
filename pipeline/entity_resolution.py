import os
import json
from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.tools import DuckDuckGoSearchResults

class EntityResolutionResult(BaseModel):
    company_name: str
    ticker: Optional[str] = Field(None, description="The stock ticker symbol of the company if publicly traded, else null.")
    website: Optional[str] = Field(None, description="The official website URL of the company.")
    country: Optional[str] = Field(None, description="The country where the company is headquartered.")
    company_type: Optional[str] = Field(None, description="Public or Private.")
    confidence: float = Field(0.0, description="Confidence score of the resolution (0.0 to 1.0).")

def resolve_entity(company_name: str, hint_website: str = None, hint_ticker: str = None) -> EntityResolutionResult:
    """
    Given a company name, searches the web to find its canonical website, ticker, country, and type.
    """
    search_tool = DuckDuckGoSearchResults()
    query = f"{company_name} official website stock ticker headquarters"
    try:
        search_results = search_tool.invoke(query)
    except Exception as e:
        print(f"Search failed for entity resolution: {e}")
        search_results = "No search results available."

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert financial data researcher. Based on the provided search results and user hints, extract the company's official website, stock ticker (if public), headquarters country, and whether it is Public or Private. Also provide a confidence score between 0.0 and 1.0 based on how clear the search results are. If the information is not found, leave it as null."),
        ("user", "Company Name: {company_name}\nHint Website: {hint_website}\nHint Ticker: {hint_ticker}\n\nSearch Results:\n{search_results}")
    ])
    
    chain = prompt | llm.with_structured_output(EntityResolutionResult)
    
    from pipeline.llm_helper import invoke_with_retry
    try:
        result = invoke_with_retry(chain, {
            "company_name": company_name,
            "hint_website": hint_website or "None",
            "hint_ticker": hint_ticker or "None",
            "search_results": search_results
        })
        return result
    except Exception as e:
        print(f"Entity resolution failed: {e}")
        return EntityResolutionResult(
            company_name=company_name,
            website=hint_website,
            ticker=hint_ticker,
            confidence=0.5
        )

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    if len(sys.argv) > 1:
        res = resolve_entity(sys.argv[1])
        print(res.model_dump_json(indent=2))
