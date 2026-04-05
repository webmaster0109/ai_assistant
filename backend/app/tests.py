import json
from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from .models import (
    ChatConversations,
    ChatDocument,
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

    @patch(
        "app.views.generate_quiz_questions",
        return_value=[
            {
                "question_text": "Which QuerySet method fetches one object by primary key?",
                "option_a": "filter()",
                "option_b": "get()",
                "option_c": "all()",
                "option_d": "values()",
                "correct_option": "B",
                "explanation": "get() fetches a single matching object.",
                "sort_order": 1,
            },
            {
                "question_text": "Which method returns SQL-ready rows as dictionaries?",
                "option_a": "values()",
                "option_b": "select_related()",
                "option_c": "prefetch_related()",
                "option_d": "first()",
                "correct_option": "A",
                "explanation": "values() returns dictionaries of selected fields.",
                "sort_order": 2,
            },
            {
                "question_text": "Which clause sorts descending?",
                "option_a": "order_by('name')",
                "option_b": "order_by('-name')",
                "option_c": "sort_by('-name')",
                "option_d": "arrange('-name')",
                "correct_option": "B",
                "explanation": "Prefixing with a minus sorts descending.",
                "sort_order": 3,
            },
        ],
    )
    def test_learning_quiz_creation_and_scoring(self, mocked_generate_quiz):
        self.client.force_login(self.owner)

        create_response = self.client.post(
            "/api/learning/quizzes/create/",
            data=json.dumps({
                "topic": "Django ORM",
                "model": "glm-5",
                "question_count": 3,
            }),
            content_type="application/json",
        )

        self.assertEqual(create_response.status_code, 201)
        payload = create_response.json()
        quiz_id = payload["quiz"]["id"]
        self.assertEqual(payload["quiz"]["topic"], "Django ORM")
        self.assertEqual(len(payload["quiz"]["questions"]), 3)
        mocked_generate_quiz.assert_called_once()

        first_question_id = payload["quiz"]["questions"][0]["id"]
        answer_response = self.client.post(
            f"/api/learning/quizzes/{quiz_id}/questions/{first_question_id}/answer/",
            data=json.dumps({"selected_option": "B"}),
            content_type="application/json",
        )

        self.assertEqual(answer_response.status_code, 200)
        answer_payload = answer_response.json()
        self.assertEqual(answer_payload["question"]["selected_option"], "B")
        self.assertTrue(answer_payload["question"]["is_correct"])
        self.assertEqual(answer_payload["question"]["correct_option"], "B")
        self.assertEqual(answer_payload["quiz"]["correct_answers"], 1)
        self.assertEqual(answer_payload["quiz"]["answered_questions"], 1)
        self.assertFalse(answer_payload["quiz"]["is_completed"])

    def test_learning_quiz_detail_returns_questions_for_owner(self):
        self.client.force_login(self.owner)
        quiz = LearningQuizSession.objects.create(
            owner=self.owner,
            topic="Django ORM",
            model="glm-5",
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
        self.assertEqual(len(payload["quiz"]["questions"]), 1)
        self.assertEqual(payload["quiz"]["questions"][0]["question_text"], "What does get() return?")

    @patch(
        "app.views.generate_learning_path",
        return_value={
            "title": "Machine Learning Roadmap",
            "summary": "A practical ML path for consistent weekly progress.",
            "first_steps": ["Revise Python basics", "Set up notebooks", "Review linear algebra"],
            "milestones": [
                {
                    "title": "Foundations",
                    "duration": "2 weeks",
                    "focus": "Python, statistics, data handling",
                    "deliverable": "Mini data analysis notebook",
                },
                {
                    "title": "Core ML",
                    "duration": "4 weeks",
                    "focus": "Regression, classification, evaluation",
                    "deliverable": "Two end-to-end ML projects",
                },
            ],
        },
    )
    def test_learning_path_generation_returns_structured_payload(self, mocked_generate_path):
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

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["path"]["title"], "Machine Learning Roadmap")
        self.assertEqual(len(payload["path"]["milestones"]), 2)
        mocked_generate_path.assert_called_once()

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

    def test_pdf_upload_rejects_file_larger_than_ten_mb(self):
        self.client.force_login(self.owner)
        file_obj = SimpleUploadedFile(
            "large-guide.pdf",
            b"x" * ((10 * 1024 * 1024) + 1),
            content_type="application/pdf",
        )

        response = self.client.post(
            "/api/chat/documents/",
            data={"file": file_obj, "model": "glm-5"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "PDF size must be 10 MB or less.")

    def test_models_catalog_exposes_document_support(self):
        response = self.client.get("/api/models/")
        self.assertEqual(response.status_code, 200)
        models = response.json()["models"]
        glm5 = next(item for item in models if item["key"] == "glm-5")
        glm47 = next(item for item in models if item["key"] == "glm-4.7")
        self.assertTrue(glm5["supports_documents"])
        self.assertFalse(glm47["supports_documents"])

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
