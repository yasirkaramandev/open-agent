import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    environmentMatchGlobs: [['src/ui/**/*.test.tsx', 'jsdom']],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
