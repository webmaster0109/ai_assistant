import json
from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from .documents import build_document_context
from .movies import (
    extract_release_year_filters,
    movie_matches_country_filter,
    movie_matches_year_filters,
)
from .models import (
    BackgroundJob,
    ChatConversations,
    ChatDocument,
    ChatImage,
    ChatSession,
    LearningQuizQuestion,
    LearningQuizSession,
)


User = get_user_model()


class AuthApiTests(TestCase):
    def test_register_creates_user_and_logs_them_in(self):
        response = self.client.post(
            "/api/auth/register/",
            data=json.dumps({
                "username": "sanju",
                "email": "sanju@example.com",
                "password": "SecretPass123!",
                "password_confirm": "SecretPass123!",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(username="sanju").exists())

        me_response = self.client.get("/api/auth/me/")
        self.assertEqual(me_response.status_code, 200)
        self.assertTrue(me_response.json()["authenticated"])

    def test_chat_endpoints_require_authentication(self):
        response = self.client.get("/api/chat/sessions/")
        self.assertEqual(response.status_code, 401)


class MovieRecommendationFilterTests(TestCase):
    def test_extract_release_year_filters_for_after_phrase(self):
        filters = extract_release_year_filters("released after 2022")
        self.assertEqual(filters["year_gte"], 2023)
        self.assertIsNone(filters["year_lte"])

    def test_movie_matches_year_filters_respects_after_2022_rule(self):
        self.assertFalse(movie_matches_year_filters({"year": "2022"}, year_gte=2023))
        self.assertTrue(movie_matches_year_filters({"year": "2023"}, year_gte=2023))
        self.assertTrue(movie_matches_year_filters({"year": "2025"}, year_gte=2023))

    def test_movie_matches_country_filter_uses_production_country(self):
        self.assertTrue(
            movie_matches_country_filter(
                {"production_countries": [{"iso_3166_1": "IN"}]},
                "IN",
            )
        )
        self.assertFalse(
            movie_matches_country_filter(
                {"production_countries": [{"iso_3166_1": "US"}]},
                "IN",
            )
        )

        usage_response = self.client.get("/api/usage-stats/")
        self.assertEqual(usage_response.status_code, 401)


class ChatPrivacyTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="SecretPass123!",
        )
        self.other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="SecretPass123!",
        )
        self.session = ChatSession.objects.create(
            owner=self.owner,
            model="glm-5",
            title="Owner chat",
        )
        ChatConversations.objects.create(
            session=self.session,
            user_message="Private question",
            ai_message="Private answer",
            input_tokens=12,
            output_tokens=34,
        )

    def test_users_only_see_their_own_sessions(self):
        self.client.force_login(self.other_user)

        sessions_response = self.client.get("/api/chat/sessions/")
        self.assertEqual(sessions_response.status_code, 200)
        self.assertEqual(sessions_response.json()["sessions"], [])

        history_response = self.client.get(f"/api/chat/sessions/{self.session.id}/messages/")
        self.assertEqual(history_response.status_code, 404)

    @patch("app.views.conversation_chain", return_value=("Model reply", {"input_tokens": 5, "output_tokens": 8}))
    @patch("app.views.generate_title", return_value="Fresh thread")
    def test_new_conversation_is_saved_for_authenticated_user(self, mocked_title, mocked_chain):
        self.client.force_login(self.owner)

        response = self.client.post(
            "/api/chat/",
            data=json.dumps({"message": "How are you?", "model": "glm-5"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        created_session = ChatSession.objects.get(id=payload["session"]["id"])
        self.assertEqual(created_session.owner, self.owner)
        self.assertEqual(created_session.title, "Fresh thread")
        self.assertEqual(created_session.model, "glm-5")

        created_message = ChatConversations.objects.get(session=created_session)
        self.assertEqual(created_message.ai_message, "Model reply")
        mocked_title.assert_called_once()
        mocked_chain.assert_called_once()

    def test_usage_stats_are_scoped_to_logged_in_user(self):
        self.client.force_login(self.owner)
        response = self.client.get("/api/usage-stats/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_input_tokens"], 12)
        self.assertEqual(payload["total_output_tokens"], 34)
        self.assertEqual(payload["total_tokens"], 46)
        self.assertEqual(payload["dashboard"]["total_messages"], 1)
        self.assertEqual(payload["dashboard"]["favorite_model"], "glm-5")
        self.assertEqual(payload["dashboard"]["favorite_model_messages"], 1)

    def test_usage_stats_include_dashboard_profile_metrics(self):
        first_message = self.session.conversations.first()
        first_message.created_at = timezone.make_aware(
            datetime(2026, 4, 5, 9, 15),
            timezone.get_current_timezone(),
        )
        first_message.save(update_fields=["created_at"])

        second_session = ChatSession.objects.create(
            owner=self.owner,
            model="deepseek-v3.2",
            title="Later chat",
        )
        second_message = ChatConversations.objects.create(
            session=second_session,
            user_message="Another question",
            ai_message="Another answer",
            input_tokens=20,
            output_tokens=30,
        )
        second_message.created_at = timezone.make_aware(
            datetime(2026, 4, 5, 21, 5),
            timezone.get_current_timezone(),
        )
        second_message.save(update_fields=["created_at"])

        third_message = ChatConversations.objects.create(
            session=second_session,
            user_message="Late follow-up",
            ai_message="Late answer",
            input_tokens=8,
            output_tokens=12,
        )
        third_message.created_at = timezone.make_aware(
            datetime(2026, 4, 5, 21, 45),
            timezone.get_current_timezone(),
        )
        third_message.save(update_fields=["created_at"])

        self.client.force_login(self.owner)
        response = self.client.get("/api/usage-stats/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dashboard"]["total_messages"], 3)
        self.assertEqual(payload["dashboard"]["favorite_model"], "deepseek-v3.2")
        self.assertEqual(payload["dashboard"]["favorite_model_messages"], 2)
        self.assertEqual(payload["dashboard"]["most_active_time"], "09 PM - 10 PM")
        self.assertEqual(payload["dashboard"]["most_active_time_messages"], 2)

    @patch("app.views.conversation_chain", return_value=("Regenerated answer", {"input_tokens": 7, "output_tokens": 9}))
    def test_regenerate_replaces_existing_ai_reply(self, mocked_chain):
        self.client.force_login(self.owner)
        conversation = self.session.conversations.first()

        response = self.client.post(
            f"/api/chat/sessions/{self.session.id}/messages/{conversation.id}/regenerate/",
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        conversation.refresh_from_db()
        self.assertEqual(conversation.ai_message, "Regenerated answer")
        self.assertEqual(conversation.input_tokens, 7)
        self.assertEqual(conversation.output_tokens, 9)
        self.assertEqual(self.session.conversations.count(), 1)
        mocked_chain.assert_called_once()

    def test_regenerate_respects_session_ownership(self):
        self.client.force_login(self.other_user)
        conversation = self.session.conversations.first()

        response = self.client.post(
            f"/api/chat/sessions/{self.session.id}/messages/{conversation.id}/regenerate/",
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_pin_toggle_updates_session_and_sorted_results(self):
        newer_session = ChatSession.objects.create(
            owner=self.owner,
            model="glm-5",
            title="Newest chat",
        )
        ChatConversations.objects.create(
            session=newer_session,
            user_message="Latest question",
            ai_message="Latest answer",
        )

        self.client.force_login(self.owner)

        toggle_response = self.client.post(
            f"/api/chat/sessions/{self.session.id}/pin/",
            data=json.dumps({"pinned": True}),
            content_type="application/json",
        )

        self.assertEqual(toggle_response.status_code, 200)
        self.session.refresh_from_db()
        self.assertTrue(self.session.is_pinned)

        sessions_response = self.client.get("/api/chat/sessions/")
        self.assertEqual(sessions_response.status_code, 200)
        returned_ids = [item["id"] for item in sessions_response.json()["sessions"]]
        self.assertEqual(returned_ids[0], self.session.id)
        self.assertEqual(returned_ids[1], newer_session.id)

    def test_pin_limit_restricts_to_three_sessions(self):
        pinned_sessions = [
            ChatSession.objects.create(
                owner=self.owner,
                model="glm-5",
                title=f"Pinned {index}",
                is_pinned=True,
            )
            for index in range(1, 4)
        ]
        target_session = ChatSession.objects.create(
            owner=self.owner,
            model="glm-5",
            title="Fourth pin target",
        )

        self.client.force_login(self.owner)

        response = self.client.post(
            f"/api/chat/sessions/{target_session.id}/pin/",
            data=json.dumps({"pinned": True}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "You can pin only 3 chats at a time.")
        target_session.refresh_from_db()
        self.assertFalse(target_session.is_pinned)
        self.assertEqual(ChatSession.objects.filter(owner=self.owner, is_pinned=True).count(), 3)

    @patch("app.views.conversation_chain", return_value=("Edited answer", {"input_tokens": 10, "output_tokens": 11}))
    def test_edit_message_updates_target_and_removes_later_conversations(self, mocked_chain):
        follow_up = ChatConversations.objects.create(
            session=self.session,
            user_message="Second question",
            ai_message="Second answer",
            input_tokens=5,
            output_tokens=6,
        )
        self.client.force_login(self.owner)
        first_conversation = self.session.conversations.order_by("created_at", "id").first()

        response = self.client.post(
            f"/api/chat/sessions/{self.session.id}/messages/{first_conversation.id}/edit/",
            data=json.dumps({"message": "Updated first question"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        first_conversation.refresh_from_db()
        self.assertEqual(first_conversation.user_message, "Updated first question")
        self.assertEqual(first_conversation.ai_message, "Edited answer")
        self.assertFalse(ChatConversations.objects.filter(id=follow_up.id).exists())
        self.assertEqual(payload["removed_count"], 1)
        self.assertEqual(len(payload["messages"]), 1)
        mocked_chain.assert_called_once()

    def test_share_toggle_and_public_history_are_read_only(self):
        self.client.force_login(self.owner)

        toggle_response = self.client.post(
            f"/api/chat/sessions/{self.session.id}/share/",
            data=json.dumps({"is_public": True}),
            content_type="application/json",
        )

        self.assertEqual(toggle_response.status_code, 200)
        self.session.refresh_from_db()
        self.assertTrue(self.session.is_public)
        self.assertTrue(self.session.share_token)

        public_response = self.client.get(f"/api/public/chat/{self.session.share_token}/")
        self.assertEqual(public_response.status_code, 200)
        public_payload = public_response.json()
        self.assertEqual(public_payload["session"]["id"], self.session.id)
        self.assertEqual(public_payload["owner"]["username"], self.owner.username)
        self.assertEqual(len(public_payload["messages"]), 1)

    def test_usage_by_model_returns_private_model_totals(self):
        ChatSession.objects.create(
            owner=self.owner,
            model="deepseek-v3.2",
            title="Second model",
        )
        second_session = ChatSession.objects.get(title="Second model")
        ChatConversations.objects.create(
            session=second_session,
            user_message="Another private question",
            ai_message="Another private answer",
            input_tokens=20,
            output_tokens=30,
        )

        self.client.force_login(self.owner)
        response = self.client.get("/api/usage-stats/models/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["models"]), 2)
        model_names = {item["model"] for item in payload["models"]}
        self.assertIn("glm-5", model_names)
        self.assertIn("deepseek-v3.2", model_names)

    def test_learning_quiz_creation_returns_background_job_locked_to_gemma4(self):
        self.client.force_login(self.owner)

        create_response = self.client.post(
            "/api/learning/quizzes/create/",
            data=json.dumps({
                "topic": "Django ORM",
                "difficulty_level": "advanced",
                "question_count": 3,
            }),
            content_type="application/json",
        )

        self.assertEqual(create_response.status_code, 202)
        payload = create_response.json()
        self.assertEqual(payload["job"]["kind"], "learning_quiz")
        self.assertEqual(payload["job"]["status"], "queued")
        self.assertEqual(payload["job"]["payload"]["topic"], "Django ORM")
        self.assertEqual(payload["job"]["payload"]["model"], "gemma4")
        self.assertEqual(payload["job"]["payload"]["difficulty_level"], "advanced")

    def test_learning_quiz_detail_returns_questions_for_owner(self):
        self.client.force_login(self.owner)
        quiz = LearningQuizSession.objects.create(
            owner=self.owner,
            topic="Django ORM",
            model="gemma4",
            difficulty_level="intermediate",
            total_questions=2,
        )
        LearningQuizQuestion.objects.create(
            quiz_session=quiz,
            question_text="What does get() return?",
            option_a="A queryset",
            option_b="One object",
            option_c="A serializer",
            option_d="A template",
            correct_option="B",
            explanation="get() returns one matching object.",
            sort_order=1,
        )

        response = self.client.get(f"/api/learning/quizzes/{quiz.id}/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["quiz"]["topic"], "Django ORM")
        self.assertEqual(payload["quiz"]["difficulty_level"], "intermediate")
        self.assertEqual(payload["quiz"]["difficulty_label"], "Intermediate")
        self.assertEqual(len(payload["quiz"]["questions"]), 1)
        self.assertEqual(payload["quiz"]["questions"][0]["question_text"], "What does get() return?")

    def test_learning_quiz_delete_removes_owner_quiz(self):
        self.client.force_login(self.owner)
        quiz = LearningQuizSession.objects.create(
            owner=self.owner,
            topic="Django ORM",
            model="gemma4",
            total_questions=2,
        )

        response = self.client.delete(f"/api/learning/quizzes/{quiz.id}/delete/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(LearningQuizSession.objects.filter(id=quiz.id).exists())

    def test_learning_path_generation_returns_background_job(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            "/api/learning/path/",
            data=json.dumps({
                "goal": "I want to learn machine learning",
                "model": "glm-5",
                "experience_level": "Beginner",
                "weekly_hours": "8",
                "timeline": "3 months",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["job"]["kind"], "learning_path")
        self.assertEqual(payload["job"]["status"], "queued")

    def test_movie_recommendation_creation_returns_background_job_locked_to_gemma4(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            "/api/movie-recommendations/",
            data=json.dumps({
                "mood": "Feel-good and uplifting",
                "genre": "Comedy",
                "country": "India",
                "extra_preferences": "Warm ending",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["job"]["kind"], "movie_recommendation")
        self.assertEqual(payload["job"]["payload"]["model"], "gemma4")
        self.assertEqual(payload["job"]["payload"]["mood"], "Feel-good and uplifting")

    @patch("app.background.generate_movie_recommendations")
    @patch("app.background.fetch_tmdb_movie_candidates")
    def test_movie_recommendation_background_job_builds_result(self, mocked_fetch, mocked_generate):
        mocked_fetch.return_value = [
            {
                "id": 11,
                "title": "Movie One",
                "year": "2024",
                "rating": 8.2,
                "overview": "Overview",
                "original_language": "en",
                "poster_url": "https://example.com/poster.jpg",
                "backdrop_url": "",
                "tmdb_url": "https://www.themoviedb.org/movie/11",
            }
        ]
        mocked_generate.return_value = {
            "title": "Tonight's perfect picks",
            "subtitle": "Great match for your mood.",
            "picks": [
                {
                    "id": 11,
                    "title": "Movie One",
                    "year": "2024",
                    "rating": 8.2,
                    "overview": "Overview",
                    "original_language": "en",
                    "poster_url": "https://example.com/poster.jpg",
                    "backdrop_url": "",
                    "tmdb_url": "https://www.themoviedb.org/movie/11",
                    "why": "Warm and uplifting.",
                }
            ],
        }
        job = BackgroundJob.objects.create(
            owner=self.owner,
            kind=BackgroundJob.KIND_MOVIE_RECOMMENDATION,
            title="Movies: uplifting",
            payload={
                "mood": "uplifting",
                "genre": "Comedy",
                "country": "India",
                "extra_preferences": "Warm ending",
                "model": "gemma4",
            },
        )

        from .background import build_movie_recommendation_job

        result = build_movie_recommendation_job(job)

        self.assertEqual(result["movies"]["title"], "Tonight's perfect picks")
        self.assertEqual(result["movies"]["picks"][0]["title"], "Movie One")
        mocked_fetch.assert_called_once()
        mocked_generate.assert_called_once()

    def test_roast_mode_creation_returns_background_job_locked_to_qwen35(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            "/api/roast-mode/",
            data=json.dumps({
                "content_type": "code",
                "language": "hindi",
                "content": "print('hello world')",
                "improvement_goal": "Make it cleaner and more professional",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["job"]["kind"], "roast")
        self.assertEqual(payload["job"]["status"], "queued")
        self.assertEqual(payload["job"]["payload"]["model"], "qwen3.5")
        self.assertEqual(payload["job"]["payload"]["content_type"], "code")
        self.assertEqual(payload["job"]["payload"]["language"], "hindi")

    def test_fortune_mode_creation_returns_background_job_locked_to_deepseek_v31(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            "/api/fortune-mode/",
            data=json.dumps({
                "focus_area": "love",
                "language": "english",
                "question": "What do the stars say about my next month?",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["job"]["kind"], "fortune")
        self.assertEqual(payload["job"]["status"], "queued")
        self.assertEqual(payload["job"]["payload"]["model"], "deepseek-v3.1")
        self.assertEqual(payload["job"]["payload"]["focus_area"], "love")

    @patch("app.views.extract_pdf_chunks", return_value=[
        {"page_number": 1, "content": "Django request lifecycle details."},
        {"page_number": 2, "content": "Middleware and URL resolution."},
    ])
    def test_pdf_upload_creates_document_session_and_chunks(self, mocked_extract):
        self.client.force_login(self.owner)
        file_obj = SimpleUploadedFile(
            "guide.pdf",
            b"%PDF-1.4 fake pdf bytes",
            content_type="application/pdf",
        )

        response = self.client.post(
            "/api/chat/documents/",
            data={"file": file_obj, "model": "glm-5"},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        session = ChatSession.objects.get(id=payload["session"]["id"])
        document = ChatDocument.objects.get(session=session, is_active=True)
        self.assertEqual(session.owner, self.owner)
        self.assertEqual(session.model, "glm-5")
        self.assertEqual(document.filename, "guide.pdf")
        self.assertEqual(document.chunks.count(), 2)
        self.assertEqual(session.documents.count(), 1)
        mocked_extract.assert_called_once()

    @patch("app.views.extract_pdf_chunks")
    def test_pdf_upload_preserves_older_documents_and_marks_latest_active(self, mocked_extract):
        mocked_extract.side_effect = [
            [{"page_number": 1, "content": "First PDF content"}],
            [{"page_number": 1, "content": "Second PDF content"}],
        ]
        self.client.force_login(self.owner)

        first_response = self.client.post(
            "/api/chat/documents/",
            data={
                "file": SimpleUploadedFile("first.pdf", b"%PDF-1.4 first", content_type="application/pdf"),
                "model": "glm-5",
            },
        )
        session_id = first_response.json()["session"]["id"]

        second_response = self.client.post(
            "/api/chat/documents/",
            data={
                "file": SimpleUploadedFile("second.pdf", b"%PDF-1.4 second", content_type="application/pdf"),
                "session_id": session_id,
            },
        )

        self.assertEqual(second_response.status_code, 201)
        session = ChatSession.objects.get(id=session_id)
        documents = list(session.documents.order_by("uploaded_at"))
        self.assertEqual(len(documents), 2)
        self.assertFalse(documents[0].is_active)
        self.assertTrue(documents[1].is_active)
        self.assertEqual(documents[0].filename, "first.pdf")
        self.assertEqual(documents[1].filename, "second.pdf")

    @patch("app.views.extract_pdf_chunks", return_value=[
        {"page_number": 1, "content": "Reusable PDF content"},
    ])
    def test_same_pdf_is_reused_within_same_chat_session(self, mocked_extract):
        self.client.force_login(self.owner)

        first_response = self.client.post(
            "/api/chat/documents/",
            data={
                "file": SimpleUploadedFile("guide.pdf", b"%PDF-1.4 same-bytes", content_type="application/pdf"),
                "model": "glm-5",
            },
        )
        session_id = first_response.json()["session"]["id"]

        second_response = self.client.post(
            "/api/chat/documents/",
            data={
                "file": SimpleUploadedFile("guide-again.pdf", b"%PDF-1.4 same-bytes", content_type="application/pdf"),
                "session_id": session_id,
            },
        )

        self.assertEqual(second_response.status_code, 200)
        payload = second_response.json()
        session = ChatSession.objects.get(id=session_id)
        self.assertEqual(session.documents.count(), 1)
        reused_document = session.documents.get()
        self.assertEqual(payload["document"]["id"], reused_document.id)
        self.assertTrue(payload["reused"])
        mocked_extract.assert_called_once()

    def test_document_selection_switches_active_pdf(self):
        self.client.force_login(self.owner)
        first_document = ChatDocument.objects.create(
            session=self.session,
            file=SimpleUploadedFile("first.pdf", b"%PDF-1.4 first", content_type="application/pdf"),
            filename="first.pdf",
            is_active=True,
            extracted_characters=1200,
        )
        second_document = ChatDocument.objects.create(
            session=self.session,
            file=SimpleUploadedFile("second.pdf", b"%PDF-1.4 second", content_type="application/pdf"),
            filename="second.pdf",
            is_active=False,
            extracted_characters=2200,
        )

        response = self.client.post(
            f"/api/chat/sessions/{self.session.id}/documents/{second_document.id}/select/",
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        first_document.refresh_from_db()
        second_document.refresh_from_db()
        self.assertFalse(first_document.is_active)
        self.assertTrue(second_document.is_active)
        payload = response.json()
        self.assertEqual(payload["document"]["id"], second_document.id)
        self.assertEqual(payload["session"]["document"]["id"], second_document.id)

    def test_document_context_prefers_requested_chapter_section(self):
        document = ChatDocument.objects.create(
            session=self.session,
            file=SimpleUploadedFile("book.pdf", b"%PDF-1.4 book", content_type="application/pdf"),
            filename="book.pdf",
            is_active=True,
            extracted_characters=3000,
        )
        document.chunks.create(chunk_index=0, page_number=1, content="Chapter 1 Introduction to Python")
        document.chunks.create(chunk_index=1, page_number=2, content="Variables, numbers, and strings.")
        document.chunks.create(chunk_index=2, page_number=120, content="Chapter 5 Functions and decorators")
        document.chunks.create(chunk_index=3, page_number=121, content="Functions accept arguments and can return values.")
        document.chunks.create(chunk_index=4, page_number=122, content="Decorators wrap callables and preserve behavior.")
        document.chunks.create(chunk_index=5, page_number=150, content="Chapter 6 Classes and inheritance")

        context = build_document_context(self.session.id, "What topics are covered in chapter 5?")

        self.assertIn("Chapter 5 Functions and decorators", context)
        self.assertIn("Functions accept arguments and can return values.", context)
        self.assertIn("Decorators wrap callables and preserve behavior.", context)
        self.assertNotIn("Chapter 1 Introduction to Python", context)

    def test_document_context_builds_overview_for_broad_pdf_review_query(self):
        document = ChatDocument.objects.create(
            session=self.session,
            file=SimpleUploadedFile("overview-book.pdf", b"%PDF-1.4 overview", content_type="application/pdf"),
            filename="overview-book.pdf",
            is_active=True,
            extracted_characters=6000,
        )
        document.chunks.create(chunk_index=0, page_number=1, content="Chapter 1 Getting Started")
        document.chunks.create(chunk_index=1, page_number=2, content="Installing Python and setting up the environment.")
        document.chunks.create(chunk_index=2, page_number=100, content="Chapter 5 Functions")
        document.chunks.create(chunk_index=3, page_number=101, content="Function arguments, return values, and decorators.")
        document.chunks.create(chunk_index=4, page_number=200, content="Chapter 9 Async IO")
        document.chunks.create(chunk_index=5, page_number=201, content="Asyncio tasks, await, and concurrency patterns.")

        context = build_document_context(self.session.id, "review the pdf content")

        self.assertIn("Chapter 1 Getting Started", context)
        self.assertIn("Chapter 5 Functions", context)
        self.assertIn("Chapter 9 Async IO", context)

    def test_pdf_upload_rejects_unsupported_model(self):
        self.client.force_login(self.owner)
        file_obj = SimpleUploadedFile(
            "guide.pdf",
            b"%PDF-1.4 fake pdf bytes",
            content_type="application/pdf",
        )

        response = self.client.post(
            "/api/chat/documents/",
            data={"file": file_obj, "model": "glm-4.7"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "This model does not support document chat. Choose one of the unlocked document models.",
        )

    def test_pdf_upload_rejects_file_larger_than_hundred_mb(self):
        self.client.force_login(self.owner)
        file_obj = SimpleUploadedFile(
            "large-guide.pdf",
            b"x" * ((100 * 1024 * 1024) + 1),
            content_type="application/pdf",
        )

        response = self.client.post(
            "/api/chat/documents/",
            data={"file": file_obj, "model": "glm-5"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "PDF size must be 100 MB or less.")

    def test_models_catalog_exposes_document_support(self):
        response = self.client.get("/api/models/")
        self.assertEqual(response.status_code, 200)
        models = response.json()["models"]
        glm5 = next(item for item in models if item["key"] == "glm-5")
        glm47 = next(item for item in models if item["key"] == "glm-4.7")
        gemma3 = next(item for item in models if item["key"] == "gemma3")
        gemma4 = next(item for item in models if item["key"] == "gemma4")
        qwen35 = next(item for item in models if item["key"] == "qwen3.5")
        qwen3vl = next(item for item in models if item["key"] == "qwen3-vl")
        kimi = next(item for item in models if item["key"] == "kimi-k2.5")
        self.assertTrue(glm5["supports_documents"])
        self.assertFalse(glm47["supports_documents"])
        self.assertTrue(gemma3["supports_vision"])
        self.assertTrue(gemma4["supports_vision"])
        self.assertTrue(qwen35["supports_vision"])
        self.assertTrue(qwen3vl["supports_vision"])
        self.assertTrue(kimi["supports_vision"])

    def test_image_upload_requires_vision_model(self):
        self.client.force_login(self.owner)
        file_obj = SimpleUploadedFile(
            "diagram.png",
            b"fake-image-bytes",
            content_type="image/png",
        )

        response = self.client.post(
            "/api/chat/images/",
            data={"file": file_obj, "model": "deepseek-v3.2"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "This model does not support image chat. Choose one of the unlocked vision models.",
        )

    def test_image_upload_creates_active_image_for_chat(self):
        self.client.force_login(self.owner)
        file_obj = SimpleUploadedFile(
            "diagram.png",
            b"fake-image-bytes",
            content_type="image/png",
        )

        response = self.client.post(
            "/api/chat/images/",
            data={"file": file_obj, "model": "gemma4"},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        session = ChatSession.objects.get(id=payload["session"]["id"])
        image = ChatImage.objects.get(session=session, is_active=True)
        self.assertEqual(session.model, "gemma4")
        self.assertEqual(payload["image"]["id"], image.id)
        self.assertEqual(image.content_type, "image/png")
        self.assertEqual(payload["session"]["active_images"][0]["id"], image.id)

    def test_multiple_image_upload_activates_all_selected_images(self):
        self.client.force_login(self.owner)
        first_file = SimpleUploadedFile(
            "diagram-1.png",
            b"fake-image-bytes-1",
            content_type="image/png",
        )
        second_file = SimpleUploadedFile(
            "diagram-2.png",
            b"fake-image-bytes-2",
            content_type="image/png",
        )

        response = self.client.post(
            "/api/chat/images/",
            data={"files": [first_file, second_file], "model": "gemma4"},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        session = ChatSession.objects.get(id=payload["session"]["id"])
        self.assertEqual(session.images.filter(is_active=True).count(), 2)
        self.assertEqual(len(payload["session"]["active_images"]), 2)
        self.assertEqual(
            [image["name"] for image in payload["session"]["active_images"]],
            ["diagram-1.png", "diagram-2.png"],
        )

    def test_multiple_image_upload_rejects_total_size_above_limit(self):
        self.client.force_login(self.owner)
        first_file = SimpleUploadedFile(
            "diagram-1.png",
            b"a" * (30 * 1024 * 1024),
            content_type="image/png",
        )
        second_file = SimpleUploadedFile(
            "diagram-2.png",
            b"b" * (21 * 1024 * 1024),
            content_type="image/png",
        )

        response = self.client.post(
            "/api/chat/images/",
            data={"files": [first_file, second_file], "model": "gemma4"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Selected images must be 50 MB or less in total.")

    def test_uploading_pdf_deactivates_active_image(self):
        self.client.force_login(self.owner)
        session = ChatSession.objects.create(
            owner=self.owner,
            model="gemma4",
            title="Vision chat",
        )
        image = ChatImage.objects.create(
            session=session,
            filename="diagram.png",
            content_type="image/png",
            is_active=True,
        )

        with patch("app.views.extract_pdf_chunks", return_value=[{"chunk_index": 0, "page_number": 1, "content": "Chapter 1"}]):
            response = self.client.post(
                "/api/chat/documents/",
                data={
                    "session_id": session.id,
                    "file": SimpleUploadedFile(
                        "notes.pdf",
                        b"%PDF-1.4 fake content",
                        content_type="application/pdf",
                    ),
                },
            )

        self.assertEqual(response.status_code, 201)
        session.refresh_from_db()
        image.refresh_from_db()
        self.assertFalse(image.is_active)
        self.assertTrue(session.documents.get().is_active)

    def test_deactivate_active_image_clears_session_image(self):
        self.client.force_login(self.owner)
        session = ChatSession.objects.create(
            owner=self.owner,
            model="gemma4",
            title="Vision chat",
        )
        image = ChatImage.objects.create(
            session=session,
            filename="diagram.png",
            content_type="image/png",
            is_active=True,
        )

        response = self.client.post(
            f"/api/chat/sessions/{session.id}/images/{image.id}/deactivate/",
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        image.refresh_from_db()
        self.assertFalse(image.is_active)
        self.assertIsNone(response.json()["session"]["image"])

    def test_deactivate_all_images_clears_active_image_set(self):
        self.client.force_login(self.owner)
        session = ChatSession.objects.create(
            owner=self.owner,
            model="gemma4",
            title="Vision chat",
        )
        first_image = ChatImage.objects.create(
            session=session,
            filename="diagram-1.png",
            content_type="image/png",
            is_active=True,
        )
        second_image = ChatImage.objects.create(
            session=session,
            filename="diagram-2.png",
            content_type="image/png",
            is_active=True,
        )

        response = self.client.post(
            f"/api/chat/sessions/{session.id}/images/deactivate-all/",
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        first_image.refresh_from_db()
        second_image.refresh_from_db()
        self.assertFalse(first_image.is_active)
        self.assertFalse(second_image.is_active)
        self.assertEqual(response.json()["session"]["active_images"], [])

    def test_selecting_second_image_keeps_first_image_active(self):
        self.client.force_login(self.owner)
        session = ChatSession.objects.create(
            owner=self.owner,
            model="gemma4",
            title="Vision chat",
        )
        active_image = ChatImage.objects.create(
            session=session,
            filename="active.png",
            content_type="image/png",
            is_active=True,
        )
        next_image = ChatImage.objects.create(
            session=session,
            filename="next.png",
            content_type="image/png",
            is_active=False,
        )

        response = self.client.post(
            f"/api/chat/sessions/{session.id}/images/{next_image.id}/select/",
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        active_image.refresh_from_db()
        next_image.refresh_from_db()
        self.assertTrue(next_image.is_active)
        self.assertTrue(active_image.is_active)
        self.assertEqual(
            [image["id"] for image in response.json()["session"]["active_images"]],
            [active_image.id, next_image.id],
        )

    def test_delete_active_document_promotes_next_saved_document(self):
        self.client.force_login(self.owner)
        session = ChatSession.objects.create(
            owner=self.owner,
            model="glm-5",
            title="Docs chat",
        )
        active_document = ChatDocument.objects.create(
            session=session,
            filename="active.pdf",
            is_active=True,
        )
        next_document = ChatDocument.objects.create(
            session=session,
            filename="next.pdf",
            is_active=False,
        )

        response = self.client.delete(f"/api/chat/sessions/{session.id}/documents/{active_document.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ChatDocument.objects.filter(id=active_document.id).exists())
        next_document.refresh_from_db()
        self.assertTrue(next_document.is_active)

    @patch(
        "app.views.conversation_chain_stream",
        return_value=iter(
            [
                {"type": "chunk", "content": "Hello"},
                {
                    "type": "final",
                    "content": "Hello there",
                    "usage": {"input_tokens": 3, "output_tokens": 5},
                    "stopped": False,
                },
            ]
        ),
    )
    def test_streaming_chat_creates_private_conversation(self, mocked_stream):
        self.client.force_login(self.owner)

        response = self.client.post(
            "/api/chat/stream/",
            data=json.dumps({"message": "Stream this", "model": "glm-5"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        streamed = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("event: init", streamed)
        self.assertIn("event: chunk", streamed)
        self.assertIn("event: done", streamed)

        session = ChatSession.objects.get(title="Stream this")
        conversation = session.conversations.get()
        self.assertEqual(session.owner, self.owner)
        self.assertEqual(conversation.user_message, "Stream this")
        self.assertEqual(conversation.ai_message, "Hello there")
        self.assertEqual(conversation.input_tokens, 3)
        self.assertEqual(conversation.output_tokens, 5)
        mocked_stream.assert_called_once()
