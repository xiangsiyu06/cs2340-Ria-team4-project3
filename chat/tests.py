import json
from io import BytesIO
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from knowledge.models import DataSource
from knowledge.services import ingest_source
from rag.services import NO_RESULT_TEXT


class ConnectedChatTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.source = DataSource.objects.create(
            name="Computer Science courses", source_type="catalog_url",
            url="https://catalog.gatech.edu/coursesaz/cs/",
            major="Computer Science", catalog_year="2026-2027",
        )
        with patch("knowledge.services.fetch_html", return_value=(
            '<main><h2 id="cs1332">CS 1332</h2><p>CS 1332. Data Structures and '
            'Algorithms for Applications. 3 Credit Hours.</p></main>'
        )):
            ingest_source(self.source)

    def ask(self, question):
        page = self.client.get(reverse("frontend:chat"))
        return self.client.post(
            reverse("rag:ask"), json.dumps({"question": question}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=page.cookies["csrftoken"].value,
        )

    def test_home_opens_connected_chat_and_preview_is_not_published(self):
        self.assertRedirects(self.client.get("/"), "/chat/")
        page = self.client.get("/chat/")
        self.assertContains(page, 'data-api-url="/rag/ask/"')
        self.assertContains(page, reverse("knowledge:source_list"))
        self.assertNotContains(page, 'class="preview-banner"')
        self.assertEqual(self.client.get("/preview/").status_code, 404)

    @patch.dict("os.environ", {"LLM_API_KEY": "integration-test-key"})
    @patch("rag.llm.urlopen")
    def test_ingested_document_reaches_provider_and_returns_cited_answer(self, provider):
        payload = json.dumps({
            "choices": [{"message": {"content": "CS 1332 is 3 credit hours [1]."}}],
        }).encode()
        # A fresh response per call: the retrieval planner calls the model before the answer does.
        provider.return_value.__enter__.side_effect = lambda *args: BytesIO(payload)
        response = self.ask("How many credit hours is CS 1332?")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["answer"], "CS 1332 is 3 credit hours [1].")
        self.assertEqual(result["question_type"], "Factual lookup")
        self.assertEqual(result["sources"][0]["url"], self.source.url + "#cs1332")
        self.assertIn("3 Credit Hours", result["sources"][0]["excerpt"])
        sent = json.loads(provider.call_args.args[0].data)
        self.assertIn("3 Credit Hours", sent["messages"][1]["content"])

    @patch("rag.llm.urlopen")
    def test_unsupported_question_uses_real_no_result_flow(self, provider):
        result = self.ask("How do I bake sourdough bread?").json()
        self.assertEqual(result["answer"], NO_RESULT_TEXT)
        self.assertEqual(result["sources"], [])
        provider.assert_not_called()

    @patch.dict("os.environ", {"LLM_API_KEY": ""})
    def test_missing_key_produces_recoverable_service_error(self):
        with self.assertLogs("rag.views", level="ERROR"):
            response = self.ask("What is CS 1332?")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("answer", response.json())

    @patch("rag.llm.urlopen")
    def test_inactive_document_is_not_used(self, provider):
        self.source.is_active = False
        self.source.save(update_fields=["is_active"])
        self.assertEqual(self.ask("What is CS 1332?").json()["sources"], [])
        provider.assert_not_called()

    def test_knowledge_pages_share_navigation_and_keep_staff_access(self):
        response = self.client.get(reverse("knowledge:source_list"))
        self.assertEqual(response.status_code, 302)
        page = self.client.get(response.url)
        self.assertContains(page, 'class="app-shell"')
        self.assertContains(page, reverse("frontend:chat"))
        self.assertContains(page, "Staff sign in")
