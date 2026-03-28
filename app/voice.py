from faster_whisper import WhisperModel
import tempfile
import os
from django.http import JsonResponse

# ← Server start hone pe ek baar load hoga
whisper_model = WhisperModel("small", device="cpu", compute_type="int8")

def voice_to_text(request):
    if request.method != 'POST':
        return JsonResponse({"error": "POST only"}, status=405)

    audio_file = request.FILES.get('audio')
    if not audio_file:
        return JsonResponse({"error": "No audio received"}, status=400)

    print(f"[DEBUG] Audio: {audio_file.name}, size: {audio_file.size}")

    try:
        # Temp file mein save karo
        suffix = '.webm'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in audio_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        # Transcribe karo
        segments, info = whisper_model.transcribe(
            tmp_path,
            language="hi",          # Hindi — ya None for auto-detect
            beam_size=5,
            condition_on_previous_text=True
        )

        transcript = " ".join(seg.text for seg in segments).strip()
        print(f"[DEBUG] Transcript: {transcript}")

        # Temp file delete karo
        os.unlink(tmp_path)

        return JsonResponse({"text": transcript})

    except Exception as e:
        print(f"[ERROR] Whisper error: {e}")
        return JsonResponse({"error": str(e)}, status=500)