import { useLayoutEffect, useRef, useState } from 'react'
import introSound from '../assets/school-badge-intro.m4a?url'

const INTRO_DURATION_MS = 5600

function shouldPlayIntro() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false
  if (document.hidden || window.scrollY > 0) return false
  return true
}

interface SchoolBadgeIntroProps {
  source: string
  target: HTMLDivElement | null
  onActiveChange?: (active: boolean) => void
}

export function SchoolBadgeIntro({ source, target, onActiveChange }: SchoolBadgeIntroProps) {
  const sceneRef = useRef<HTMLDivElement>(null)
  const introRef = useRef<HTMLImageElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const completeRef = useRef<() => void>(() => {})
  const restartRef = useRef<() => void>(() => {})
  const startedAtRef = useRef(0)
  const [enabled] = useState(shouldPlayIntro)
  const [finished, setFinished] = useState(false)
  const [soundEnabled, setSoundEnabled] = useState(false)

  useLayoutEffect(() => {
    if (!enabled) return
    const scene = sceneRef.current
    const intro = introRef.current
    if (!scene || !intro || !target) return
    const page = target.closest<HTMLElement>('.invite-page')
    const layout = target.closest<HTMLElement>('.invite-layout')

    // Cover the page while the shared badge decodes, then start both timelines together.
    target.classList.add('school-badge--intro-pending', 'school-badge--intro-static')
    page?.classList.add('invite-page--intro-active')
    layout?.setAttribute('inert', '')
    scene.classList.add('is-awaiting')
    scene.focus({ preventScroll: true })
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    let active = false
    let disposed = false
    let completed = false
    let started = false
    let fallbackTimer = 0

    const setActive = (next: boolean) => {
      if (active === next) return
      active = next
      onActiveChange?.(next)
    }

    const removeListeners = () => {
      window.clearTimeout(fallbackTimer)
      intro.removeEventListener('animationend', complete)
      window.removeEventListener('scroll', complete)
      window.removeEventListener('resize', complete)
      window.removeEventListener('keydown', handleKeydown)
      document.removeEventListener('visibilitychange', handleVisibility)
      motionQuery.removeEventListener('change', handleMotion)
    }

    const complete = () => {
      if (disposed || completed) return
      completed = true
      removeListeners()
      audioRef.current?.pause()
      scene.classList.remove('is-running', 'is-awaiting')
      intro.classList.remove('is-running')
      page?.classList.remove('invite-page--intro-active', 'invite-page--intro-running')
      layout?.removeAttribute('inert')
      target.classList.remove('school-badge--intro-pending')
      if (started) target.classList.add('school-badge--intro-static')
      setActive(false)
      setFinished(true)
    }
    completeRef.current = complete

    const restart = () => {
      if (disposed || completed || !started) return
      window.clearTimeout(fallbackTimer)
      scene.classList.remove('is-running')
      intro.classList.remove('is-running')
      page?.classList.remove('invite-page--intro-running')
      void intro.offsetWidth
      startedAtRef.current = performance.now()
      page?.classList.add('invite-page--intro-running')
      scene.classList.add('is-running')
      intro.classList.add('is-running')
      fallbackTimer = window.setTimeout(complete, INTRO_DURATION_MS + 400)
    }
    restartRef.current = restart

    const handleVisibility = () => {
      if (document.hidden) complete()
    }

    const handleMotion = () => {
      if (motionQuery.matches) complete()
    }

    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') complete()
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
      const fullSize = Math.min(960, Math.min(window.innerWidth, window.innerHeight) * 0.88)
      const translateX = window.innerWidth / 2 - (bounds.left + bounds.width / 2)
      const translateY = window.innerHeight / 2 - (bounds.top + bounds.height / 2)

      intro.style.left = `${bounds.left}px`
      intro.style.top = `${bounds.top}px`
      intro.style.width = `${bounds.width}px`
      intro.style.height = `${bounds.height}px`
      intro.style.setProperty('--school-intro-x', `${translateX}px`)
      intro.style.setProperty('--school-intro-y', `${translateY}px`)
      intro.style.setProperty('--school-intro-scale', String(introSize / finalSize))
      intro.style.setProperty('--school-intro-scale-full', String(fullSize / finalSize))
      intro.style.setProperty('--school-intro-scale-start', String((introSize / finalSize) * 0.88))

      started = true
      startedAtRef.current = performance.now()
      target.classList.add('school-badge--intro-pending', 'school-badge--intro-static')
      page?.classList.add('invite-page--intro-running')
      intro.addEventListener('animationend', complete, { once: true })
      scene.classList.remove('is-awaiting')
      scene.classList.add('is-running')
      intro.classList.add('is-running')
      scene.focus({ preventScroll: true })
      fallbackTimer = window.setTimeout(complete, INTRO_DURATION_MS + 400)

      // Browsers may reject unmuted autoplay. The visible sound button then replays
      // both timelines from the beginning inside a user gesture.
      const audio = audioRef.current
      if (audio) {
        audio.volume = 0.7
        try {
          void audio.play().catch(() => setSoundEnabled(false))
        } catch {
          setSoundEnabled(false)
        }
      }
    }

    setActive(true)
    window.addEventListener('scroll', complete, { passive: true, once: true })
    window.addEventListener('resize', complete, { once: true })
    window.addEventListener('keydown', handleKeydown)
    document.addEventListener('visibilitychange', handleVisibility)
    motionQuery.addEventListener('change', handleMotion)
    void start()

    return () => {
      disposed = true
      removeListeners()
      completeRef.current = () => {}
      restartRef.current = () => {}
      audioRef.current?.pause()
      scene.classList.remove('is-running', 'is-awaiting')
      intro.classList.remove('is-running')
      page?.classList.remove('invite-page--intro-active', 'invite-page--intro-running')
      layout?.removeAttribute('inert')
      target.classList.remove('school-badge--intro-pending')
      if (!completed) target.classList.remove('school-badge--intro-static')
      setActive(false)
    }
  }, [enabled, onActiveChange, target])

  const syncSoundOffset = () => {
    const audio = audioRef.current
    if (!audio || audio.paused || audio.readyState < HTMLMediaElement.HAVE_METADATA) return
    const elapsed = Math.min(Math.max((performance.now() - startedAtRef.current) / 1000, 0), 5.55)
    try {
      if (Math.abs(audio.currentTime - elapsed) > 0.12) audio.currentTime = elapsed
    } catch {
      // Playback continues even if the browser has not exposed a seekable range yet.
    }
  }

  const toggleSound = () => {
    const audio = audioRef.current
    if (!audio) return
    if (!audio.paused) {
      audio.pause()
      return
    }

    audio.volume = 0.7
    try {
      audio.currentTime = 0
    } catch {
      // Metadata may not be available yet; the playing/metadata handlers will sync.
    }
    try {
      // Start audio synchronously in the click gesture before restarting the visuals.
      const playback = audio.play()
      restartRef.current()
      void playback.catch(() => setSoundEnabled(false))
    } catch {
      setSoundEnabled(false)
    }
    syncSoundOffset()
  }

  if (!enabled || finished) return null
  return (
    <div
      ref={sceneRef}
      className="school-badge-scene"
      role="dialog"
      aria-modal="true"
      aria-label="江苏警官学院校徽开场动画"
      tabIndex={-1}
    >
      <div className="school-badge-scene__veil" aria-hidden="true" />
      <img
        ref={introRef}
        className="school-badge-intro"
        src={source}
        alt=""
        aria-hidden="true"
        draggable="false"
      />
      <span className="school-badge-intro__light" aria-hidden="true" />
      <div className="school-badge-scene__controls" role="group" aria-label="开场动画控制">
        <button
          type="button"
          className="school-badge-scene__control"
          aria-pressed={soundEnabled}
          onClick={toggleSound}
        >
          {soundEnabled ? '关闭音效' : '开启音效并重播'}
        </button>
        <button
          type="button"
          className="school-badge-scene__control"
          onClick={() => completeRef.current()}
        >
          跳过动画
        </button>
      </div>
      <audio
        ref={audioRef}
        src={introSound}
        preload="auto"
        aria-hidden="true"
        onLoadedMetadata={syncSoundOffset}
        onPlaying={syncSoundOffset}
        onPlay={() => setSoundEnabled(true)}
        onPause={() => setSoundEnabled(false)}
        onEnded={() => setSoundEnabled(false)}
      />
    </div>
  )
}
