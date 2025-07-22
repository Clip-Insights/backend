import os
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings      # for embeddings
from langchain_groq import ChatGroq
from groq import Groq
from credentials import GROK_API_KEYS, CLIPINSIGHTS_PRODUCTION_KEY
from chromadb import PersistentClient
from collections import deque

EMBEDDINGS_DIR = os.getcwd().replace('\\', '/') + '/textutils/embeddings/'
# Constants for initialization
CHROMA_PERSIST_DIR = "./chroma_db"  # creating in root directory 
COLLECTION_NAME = "video_transcripts"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 50
PAID_LLM = True

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
        return ChatGroq(
            model="llama-3.1-8b-instant",
            api_key=CLIPINSIGHTS_PRODUCTION_KEY,
            temperature=0,
            streaming=True
        )
    else:
        return ChatGroq(
            model="llama-3.1-8b-instant",
            api_key=key_manager.get_next_key(),
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


def get_chroma_collection():
    # Use PersistentClient instead of Chroma
    db = PersistentClient(path=CHROMA_PERSIST_DIR)
    
    # Use create_collection instead of get_or_create_collection
    collection = db.get_or_create_collection(name=COLLECTION_NAME)
    return db, collection


CHROMA_DB, CHROMA_COLLECTION = get_chroma_collection()
