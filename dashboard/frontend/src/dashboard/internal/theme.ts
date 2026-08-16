/**
 * CSS 토큰을 JS에서 읽는다.
 *
 * SVG 차트(Recharts)는 색을 속성값으로 받기 때문에 `fill="var(--x)"`가 해석되지 않는다.
 * 그래서 계산된 토큰 값을 읽어 실제 색 문자열로 넘긴다.
 * **색 값 자체는 여전히 `styles/tokens.css` 한 곳에만 있다.**
 */
import type { VerdictCategory } from './types'

const cache = new Map<string, string>()

function token(name: string, fallback: string): string {
  const cached = cache.get(name)
  if (cached !== undefined) {
    return cached
  }

  // 스타일시트가 아직 붙지 않았으면 fallback을 캐시하지 않고 그대로 돌려준다.
  if (typeof document === 'undefined') {
    return fallback
  }

  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim()

  if (!value) {
    return fallback
  }

  cache.set(name, value)
  return value
}

/** 판정 4분류 색. fallback은 tokens.css의 현재 값과 같게 유지한다. */
export function verdictColor(category: VerdictCategory): string {
  switch (category) {
    case 'benign':
      return token('--verdict-benign', '#16a34a')
    case 'cleared':
      return token('--verdict-cleared', '#0066a5')
    case 'drop':
      return token('--verdict-drop', '#c8102e')
    case 'relay':
      return token('--verdict-relay', '#f15a22')
  }
}

/** 흰 배경에서 글자로 쓸 때. 주황 원색은 대비가 모자라 어두운 단계를 쓴다. */
export function verdictTextColor(category: VerdictCategory): string {
  return category === 'relay'
    ? token('--verdict-relay-text', '#b03a0f')
    : verdictColor(category)
}

/** 판정이 없는 평시 간선 색. SVG marker는 CSS 변수를 못 읽어 계산값이 필요하다. */
export function edgeBaseColor(): string {
  return token('--color-edge', '#cbd5e1')
}

/** 지연 백분위수 라인. 낮을수록 정상(success), 높을수록 위험(danger) 쪽으로 읽히게 둔다. */
export function latencyColor(percentile: 'p50' | 'p95' | 'p99'): string {
  switch (percentile) {
    case 'p50':
      return token('--color-success', '#16a34a')
    case 'p95':
      return token('--color-primary', '#0066a5')
    case 'p99':
      return token('--color-danger', '#c8102e')
  }
}
