import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

function narrowRules() {
  const style = document.createElement('style')
  style.textContent = readFileSync(resolve(process.cwd(), 'src/styles/motion.css'), 'utf8')
  document.head.append(style)
  const media = Array.from(style.sheet?.cssRules ?? []).find(
    (rule): rule is CSSMediaRule => rule.type === CSSRule.MEDIA_RULE && (rule as CSSMediaRule).conditionText === '(max-width: 760px)',
  )
  return { style, rules: Array.from(media?.cssRules ?? []) as CSSStyleRule[] }
}

function findRule(rules: CSSStyleRule[], selector: string) {
  return rules.find((rule) => rule.selectorText.split(',').map((part) => part.trim()).includes(selector))
}

describe('narrow-screen motion fallbacks', () => {
  it('uses opacity-only line and receipt entrances without panel sweep or line translation', () => {
    const { style, rules } = narrowRules()
    for (const selector of ['.motion-panel__line', '.wizard-receipt']) {
      const rule = findRule(rules, selector)
      expect(rule, selector).toBeDefined()
      expect(rule?.style.getPropertyValue('animation')).toContain('fadeOnly')
      expect(rule?.style.getPropertyValue('transform')).toBe('none')
      expect(rule?.style.getPropertyPriority('transform')).toBe('important')
      expect(rule?.style.animation).not.toContain('panelSweep')
      expect(rule?.style.animation).not.toContain('lineFade')
    }
    style.remove()
  })
})
