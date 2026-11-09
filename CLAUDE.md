# CLAUDE.md

Shared context for every Ria 4 teammate's Claude Code. Read this before making changes.

## Project

- **Course:** Georgia Tech CS 2340 Objects and Design, Fall 2026, Project 3. Team Ria 4 (5 people).
- **Product:** DegreeGuide is a RAG chatbot, hosted as a web app, that answers undergraduates' questions about degree requirements, prerequisites, and graduation progress. Answers may be based **only** on the official course catalog and degree-requirement PDFs, and must cite their sources.
- **Data import, two ways:** (1) scraping catalog web pages (e.g. catalog.gatech.edu); (2) uploading degree-requirement PDFs.
- **Stack:** Django 5.2, Trello, GitHub. Deployed on a **PythonAnywhere free account**.
- **Not decided yet:** the LLM, the embedding model, and the vector store. Do not add a dependency for any of these until the team agrees.
- **Deployment constraint:** a PythonAnywhere free account only allows outbound requests to whitelisted hosts. LLM APIs and catalog scraping may be blocked; the team is still confirming this. Do not assume production has general internet access. Free accounts also have a small disk quota, so check before adding heavy packages (e.g. local ML models).

## Grading rules (these drive how "done" is defined)

- Each user story is **all-or-nothing**. A partly working story earns zero.
- A story counts only if it works **on the deployed website**. Working locally is not enough.
- **Administrator** stories must be features of the website itself, not something done only in a cloud console.
- Each person does **only their own stories**. Building someone else's story is discouraged, even partly.
- Each sprint has a **live demo** where every member must explain their own code, plus a 5–10 minute summary video. Keep code simple enough for its owner to explain, and walk the teammate through what you wrote.

## User stories

| ID | Story | Owner | Sprint | App |
|----|-------|-------|--------|-----|
| US1 | End user accesses the chatbot through the hosted web app | Yinuo Chen | 1 | deployment |
| US2 | End user asks questions in natural language | Bingchang Wu | 1 | `chat` |
| US3 | Answers are grounded in the dataset; when nothing relevant is found, say so instead of inventing an answer | Yuhang Jiang | 1 | `rag` |
| US4 | Show which documents or sources an answer used | Bingchang Wu | 1 | `chat` |
| US5 | Developer defines and updates the dataset (data source management) | Siyu Xiang | 1 | `knowledge` |
| US6 | Developer has at least two import methods: web scraping + PDF upload | Yongyi Zhang | 1 | `knowledge` |
| US7 | Developer cleans and preprocesses data before import | Yongyi Zhang | 1 | `knowledge` |
| US8 | Select or build the prompt dynamically at runtime based on question type (editing one static prompt does not count) | Yuhang Jiang | 1 | `rag` |
| US9 | Test answer accuracy with a set of known questions | Yuhang Jiang | 2 | `rag` |
| US10 | Administrator monitors performance (latency, failures) | Yinuo Chen | 2 | `monitoring` |
| US11 | Administrator manually clears or reloads the knowledge base | Yongyi Zhang | 2 | `knowledge` |
| US12 | Administrator views usage logs (query count, timestamps, response times) | Yinuo Chen | 2 | `monitoring` |
| C1 | (Custom) Student enters major and completed courses, sees which degree requirements are still missing | Siyu Xiang | 2 | `planner` |
| C2 | (Custom) Student sees how completed courses would count toward another major, to judge the cost of switching | Bingchang Wu | 2 | `planner` |

Acceptance criteria for each story are written by the Product Owner (Siyu) and tracked in Trello. Check them before you implement a story.

## Team

| Member | Role | Sprint 1 | Sprint 2 |
|--------|------|----------|----------|
| Siyu Xiang | Product Owner | US5 | C1 |
| Yinuo Chen | Scrum Master | US1 (incl. PythonAnywhere deployment) | US10, US12 |
| Yongyi Zhang | Back-end | US6, US7 | US11 |
| Yuhang Jiang | Full-stack | US3, US8 | US9 |
| Bingchang Wu | Front-end | US2, US4 | C2 |

## Apps

| App | URL prefix | Purpose / stories | Owner(s) |
|-----|------------|-------------------|----------|
| `core` | `/` | Shared pages and the base template | Bingchang Wu, Yinuo Chen |
| `chat` | `/chat/` | US2, US4 | Bingchang Wu |
| `knowledge` | `/knowledge/` | US5, US6, US7, US11 | Siyu Xiang (US5), Yongyi Zhang (US6, US7, US11) |
| `rag` | `/rag/` | US3, US8, US9 | Yuhang Jiang |
| `monitoring` | `/monitoring/` | US10, US12 | Yinuo Chen |
| `planner` | `/planner/` | C1, C2 | Siyu Xiang (C1), Bingchang Wu (C2) |

Other top-level paths:
- `config/`: `settings.py` and root `urls.py` (shared files).
- `templates/`: project-wide templates, including the base template (shared).
- `static/`: project-wide static files. `staticfiles/` is the `collectstatic` output and is git-ignored.

## Interfaces being agreed in Sprint 1

- **Q&A interface (Yuhang + Bingchang):** `answer(question) -> {text, sources, intent}`, provided by `rag` and called by `chat`. Treat the exact field types as provisional until both owners confirm them.
- **Data source and document models (Siyu + Yongyi):** shared by US5, US6, US7, and later US11 in `knowledge`. Don't change these models without both owners agreeing.
- **LLM, embedding model, and vector store (Yongyi + Yuhang):** still open, and they depend on the PythonAnywhere whitelist check (Yinuo).
- **UI design system and base template (Bingchang):** colors, fonts, base template, components. Other pages should extend the base template instead of defining their own layout.

## Rules for working in this repo

1. **Know whose work this is.** Find out which teammate you are working for (ask, or check `git config user.name`). Implement only that person's stories. If a task belongs to another teammate's story, say so and stop. Don't build it, even partly.
2. **Change only your own app.** In apps with two owners (`knowledge`, `planner`), stay in your own story's code. Coordinate with the co-owner before changing anything you both depend on, such as `models.py` or `urls.py`.
3. **Shared files need a heads-up.** Before you change `config/settings.py`, `config/urls.py`, or the base template, post on Teams first. If you are about to edit one, remind the user to do this.
4. **No secrets in git.** Never commit `.env` or any key. Read secrets with `os.getenv(...)`; `settings.py` already calls `load_dotenv`. When you add a new variable, add it to `.env.example` with a placeholder value only.
5. **Ownership of setup and deployment.** Siyu pushes the Sprint 1 skeleton. Yinuo owns deployment and US1. Don't write deployment configuration (PythonAnywhere WSGI file, web app setup, etc.) unless you are working for Yinuo.
6. **Branches and PRs.** One branch per story, named after it (e.g. `us5-dataset-management`). Merge into `main` only through a pull request with at least one teammate's review. Never push directly to `main`.
7. **Dependencies.** Add new packages to `requirements.txt` pinned with `==`. Add only the packages you need; don't overwrite the file with your whole `pip freeze`. Mention new dependencies in the PR description.
8. **Definition of done.** A story is done only when every acceptance criterion works on the deployed PythonAnywhere site.

## Commands

```bash
python3 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
python manage.py check
python manage.py makemigrations <app>
python manage.py test
```

Settings come from `.env`: `SECRET_KEY`, `DEBUG` (defaults to False if unset), `ALLOWED_HOSTS` (comma-separated), `LLM_API_KEY`.
