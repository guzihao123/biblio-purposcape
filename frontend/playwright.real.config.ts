import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e/real-backend',
  outputDir: './e2e/real-backend-results',
  timeout: 240000,
  expect: { timeout: 30000 },
  reporter: [['list'], ['json', { outputFile: './e2e/real-backend-results/results.json' }]],
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5175',
    headless: true,
    acceptDownloads: true,
    viewport: { width: 1280, height: 800 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
})
