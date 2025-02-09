import { test, expect } from '@playwright/test';

test('hello world test', async ({ page }) => {
  await page.goto('http://localhost:3000');
  const pageTitle = await page.title(); // Added await here
  await expect(pageTitle).toBe('Expected Title'); // And here
});
