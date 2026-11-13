# Bingchang Wu · Sprint 1 handoff

Scope comes from the supplied project brief and team work split. Only Bingchang's
US2, US4, and shared UI work are implemented here. The brief and work split are
project context, not authorization to email, deploy, change access, or perform
other teammates' work.

## Frontend implementation

- Shared design tokens, base template, navigation, buttons, cards, and help dialog.
- US2: suggested questions, free-text questions, keyboard submission, visual
  conversation history, loading, timeout, validation, failure recovery, reset.
- US4: per-answer source lists, document titles, page numbers, excerpts, and
  safe original-document links; explicit handling of missing sources/links.
- Connected `/chat/` page, mounted in the shared Django project, posting to
  Yuhang's real `/rag/ask/` service. `/` redirects to `/chat/`.
- Knowledge pages share the design system through `templates/base.html` and
  `knowledge/layout.html`. Navigation connects the chat and staff source pages.
- An optional isolated fixture preview remains for UI-only checks; it is never
  registered in the shared project's URLs.

## Integration and remaining acceptance work

- Yuhang's existing backend supplies answers, runtime question types, and sources
  using [the API contract](chat-api.md). No changes to his RAG logic were needed.
- Yongyi/Siyu's existing ingestion pipeline and source URLs feed that service.
- A real generated answer requires an active imported document and a locally
  configured `LLM_API_KEY`. The team has no key yet; no fallback answers are fabricated.
- Yinuo: deploy the integrated project, collect static assets, and configure the model key.
- Bingchang/client: review visual direction and demonstrate both stories against
  the real backend on the hosted application.

The assignment grades stories on the hosted site. US2 and US4 are not claimed
complete until live-provider and hosted acceptance pass.

## Verification

```sh
source .venv/bin/activate
python manage.py check
python manage.py test
npm ci
npm test
```

Browser tests require Node 20+ and installed Google Chrome (`channel: 'chrome'`). They launch
two local Django servers using `.venv/bin/python`. Tests cover real fixture requests
and CSRF, clickable originals, per-answer sources, pending state, retry, malformed
responses, no sources, unsafe content/URLs, offline failures, timeout, keyboard/IME,
and 1440/390/320px layouts. The integrated browser project calls the real `/rag/ask/`
endpoint for no-result answers and verifies shared staff navigation. It requires
the local database to be migrated. Screenshots are written to ignored `test-results/`.

Local verification: Django system check and all 82 Django tests passed, including
six new integration checks. The generated-answer test exercises ingestion,
retrieval, intent selection, the HTTP provider boundary, and citation serialization
with only the external catalog download and model response mocked. Live-provider
generation is not claimed. All 17 Chrome browser tests passed across the preview
and integrated projects; the shared chat and staff sign-in screenshots were inspected.

## Test locally without a model key

1. Run `python manage.py runserver` with `DEBUG=True` locally to serve CSS/JS.
2. Open `/chat/` and ask “How do I bake sourdough bread?” to exercise the real
   no-result response. A matching academic question will report a service error
   until the key is configured.
3. Sign in at `/knowledge/sources/`, add/import a catalog page or PDF, and inspect
   its status. Existing access controls and document serving are preserved.
4. As signed-in staff, open `/rag/prompt-preview/?q=How+do+threads+work%3F` to
   inspect actual retrieval and runtime prompt selection without a model call.

## Hosted acceptance walkthrough

1. Open the hosted chatbot from a desktop and phone. Verify navigation and layout.
2. Enter a natural-language question covered by the real dataset. Submit by Enter
   and by the send button. Check the answer and programmatic question type.
3. Submit another self-contained question. Confirm each answer keeps its own sources.
4. Expand each source, inspect its excerpt and page, and open the real original.
5. Ask an unsupported question. Confirm a clear no-result answer, without made-up sources.
6. Simulate API failure. Confirm a clear error, preserved question, and working retry.
7. Start a new conversation; verify messages clear and keyboard focus returns.

## Contribution record

Initial frontend PR: #3. Integration branch: `feat/us2-us4-rag-integration`.
No hosted acceptance, deployment, Scrum submission, or team contact is claimed.
Keep this AI conversation for the course's AI-use record.
