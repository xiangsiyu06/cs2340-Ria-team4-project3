# DegreeGuide

DegreeGuide is a web-hosted RAG chatbot that answers undergraduate students' questions about degree requirements, prerequisites, and graduation progress. Every answer is grounded only in the official course catalog and degree-requirement PDFs, and cites its sources.

CS 2340 Objects and Design, Fall 2026, Project 3. Team Ria 4.

**Stack:** Django 5.2, SQLite, deployed on PythonAnywhere. The LLM, embedding model, and vector store have not been chosen yet.

## Run locally

Requires Python 3.10 or newer.

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your local environment file
cp .env.example .env              # Windows: copy .env.example .env

# 4. Set up the database
python manage.py migrate

# 5. Start the dev server
python manage.py runserver
```

The server runs at http://127.0.0.1:8000/. Until the first views are merged, `/admin/` is the only working route.

### Bingchang's Sprint 1 frontend preview

The reusable `frontend/` app contains the US2 chat interface, US4 source cards,
and shared UI styles. It is not yet mounted in the shared project or connected
to Yuhang's RAG API. `manage.py` continues to use the team's `config.settings`.
To review the frontend independently, run:

```bash
python manage.py runserver --settings=devpreview.settings
```

Open http://127.0.0.1:8000/preview/ for clearly labeled sample responses. This
preview uses no database or API keys. Its `/` route targets the proposed live
API and reports unavailable until integration; sample routes are local fixtures.

```bash
python manage.py test frontend --settings=devpreview.settings
```

Optional browser checks: Node 20+, Google Chrome, `npm ci`, then `npm test`.
Playwright starts the preview server using `.venv/bin/python`.
See [the handoff](docs/sprint-1-handoff.md), [API contract](docs/chat-api.md),
and [UI guide](docs/ui-system.md) for integration and hosted acceptance work.

`.env` holds your local settings and is git-ignored. The placeholder `SECRET_KEY=change-me` works for local development. To use a real random key instead, run:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

## Project layout

```
config/       Project settings and root URLs (shared; see rules below)
templates/    Project-wide templates, including the base template
static/       Project-wide CSS, JS, and images
core/ chat/ knowledge/ rag/ monitoring/ planner/   Django apps, one per area
```

## User stories

| ID | Story | Owner | Sprint |
|----|-------|-------|--------|
| US1 | End user accesses the chatbot through the hosted web app | Yinuo Chen | 1 |
| US2 | End user asks questions in natural language | Bingchang Wu | 1 |
| US3 | Answers are grounded in the dataset; no made-up answer when nothing relevant is found | Yuhang Jiang | 1 |
| US4 | Answers show which documents or sources they used | Bingchang Wu | 1 |
| US5 | Developer defines and updates the dataset (data source management) | Siyu Xiang | 1 |
| US6 | Developer imports data in at least two ways (web scraping + PDF upload) | Yongyi Zhang | 1 |
| US7 | Developer cleans and preprocesses data before import | Yongyi Zhang | 1 |
| US8 | Prompt is selected or built at runtime based on question type | Yuhang Jiang | 1 |
| US9 | Answer accuracy is tested against known questions | Yuhang Jiang | 2 |
| US10 | Administrator monitors performance (latency, failures) | Yinuo Chen | 2 |
| US11 | Administrator manually clears or reloads the knowledge base | Yongyi Zhang | 2 |
| US12 | Administrator views usage logs (query count, timestamps, response times) | Yinuo Chen | 2 |
| C1 | Student enters major and completed courses, sees which degree requirements are still missing | Siyu Xiang | 2 |
| C2 | Student sees how completed courses count toward another major, to judge the cost of switching | Bingchang Wu | 2 |

## Apps and ownership

| App | URL prefix | Stories | Owner(s) |
|-----|------------|---------|----------|
| `core` | `/` | Shared pages, base template | Bingchang Wu, Yinuo Chen |
| `chat` | `/chat/` | US2, US4 | Bingchang Wu |
| `knowledge` | `/knowledge/` | US5 / US6, US7, US11 | Siyu Xiang (US5) / Yongyi Zhang (US6, US7, US11) |
| `rag` | `/rag/` | US3, US8, US9 | Yuhang Jiang |
| `monitoring` | `/monitoring/` | US10, US12 | Yinuo Chen |
| `planner` | `/planner/` | C1 / C2 | Siyu Xiang (C1) / Bingchang Wu (C2) |

US1 and the PythonAnywhere deployment belong to Yinuo Chen.

## Branches and pull requests

- One branch per user story, named after it, e.g. `us5-dataset-management` or `c1-requirement-gaps`.
- Every change reaches `main` through a pull request. The only exception is the initial project skeleton.
- Each PR needs approval from at least one teammate before merging.
- Work only on your own stories and your own app. Post on Teams before you change a shared file (`config/settings.py`, `config/urls.py`, or the base template).
- Never commit `.env` or any API key. If you add a new environment variable, add it to `.env.example` with a placeholder value.
- A story counts only when all of it works on the deployed site. A partly finished story earns nothing.
