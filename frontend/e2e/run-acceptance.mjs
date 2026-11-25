import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const suite = process.argv[2]
if (!['main', 'motion'].includes(suite)) {
  console.error('Usage: node e2e/run-acceptance.mjs <main|motion>')
  process.exit(2)
}
const config = suite === 'motion' ? 'playwright.motion.config.ts' : 'playwright.config.ts'
const runId = process.env.ACCEPTANCE_RUN_ID || `${suite}-${process.pid}-${Date.now()}`
const result = spawnSync(
  process.execPath,
  [resolve('node_modules/playwright/cli.js'), 'test', `--config=${config}`],
  {
    cwd: process.cwd(),
    env: { ...process.env, ACCEPTANCE_RUN_ID: runId },
    stdio: 'inherit',
  },
)
if (result.error) throw result.error
process.exit(result.status ?? 1)
