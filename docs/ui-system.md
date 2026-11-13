# DegreeGuide UI foundation

For Georgia Tech students exploring degree requirements, courses, and next steps.
The current visual direction is a proposal pending mentor/client feedback.

## Shared files

- `frontend/templates/frontend/base.html`: navigation, header, skip link, help dialog.
- `templates/base.html`: shared entry point that extends the frontend base.
- `knowledge/templates/knowledge/layout.html`: source-management wrapper using
  that shared base; knowledge pages override `knowledge_content`.
- `frontend/static/frontend/styles.css`: tokens, components, responsive layouts.
- `frontend/templates/frontend/chat.html`: US2/US4 page.
- `frontend/static/frontend/chat.js`: submissions and answer/source rendering.

## Visual language

| Token | Value | Use |
| --- | --- | --- |
| `--forest` | `#174c3c` | Primary actions, brand, links |
| `--sage` | `#e8eee7` | Quiet highlights and user messages |
| `--paper` | `#fbfcf9` | Main background |
| `--sidebar` | `#f3f5ef` | Navigation background |
| `--ink` | `#25372f` | Main text |
| `--muted` | `#657168` | Supporting text |
| `--line` | `#dfe5dc` | Dividers and borders |
| `--error` | `#963d2f` | Recoverable error text |

Body/UI: platform sans-serif. Display headings: Georgia serif. Both are local
system fonts, without remote font requests. Use short, direct, supportive copy.
Round panels use `--radius` (14px); controls use smaller corners.

## Reuse in another page

```django
{% extends 'base.html' %}
{% block title %}Dataset · DegreeGuide{% endblock %}
{% block chat_current %}{% endblock %}
{% block breadcrumb %}Dataset{% endblock %}
{% block content %}
<section class="card">
  <span class="eyebrow">KNOWLEDGE BASE</span>
  <h1>Dataset</h1>
  <button class="button button-primary" type="button">Add source</button>
</section>
{% endblock %}
```

Base blocks: `title`, `extra_head`, `breadcrumb`, `chat_current`, `content`,
`scripts`. As teammates add real routes, extend the navigation for those pages;
there are no placeholder links to future Sprint 2 features.

Components: `.button`, `.button-primary`, `.button-subtle`, `.card`, `.eyebrow`,
`.error-message`, `.source-card`. Inputs use native labels, buttons, and focus
states. Source disclosures are native `<details>`; help uses a native `<dialog>`
with Escape and a labeled close button. The chat log and request status announce
updates. Enter submits; Shift+Enter adds a newline; IME composition is preserved.

Below 760px, navigation becomes a compact header and question suggestions stack.
Respect reduced-motion preferences. No conversation is written to browser storage.
