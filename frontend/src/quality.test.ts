import { describe, expect, it } from 'vitest'

import {
  QUALITY_MODE_STORAGE_KEY,
  baselineLevel,
  nextQualityMode,
  qualityModeLabel,
  readQualityMode,
  shouldDowngrade,
  shouldRecover,
  writeQualityMode,
} from './quality'

function storage(initial: Record<string, string> = {}) {
  const values = { ...initial }
  return {
    getItem: (key: string) => values[key] ?? null,
    setItem: (key: string, value: string) => {
      values[key] = value
    },
  }
}

describe('quality mode', () => {
  it('defaults to auto when nothing valid is stored', () => {
    expect(readQualityMode(storage())).toBe('auto')
    expect(readQualityMode(storage({ [QUALITY_MODE_STORAGE_KEY]: 'bogus' }))).toBe('auto')
    expect(readQualityMode(null)).toBe('auto')
  })

  it('reads and persists explicit modes', () => {
    const store = storage({ [QUALITY_MODE_STORAGE_KEY]: 'lite' })
    expect(readQualityMode(store)).toBe('lite')
    writeQualityMode('full', store)
    expect(store.getItem(QUALITY_MODE_STORAGE_KEY)).toBe('full')
  })

  it('cycles auto to lite to full and back', () => {
    expect(nextQualityMode('auto')).toBe('lite')
    expect(nextQualityMode('lite')).toBe('full')
    expect(nextQualityMode('full')).toBe('auto')
  })

  it('maps modes to readable labels', () => {
    expect(qualityModeLabel('auto')).toBe('自动')
    expect(qualityModeLabel('lite')).toBe('流畅优先')
    expect(qualityModeLabel('full')).toBe('画质优先')
  })

  it('starts low-end hardware in lite mode but keeps manual choices', () => {
    expect(baselineLevel('auto', { deviceMemory: 4, hardwareConcurrency: 8 })).toBe('lite')
    expect(baselineLevel('auto', { deviceMemory: 8, hardwareConcurrency: 4 })).toBe('lite')
    expect(baselineLevel('auto', { deviceMemory: 8, hardwareConcurrency: 8 })).toBe('full')
    expect(baselineLevel('auto', {})).toBe('full')
    expect(baselineLevel('full', { deviceMemory: 2, hardwareConcurrency: 2 })).toBe('full')
    expect(baselineLevel('lite', { deviceMemory: 32, hardwareConcurrency: 16 })).toBe('lite')
  })

  it('downgrades only when the frame rate or draw cost stays expensive', () => {
    expect(shouldDowngrade({ fps: 44, drawMs: 4 })).toBe(true)
    expect(shouldDowngrade({ fps: 60, drawMs: 15 })).toBe(true)
    expect(shouldDowngrade({ fps: 60, drawMs: 10 })).toBe(false)
  })

  it('recovers only with healthy frame rate and draw cost', () => {
    expect(shouldRecover({ fps: 55, drawMs: 8 })).toBe(true)
    expect(shouldRecover({ fps: 54, drawMs: 4 })).toBe(false)
    expect(shouldRecover({ fps: 60, drawMs: 9 })).toBe(false)
  })
})