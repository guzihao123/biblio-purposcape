export type QualityMode = 'auto' | 'lite' | 'full'
export type QualityLevel = 'lite' | 'full'

export const QUALITY_MODE_STORAGE_KEY = 'pl-quality-mode'

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>

export interface QualitySample {
  fps: number
  drawMs: number
}

function defaultStorage(): StorageLike | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

export function readQualityMode(storage: StorageLike | null = defaultStorage()): QualityMode {
  try {
    const value = storage?.getItem(QUALITY_MODE_STORAGE_KEY)
    if (value === 'auto' || value === 'lite' || value === 'full') return value
  } catch {
    // Private browsing can throw on access; fall back to auto.
  }
  return 'auto'
}

export function writeQualityMode(mode: QualityMode, storage: StorageLike | null = defaultStorage()) {
  try {
    storage?.setItem(QUALITY_MODE_STORAGE_KEY, mode)
  } catch {
    // Recording the preference is best-effort only.
  }
}

export function nextQualityMode(mode: QualityMode): QualityMode {
  if (mode === 'auto') return 'lite'
  if (mode === 'lite') return 'full'
  return 'auto'
}

export function qualityModeLabel(mode: QualityMode): string {
  if (mode === 'lite') return '流畅优先'
  if (mode === 'full') return '画质优先'
  return '自动'
}

export function baselineLevel(
  mode: QualityMode,
  hardware: { deviceMemory?: number; hardwareConcurrency?: number } = {},
): QualityLevel {
  if (mode !== 'auto') return mode
  const memory = hardware.deviceMemory ?? 8
  const cores = hardware.hardwareConcurrency ?? 8
  return memory <= 4 || cores <= 4 ? 'lite' : 'full'
}

export function shouldDowngrade({ fps, drawMs }: QualitySample): boolean {
  return fps < 45 || drawMs > 14
}

export function shouldRecover({ fps, drawMs }: QualitySample): boolean {
  return fps >= 55 && drawMs <= 8
}