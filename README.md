# DegreeGuide · Ria Team 4

Bingchang Wu's Sprint 1 frontend: US2 (natural-language questions), US4
(answer sources), and a shared Django UI foundation.

## Run locally

Python 3.10+ is required. No database, API key, or Node build is needed.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py runserver
```

- http://127.0.0.1:8000/ — frontend targeting the proposed live `/api/chat/` API.
  Until the backend is integrated, submissions show an unavailable message.
- http://127.0.0.1:8000/preview/ — explicitly labeled UI preview with fixed
  sample responses and a local sample source. It performs no retrieval or AI generation.

`devpreview/` is a local development harness, not the team's hosting project.
Yinuo can mount the reusable `frontend/` app into the shared Django project;
Yuhang supplies the live API. See [the integration contract](docs/chat-api.md).

## Checks

```sh
python manage.py check
python manage.py test
```

Browser checks and the manual acceptance steps are in
[the Sprint 1 handoff](docs/sprint-1-handoff.md).
Shared styles and template blocks are documented in [the UI guide](docs/ui-system.md).
