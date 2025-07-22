from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from django.http import StreamingHttpResponse   # for streaming response
from django.http import JsonResponse
from collections import deque
import os
from .models import VideoResource, VideoTranscriptTimeSlice
from django.utils.timezone import now
from .chroma_initialization import CHROMA_COLLECTION, EMBEDDING_MODEL, client, TEXT_SPLITTER, get_llm, key_manager
caching = True  # True will store summary, keypoints to database

# For chatting, we are using LLM = 70B llama, for summary and keypoints, we are using LLM = 8B llama using client.chat.completions.create
class ChatView(APIView):
    def post(self, request, *args, **kwargs):
        youtube_url = request.data.get('youtube_url')
        user_query = request.data.get('query')
        transcription = request.data.get('transcription')
        slice_time = request.data.get('slice_time', -1)  # Default slice_time to -1 if not provided, -1 means complete video
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
                # print("Relevant Docs",relevant_docs)
                context = "\n\n".join(doc[0] for doc in relevant_docs["documents"])
                # Generate response using LLM
                prompt = f"""Provide a concise answer to the user's question (50-60 words max) based on the video content. \
                Ensure the response is contextually accurate.\n\nUser Query: {user_query}\nRelevant Context: {context}\n"""

                # Get a new LLM instance with the next API key
                llm = get_llm()
                for chunk in llm.stream(prompt):
                    if chunk.content:
                        yield f"data: {chunk.content}\n\n"

                yield "data: [DONE]\n\n"

            except Exception as e:
                print(f"Error during chat streaming: {e}")
                yield f"data: Error: {str(e)}\n\n"

        # Check the mode of operation
        if request.data.get('stream', False):
            return StreamingHttpResponse(generate_streaming_response(), content_type='text/event-stream')
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

class SummaryView(APIView):
    def post(self, request, *args, **kwargs):
        youtube_url = request.data.get('youtube_url')
        transcription = request.data.get('transcription')
        slice_time = request.data.get('slice_time', -1)  # Default slice_time to -1 if not provided

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
                        'message': 'YouTube summary retrieved from the database.',
                        'youtube_url': youtube_url,
                        'summary': video_resource.summary,
                        'bullets': video_resource.keypoints,
                        'slice_time': video_resource.slice_time,
                        'view_count': video_resource.view_count
                    }
                    print("Retrieved from cache")
                    summarization = None       # Set summarization to None to skip storing in database again
                    return JsonResponse(response_data, status=status.HTTP_200_OK)

            # Generate summarization and bullets
            summarization = self._get_summarization(transcription)
            bullets = self._get_summary_bullets(summarization)

            # Prepare the response data
            response_data = {
                'message': 'YouTube summary generated successfully.',
                'youtube_url': youtube_url,
                'summary': summarization,
                'bullets': bullets,
                'slice_time': slice_time
            }

            return JsonResponse(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            response_data = {'error': str(e)}
            return Response(response_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        finally:
            if caching and 'error' not in response_data:
                # Store the data in the database if caching is enabled
                try:
                    if summarization and summarization != "Failed to generate summary.":
                        print("storing in database")
                        VideoResource.objects.create(
                            youtube_url=youtube_url,
                            summary=summarization,
                            keypoints= bullets,
                            slice_time=slice_time,
                            updated=now()
                        )
                        
                except Exception as db_error:
                    # Log or handle database errors
                    print(f"Database Error: {db_error}")

    def _get_summarization(self, transcription):
        try:
            # Update client API key before making the request
            client.api_key = key_manager.get_next_key()
            chat_completion = client.chat.completions.create(
                # model="llama-3.1-70b-versatile",
                model="llama3-8b-8192",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {
                        "role": "user",
                        "content": f"Summarize the following transcription of video such that the user gets the full story of the video. Don't write any starting line just start providing the summary of the video. Transcription: {transcription}"
                    }
                ],
                temperature=0.2,
                # max_tokens=1024,
                top_p=1,
                stream=False
            )
            # Extract the summary text from the response
            return chat_completion.choices[0].message.content
        
        except Exception as e:
            print(f"Error generating summary with Groq: {e}")
            return "Failed to generate summary."
        
    def _get_summary_bullets(self, summarization):
        try:
            # Update client API key before making the request
            client.api_key = key_manager.get_next_key()
            chat_completion = client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {
                        "role": "user",
                        "content": f"Write 4 to 5 key take aways from the following context in the form of bullets.: {summarization}"
                    }
                ],
                temperature=0.1,
                # max_tokens=1024,
                top_p=1,
                stream=False
            )
            # Extract the summary text from the response
            return chat_completion.choices[0].message.content
        
        except Exception as e:
            print(f"Error generating summary with Groq: {e}")
            return "Failed to generate summary"