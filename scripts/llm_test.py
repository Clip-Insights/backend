from langchain_google_genai import GoogleGenerativeAI
from dotenv import load_dotenv
load_dotenv()
import os

api_keys = os.getenv("LLM_API_KEYS", "").split(",")
llm = GoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_keys[-5].strip())
print(llm.invoke("Hello world"))