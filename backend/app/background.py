import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections, transaction
from django.utils import timezone

from .documents import extract_pdf_chunks, replace_document_chunks
from .langchain import (
    clear_history_cache,
    generate_fortune_reading,
    generate_learning_path,
    generate_quiz_questions,
    generate_roast_analysis,
)
from .models import BackgroundJob, ChatDocument, ChatSession, LearningQuizQuestion, LearningQuizSession


POLL_INTERVAL_SECONDS = 1.0
MAX_WORKERS = 2
SKIP_COMMANDS = {
    "check",
    "collectstatic",
    "createsuperuser",
    "dbshell",
    "flush",
    "makemigrations",
    "migrate",
    "shell",
    "showmigrations",
    "test",
}

_runner_lock = threading.Lock()
_runner_started = False
_runner_thread = None
_executor = None
_inflight = set()


def serialize_learning_quiz_question(question):
    revealed = bool(question.selected_option)
    return {
        "id": question.id,
        "sort_order": question.sort_order,
        "question_text": question.question_text,
        "options": {
            "A": question.option_a,
            "B": question.option_b,
            "C": question.option_c,
            "D": question.option_d,
        },
        "selected_option": question.selected_option or "",
        "is_correct": question.is_correct,
        "correct_option": question.correct_option if revealed else "",
        "explanation": question.explanation if revealed else "",
    }


def serialize_learning_quiz_session(quiz):
    questions = list(quiz.questions.all())
    answered_questions = sum(1 for item in questions if item.selected_option)
    total_questions = quiz.total_questions or len(questions)
    score_percent = round((quiz.correct_answers / total_questions) * 100) if total_questions else 0
    return {
        "id": quiz.id,
        "topic": quiz.topic,
        "model": quiz.model,
        "difficulty_level": quiz.difficulty_level,
        "difficulty_label": quiz.get_difficulty_level_display(),
        "total_questions": total_questions,
        "answered_questions": answered_questions,
        "correct_answers": quiz.correct_answers,
        "score_percent": score_percent,
        "is_completed": bool(quiz.completed_at),
        "created_at": quiz.created_at.isoformat(),
        "completed_at": quiz.completed_at.isoformat() if quiz.completed_at else None,
        "questions": [serialize_learning_quiz_question(question) for question in questions],
    }


def should_start_background_runner():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command in SKIP_COMMANDS:
        return False
    if command == "runserver" and os.environ.get("RUN_MAIN") != "true":
        return False
    return True


def claim_next_job():
    with transaction.atomic():
        job = (
            BackgroundJob.objects.select_for_update()
            .filter(status=BackgroundJob.STATUS_QUEUED)
            .order_by("created_at")
            .first()
        )
        if job is None:
            return None

        job.status = BackgroundJob.STATUS_RUNNING
        job.started_at = timezone.now()
        job.error_message = ""
        job.save(update_fields=["status", "started_at", "error_message"])
        return job.id


def build_learning_quiz_job(job):
    payload = job.payload or {}
    topic = str(payload.get("topic") or "").strip()
    model = str(payload.get("model") or "").strip()
    difficulty_level = str(
        payload.get("difficulty_level") or LearningQuizSession.LEVEL_BEGINNER
    ).strip().lower()
    question_count = int(payload.get("question_count") or 5)

    previous_questions = list(
        LearningQuizQuestion.objects.filter(
            quiz_session__owner=job.owner,
            quiz_session__topic__iexact=topic,
        )
        .order_by("-id")
        .values_list("question_text", flat=True)[:40]
    )
    generated_questions = generate_quiz_questions(
        model,
        topic,
        difficulty_level=difficulty_level,
        question_count=question_count,
        previous_questions=previous_questions,
    )

    quiz = LearningQuizSession.objects.create(
        owner=job.owner,
        topic=topic,
        model=model,
        difficulty_level=difficulty_level,
        total_questions=len(generated_questions),
    )
    LearningQuizQuestion.objects.bulk_create(
        [
            LearningQuizQuestion(
                quiz_session=quiz,
                question_text=item["question_text"],
                option_a=item["option_a"],
                option_b=item["option_b"],
                option_c=item["option_c"],
                option_d=item["option_d"],
                correct_option=item["correct_option"],
                explanation=item["explanation"],
                sort_order=item["sort_order"],
            )
            for item in generated_questions
        ]
    )
    quiz = LearningQuizSession.objects.prefetch_related("questions").get(id=quiz.id)
    return {"quiz": serialize_learning_quiz_session(quiz)}


def build_learning_path_job(job):
    payload = job.payload or {}
    goal = str(payload.get("goal") or "").strip()
    model = str(payload.get("model") or "").strip()
    experience_level = str(payload.get("experience_level") or "").strip()
    weekly_hours = str(payload.get("weekly_hours") or "").strip()
    timeline = str(payload.get("timeline") or "").strip()
    path = generate_learning_path(model, goal, experience_level, weekly_hours, timeline)
    return {
        "path": path,
        "meta": {
            "goal": goal,
            "model": model,
            "experience_level": experience_level,
            "weekly_hours": weekly_hours,
            "timeline": timeline,
        },
    }


def build_roast_job(job):
    payload = job.payload or {}
    content_type = str(payload.get("content_type") or "auto").strip().lower()
    language = str(payload.get("language") or "english").strip().lower()
    content = str(payload.get("content") or "").strip()
    improvement_goal = str(payload.get("improvement_goal") or "").strip()
    model = str(payload.get("model") or "qwen3.5").strip()
    roast = generate_roast_analysis(model, content_type, content, language, improvement_goal)
    return {
        "roast": roast,
        "meta": {
            "content_type": content_type,
            "language": language,
            "model": model,
            "improvement_goal": improvement_goal,
        },
    }


def build_fortune_job(job):
    payload = job.payload or {}
    question = str(payload.get("question") or "").strip()
    focus_area = str(payload.get("focus_area") or "general").strip().lower()
    language = str(payload.get("language") or "english").strip().lower()
    model = str(payload.get("model") or "deepseek-v3.1").strip()
    fortune = generate_fortune_reading(model, question, focus_area, language)
    return {
        "fortune": fortune,
        "meta": {
            "focus_area": focus_area,
            "language": language,
            "model": model,
        },
    }


def process_document_job(job):
    document = ChatDocument.objects.filter(id=job.document_id).select_related("session").first()
    if document is None:
        raise ValueError("The selected document is no longer available.")
    if not document.file:
        raise ValueError("The selected document file is missing.")

    document.processing_status = ChatDocument.STATUS_PROCESSING
    document.processing_error = ""
    document.save(update_fields=["processing_status", "processing_error"])

    chunks = extract_pdf_chunks(document.file.path)
    if not chunks:
        raise ValueError("No readable text was found in this PDF.")

    replace_document_chunks(document, chunks)
    document.extracted_characters = sum(len(chunk["content"]) for chunk in chunks)
    document.processing_status = ChatDocument.STATUS_READY
    document.processing_error = ""
    document.save(
        update_fields=["extracted_characters", "processing_status", "processing_error"]
    )

    if document.session_id:
        clear_history_cache(document.session_id)
        ChatSession.objects.filter(id=document.session_id).update(updated_at=timezone.now())

    return {
        "document_id": document.id,
        "session_id": document.session_id,
        "extracted_characters": document.extracted_characters,
        "chunk_count": len(chunks),
    }


def run_job(job_id):
    close_old_connections()
    try:
        job = BackgroundJob.objects.select_related("owner", "document", "session").get(id=job_id)
        if job.kind == BackgroundJob.KIND_LEARNING_QUIZ:
            result = build_learning_quiz_job(job)
        elif job.kind == BackgroundJob.KIND_LEARNING_PATH:
            result = build_learning_path_job(job)
        elif job.kind == BackgroundJob.KIND_ROAST:
            result = build_roast_job(job)
        elif job.kind == BackgroundJob.KIND_FORTUNE:
            result = build_fortune_job(job)
        elif job.kind == BackgroundJob.KIND_DOCUMENT_INGEST:
            result = process_document_job(job)
        else:
            raise ValueError("Unsupported background job.")

        BackgroundJob.objects.filter(id=job_id).update(
            status=BackgroundJob.STATUS_COMPLETED,
            result=result,
            error_message="",
            finished_at=timezone.now(),
        )
    except Exception as error:
        BackgroundJob.objects.filter(id=job_id).update(
            status=BackgroundJob.STATUS_FAILED,
            error_message=str(error) or "Background job failed.",
            finished_at=timezone.now(),
        )
        job = BackgroundJob.objects.select_related("document").filter(id=job_id).first()
        if job and job.kind == BackgroundJob.KIND_DOCUMENT_INGEST and job.document_id:
            ChatDocument.objects.filter(id=job.document_id).update(
                processing_status=ChatDocument.STATUS_FAILED,
                processing_error=str(error) or "Document processing failed.",
            )
    finally:
        close_old_connections()


def background_loop():
    global _inflight
    while True:
        close_old_connections()
        done_futures = {future for future in _inflight if future.done()}
        if done_futures:
            _inflight -= done_futures

        while len(_inflight) < MAX_WORKERS:
            job_id = claim_next_job()
            if job_id is None:
                break
            future = _executor.submit(run_job, job_id)
            _inflight.add(future)

        time.sleep(POLL_INTERVAL_SECONDS)


def start_background_runner():
    global _runner_started, _runner_thread, _executor
    if not should_start_background_runner():
        return

    with _runner_lock:
        if _runner_started:
            return

        _executor = ThreadPoolExecutor(
            max_workers=MAX_WORKERS,
            thread_name_prefix="app-background",
        )
        _runner_thread = threading.Thread(
            target=background_loop,
            name="app-background-runner",
            daemon=True,
        )
        _runner_thread.start()
        _runner_started = True
