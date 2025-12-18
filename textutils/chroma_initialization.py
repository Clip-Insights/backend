import os
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from google.generativeai import GenerativeModel
import google.generativeai as genai
from groq import Groq
from credentials import GOOGLE_API_KEYS, GROK_API_KEYS, CLIPINSIGHTS_PRODUCTION_KEY, PINECONE_API_KEY
from pinecone import Pinecone, ServerlessSpec
from collections import deque

EMBEDDINGS_DIR = os.getcwd().replace('\\', '/') + '/textutils/embeddings/'
PINECONE_INDEX_NAME = "clip-insights1"
CHROMA_PERSIST_DIR = "./chroma_db"
COLLECTION_NAME = "video_transcripts"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 50
PAID_LLM = False

def get_embedding_model(model_name='all-MiniLM-L6-v2'):
    os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
    model_path = os.path.join(EMBEDDINGS_DIR, model_name)
    print(model_path)
    if os.path.exists(model_path):
        print(f"Loading embeddings from local directory: {model_path}")
        return HuggingFaceEmbeddings(model_name=model_path)
    else:
        print(f"Downloading embeddings: {model_name}")
        embeddings = HuggingFaceEmbeddings(model_name=model_name)
        embeddings._client.save_pretrained(model_path)
        return embeddings

class GoogleKeyManager:
    def __init__(self, api_keys):
        self.api_keys = deque(api_keys)
    
    def get_next_key(self):
        current_key = self.api_keys[0]
        self.api_keys.rotate(-1)
        return current_key

class GoogleKeyManagerPaid:
    def __init__(self, api_keys):
        self.api_keys = api_keys
    def get_next_key(self):
        return self.api_keys[0]

class GroqKeyManager:
    def __init__(self, api_keys):
        self.api_keys = deque(api_keys)
    
    def get_next_key(self):
        current_key = self.api_keys[0]
        self.api_keys.rotate(-1)
        return current_key

class GroqKeyManagerPaid:
    def __init__(self, api_keys):
        self.api_keys = api_keys
    def get_next_key(self):
        return self.api_keys[0]

# Initialize key managers for both Google and Groq
if PAID_LLM:
    google_key_manager = GoogleKeyManagerPaid([CLIPINSIGHTS_PRODUCTION_KEY])
    groq_key_manager = GroqKeyManagerPaid([CLIPINSIGHTS_PRODUCTION_KEY])
else:
    google_key_manager = GoogleKeyManager(GOOGLE_API_KEYS)
    groq_key_manager = GroqKeyManager(GROK_API_KEYS)

# Configure Google API key and initialize clients
if PAID_LLM:
    genai.configure(api_key=CLIPINSIGHTS_PRODUCTION_KEY)
    llm_client = GenerativeModel('gemini-2.0-flash')
    transcription_client = Groq(api_key=CLIPINSIGHTS_PRODUCTION_KEY)
else:
    genai.configure(api_key=GOOGLE_API_KEYS[0])
    llm_client = GenerativeModel('gemini-2.0-flash')
    transcription_client = Groq(api_key=GROK_API_KEYS[0])

def get_llm():
    if PAID_LLM:
        api_key = google_key_manager.get_next_key()
        print(f"Using Google API key: {api_key}")
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=api_key,
            temperature=0,
            streaming=True
        )
    else:
        api_key = google_key_manager.get_next_key()
        print(f"Using Google API key: {api_key}")
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=api_key,
            temperature=0,
            streaming=True
        )

EMBEDDING_MODEL = get_embedding_model()
TEXT_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

def get_pinecone_index():
    pc = Pinecone(api_key=PINECONE_API_KEY)
    if PINECONE_INDEX_NAME not in pc.list_indexes().names():
        pc.create_index(
            name=PINECONE_INDEX_NAME,
            dimension=384,
            metric="cosine",
            spec=ServerlessSpec(
                cloud="aws",
                region="us-east-1"
            )
        )
    return pc.Index(PINECONE_INDEX_NAME)

PINECONE_INDEX = get_pinecone_index()