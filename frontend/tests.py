import json

from django.test import Client, SimpleTestCase, override_settings
from django.urls import resolve, reverse

from devpreview import settings as preview_settings


@override_settings(
    ROOT_URLCONF="devpreview.urls",
    INSTALLED_APPS=preview_settings.INSTALLED_APPS,
    MIDDLEWARE=preview_settings.MIDDLEWARE,
)
class FrontendTests(SimpleTestCase):
    def test_home_renders_live_endpoint_and_csrf_token(self):
        response = self.client.get(reverse("frontend:chat"))
        self.assertContains(response, 'data-api-url="/api/chat/"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertNotContains(response, 'class="preview-banner"')
        self.assertIn("csrftoken", response.cookies)

    @override_settings(DEGREEGUIDE_CHAT_API_URL="/rag/ask/")
    def test_host_project_can_configure_api_url(self):
        self.assertContains(self.client.get("/"), 'data-api-url="/rag/ask/"')

    def test_frontend_app_exposes_no_fixture_api(self):
        from frontend.urls import urlpatterns

        self.assertEqual(len(urlpatterns), 1)
        self.assertEqual(resolve("/").view_name, "frontend:chat")

    def test_preview_is_labeled_and_original_document_opens(self):
        response = self.client.get("/preview/")
        self.assertContains(response, "Fixed sample answers and sources")
        self.assertContains(response, 'data-api-url="/preview/api/chat/"')
        answer = self.client.post("/preview/api/chat/", {"question": "How do threads work?"}, content_type="application/json")
        self.assertEqual(answer.status_code, 200)
        data = answer.json()
        self.assertIn("not academic advice", data["answer"])
        self.assertContains(self.client.get(data["sources"][0]["url"]), data["sources"][0]["excerpt"])

    def test_preview_rejects_bad_questions(self):
        for payload in ({}, {"question": " "}, {"question": 2}, {"question": "x" * 2001}, [], None):
            with self.subTest(payload=type(payload).__name__):
                response = self.client.post("/preview/api/chat/", json.dumps(payload), content_type="application/json")
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post("/preview/api/chat/", "{", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/preview/api/chat/", {"question": "Test"}).status_code, 415)
        self.assertEqual(self.client.get("/preview/api/chat/").status_code, 405)

    def test_live_harness_never_returns_sample_answers(self):
        response = self.client.post("/api/chat/", {"question": "Test"}, content_type="application/json")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("answer", response.json())

    def test_csrf_is_required_and_rendered_token_is_accepted(self):
        client = Client(enforce_csrf_checks=True)
        payload = {"question": "What are the requirements?"}
        self.assertEqual(client.post("/preview/api/chat/", payload, content_type="application/json").status_code, 403)
        page = client.get("/preview/")
        response = client.post("/preview/api/chat/", payload, content_type="application/json", HTTP_X_CSRFTOKEN=page.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 200)
