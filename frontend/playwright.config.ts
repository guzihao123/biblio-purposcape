import { defineConfig } from '@playwright/test'

const acceptanceBackendPort = process.env.ACCEPTANCE_BACKEND_PORT || '8000'
const acceptanceFrontendPort = process.env.ACCEPTANCE_FRONTEND_PORT || '5185'
const acceptanceRunId = process.env.ACCEPTANCE_RUN_ID || `main-${acceptanceBackendPort}`
process.env.ACCEPTANCE_RUN_ID = acceptanceRunId
const outputRoot = `test-results/${acceptanceRunId}`

export default defineConfig({
  testDir: './e2e',
  testIgnore: ['**/real-backend/**', '**/motion.spec.ts', '**/motion-components.spec.ts'],
  timeout: 120000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  workers: 1,
  outputDir: `${outputRoot}/playwright-artifacts`,
  reporter: [
    ['list'],
    ['json', { outputFile: `${outputRoot}/acceptance-results.json` }],
    ['html', { outputFolder: `${outputRoot}/acceptance-html`, open: 'never' }],
  ],
  use: {
    baseURL: `http://127.0.0.1:${acceptanceFrontendPort}`,
    headless: true,
    viewport: { width: 1440, height: 900 },
    actionTimeout: 15000,
    navigationTimeout: 30000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: '../.venv/bin/python e2e/acceptance_server.py',
      url: `http://127.0.0.1:${acceptanceBackendPort}/api/health`,
      reuseExistingServer: false,
      timeout: 180000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${acceptanceFrontendPort}`,
      url: `http://127.0.0.1:${acceptanceFrontendPort}`,
      reuseExistingServer: false,
      timeout: 30000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
  projects: [
    { name: 'chromium', use: { viewport: { width: 1440, height: 900 } } },
  ],
})
