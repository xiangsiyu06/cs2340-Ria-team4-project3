const { test, expect } = require('@playwright/test');

const answer = {
  answer: 'An answer grounded in a test document.',
  question_type: 'factual',
  sources: [{ title: 'CS requirements', url: 'https://example.org/catalog.pdf', page: 7, excerpt: 'An excerpt from the test document.' }],
};

async function submit(page, question = 'What are the CS requirements?') {
  await page.getByRole('textbox', { name: 'Your question' }).fill(question);
  await page.getByRole('button', { name: 'Send question' }).click();
}

test('preview posts a real CSRF-protected request and opens its source', async ({ page }) => {
  await page.goto('/preview/');
  await page.getByRole('button', { name: /Know your requirements/ }).click();
  await expect(page.getByRole('textbox', { name: 'Your question' })).toHaveValue(/BS in Computer Science/);
  const sent = page.waitForRequest('**/preview/api/chat/');
  await page.getByRole('button', { name: 'Send question' }).click();
  const request = await sent;
  expect(request.headers()['x-csrftoken']).toBeTruthy();
  expect(request.postDataJSON()).toEqual({ question: 'What are the degree requirements for the BS in Computer Science?' });
  await expect(page.locator('.message-assistant')).toContainText('not academic advice');
  await page.locator('.source-summary').click();
  await expect(page.locator('.source-content')).toContainText('Source cards help you check');
  const popupPromise = page.waitForEvent('popup');
  await page.getByRole('link', { name: /Open original document/ }).click();
  const popup = await popupPromise;
  await expect(popup.getByRole('heading', { name: 'DegreeGuide sample document' })).toBeVisible();
  await popup.close();
  await page.getByRole('button', { name: /New conversation/ }).click();
  await expect(page.getByRole('heading', { name: /A clearer path/ })).toBeVisible();
  await expect(page.locator('.message')).toHaveCount(0);
});

test('preserves order, blocks duplicate requests while loading, and attaches sources to each answer', async ({ page }) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/api/chat/', async route => {
    await gate;
    await route.fulfill({ json: answer });
  });
  await page.goto('/');
  await submit(page);
  await expect(page.getByRole('status')).toHaveText('Looking for an answer and its sources…');
  await expect(page.getByRole('button', { name: 'Send question' })).toBeDisabled();
  await expect(page.getByRole('button', { name: /New conversation/ })).toBeDisabled();
  release();
  await expect(page.locator('.message-assistant')).toHaveCount(1);
  await submit(page, 'A second independent question');
  await expect(page.locator('.message')).toHaveCount(4);
  await expect(page.locator('.message-assistant .answer-sources')).toHaveCount(2);
  await page.locator('.source-summary').first().click();
  await expect(page.getByRole('link', { name: /Open original document/ }).first()).toHaveAttribute('href', 'https://example.org/catalog.pdf#page=7');
});

test('server failure retains question and retries without duplicating it', async ({ page }) => {
  let requests = 0;
  await page.route('**/api/chat/', route => {
    requests += 1;
    return route.fulfill(requests === 1 ? { status: 503, body: 'Unavailable' } : { json: answer });
  });
  await page.goto('/');
  await submit(page);
  await expect(page.getByRole('alert')).toContainText('unavailable');
  await expect(page.getByRole('textbox', { name: 'Your question' })).toHaveValue('What are the CS requirements?');
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.locator('.message-assistant')).toHaveCount(1);
  await expect(page.locator('.message-user')).toHaveCount(1);
  await expect(page.getByRole('alert')).toBeHidden();
});

test('renders untrusted text literally and rejects executable source links', async ({ page }) => {
  await page.route('**/api/chat/', route => route.fulfill({ json: {
    answer: '<img src=x onerror="window.injected=true">',
    sources: [{ title: '<script>bad()</script>', url: 'javascript:alert(1)', excerpt: '<b>plain text</b>' }],
  } }));
  await page.goto('/');
  await submit(page);
  await expect(page.locator('.message-assistant')).toContainText('<img src=x');
  await expect(page.locator('.message-assistant img, .message-assistant script')).toHaveCount(0);
  await page.locator('.source-summary').click();
  await expect(page.locator('.source-content')).toContainText('Original document link unavailable');
  await expect(page.locator('.source-content a')).toHaveCount(0);
});

test('answers with no sources are explicit', async ({ page }) => {
  await page.route('**/api/chat/', route => route.fulfill({ json: { answer: 'No relevant information found.', sources: [] } }));
  await page.goto('/');
  await submit(page);
  await expect(page.locator('.message-assistant')).toContainText('No sources were returned');
});

for (const [name, response] of [
  ['malformed JSON', { body: '<html>Not JSON</html>' }],
  ['missing answer', { json: { sources: [] } }],
  ['invalid sources', { json: { answer: 'Answer', sources: [null] } }],
]) {
  test(`${name} shows a recoverable error`, async ({ page }) => {
    await page.route('**/api/chat/', route => route.fulfill(response));
    await page.goto('/');
    await submit(page);
    await expect(page.getByRole('alert')).toContainText('could not be read');
    await expect(page.locator('.message-assistant')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Send question' })).toBeEnabled();
  });
}

test('offline requests can be retried', async ({ page }) => {
  await page.route('**/api/chat/', route => route.abort());
  await page.goto('/');
  await submit(page);
  await expect(page.getByRole('alert')).toContainText('Could not connect');
});

test('timeout restores the composer', async ({ page }) => {
  await page.clock.install();
  await page.route('**/api/chat/', () => {});
  await page.goto('/');
  await submit(page);
  await page.clock.fastForward(60001);
  await expect(page.getByRole('alert')).toContainText('taking too long');
  await expect(page.getByRole('textbox', { name: 'Your question' })).toBeEditable();
});

test('keyboard input supports multiline and IME without sending blank questions', async ({ page }) => {
  await page.goto('/preview/');
  const input = page.getByRole('textbox', { name: 'Your question' });
  await input.fill('   ');
  await expect(page.getByRole('button', { name: 'Send question' })).toBeDisabled();
  await input.fill('First line');
  await input.press('Shift+Enter');
  await input.press('a');
  await expect(input).toHaveValue('First line\na');
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true });
  await expect(page.locator('.message')).toHaveCount(0);
  await input.press('Enter');
  await expect(page.locator('.message-assistant')).toHaveCount(1);
  await page.getByRole('button', { name: 'How it works' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
});

for (const width of [1440, 390, 320]) {
  test(`layout fits a ${width}px viewport`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/preview/');
    await expect(page.getByRole('heading', { name: /A clearer path/ })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/welcome-${width}.png`, fullPage: true });
    await submit(page);
    await expect(page.locator('.message-assistant')).toHaveCount(1);
    await page.locator('.source-summary').click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/answer-${width}.png`, fullPage: true });
  });
}
