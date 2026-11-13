const { test, expect } = require('@playwright/test');

test('shared project sends a real CSRF-protected request to the RAG endpoint', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/chat\/$/);
  await expect(page.locator('.preview-banner')).toHaveCount(0);
  const input = page.getByRole('textbox', { name: 'Your question' });
  await input.fill('How do I bake sourdough bread?');
  const responsePromise = page.waitForResponse('**/rag/ask/');
  await page.getByRole('button', { name: 'Send question' }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(response.request().headers()['x-csrftoken']).toBeTruthy();
  expect((await response.json()).sources).toEqual([]);
  await expect(page.locator('.message-assistant')).toContainText("so I won't guess");
  await expect(page.locator('.message-assistant .question-type')).toBeVisible();
  await expect(page.locator('.answer-sources')).toContainText('No sources were returned');
});

test('source management uses shared navigation and still requires staff sign-in', async ({ page }) => {
  await page.goto('/chat/');
  await page.getByRole('link', { name: 'Manage sources' }).click();
  await expect(page).toHaveURL(/\/knowledge\/login\//);
  await expect(page.getByRole('heading', { name: 'Staff sign in' })).toBeVisible();
  await expect(page.locator('.brand')).toBeVisible();
  await page.getByRole('link', { name: /Ask DegreeGuide/ }).click();
  await expect(page).toHaveURL(/\/chat\/$/);
});

test('connected layout fits a phone', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto('/chat/');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/integrated-chat-320.png', fullPage: true });
  await page.getByRole('link', { name: 'Manage sources' }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/integrated-login-320.png', fullPage: true });
});
