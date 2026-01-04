from langchain_google_genai import GoogleGenerativeAI
import logging
from dotenv import load_dotenv
load_dotenv()
import os
logger = logging.getLogger(__name__)

api_keys = os.getenv("LLM_API_KEYS", "").split(",")
llm = GoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_keys[-5].strip())
logger.info(llm.invoke("Hello world"))