import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from knowledge.models import Chunk, DataSource
from knowledge.services import term_vector

from .llm import LLMUnavailable
from .prompts import INTENTS, NOT_IN_SOURCES, build_messages, classify, comparison_sides
from .retrieval import retrieve, with_neighbors
from .services import NO_RESULT_TEXT, InvalidQuestion, answer, retrieve_for

ASK_URL = reverse("rag:ask")
PREVIEW_URL = reverse("rag:prompt_preview")

THREADS_TEXT = (
    "The Threads represent partial paths through the curriculum. Students weave two "
    "Threads together to earn the Bachelor of Science in Computer Science degree."
)
COURSE_TEXT = (
    "CS 1332. Data Structures and Algorithms for Applications. 3 Credit Hours. "
    "Computer data structures and algorithms in the context of object-oriented programming."
)
MATH_TEXT = (
    "The minimum GPA for graduation with a BS in Mathematics is 2.0. Students must "
    "complete the linear algebra sequence and a probability course."
)


def make_source(name, major, **overrides):
    fields = dict(
        source_type=DataSource.SourceType.CATALOG_URL,
        url=f"https://catalog.gatech.edu/{name.lower().replace(' ', '-')}/",
        major=major,
        catalog_year="2026-2027",
        status=DataSource.Status.READY,
        is_active=True,
    )
    fields.update(overrides)
    return DataSource.objects.create(name=name, **fields)


def make_chunk(source, position, text, section="", anchor=""):
    return Chunk.objects.create(
        source=source, position=position, text=text, section=section, anchor=anchor,
        vector=term_vector(text),
    )


class KnowledgeBaseMixin:
    def setUp(self):
        self.cs = make_source("BS Computer Science", "Computer Science")
        self.threads = make_chunk(self.cs, 0, THREADS_TEXT, section="Threads", anchor="threads")
        self.course = make_chunk(self.cs, 1, COURSE_TEXT, section="Courses")
        self.math = make_source("BS Mathematics", "Mathematics")
        self.gpa = make_chunk(self.math, 0, MATH_TEXT, section="Graduation")
        # Must never be retrieved: inactive, or not finished importing.
        inactive = make_source("Old CS page", "Computer Science", is_active=False)
        make_chunk(inactive, 0, "CS 1332 was retired. Threads Threads Threads.")
        pending = make_source("Half imported", "Computer Science", status=DataSource.Status.PENDING)
        make_chunk(pending, 0, "Threads Threads Threads partial paths curriculum weave.")


class RetrievalTests(KnowledgeBaseMixin, TestCase):
    def test_ranks_matching_chunk_first(self):
        hits = retrieve("How do threads work in the computer science degree?")
        self.assertEqual(hits[0].chunk, self.threads)
        self.assertGreater(hits[0].score, 0.5)

    def test_course_code_finds_the_course_entry(self):
        hits = retrieve("What is CS 1332?")
        self.assertEqual([hit.chunk for hit in hits], [self.course])

    def test_only_active_ready_sources_take_part(self):
        chunks = {hit.chunk for hit in retrieve("Threads threads", floor=0.0)}
        self.assertEqual(chunks, {self.threads})

    def test_unrelated_question_returns_nothing(self):
        self.assertEqual(retrieve("How do I bake sourdough bread?"), [])
        self.assertEqual(retrieve("what is the"), [])

    def test_matches_on_source_metadata(self):
        hits = retrieve("mathematics graduation requirements")
        self.assertEqual(hits[0].chunk, self.gpa)

    def test_short_chunk_brings_in_the_chunk_that_follows(self):
        heading = make_chunk(self.math, 1, "The following courses count toward the option:", section="Option")
        table = make_chunk(self.math, 2, "MATH 4150 | Introduction to Number Theory | 3", section="Option")
        make_chunk(self.math, 3, "Unrelated closing paragraph about advising.", section="Advising")
        hits = retrieve("Which courses count toward the option?", floor=0.0)
        self.assertEqual(hits[0].chunk, heading)
        chunks = with_neighbors(hits)
        self.assertEqual(chunks[:2], [heading, table])
        self.assertEqual(len(chunks), len({c.id for c in chunks}))
        prompt = build_messages("q", chunks)[1]["content"]
        self.assertIn("[2] BS Mathematics (Mathematics, 2026-2027) - section: Option - continues directly from [1]", prompt)
        self.assertNotIn("[1] BS Mathematics (Mathematics, 2026-2027) - section: Option - continues", prompt)

    def test_comparison_retrieves_each_side(self):
        question = "What is the difference between the Threads and the GPA?"
        self.assertEqual(comparison_sides(question), ["Threads", "GPA"])
        merged = retrieve_for(question, INTENTS["comparison"])
        chunks = [hit.chunk for hit in merged]
        self.assertIn(self.threads, chunks)
        self.assertIn(self.gpa, chunks)
        self.assertEqual(len(chunks), len(set(chunks)))
        self.assertLessEqual(len(chunks), INTENTS["comparison"].retrieval_limit)
        self.assertEqual([hit.score for hit in merged], sorted((hit.score for hit in merged), reverse=True))


class ClassifierTests(TestCase):
    CASES = {
        "factual_lookup": [
            "How many credit hours does the CS degree require?",
            "What is the prerequisite for CS 1332?",
            "What is CS 1332?",
            "Is CS 2340 required?",
            "What GPA do I need for the BS/MS program?",
        ],
        "explanation": [
            "How do threads work in the Computer Science degree?",
            "Why do threads exist?",
            "Tell me about the Media thread",
            "What are the degree requirements for the BS in Computer Science?",
        ],
        "comparison": [
            "What is the difference between the Intelligence and Systems threads?",
            "Which is harder, CS 1332 or CS 2110?",
            "Compare the math and CS majors",
        ],
        "planning": [
            "Can I take CS 3510 before CS 1332?",
            "What should I take next semester if I finished CS 1331?",
            "Which courses count toward the Research Option?",
        ],
        "general": ["threads", "Media thread"],
    }

    def test_rules_pick_the_intent_at_runtime(self):
        for key, questions in self.CASES.items():
            for question in questions:
                with self.subTest(question=question):
                    result = classify(question)
                    self.assertEqual(result.intent.key, key)
                    self.assertEqual(bool(result.matched), key != "general")

    def test_comparison_sides_are_extracted(self):
        cases = {
            "What is the difference between the Intelligence and Systems threads?": ["Intelligence", "Systems"],
            "Which is harder, CS 1332 or CS 2110?": ["CS 1332", "CS 2110"],
            "How does the People thread compare to Media?": ["People", "Media"],
            "Intelligence thread vs Theory thread": ["Intelligence", "Theory"],
            "What is CS 1332?": [],
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(comparison_sides(question), expected)

    def test_every_intent_has_its_own_instructions(self):
        instructions = {intent.instructions for intent in INTENTS.values()}
        self.assertEqual(len(instructions), len(INTENTS))
        for intent in INTENTS.values():
            system = build_messages("q", [], intent)[0]["content"]
            self.assertIn(intent.instructions, system)
            self.assertIn(NOT_IN_SOURCES, system)


class PromptTests(KnowledgeBaseMixin, TestCase):
    def test_messages_number_sources_and_require_grounding(self):
        messages = build_messages("What is CS 1332?", [self.threads, self.course])
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn(NOT_IN_SOURCES, messages[0]["content"])
        user = messages[1]["content"]
        self.assertIn("[1] BS Computer Science (Computer Science, 2026-2027) - section: Threads", user)
        self.assertIn("[2] BS Computer Science", user)
        self.assertIn(COURSE_TEXT, user)
        self.assertTrue(user.rstrip().endswith(f"reply with exactly {NOT_IN_SOURCES}."))


@mock.patch("rag.services.complete")
class AnswerServiceTests(KnowledgeBaseMixin, TestCase):
    def test_no_relevant_chunks_means_no_model_call(self, complete):
        result = answer("How do I bake sourdough bread?")
        self.assertEqual(result.text, NO_RESULT_TEXT)
        self.assertEqual(result.sources, [])
        complete.assert_not_called()

    def test_model_can_decline_when_sources_do_not_answer(self, complete):
        complete.return_value = NOT_IN_SOURCES
        result = answer("What is the CS 1332 grading policy?")
        self.assertEqual(result.text, NO_RESULT_TEXT)
        self.assertEqual(result.sources, [])

    def test_sources_are_the_cited_chunks_in_order(self, complete):
        complete.return_value = "Two Threads make a degree [2]. CS 1332 is 3 credits [1] [2]. Unknown [7]."
        result = answer("Threads and CS 1332")
        self.assertEqual(result.text, "Two Threads make a degree [1]. CS 1332 is 3 credits [2] [1]. Unknown.")
        self.assertEqual(len(result.sources), 2)
        first, second = result.sources
        self.assertEqual(first.title, "BS Computer Science: Threads")
        self.assertEqual(first.url, self.cs.url + "#threads")
        self.assertIsNone(first.page)
        self.assertTrue(THREADS_TEXT.startswith(first.excerpt[:40]))
        self.assertEqual(second.title, "BS Computer Science: Courses")

    def test_uncited_answer_falls_back_to_best_chunk(self, complete):
        complete.return_value = "CS 1332 covers data structures."
        result = answer("What is CS 1332?")
        self.assertEqual([s.title for s in result.sources], ["BS Computer Science: Courses"])

    def test_as_dict_matches_chat_api_contract(self, complete):
        complete.return_value = "Answer [1]."
        data = answer("What is CS 1332?").as_dict()
        self.assertEqual(set(data), {"answer", "question_type", "sources"})
        self.assertEqual(data["question_type"], "Factual lookup")
        self.assertEqual(set(data["sources"][0]), {"title", "url", "page", "excerpt"})

    def test_intent_controls_prompt_retrieval_and_temperature(self, complete):
        complete.return_value = "Answer [1]."
        with mock.patch("rag.services.retrieve", wraps=__import__("rag.services", fromlist=["retrieve"]).retrieve) as retrieve_spy:
            result = answer("Compare the Threads with CS 1332")
        self.assertEqual(result.intent, "Comparison")
        self.assertEqual(retrieve_spy.call_args.kwargs["limit"], INTENTS["comparison"].retrieval_limit)
        messages, kwargs = complete.call_args.args[0], complete.call_args.kwargs
        self.assertIn(INTENTS["comparison"].instructions, messages[0]["content"])
        self.assertEqual(kwargs["temperature"], INTENTS["comparison"].temperature)

    def test_rejects_bad_questions(self, complete):
        for bad in (None, 3, "", "   \n ", "x" * 2001):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidQuestion):
                    answer(bad)
        complete.assert_not_called()

    def test_model_failure_propagates(self, complete):
        complete.side_effect = LLMUnavailable("down")
        with self.assertRaises(LLMUnavailable):
            answer("What is CS 1332?")


class AskViewTests(KnowledgeBaseMixin, TestCase):
    def post(self, body, content_type="application/json"):
        if not isinstance(body, str):
            body = json.dumps(body)
        return self.client.post(ASK_URL, body, content_type=content_type)

    @mock.patch("rag.services.complete", return_value="CS 1332 is Data Structures [1].")
    def test_answers_with_sources(self, complete):
        response = self.post({"question": "What is CS 1332?"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["answer"], "CS 1332 is Data Structures [1].")
        self.assertEqual(data["sources"][0]["title"], "BS Computer Science: Courses")
        self.assertEqual(data["sources"][0]["url"], self.cs.url)

    def test_no_result_answer_has_empty_sources(self):
        with mock.patch("rag.services.complete") as complete:
            data = self.post({"question": "Who won the world cup?"}).json()
            complete.assert_not_called()
        self.assertEqual(data, {"answer": NO_RESULT_TEXT, "question_type": "Factual lookup", "sources": []})

    def test_rejects_bad_requests(self):
        self.assertEqual(self.client.get(ASK_URL).status_code, 405)
        self.assertEqual(self.post("question=hi", content_type="application/x-www-form-urlencoded").status_code, 415)
        self.assertEqual(self.post("{not json").status_code, 400)
        for payload in ({}, [], {"question": " "}, {"question": 2}, {"question": "x" * 2001}):
            with self.subTest(payload=payload):
                self.assertEqual(self.post(payload).status_code, 400)

    @mock.patch("rag.services.complete", side_effect=LLMUnavailable("timeout"))
    def test_model_outage_is_a_503_not_a_guess(self, complete):
        response = self.post({"question": "What is CS 1332?"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("answer", response.json())

    def test_csrf_token_is_required(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(ASK_URL, json.dumps({"question": "What is CS 1332?"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)


class PromptPreviewTests(KnowledgeBaseMixin, TestCase):
    def test_requires_staff(self):
        response = self.client.get(PREVIEW_URL, {"q": "What is CS 1332?"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_shows_intent_rule_and_prompt_without_calling_the_model(self):
        staff = get_user_model().objects.create_user("staff", password="pw", is_staff=True)
        self.client.force_login(staff)
        with mock.patch("rag.llm.complete") as complete:
            response = self.client.get(PREVIEW_URL, {"q": "Compare the Threads with CS 1332"})
            complete.assert_not_called()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["intent"], "comparison")
        self.assertEqual(data["question_type"], "Comparison")
        self.assertEqual(data["matched_text"], "Compare")
        self.assertEqual(data["retrieval_limit"], INTENTS["comparison"].retrieval_limit)
        self.assertEqual([r["source"] for r in data["retrieved"]], ["BS Computer Science", "BS Computer Science"])
        self.assertIn(INTENTS["comparison"].instructions, data["messages"][0]["content"])
        self.assertIn(COURSE_TEXT, data["messages"][1]["content"])
        self.assertEqual(self.client.get(PREVIEW_URL, {"q": " "}).status_code, 400)
