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
- Local fixture preview for independent UI review. It is not a working RAG system.

## Team dependencies before story acceptance

- Yuhang: agree on [the API contract](chat-api.md) and connect real grounded answers,
  document URLs, and runtime question types.
- Yongyi/Siyu: provide real ingested source metadata and accessible originals.
- Yinuo: mount `frontend` in the shared project, serve static assets, and deploy.
- Bingchang/client: review visual direction and demonstrate both stories against
  the real backend on the hosted application.

The assignment grades stories on the hosted site. US2 and US4 are not claimed
complete until live integration and hosted acceptance pass.

## Verification

```sh
source .venv/bin/activate
python manage.py check
python manage.py test
npm ci
npm test
```

Browser tests require Node 20+ and installed Google Chrome (`channel: 'chrome'`). They launch
the local Django server using `.venv/bin/python`. Tests cover real fixture requests
and CSRF, clickable originals, per-answer sources, pending state, retry, malformed
responses, no sources, unsafe content/URLs, offline failures, timeout, keyboard/IME,
and 1440/390/320px layouts. Layout screenshots are written to ignored `test-results/`.

Local verification: Django system check passed, all 7 Django tests passed, and all
14 Chrome browser tests passed. Desktop and phone screenshots were visually
inspected, including an expanded source at 320px. Live RAG behavior and hosted
deployment remain unverified until team integration.

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

Working branch: `feat/bingchang-sprint1-chat-ui`. The frontend changes are committed
on this branch for team review. No PR review, deployment, Scrum submission, or
team contact is claimed. Keep this AI conversation for the course's AI-use record.
