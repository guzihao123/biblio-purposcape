import { useEffect, useRef } from 'react'

import { baselineLevel, shouldDowngrade, shouldRecover } from '../quality'
import type { QualityLevel, QualityMode } from '../quality'

interface Star {
  x: number
  y: number
  depth: number
  size: number
  phase: number
  mint: boolean
}

interface Debris {
  angle: number
  orbit: number
  size: number
  speed: number
  spin: number
  shape: number[]
}

interface PlanetGeometry {
  centerX: number
  centerY: number
  radius: number
}

const TAU = Math.PI * 2

function seededRandom(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) >>> 0
    return seed / 4294967296
  }
}

function createStars(count: number): Star[] {
  const random = seededRandom(20261125)
  return Array.from({ length: count }, () => ({
    x: random() * 2 - 1,
    y: random() * 2 - 1,
    depth: random(),
    size: 0.4 + random() * 1.35,
    phase: random() * TAU,
    mint: random() > 0.87,
  }))
}

function createDebris(count: number): Debris[] {
  const random = seededRandom(9252026)
  return Array.from({ length: count }, () => ({
    angle: random() * TAU,
    orbit: 0.95 + random() * 0.45,
    size: 2 + random() * 12,
    speed: 0.7 + random() * 0.55,
    spin: random() * TAU,
    shape: Array.from({ length: 7 }, () => 0.72 + random() * 0.36),
  }))
}

interface SceneBackdropProps {
  qualityMode?: QualityMode
  onQualityChange?: (level: QualityLevel) => void
}

export function SceneBackdrop({ qualityMode = 'auto', onQualityChange }: SceneBackdropProps) {
  const sceneRef = useRef<HTMLDivElement>(null)
  const backCanvasRef = useRef<HTMLCanvasElement>(null)
  const frontCanvasRef = useRef<HTMLCanvasElement>(null)
  const planetRef = useRef<HTMLDivElement>(null)
  const onQualityChangeRef = useRef(onQualityChange)

  useEffect(() => {
    onQualityChangeRef.current = onQualityChange
  }, [onQualityChange])

  useEffect(() => {
    const scene = sceneRef.current
    const backCanvas = backCanvasRef.current
    const frontCanvas = frontCanvasRef.current
    const planet = planetRef.current
    if (!scene || !backCanvas || !frontCanvas || !planet || typeof window.matchMedia !== 'function') return
    const back = backCanvas.getContext('2d')
    const front = frontCanvas.getContext('2d')
    if (!back || !front) return

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    const mobileQuery = window.matchMedia('(max-width: 760px)')
    const navigatorHints = navigator as Navigator & { deviceMemory?: number }
    const hardwareLevel: QualityLevel = baselineLevel(qualityMode, {
      deviceMemory: navigatorHints.deviceMemory,
      hardwareConcurrency: navigatorHints.hardwareConcurrency,
    })
    let level: QualityLevel = hardwareLevel
    let width = 0
    let height = 0
    let stars: Star[] = []
    let debris: Debris[] = []
    let planetGeometry: PlanetGeometry = { centerX: 0, centerY: 0, radius: 0 }
    let animationFrame = 0
    let previousFrame = 0
    let pointerX = 0
    let pointerY = 0
    let targetX = 0
    let targetY = 0
    let scrollDepth = 0
    let targetScroll = 0
    let downgradeCount = 0
    let levelChangedAt = performance.now()
    let lastEvaluation = performance.now()
    let lastFrameTime = 0
    let fpsSamples: number[] = []
    let drawSamples: number[] = []

    const average = (values: number[]) => (
      values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1)
    )

    const particleCounts = () => (
      level === 'lite'
        ? { stars: mobileQuery.matches ? 65 : 160, debris: mobileQuery.matches ? 14 : 44 }
        : { stars: mobileQuery.matches ? 130 : 320, debris: mobileQuery.matches ? 28 : 88 }
    )

    const drawStar = (star: Star, time: number) => {
      const perspective = 1 / (0.78 + star.depth * 0.9)
      const drift = motionQuery.matches ? 0 : Math.sin(time * 0.00008 + star.phase) * 1.8
      const x = width / 2 + star.x * width * 0.58 * perspective + pointerX * 17 * (1 - star.depth)
      const y = height / 2 + star.y * height * 0.62 * perspective
        + pointerY * 12 * (1 - star.depth) + drift - scrollDepth * 22 * (1 - star.depth)
      if (x < -5 || x > width + 5 || y < -5 || y > height + 5) return
      const twinkle = motionQuery.matches ? 0.72 : 0.65 + Math.sin(time * 0.00055 + star.phase) * 0.17
      const alpha = (0.12 + (1 - star.depth) * 0.46) * twinkle
      back.beginPath()
      back.fillStyle = star.mint
        ? `rgba(126, 224, 213, ${alpha * 0.8})`
        : `rgba(145, 190, 224, ${alpha})`
      back.shadowColor = 'rgba(101, 177, 221, 0.28)'
      back.shadowBlur = level === 'full' && star.depth < 0.18 ? 5 : 0
      back.arc(x, y, Math.max(0.35, star.size * perspective), 0, TAU)
      back.fill()
    }

    const drawDebris = (
      piece: Debris,
      time: number,
      isFront: boolean,
      planetX: number,
      planetY: number,
    ) => {
      const angle = piece.angle + (motionQuery.matches ? 0 : time * 0.000012 * piece.speed)
      const frontSide = Math.sin(angle) > 0
      if (frontSide !== isFront) return
      const orbitRadius = planetGeometry.radius * piece.orbit * 1.46
      const rawX = Math.cos(angle) * orbitRadius
      const rawY = Math.sin(angle) * orbitRadius * 0.23
      const tilt = -17 * Math.PI / 180
      const depthScale = isFront ? 1.08 : 0.82
      const x = planetGeometry.centerX + rawX * Math.cos(tilt) - rawY * Math.sin(tilt)
        + planetX * (isFront ? 1.45 : 0.75)
      const y = planetGeometry.centerY + rawX * Math.sin(tilt) + rawY * Math.cos(tilt)
        + planetY * (isFront ? 1.35 : 0.7) - scrollDepth * (isFront ? 24 : 8)
      const size = piece.size * depthScale * (mobileQuery.matches ? 0.72 : 1)
      if (x < -30 || x > width + 30 || y < -30 || y > height + 30) return
      const context = isFront ? front : back
      const alpha = isFront ? 0.54 : 0.2
      context.save()
      context.translate(x, y)
      context.rotate(piece.spin + (motionQuery.matches ? 0 : time * 0.000025 * piece.speed))
      context.beginPath()
      piece.shape.forEach((radius, index) => {
        const vertexAngle = (index / piece.shape.length) * TAU
        const vertexX = Math.cos(vertexAngle) * size * 1.4 * radius
        const vertexY = Math.sin(vertexAngle) * size * radius
        if (index === 0) context.moveTo(vertexX, vertexY)
        else context.lineTo(vertexX, vertexY)
      })
      context.closePath()
      const gradient = context.createLinearGradient(-size, -size, size, size)
      gradient.addColorStop(0, `rgba(101, 139, 164, ${alpha})`)
      gradient.addColorStop(0.46, `rgba(25, 46, 65, ${alpha})`)
      gradient.addColorStop(1, `rgba(3, 9, 17, ${alpha})`)
      context.fillStyle = gradient
      context.fill()
      context.restore()
    }

    const draw = (time: number) => {
      back.clearRect(0, 0, width, height)
      front.clearRect(0, 0, width, height)
      const sceneTime = motionQuery.matches ? 0 : time
      pointerX += (targetX - pointerX) * 0.04
      pointerY += (targetY - pointerY) * 0.04
      scrollDepth += (targetScroll - scrollDepth) * 0.055
      const planetX = pointerX * -12
      const planetY = pointerY * -8 + scrollDepth * 68
      scene.style.setProperty('--planet-x', `${planetX}px`)
      scene.style.setProperty('--planet-y', `${planetY}px`)

      back.globalCompositeOperation = 'lighter'
      stars.forEach((star) => drawStar(star, sceneTime))
      back.shadowBlur = 0
      back.globalCompositeOperation = 'source-over'
      debris.forEach((piece) => drawDebris(piece, sceneTime, false, planetX, planetY))
      debris.forEach((piece) => drawDebris(piece, sceneTime, true, planetX, planetY))

      if (!motionQuery.matches) {
        const foregroundStars = level === 'lite' ? 6 : 14
        for (let index = 0; index < foregroundStars; index += 1) {
          const star = stars[index]
          const depth = 1 - star.depth
          const x = width / 2 + star.x * width * 0.55 + pointerX * 30 * depth
          const y = height / 2 + star.y * height * 0.58 + pointerY * 24 * depth - scrollDepth * 42 * depth
          front.beginPath()
          front.fillStyle = `rgba(117, 180, 215, ${0.08 + depth * 0.16})`
          front.arc(x, y, 1.2 + depth * 2.3, 0, TAU)
          front.fill()
        }
      }
    }

    const applyLevel = (next: QualityLevel, time: number) => {
      if (next === level) return
      level = next
      if (next === 'lite') downgradeCount += 1
      levelChangedAt = time
      previousFrame = 0
      fpsSamples = []
      drawSamples = []
      scene.dataset.quality = level
      resize()
      onQualityChangeRef.current?.(level)
    }

    const evaluateQuality = (time: number) => {
      if (qualityMode !== 'auto' || fpsSamples.length < 36) return
      const fps = 1000 / Math.max(average(fpsSamples), 1)
      const drawMs = average(drawSamples)
      if (level === 'full' && time - levelChangedAt > 2500 && shouldDowngrade({ fps, drawMs })) {
        applyLevel('lite', time)
        return
      }
      if (
        level === 'lite'
        && hardwareLevel === 'full'
        && time - levelChangedAt > 12000
        && downgradeCount < 2
        && shouldRecover({ fps, drawMs })
      ) {
        applyLevel('full', time)
      }
    }

    const animate = (time: number) => {
      if (lastFrameTime > 0) {
        fpsSamples.push(time - lastFrameTime)
        if (fpsSamples.length > 90) fpsSamples.shift()
      }
      lastFrameTime = time
      const frameInterval = level === 'lite' ? 66 : mobileQuery.matches ? 50 : 33
      if (time - previousFrame >= frameInterval) {
        const startedAt = performance.now()
        draw(time)
        drawSamples.push(performance.now() - startedAt)
        if (drawSamples.length > 30) drawSamples.shift()
        previousFrame = time
      }
      if (time - lastEvaluation >= 2000) {
        lastEvaluation = time
        evaluateQuality(time)
      }
      animationFrame = window.requestAnimationFrame(animate)
    }

    const stop = () => {
      window.cancelAnimationFrame(animationFrame)
      animationFrame = 0
    }

    const start = () => {
      stop()
      if (motionQuery.matches || document.hidden) {
        draw(0)
        return
      }
      fpsSamples = []
      drawSamples = []
      lastFrameTime = 0
      lastEvaluation = performance.now()
      levelChangedAt = performance.now()
      previousFrame = 0
      animationFrame = window.requestAnimationFrame(animate)
    }

    const resize = () => {
      const pixelRatio = level === 'lite'
        ? 1
        : Math.min(window.devicePixelRatio || 1, mobileQuery.matches ? 1.25 : 1.5)
      width = window.innerWidth
      height = window.innerHeight
      for (const [canvas, context] of [[backCanvas, back], [frontCanvas, front]] as const) {
        canvas.width = Math.round(width * pixelRatio)
        canvas.height = Math.round(height * pixelRatio)
        context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
      }
      scene.style.setProperty('--planet-x', '0px')
      scene.style.setProperty('--planet-y', '0px')
      const bounds = planet.getBoundingClientRect()
      planetGeometry = {
        centerX: bounds.left + bounds.width / 2,
        centerY: bounds.top + bounds.height / 2,
        radius: bounds.width / 2,
      }
      const counts = particleCounts()
      stars = createStars(counts.stars)
      debris = createDebris(counts.debris)
      scene.dataset.quality = level
      draw(performance.now())
    }

    const handlePointer = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse' || motionQuery.matches) return
      targetX = (event.clientX / Math.max(width, 1)) * 2 - 1
      targetY = (event.clientY / Math.max(height, 1)) * 2 - 1
    }
    const resetPointer = () => {
      targetX = 0
      targetY = 0
    }
    const handleScroll = () => {
      if (motionQuery.matches) return
      targetScroll = Math.min(window.scrollY / Math.max(window.innerHeight, 1), 1)
    }
    const handleVisibility = () => {
      if (document.hidden) stop()
      else start()
    }

    resize()
    handleScroll()
    start()
    onQualityChangeRef.current?.(level)
    window.addEventListener('resize', resize)
    window.addEventListener('pointermove', handlePointer, { passive: true })
    window.addEventListener('scroll', handleScroll, { passive: true })
    window.addEventListener('blur', resetPointer)
    document.addEventListener('visibilitychange', handleVisibility)
    motionQuery.addEventListener('change', start)
    mobileQuery.addEventListener('change', resize)

    return () => {
      stop()
      window.removeEventListener('resize', resize)
      window.removeEventListener('pointermove', handlePointer)
      window.removeEventListener('scroll', handleScroll)
      window.removeEventListener('blur', resetPointer)
      document.removeEventListener('visibilitychange', handleVisibility)
      motionQuery.removeEventListener('change', start)
      mobileQuery.removeEventListener('change', resize)
    }
  }, [qualityMode])

  return (
    <div ref={sceneRef} className="scene-backdrop" aria-hidden="true">
      <div className="scene-backdrop__nebula" />
      <svg className="scene-backdrop__clouds" viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMid slice">
        <defs>
          <filter id="dark-matter-cloud-noise" x="-20%" y="-20%" width="140%" height="140%">
            <feTurbulence type="fractalNoise" baseFrequency=".004 .009" numOctaves="5" seed="27" />
            <feColorMatrix values="0 0 0 0 .18  0 0 0 0 .36  0 0 0 0 .58  0 0 0 .7 -.18" />
            <feGaussianBlur stdDeviation="9" />
          </filter>
          <radialGradient id="dark-matter-cloud-fade">
            <stop offset="0" stopColor="white" stopOpacity=".85" />
            <stop offset="1" stopColor="white" stopOpacity="0" />
          </radialGradient>
          <mask id="dark-matter-cloud-mask">
            <ellipse cx="850" cy="460" rx="760" ry="480" fill="url(#dark-matter-cloud-fade)" />
          </mask>
        </defs>
        <rect width="1600" height="1000" filter="url(#dark-matter-cloud-noise)" mask="url(#dark-matter-cloud-mask)" />
      </svg>
      <canvas ref={backCanvasRef} className="scene-backdrop__canvas scene-backdrop__canvas--back" />
      <div className="scene-backdrop__orbit" />
      <div ref={planetRef} className="scene-backdrop__planet">
        <svg className="scene-backdrop__planet-texture" viewBox="0 0 850 850">
          <defs>
            <filter id="dark-matter-planet-noise">
              <feTurbulence type="fractalNoise" baseFrequency=".018" numOctaves="5" seed="9" />
              <feColorMatrix values="0 0 0 0 .44  0 0 0 0 .58  0 0 0 0 .7  0 0 0 .72 -.2" />
            </filter>
          </defs>
          <rect width="850" height="850" filter="url(#dark-matter-planet-noise)" />
        </svg>
      </div>
      <canvas ref={frontCanvasRef} className="scene-backdrop__canvas scene-backdrop__canvas--front" />
      <div className="scene-backdrop__vignette" />
    </div>
  )
}
