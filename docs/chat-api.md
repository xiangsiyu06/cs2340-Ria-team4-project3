# Chat API · Sprint 1

Owner: Yuhang Jiang (US3/US8). Consumer: Bingchang Wu (US2/US4).
Implemented by the `rag` app at **`POST /rag/ask/`** (`rag/views.py`,
`rag/services.py`). The contract below is the one the frontend was built
against; the backend follows it as written.

## Mount the frontend in the shared Django project

1. Add `frontend` and `django.contrib.staticfiles` to `INSTALLED_APPS`.
2. Enable Django templates with `APP_DIRS=True` and the request context processor.
3. Keep `CsrfViewMiddleware` enabled. The rendered form provides the masked token
   sent in `X-CSRFToken`, following the [Django CSRF guide](https://docs.djangoproject.com/en/5.2/howto/csrf/).
4. `chat.urls` includes `frontend.urls`, mounting the UI at `/chat/`.
   `core.urls` redirects `/` to that page.
5. Register the real API separately. Do not include `devpreview.urls` or deploy
   `devpreview.settings`. Configure and collect static files in the hosting project.

The frontend resolves `rag:ask` as its default endpoint (`/rag/ask/`). No extra
setting is needed. `DEGREEGUIDE_CHAT_API_URL` can override it for same-origin
integrations; only the standalone fixture harness defaults to `/api/chat/`.

It must be on the same origin as the frontend. No browser LLM keys or
cross-origin proxy configuration is needed. The backend reads its model
settings from `.env` (`LLM_API_URL`, `LLM_MODEL`, `LLM_API_KEY`); see `.env.example`.

## Request

`POST /rag/ask/`, `Content-Type: application/json`, `Accept: application/json`,
`X-CSRFToken: <rendered form token>`, same-origin credentials.

```json
{ "question": "How do threads work in the Computer Science degree?" }
```

Questions are trimmed and limited to 2,000 characters. The backend must validate
this independently. Each request is standalone; the visible conversation is not
sent as model history. Students should include necessary context in each question.

## Success: HTTP 200

```json
{
  "answer": "Plain text grounded in retrieved documents.\n\nA second paragraph.",
  "question_type": "explanation",
  "sources": [
    {
      "title": "Retrieved document title",
      "url": "https://example.org/original.pdf",
      "page": 7,
      "excerpt": "The relevant passage from the retrieved document."
    }
  ]
}
```

- `answer`: required nonempty plain text. HTML and Markdown are displayed literally.
- `question_type`: the intent chosen at runtime by `rag/prompts.py` (US8). One of
  `Factual lookup`, `Explanation`, `Comparison`, `Planning`, `General`. Staff can
  see why a question was classified and the exact prompt built for it at
  `GET /rag/prompt-preview/?q=...`.
- `sources`: required array; `[]` is allowed for an explicit no-result answer.
  Return the documents actually used for this answer. The UI never invents sources.
- Each source requires a nonempty `title`. `url`, `page`, and `excerpt` may be
  omitted or null. `page` is a positive, one-based integer.
- URLs may be HTTP(S) originals or relative document routes. Uploaded PDFs need
  a stable, authorized serving URL supplied by the backend. The frontend adds
  `#page=N` to PDF links without an existing fragment. Expanding a source shows
  the excerpt and an original-document link that opens in a new tab.
- Missing or unsafe links show “Original document link unavailable.” An empty
  source list explicitly says that no sources were returned.
- Answers cite sources inline as `[1]`, `[2]`, … in the same order as the
  `sources` array. Catalog pages link to the page (plus `#anchor` when the
  section has one); uploaded PDFs link to `/knowledge/sources/<pk>/pdf/#page=N`.
- **No-result answer (US3):** when nothing relevant is in the knowledge base, or
  the model reports that the retrieved text does not answer the question, the
  backend returns a fixed explanatory `answer` with `"sources": []`. It never
  answers from outside the dataset.

## Failure

Use a non-2xx status: 400 invalid question or JSON, 403 CSRF/session,
405 not POST, 415 not `application/json`, 429 rate limit, or 503 when the
model cannot be reached (the backend never substitutes a made-up answer). JSON `{ "error": "..." }` is useful for API consumers;
the frontend uses its own status-based messages instead of exposing server details.
Malformed JSON/schema and network failures also show a recoverable error.

The frontend aborts after 60 seconds, preserves the failed question, and offers
retry without duplicating the user message. Only one request is active at a time.

## Local fixtures

Only `devpreview.urls` registers `/preview/`, `/preview/api/chat/`, and
`/preview/source/`. They are labeled fixtures without retrieval or academic claims.
The fixture harness's `/api/chat/` deliberately returns 503. The shared project
uses `/rag/ask/` and never registers sample-response routes.
