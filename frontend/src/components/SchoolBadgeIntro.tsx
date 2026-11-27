import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'

const INTRO_SESSION_KEY = 'jspi-school-badge-intro-played'

function shouldPlayIntro() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false
  if (document.hidden || window.scrollY > 0) return false
  try {
    return window.sessionStorage.getItem(INTRO_SESSION_KEY) !== '1'
  } catch {
    return true
  }
}

interface SchoolBadgeIntroProps {
  source: string
  targetRef: RefObject<HTMLDivElement | null>
  onActiveChange?: (active: boolean) => void
}

export function SchoolBadgeIntro({ source, targetRef, onActiveChange }: SchoolBadgeIntroProps) {
  const introRef = useRef<HTMLImageElement>(null)
  const [enabled] = useState(shouldPlayIntro)
  const [finished, setFinished] = useState(false)

  useEffect(() => {
    if (!enabled) return
    const intro = introRef.current
    const target = targetRef.current
    if (!intro || !target) return

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    let disposed = false
    let completed = false
    let started = false
    let fallbackTimer = 0

    const removeListeners = () => {
      window.clearTimeout(fallbackTimer)
      intro.removeEventListener('animationend', complete)
      window.removeEventListener('scroll', complete)
      window.removeEventListener('resize', complete)
      document.removeEventListener('visibilitychange', handleVisibility)
      motionQuery.removeEventListener('change', handleMotion)
    }

    const pauseBackdrop = (active: boolean) => {
      if (started || !active) onActiveChange?.(active)
    }

    const releaseBackdrop = () => {
      if (!started) return
      started = false
      onActiveChange?.(false)
    }

    const complete = () => {
      if (disposed || completed) return
      completed = true
      removeListeners()
      intro.classList.remove('is-running')
      target.classList.remove('school-badge--intro-pending')
      if (started) target.classList.add('school-badge--intro-static')
      releaseBackdrop()
      setFinished(true)
    }

    const handleVisibility = () => {
      if (document.hidden) complete()
    }

    const handleMotion = () => {
      if (motionQuery.matches) complete()
    }

    const start = async () => {
      try {
        await intro.decode()
      } catch {
        complete()
        return
      }
      if (disposed || completed) return
      if (motionQuery.matches || document.hidden || window.scrollY > 0) {
        complete()
        return
      }

      const bounds = target.getBoundingClientRect()
      if (bounds.width <= 0 || bounds.height <= 0) {
        complete()
        return
      }

      const finalSize = Math.min(bounds.width, bounds.height)
      const introSize = window.innerWidth <= 760 ? 132 : 176
      const scale = introSize / finalSize
      const translateX = window.innerWidth / 2 - (bounds.left + bounds.width / 2)
      const translateY = window.innerHeight / 2 - (bounds.top + bounds.height / 2)

      intro.style.left = `${bounds.left}px`
      intro.style.top = `${bounds.top}px`
      intro.style.width = `${bounds.width}px`
      intro.style.height = `${bounds.height}px`
      intro.style.setProperty('--school-intro-x', `${translateX}px`)
      intro.style.setProperty('--school-intro-y', `${translateY}px`)
      intro.style.setProperty('--school-intro-scale', String(scale))
      intro.style.setProperty('--school-intro-scale-start', String(scale * 0.88))

      try {
        window.sessionStorage.setItem(INTRO_SESSION_KEY, '1')
      } catch {
        // Storage is optional; the animation still works without it.
      }

      started = true
      target.classList.add('school-badge--intro-pending', 'school-badge--intro-static')
      intro.classList.add('is-running')
      pauseBackdrop(true)
      intro.addEventListener('animationend', complete, { once: true })
      window.addEventListener('scroll', complete, { passive: true, once: true })
      window.addEventListener('resize', complete, { once: true })
      document.addEventListener('visibilitychange', handleVisibility)
      motionQuery.addEventListener('change', handleMotion)
      fallbackTimer = window.setTimeout(complete, 2200)
    }

    void start()
    return () => {
      disposed = true
      removeListeners()
      intro.classList.remove('is-running')
      target.classList.remove('school-badge--intro-pending', 'school-badge--intro-static')
      releaseBackdrop()
    }
  }, [enabled, onActiveChange, targetRef])

  if (!enabled || finished) return null
  return (
    <img
      ref={introRef}
      className="school-badge-intro"
      src={source}
      alt=""
      aria-hidden="true"
      draggable="false"
    />
  )
}
