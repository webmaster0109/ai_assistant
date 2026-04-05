import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import ChatConversations, ChatSession


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
