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
