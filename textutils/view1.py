from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from django.http import StreamingHttpResponse, JsonResponse
from collections import deque
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field
from typing import List
import json

from .models import VideoResource, VideoTranscriptTimeSlice
from django.utils.timezone import now
from .chroma_initialization import CHROMA_COLLECTION, EMBEDDING_MODEL, client, TEXT_SPLITTER, get_llm, key_manager
from .utils import parse_keypoints, robust_json_parser, fix_pydantic_validation
from .serializers import ChatInputSerializer, SummaryInputSerializer

caching = True  # True will store summary, keypoints to database


class ChatView(APIView):
    def post(self, request, *args, **kwargs):
        # youtube_url = request.data.get('youtube_url')
        # user_query = request.data.get('query')
        # transcription = request.data.get('transcription')
        # slice_time = request.data.get('slice_time', -1)
        # chat_memory_enabled = request.data.get('chat_memory_enabled', False)
        # chat_history = request.data.get('chat_history', [])

        serializer = ChatInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        validated_data = serializer.validated_data

        youtube_url = validated_data.get('youtube_url')
        user_query = validated_data.get('query')
        transcription = validated_data.get('transcription')
        slice_time = validated_data.get('slice_time', -1)
        stream_mode = validated_data.get('stream', False)

        if not youtube_url or not user_query:
            return Response(
                {
                    'youtube_url': ['This field is required.'],
                    'query': ['This field is required.']
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        def process_transcription_and_store_embeddings():
            try:
                # Retrieve or create a VideoTranscriptTimeSlice entry for the video
                transcript_entry, created = VideoTranscriptTimeSlice.objects.get_or_create(
                    youtube_url=youtube_url,
                    defaults={"slice_time": slice_time}
                )
                transcript_entry.increment_access_count()
                
                if not created:
                    previous_slice_time = transcript_entry.slice_time
                    print(f"Previous slice_time: {previous_slice_time}, New slice_time: {slice_time}")

                    # Scenario 1: Full transcript embeddings already exist (-1 in slice_time)
                    if previous_slice_time == -1:
                        print("Full transcript embeddings already exist. Skipping embedding creation.")
                        return CHROMA_COLLECTION

                    # Scenario 2: New slice_time is greater than the previous slice_time
                    if slice_time > previous_slice_time:
                        print("New slice_time is greater than the previous one. Recreating embeddings.")

                    # Scenario 3: Previous slice_time is not -1 and new slice_time is -1 (complete video)
                    elif previous_slice_time != -1 and slice_time == -1:
                        print("Complete video transcription received. Recreating embeddings.")

                    else:
                        # No valid scenario to create embeddings
                        print("No changes in slice_time warrant embedding recreation. Skipping embedding creation.")
                        return CHROMA_COLLECTION

                # If we're here, it means embeddings need to be created or updated
                print("Creating chunks and storing embeddings...")

                # Chunk the transcription
                chunks = TEXT_SPLITTER.split_text(transcription)
                # Generate unique IDs for each chunk
                print("Chunks:", len(chunks))
                ids = [f"{youtube_url}_chunk_{idx}" for idx in range(len(chunks))]
                # Store embeddings and metadata
                metadatas = [
                    {
                        "youtube_url": youtube_url,
                        "chunk_index": idx
                    }
                    for idx in range(len(chunks))
                ]
                print("Creating embeddings...")
                # Use embeddings directly from HuggingFaceEmbeddings
                embeddings = EMBEDDING_MODEL.embed_documents(chunks)
                print("Storing embeddings...")
                CHROMA_COLLECTION.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=chunks,
                    metadatas=metadatas
                )
                print("Embeddings stored successfully.")

                # Update the slice_time in the database
                transcript_entry.slice_time = slice_time
                transcript_entry.save()

                return CHROMA_COLLECTION

            except Exception as e:
                print(f"Error during transcription and embedding storage: {e}")
                raise
            
        def generate_streaming_response():
            try:
                collection = process_transcription_and_store_embeddings()

                # Retrieve relevant chunks
                relevant_docs = collection.query(
                    query_texts=[user_query],
                    where={"youtube_url": youtube_url},
                    n_results=3
                )
                context = "\n\n".join(doc[0] for doc in relevant_docs["documents"])

                # Modify prompt based on chat memory setting
                if chat_memory_enabled and chat_history:
                    chat_context = "\n".join([
                        f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content']}"
                        for msg in chat_history[-4:]  # Use last 4 messages
                    ])
                    prompt = f"""You are a helpful AI assistant answering questions about a video. 
                    Previous conversation:
                    {chat_context}
                    
                    Based on this context and the video content below, provide a concise answer (50-60 words) 
                    to the user's latest question. Maintain conversation continuity while staying focused on the video content.
                    
                    Video Content: {context}
                    
                    User's Latest Question: {user_query}"""
                else:
                    # Use original prompt for independent queries
                    prompt = f"""Provide a concise answer to the user's question (50-60 words max) based on the video content. 
                    Ensure the response is contextually accurate.
                    
                    User Query: {user_query}
                    Relevant Context: {context}"""

                # # print(len(relevant_docs['documents']), len(relevant_docs['documents'][0]))
                # # print("Relevant Docs",relevant_docs)
                # context = "\n------------------------------------------------\n".join(relevant_docs["documents"][0])
                # # print("context",context)
                # # Generate response using LLM
                # prompt = f"""Provide a concise answer to the user's question (50-60 words max) based on the video content. \
                # Ensure the response is contextually accurate. Respond in **English language** until unless specified in user query.\n\nUser Query: {user_query}\nRelevant Context: {context}\n"""
                # # print(len(prompt)//3.5)
                # # Get a new LLM instance with the next API key
                # Build the context string from relevant documents
                # context = "\n------------------------------------------------\n".join(relevant_docs["documents"][0])
                # # Generate response using LLM
                # prompt = f"""Provide a concise answer to the user's question (50-60 words max) based on the video content. \
                # Ensure the response is contextually accurate. Respond in **English language** even if relevant context is in some other language.\n\nUser Query: {user_query}\nRelevant Context: {context}\n"""
                # # Get a new LLM instance with the next API key
                llm = get_llm()
                for chunk in llm.stream(prompt):
                    if chunk.content:
                        yield f"data: {chunk.content}\n\n"

                yield "data: [DONE]\n\n"

            except Exception as e:
                print(f"Error during chat streaming: {e}")
                yield f"data: Error: {str(e)}\n\n"

        # Check the mode of operation
        if stream_mode:
            response = StreamingHttpResponse(
                generate_streaming_response(), 
                content_type='text/event-stream'
            )
            # Manually set the CORS headers using the Origin from the request, or a fixed value.
            origin = request.headers.get('Origin')
            if origin:
                response['Access-Control-Allow-Origin'] = origin
            else:
                response['Access-Control-Allow-Origin'] = 'https://www.youtube.com'
            response['Access-Control-Allow-Credentials'] = 'true'
            print(response.headers)
            return response
        else:
            try:
                return Response(
                    {"message": "Data processed. Start streaming."},
                    status=status.HTTP_200_OK
                )
            except Exception as e:
                return Response(
                    {"error": "Failed to process chat."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )


class VideoSummary(BaseModel):
    """Schema for video summary output"""
    summary: str = Field(description="A comprehensive summary of the video content")
    keypoints: List[str] = Field(description="4-5 key points from the video")


class SummaryView(APIView):
    def __init__(self):
        self.parser = PydanticOutputParser(pydantic_object=VideoSummary)
        self.prompt_template = self._create_prompt_template()

    def _create_prompt_template(self) -> PromptTemplate:
        template = """You are an advanced summarization and key points extract assistant specializing in video content analysis.

        Task: You have to provide 2 things, summary and keypoints. Analyze the following video transcript and extract a **concise summary** that captures the **full context** of the video. 
        Also, extract **4 to 5 key points** that highlight the most **important insights or facts** from the transcript. Write answer in **English Language** only even if the transcript is in some other language.

        Requirements:
        1. Summary (500 - 600 words):
        - Capture the main narrative and purpose
        - Include critical context and key discussions

        2. Key Points (4-5):
        - Focus on the most significant insights
        - Be specific and actionable

        Format Instructions:
        {format_instructions}

        Transcript: {transcript}"""

        return PromptTemplate(
            template=template,
            input_variables=["transcript"],
            partial_variables={"format_instructions": self.parser.get_format_instructions()}
        )

    def post(self, request, *args, **kwargs):
        serializer = SummaryInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        validated_data = serializer.validated_data

        youtube_url = validated_data.get('youtube_url')
        transcript = validated_data.get('transcription')
        slice_time = validated_data.get('slice_time', -1)
        print("Tokens", len(transcript) // 3.5)
        if not youtube_url:
            return Response(
                {'youtube_url': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not transcript:
            return Response(
                {'transcription': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST
            )

        response_data = {}

        try:
            if caching:
                # Check if the video resource exists in the database
                video_resource = VideoResource.objects.filter(youtube_url=youtube_url).first()
                if video_resource:
                    # Increment view count and update slice time
                    video_resource.view_count += 1
                    video_resource.updated = now()
                    video_resource.save()
                    video_resource.slice_time = slice_time

                    response_data = {
                        'success': True,
                        'message': 'YouTube summary retrieved from the database.',
                        'youtube_url': youtube_url,
                        'summary': video_resource.summary,
                        'keypoints': video_resource.keypoints,
                        'slice_time': video_resource.slice_time,
                        'view_count': video_resource.view_count
                    }
                    print("Retrieved from cache")
                    success = True       # Set success to True to simulate successful response
                    summary = None       # Set summarization to None to skip storing in database again
                    keypoints = None     # Set keypoints to None to skip storing in database again
                    return JsonResponse(response_data, status=status.HTTP_200_OK)

            # Generate summarization and bullets
            response = self._get_summary_keypoints(transcript)
            print("Response:>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>", response)
            success = response["success"]
            if success:
                summary = response["data"]["summary"]
                keypoints = response["data"]["keypoints"]
                response_data = {
                    'success': success,
                    'message': response["display_message"],
                    'youtube_url': youtube_url,
                    'summary': summary,
                    'keypoints': keypoints,
                    'slice_time': slice_time
                }

                return JsonResponse(response_data, status=status.HTTP_200_OK)
            if not success:
                response_data = {
                    'success': success,
                    'error': response["error"],
                    'message': response["display_message"]
                }
                return JsonResponse(response_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            response_data = {'error': str(e)}
            return Response(response_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        finally:
            if caching == True and success == True:
                # Store the data in the database if caching is enabled
                try:
                    if summary and keypoints:
                        print("storing in database")
                        VideoResource.objects.create(
                            youtube_url=youtube_url,
                            summary=summary,
                            keypoints=keypoints,
                            slice_time=slice_time,
                            updated=now()
                        )
                        
                except Exception as db_error:
                    # Log or handle database errors
                    print(f"Database Error: {db_error}")

    # Created a single function to generate summary and keypoints in single LLM call
    def _get_summary_keypoints(self, transcript):
        try:
            # Format the prompt
            formatted_prompt = self.prompt_template.format(transcript=transcript)
            client.api_key = key_manager.get_next_key()
            print("API Key:>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>", client.api_key)
            chat_completion = client.chat.completions.create(
                model="llama-3.2-3b-preview",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an advanced summarization and keypoints extract assistant. Your task is to generate a structured summary "
                                   "and key points from a provided video transcript. Focus on capturing the **core message**, "
                                   "important events, and any key takeaways in a **concise, well-structured, and professional** manner. "
                                   "Always respond in **English language** even if the context is in some other language."
                                   'Ensure the response is strictly in the required JSON format with only 2 fields: "summary" and "keypoints".'
                    },
                    {
                        "role": "user",
                        "content": formatted_prompt
                    }
                ],
                temperature=0,
                stream=False
            )
            # Get response content
            response_text = chat_completion.choices[0].message.content
            # Use the new robust parsing
            parsed_response = fix_pydantic_validation(response_text)
            
            if parsed_response is None:
                return {
                    "success": False,
                    "error": "Unable to parse response",
                    "display_message": "Oops! Something went wrong. Please try again."
                }
            
            return {
                "success": True,
                "data": parsed_response,
                "display_message": "Your response has been generated successfully."
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"API error: {str(e)}",
                "display_message": "Sorry, there was some error in generating the response. Please try again."
            }


class TokenLimitView(APIView):
    def get(self, request):
        return JsonResponse({"tokens": 50000, "charPerToken": 2.5}, status=status.HTTP_200_OK)
