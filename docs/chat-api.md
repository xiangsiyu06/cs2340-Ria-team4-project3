# Proposed chat API · Sprint 1

Owner: Yuhang Jiang (US3/US8). Consumer: Bingchang Wu (US2/US4).
This is a proposed contract, pending teammate agreement.

## Mount the frontend in the shared Django project

1. Add `frontend` and `django.contrib.staticfiles` to `INSTALLED_APPS`.
2. Enable Django templates with `APP_DIRS=True` and the request context processor.
3. Keep `CsrfViewMiddleware` enabled. The rendered form provides the masked token
   sent in `X-CSRFToken`, following the [Django CSRF guide](https://docs.djangoproject.com/en/5.2/howto/csrf/).
4. Add `path("", include("frontend.urls"))` to the project's URL configuration.
5. Register the real API separately. Do not include `devpreview.urls` or deploy
   `devpreview.settings`. Configure and collect static files in the hosting project.

The default endpoint is `/api/chat/`. Override `DEGREEGUIDE_CHAT_API_URL` in the
host settings if needed. It must be on the same origin as the frontend. No browser
LLM keys or cross-origin proxy configuration is needed.

## Request

`POST /api/chat/`, `Content-Type: application/json`, `Accept: application/json`,
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
- `question_type`: optional string from runtime prompt selection.
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

## Failure

Use a non-2xx status: 400 invalid question, 403 CSRF/session, 429 rate limit,
or 5xx unavailable. JSON `{ "error": "..." }` is useful for API consumers;
the frontend uses its own status-based messages instead of exposing server details.
Malformed JSON/schema and network failures also show a recoverable error.

The frontend aborts after 60 seconds, preserves the failed question, and offers
retry without duplicating the user message. Only one request is active at a time.

## Local fixtures

Only `devpreview.urls` registers `/preview/`, `/preview/api/chat/`, and
`/preview/source/`. They are labeled fixtures without retrieval or academic claims.
The local `/api/chat/` deliberately returns 503 until the real project takes over.
