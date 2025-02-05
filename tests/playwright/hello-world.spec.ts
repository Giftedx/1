import { test, expect } from '@playwright/test';

test('hello world test', async ({ page }) => {
  await page.goto('http://localhost:3000');
  const helloWorldText = await page.locator('text=Hello World').isVisible();
  expect(helloWorldText).toBe(true);
});
