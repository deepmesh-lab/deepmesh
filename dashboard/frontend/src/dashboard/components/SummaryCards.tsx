import { useEffect, useRef, useState } from 'react'
import type { SummaryResponse } from '../internal/types'
import { fixed } from '../internal/format'
import { formatPercent } from '../internal/verdict'

type CardSpec = {
  /** 값 변화를 추적하는 식별자. 화면에는 label이 나간다. */
  key: string
  label: string
  tone: '' | 'forward' | 'drop' | 'relay'
  value: string
  sub: string
  /** 있으면 sub 아래 줄에 붙는다 */
  sub2?: string
}

function buildCards(summary: SummaryResponse): CardSpec[] {
  return [
    {
      key: 'totalSequences',
      label: '판정 건수',
      tone: '',
      value: summary.totalSequences.toLocaleString(),
      sub: '판정된 HTTP 메시지 수 — 로그 조회와 같은 단위',
    },
    {
      // benign + cleared. 둘 다 전달된 트래픽이다. (verdict.ts DisplayCategory)
      key: 'forwardCount',
      label: '전달 (forward)',
      tone: 'forward',
      value: (summary.benignCount + summary.clearedCount).toLocaleString(),
      sub: '서비스로 그대로 전달된 트래픽',
    },
    {
      key: 'dropCount',
      label: '차단 (drop)',
      tone: 'drop',
      value: summary.dropCount.toLocaleString(),
      sub: '악성 요청 차단',
    },
    {
      key: 'relayCount',
      label: '응답 대체 (relay)',
      tone: 'relay',
      value: summary.relayCount.toLocaleString(),
      sub: '정상 응답으로 대체',
    },
    {
      // 차단률만 보인다. 이상 판정률은 교차 검증이 뒤집은 건(cleared)까지 세므로
      // 오탐이 많으면 큰 숫자가 그대로 위험으로 읽힌다. 화면이 cleared를 forward로
      // 합친 것과도 어긋난다.
      key: 'blockRate',
      label: '차단률',
      tone: '',
      value: formatPercent(summary.blockRate),
      // 평균과 p95를 나란히 둔다. 평균만 보면 꼬리 지연이 가려진다. (명세 1-4)
      //
      // 두 값은 구간에 표본이 없으면 null이다. 트래픽이 잠깐만 끊겨도 그렇게 되므로
      // fixed()로 받아 대시로 떨어뜨린다. 0ms로 대체하지 않는다 — "측정 안 됨"과
      // "0ms"는 다르고, 0으로 보이면 탐지가 공짜인 것처럼 읽힌다.
      sub: `지연 평균 ${fixed(summary.avgDetectionLatencyMs, 2) ?? '—'}ms`,
      sub2: `p95 ${fixed(summary.p95DetectionLatencyMs, 2) ?? '—'}ms`,
    },
  ]
}

/** 값이 바뀐 카드만 잠깐 하이라이트한다. */
function useFlashed(cards: CardSpec[]) {
  const previousRef = useRef<Record<string, string>>({})
  const [flashed, setFlashed] = useState<string[]>([])

  useEffect(() => {
    const changed = cards
      .filter((card) => {
        const previous = previousRef.current[card.key]
        return previous !== undefined && previous !== card.value
      })
      .map((card) => card.key)

    previousRef.current = Object.fromEntries(
      cards.map((card) => [card.key, card.value]),
    )

    if (changed.length === 0) {
      return
    }

    setFlashed(changed)
    const timer = window.setTimeout(() => setFlashed([]), 560)
    return () => window.clearTimeout(timer)
  }, [cards])

  return flashed
}

export function SummaryCards({ summary }: { summary: SummaryResponse | null }) {
  const cards = summary ? buildCards(summary) : []
  const flashed = useFlashed(cards)

  if (!summary) {
    return (
      <div className="cards">
        {Array.from({ length: 5 }, (_unused, index) => (
          <div className="card" key={index}>
            <div className="k">—</div>
            <div className="n">—</div>
            <div className="s">불러오는 중</div>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="cards">
      {cards.map((card) => (
        <div
          className={`card ${card.tone} ${flashed.includes(card.key) ? 'flash' : ''}`}
          key={card.key}
        >
          <div className="k">{card.label}</div>
          <div className="n">{card.value}</div>
          <div className="s">{card.sub}</div>
          {card.sub2 ? <div className="s">{card.sub2}</div> : null}
        </div>
      ))}
    </div>
  )
}
