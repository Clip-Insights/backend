from langchain_google_genai import ChatGoogleGenerativeAI
import google.generativeai as genai
from credentials import GOOGLE_API_KEY, GOOGLE_API_KEY_1, GOOGLE_API_KEY_2, GOOGLE_API_KEY_3,GOOGLE_API_KEY_4, GOOGLE_API_KEY_5
from credentials import GOOGLE_API_KEY_6, GOOGLE_API_KEY_7
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings 
from chromadb import PersistentClient
from collections import deque
import os

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

EMBEDDINGS_DIR = os.getcwd().replace('\\', '/') + '/textutils/embeddings/'

class GeminiKeyManager:
    def __init__(self, api_keys):
        self.api_keys = deque(api_keys)
    
    def get_next_key(self):
        # Get the current key and rotate the queue
        current_key = self.api_keys[0]
        self.api_keys.rotate(-1)
        return current_key

# Replace single API key with multiple keys
GEMINI_KEYS = [
    GOOGLE_API_KEY,
    GOOGLE_API_KEY_1,
    GOOGLE_API_KEY_2,
    GOOGLE_API_KEY_3,
    GOOGLE_API_KEY_4,
    GOOGLE_API_KEY_5,
    GOOGLE_API_KEY_6,
    GOOGLE_API_KEY_7,
]
key_manager = GeminiKeyManager(GEMINI_KEYS)

# Configure Gemini with initial key
genai.configure(api_key=GEMINI_KEYS[0], transport="rest")

# Update LLM initialization to use the key manager
def get_llm():
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0.2,
        streaming=True,
        google_api_key=key_manager.get_next_key(),
    )

# Remove Groq-specific code and keep the rest of the initialization code
CHROMA_PERSIST_DIR = "./chroma_db"
CHROMA_COLLECTION = "video_transcripts"
CHUNK_SIZE = 150
CHUNK_OVERLAP = 20
# Initialize global objects
EMBEDDING_MODEL = get_embedding_model()
TEXT_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

def get_chroma_collection():
    # Use PersistentClient instead of Chroma
    db = PersistentClient(path=CHROMA_PERSIST_DIR)
    
    # Use create_collection instead of get_or_create_collection
    collection = db.get_or_create_collection(name=CHROMA_COLLECTION)
    return db, collection


CHROMA_DB, CHROMA_COLLECTION = get_chroma_collection()