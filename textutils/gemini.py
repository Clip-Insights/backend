from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView
from langchain_groq import ChatGroq
from groq import Groq
import os
import credentials
from rest_framework import status
from langchain_chroma import Chroma    
from langchain_community.embeddings import HuggingFaceEmbeddings      # for embeddings
from langchain.text_splitter import CharacterTextSplitter
from django.http import StreamingHttpResponse   # for streaming response
from django.http import JsonResponse
from collections import deque
from langchain_google_genai import ChatGoogleGenerativeAI
import google.generativeai as genai
from credentials import GOOGLE_API_KEY
from google.api_core import retry


def get_embedding_model(model_name='all-MiniLM-L6-v2'):
    EMBEDDINGS_DIR = os.getcwd().replace('\\', '/') + '/textutils/embeddings/'
    
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

# At the top of the file with other imports
genai.configure(api_key=GOOGLE_API_KEY, transport="rest")

# Initialize the base client with the first key
# client = Groq(
# api_key=GROQ_KEYS[0],
#)

# Update LLM initialization to use the key manager
def get_llm():
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0.2,
        streaming=True,
        google_api_key=GOOGLE_API_KEY,  # Explicitly pass the API key
    )

# Usage
EMBEDDING_MODEL = get_embedding_model()

#LLM = ChatGroq(
#     model="llama-3.1-70b-versatile",
#     api_key=credentials.GROQ_API_KEY,
#     temperature=0.2,
#     streaming=True
#)


class ChatView(APIView):
    def post(self, request, *args, **kwargs):
        youtube_url = request.data.get('youtube_url')
        user_query = request.data.get('query')
        transcription = request.data.get('transcription')

        if not youtube_url or not user_query:
            return Response(
                {
                    'youtube_url': ['This field is required.'],
                    'query': ['This field is required.']
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        def process_transcription_and_embeddings():
            try:
                video_id = youtube_url.split("v=")[1]
                embeddings_path = f'./youtube/embeddings/{video_id}_embeddings'

                if not os.path.exists(embeddings_path):
                    text_splitter = CharacterTextSplitter(
                        chunk_size=150, chunk_overlap=20
                    )
                    chunks = text_splitter.split_text(transcription)
                    
                    # Use langchain_chroma to create and persist the vector store
                    db = Chroma.from_texts(
                        texts=chunks, 
                        embedding=EMBEDDING_MODEL, 
                        persist_directory=embeddings_path
                    )
                else:
                    # Load existing Chroma database
                    db = Chroma(
                        persist_directory=embeddings_path, 
                        embedding_function=EMBEDDING_MODEL
                    )

                retriever = db.as_retriever(search_kwargs={"k": 3})
                return retriever, video_id

            except Exception as e:
                print(f"Error during transcription and embedding processing: {e}")
                raise

        def generate_streaming_response():
            try:
                retriever, video_id = process_transcription_and_embeddings()
                relevant_contexts = retriever.get_relevant_documents(user_query)
                context = "\n\n".join([context.page_content for context in relevant_contexts])

                prompt = f"""Provide a concise answer to the user's question (50-60 words max) based on the video content. \
                Ensure the response is contextually accurate.\n\nUser Query: {user_query}\nRelevant Context: {context}\n"""

                llm = get_llm()
                try:
                    for chunk in llm.stream(prompt):
                        if chunk.content:
                            yield f"data: {chunk.content}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as stream_error:
                    print(f"Streaming error: {stream_error}")
                    # Fallback to non-streaming response if streaming fails
                    response = llm(prompt)
                    yield f"data: {response.content}\n\n"
                    yield "data: [DONE]\n\n"

            except Exception as e:
                print(f"Error during chat streaming: {e}")
                yield f"data: Error: {str(e)}\n\n"

        # Check the mode of operation (streaming or just transcription setup)
        if request.data.get('stream', False):
            return StreamingHttpResponse(generate_streaming_response(), content_type='text/event-stream')
        else:
            try:
                request.session['transcription'] = transcription
                request.session['query'] = user_query
                return Response(
                    {"message": "Data processed. Start streaming."},
                    status=status.HTTP_200_OK
                )
            except Exception as e:
                return Response(
                    {"error": "Failed to process chat."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            

class SummaryView(APIView):
    def post(self, request, *args, **kwargs):
        youtube_url = request.data.get('youtube_url')
        transcription = request.data.get('transcription')

        # Check if youtube_url and transcription are provided
        if not youtube_url:
            return Response(
                {'youtube_url': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not transcription:
            return Response(
                {'transcription': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Generate summarization with Groq
            summarization = self._get_summarization(transcription)
            print(summarization)
            bullets = self._get_summary_bullets(summarization)
            # print(">>" * 10)
            # print(bullets)
            # Generate PDF with summary
            # path = f'./media/pdfs/{video_id}.pdf'
            # pdf = generate_pdf(youtube_url, summarization, filename=path)

            return JsonResponse(
                {
                    'message': 'YouTube summary generated successfully.',
                    # 'pdf_path': f'/Backend/media/pdfs/{video_id}.pdf',
                    'youtube_url': youtube_url,
                    'summary': summarization,
                    'bullets': bullets
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    def _get_summarization(self, transcription):
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(
                f"Summarize the following transcription of video such that the user gets the full story of the video. Don't write any starting line just start providing the summary of the video. Transcription: {transcription}",
                generation_config={
                    'temperature': 0.2,
                }
            )
            return response.text
        except Exception as e:
            print(f"Error generating summary with Gemini: {e}")
            return "Failed to generate summary."
        
    def _get_summary_bullets(self, summarization):
        try:
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(
                f"Write 4 to 5 key take aways from the following context in the form of bullets.: {summarization}",
                generation_config={
                    'temperature': 0.1,
                }
            )
            return response.text
        except Exception as e:
            print(f"Error generating summary with Gemini: {e}")
            return "Failed to generate summary."
