import { defineConfig } from '@playwright/test'

const acceptanceRunId = process.env.ACCEPTANCE_RUN_ID || `motion-${process.env.ACCEPTANCE_BACKEND_PORT || '8000'}`
process.env.ACCEPTANCE_RUN_ID = acceptanceRunId
const { default: baseConfig } = await import('./playwright.config')
const outputRoot = `test-results/${acceptanceRunId}`

export default defineConfig({
  ...baseConfig,
  testIgnore: ['**/real-backend/**', '**/task-browser-acceptance.spec.ts'],
  outputDir: `${outputRoot}/playwright-artifacts`,
  reporter: [
    ['list'],
    ['json', { outputFile: `${outputRoot}/acceptance-results.json` }],
    ['html', { outputFolder: `${outputRoot}/acceptance-html`, open: 'never' }],
  ],
})
