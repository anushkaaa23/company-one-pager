import time
import random

def invoke_with_retry(chain, inputs, max_retries=5, initial_delay=5.0, backoff_factor=2.0):
    """
    Invokes a LangChain chain with retry logic for Gemini API 429 rate limit exceptions.
    """
    delay = initial_delay
    for attempt in range(max_retries + 1):
        try:
            return chain.invoke(inputs)
        except Exception as e:
            err_msg = str(e).lower()
            is_rate_limit = any(term in err_msg for term in ["429", "resource_exhausted", "rate_limit", "quota", "exhausted", "rate limit"])
            if is_rate_limit and attempt < max_retries:
                sleep_time = delay + random.uniform(0.0, 1.0)
                print(f"Rate limit hit during LLM invocation ({e}). Retrying attempt {attempt+1}/{max_retries} in {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)
                delay *= backoff_factor
            else:
                raise e
