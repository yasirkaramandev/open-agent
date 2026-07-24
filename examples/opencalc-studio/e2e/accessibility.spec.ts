import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

test('main view has no serious or critical accessibility violations', async ({
  page,
}) => {
  await page.goto('/');

  const scan = await new AxeBuilder({ page }).analyze();
  const seriousOrCritical = scan.violations.filter(
    ({ impact }) => impact === 'serious' || impact === 'critical',
  );

  expect(seriousOrCritical).toEqual([]);
});
