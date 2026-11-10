const app = document.querySelector('[data-chat-app]');
const form = document.querySelector('#question-form');
const input = document.querySelector('#question');
const send = document.querySelector('#send-question');
const reset = document.querySelector('#new-chat');
const welcome = document.querySelector('#welcome');
const conversation = document.querySelector('#conversation');
const status = document.querySelector('#request-status');
const errorBox = document.querySelector('#request-error');
const errorText = document.querySelector('#error-text');
const retry = document.querySelector('#retry-question');
let busy = false;
let failedQuestion = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function updateComposer() {
  document.querySelector('#character-count').textContent = `${input.value.length.toLocaleString('en-US')} / 2,000`;
  send.disabled = busy || !input.value.trim() || input.value.length > 2000;
}

function setBusy(value) {
  busy = value;
  input.readOnly = value;
  reset.disabled = value || !conversation.childElementCount;
  retry.disabled = value;
  conversation.setAttribute('aria-busy', String(value));
  status.textContent = value ? 'Looking for an answer and its sources…' : '';
  updateComposer();
}

function addMessage(role, text, questionType) {
  const article = element('article', `message message-${role}`);
  const header = element('div', 'message-header');
  header.append(element('span', `message-avatar avatar-${role}`, role === 'user' ? 'Y' : 'dg'));
  header.append(element('h2', 'message-author', role === 'user' ? 'You' : 'DegreeGuide'));
  if (questionType) header.append(element('span', 'question-type', questionType));
  article.append(header, element('div', 'message-body', text));
  conversation.append(article);
  return article;
}

function sourceUrl(value, page) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const url = new URL(value, window.location.href);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return null;
    if (Number.isInteger(page) && page > 0 && /\.pdf$/i.test(url.pathname) && !url.hash) url.hash = `page=${page}`;
    return url;
  } catch {
    return null;
  }
}

function addSources(article, sources) {
  const section = element('section', 'answer-sources');
  section.setAttribute('aria-label', 'Sources for this answer');
  section.append(element('h3', 'sources-title', `SOURCES · ${sources.length}`));
  if (!sources.length) {
    section.append(element('p', 'no-sources', 'No sources were returned for this answer. Confirm the information with your catalog or advisor.'));
  }
  sources.forEach((source, index) => {
    const details = element('details', 'source-card');
    const summary = element('summary', 'source-summary');
    const title = element('span', 'source-title');
    title.append(element('strong', '', source.title));
    const url = sourceUrl(source.url, source.page);
    const location = [url?.hostname, source.page ? `Page ${source.page}` : ''].filter(Boolean).join(' · ');
    title.append(element('small', '', location || 'Document reference'));
    summary.append(element('span', 'source-number', String(index + 1)), title, element('span', 'source-chevron', '+'));
    const content = element('div', 'source-content');
    content.append(element('blockquote', '', source.excerpt || 'No excerpt was provided for this source.'));
    if (url) {
      const link = element('a', 'source-link', 'Open original document ↗');
      link.href = url.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.setAttribute('aria-label', `Open original document: ${source.title} (opens in a new tab)`);
      content.append(link);
    } else {
      content.append(element('p', 'no-sources', 'Original document link unavailable.'));
    }
    details.append(summary, content);
    section.append(details);
  });
  article.append(section);
}

function validAnswer(data) {
  return data && typeof data.answer === 'string' && data.answer.trim() &&
    Array.isArray(data.sources) && data.sources.every(source =>
      source && typeof source.title === 'string' && source.title.trim() &&
      (source.url == null || typeof source.url === 'string') &&
      (source.excerpt == null || typeof source.excerpt === 'string') &&
      (source.page == null || (Number.isInteger(source.page) && source.page > 0))) &&
    (data.question_type == null || typeof data.question_type === 'string');
}

async function ask(question, isRetry = false) {
  if (busy || !question || question.length > 2000) return;
  errorBox.hidden = true;
  welcome.hidden = true;
  conversation.hidden = false;
  if (!isRetry) addMessage('user', question);
  input.value = '';
  failedQuestion = null;
  setBusy(true);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);
  try {
    const endpoint = new URL(app.dataset.apiUrl, window.location.href);
    if (endpoint.origin !== window.location.origin) throw new Error('The question service is misconfigured. Please contact the project team.');
    const response = await fetch(endpoint, {
      method: 'POST',
      mode: 'same-origin',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]').value,
      },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const messages = {
        400: 'The question could not be accepted. Please check it and try again.',
        403: 'Your session needs a refresh. Reload this page before trying again.',
        404: 'The question service is not available yet. Please try again later.',
        429: 'Too many questions at once. Please wait a moment and try again.',
      };
      throw new Error(messages[response.status] || 'The question service is unavailable right now. Please try again later.');
    }
    const data = await response.json();
    if (!validAnswer(data)) throw new Error('The answer could not be read. Please try again.');
    const answer = addMessage('assistant', data.answer, data.question_type);
    addSources(answer, data.sources);
    answer.scrollIntoView({ block: 'nearest', behavior: 'instant' });
  } catch (error) {
    failedQuestion = question;
    input.value = question;
    errorText.textContent = error.name === 'AbortError'
      ? 'This answer is taking too long. Please try again.'
      : error instanceof TypeError
        ? 'Could not connect. Check your connection and try again.'
        : error instanceof SyntaxError
          ? 'The answer could not be read. Please try again.'
          : error.message;
    errorBox.hidden = false;
  } finally {
    clearTimeout(timeout);
    setBusy(false);
    input.focus({ preventScroll: true });
  }
}

input.addEventListener('input', () => {
  if (failedQuestion && input.value.trim() !== failedQuestion) {
    errorBox.hidden = true;
    failedQuestion = null;
  }
  updateComposer();
});
input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});
form.addEventListener('submit', event => {
  event.preventDefault();
  const question = input.value.trim();
  ask(question, question === failedQuestion);
});
retry.addEventListener('click', () => {
  if (failedQuestion) ask(failedQuestion, true);
});
document.querySelectorAll('[data-question]').forEach(button => {
  button.addEventListener('click', () => {
    input.value = button.dataset.question;
    updateComposer();
    input.focus();
  });
});
reset.addEventListener('click', () => {
  if (busy) return;
  conversation.replaceChildren();
  conversation.hidden = true;
  welcome.hidden = false;
  input.value = '';
  failedQuestion = null;
  errorBox.hidden = true;
  setBusy(false);
  input.focus();
});
updateComposer();
