import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, it } from 'vitest'

const frontend = process.cwd()
const playwright = resolve('node_modules/playwright/cli.js')

function listTests(config?: string) {
  const args = [playwright, 'test', '--list']
  if (config) args.push(`--config=${config}`)
  const result = spawnSync(process.execPath, args, {
    cwd: frontend,
    encoding: 'utf8',
    env: { ...process.env },
  })
  assert.equal(result.status, 0, result.stderr || result.stdout)
  return result.stdout
}

describe('browser acceptance isolation', () => {
  it('keeps the default suite on the ten main-flow tests', () => {
    const output = listTests()
    assert.match(output, /Total: 10 tests in 1 file/)
    assert.doesNotMatch(output, /motion(?:-components)?\.spec\.ts/)
  })

  it('discovers the six motion tests in their own configuration', () => {
    const output = listTests('playwright.motion.config.ts')
    assert.match(output, /Total: 6 tests in 2 files/)
    assert.doesNotMatch(output, /task-browser-acceptance\.spec\.ts/)
  })

  it('derives fixture and report locations from an isolated run id', () => {
    const config = readFileSync(resolve('playwright.config.ts'), 'utf8')
    const server = readFileSync(resolve('e2e/acceptance_server.py'), 'utf8')
    assert.match(config, /ACCEPTANCE_RUN_ID/)
    assert.match(server, /ACCEPTANCE_RUN_ID/)
  })
})
