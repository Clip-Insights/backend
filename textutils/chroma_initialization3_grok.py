import os
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings      # for embeddings
from langchain_groq import ChatGroq
from groq import Groq
from credentials import GROK_API_KEYS, CLIPINSIGHTS_PRODUCTION_KEY, PINECONE_API_KEY
from chromadb import PersistentClient
from pinecone import Pinecone, ServerlessSpec  # Add Pinecone import
from collections import deque
import yt_dlp
import requests

EMBEDDINGS_DIR = os.getcwd().replace('\\', '/') + '/textutils/embeddings/'
# Constants for initialization


PINECONE_INDEX_NAME = "clip-insights1"  # Pinecone index name
CHROMA_PERSIST_DIR = "./chroma_db"  # creating in root directory 
COLLECTION_NAME = "video_transcripts"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 50
PAID_LLM = True  # Set to True if using paid LLM

def get_embedding_model(model_name='all-MiniLM-L6-v2'):
    # Create embeddings directory if not exists
    os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
    
    # Check if model already downloaded
    model_path = os.path.join(EMBEDDINGS_DIR, model_name)
    print(model_path)
    if os.path.exists(model_path):
        print(f"Loading embeddings from local directory: {model_path}")
        return HuggingFaceEmbeddings(model_name=model_path)
    else:
        print(f"Downloading embeddings: {model_name}")
        embeddings = HuggingFaceEmbeddings(model_name=model_name)
        
        # Save model locally
        embeddings.client.save_pretrained(model_path)
        return embeddings



# Add this at the top level of your file
class GroqKeyManager:
    def __init__(self, api_keys):
        self.api_keys = deque(api_keys)
    
    def get_next_key(self):
        # Get the current key and rotate the queue
        current_key = self.api_keys[0]
        self.api_keys.rotate(-1)
        return current_key

# This will have one key only which will rotate and nothing will happen. This is for code comaptibility
class GroqKeyManagerPaid:
    def __init__(self, api_keys):
        self.api_keys = api_keys
    def get_next_key(self):
        return self.api_keys[0]


# Replace the single API key initialization with the key manager
if PAID_LLM:
    key_manager = GroqKeyManagerPaid([CLIPINSIGHTS_PRODUCTION_KEY])
else:
    key_manager = GroqKeyManager(GROK_API_KEYS)

# Initialize the base client with the first key
if PAID_LLM:
    client = Groq(api_key=CLIPINSIGHTS_PRODUCTION_KEY)
else:
    client = Groq(api_key=GROK_API_KEYS[0])        # initialize with the first key


# Update LLM initialization to use the key manager
def get_llm():
    if PAID_LLM:
        api_key=CLIPINSIGHTS_PRODUCTION_KEY
        print(f"Using API key: {api_key}")
        return ChatGroq(
            model="llama-3.1-8b-instant",
            # api_key=CLIPINSIGHTS_PRODUCTION_KEY,
            api_key=api_key,
            temperature=0,
            streaming=True
        )
    else:
        api_key=key_manager.get_next_key()
        print(f"Using API key: {api_key}")
        return ChatGroq(
            model="llama-3.1-8b-instant",
            # api_key=key_manager.get_next_key(),
            api_key=api_key,
            temperature=0,
            streaming=True
        )

# # Load environment variables and initialize Groq client
# client = Groq(
#     api_key= credentials.GROQ_API_KEY,
# )

# LLM = ChatGroq(
#     model="llama-3.1-70b-versatile",
#     api_key=credentials.GROQ_API_KEY,
#     temperature=0.2,
#     streaming=True
# )

# Initialize global objects
EMBEDDING_MODEL = get_embedding_model()
TEXT_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

def get_pinecone_index():
    # Initialize Pinecone using the imported API key
    pc = Pinecone(api_key=PINECONE_API_KEY)
    
    # Create or connect to index
    if PINECONE_INDEX_NAME not in pc.list_indexes().names():
        pc.create_index(
            name=PINECONE_INDEX_NAME,
            dimension=384,  # Should match your embedding model's dimension
            metric="cosine",
            spec=ServerlessSpec(
                cloud="aws",
                region="us-east-1"
            )
        )
    
    return pc.Index(PINECONE_INDEX_NAME)

# Replace Chroma initialization with Pinecone
PINECONE_INDEX = get_pinecone_index()

