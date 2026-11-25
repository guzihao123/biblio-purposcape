import path from 'node:path'
import { defineConfig } from '@playwright/test'

// Loaded as CJS (no package.json type=module in this tree): __dirname is available.
const here = __dirname
const evidenceRoot = path.resolve(here, '..')

export default defineConfig({
  testDir: path.join(here, 'e2e'),
  outputDir: path.join(evidenceRoot, 'run', 'playwright-artifacts'),
  timeout: 240000,
  expect: { timeout: 30000 },
  workers: 1,
  reporter: [
    ['list'],
    ['json', { outputFile: path.join(evidenceRoot, 'evidence', 'playwright-results.json') }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5194',
    headless: true,
    acceptDownloads: true,
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
})
