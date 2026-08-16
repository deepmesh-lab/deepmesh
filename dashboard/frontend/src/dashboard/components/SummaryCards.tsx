import { useEffect, useRef, useState } from 'react'
import type { SummaryResponse } from '../internal/types'
import { formatPercent } from '../internal/verdict'

type CardSpec = {
  key: string
  tone: '' | 'benign' | 'cleared' | 'drop' | 'relay'
  value: string
  sub: string
  /** 있으면 sub 아래 줄에 붙는다 */
  sub2?: string
}

function buildCards(summary: SummaryResponse): CardSpec[] {
  return [
    {
      key: 'totalSequences',
      tone: '',
      value: summary.totalSequences.toLocaleString(),
      sub: 'east-west 판정 시퀀스',
    },
    {
      key: 'benignCount',
      tone: 'benign',
      value: summary.benignCount.toLocaleString(),
      sub: '모델 BENIGN (정상 전달)',
    },
    {
      key: 'clearedCount',
      tone: 'cleared',
      value: summary.clearedCount.toLocaleString(),
      sub: '교차 검증이 판정을 뒤집음',
    },
    {
      key: 'dropCount',
      tone: 'drop',
      value: summary.dropCount.toLocaleString(),
      sub: '악성 요청 차단',
    },
    {
      key: 'relayCount',
      tone: 'relay',
      value: summary.relayCount.toLocaleString(),
      sub: '정상 응답으로 대체',
    },
    {
      key: 'attackRate',
      tone: '',
      // 평균과 p95를 나란히 둔다. 평균만 보면 꼬리 지연이 가려진다. (명세 1-4)
      value: formatPercent(summary.attackRate),
      sub: `blockRate ${formatPercent(summary.blockRate)}`,
      sub2:
        `avg ${summary.avgDetectionLatencyMs.toFixed(2)}ms, ` +
        `p95 ${summary.p95DetectionLatencyMs.toFixed(2)}ms`,
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
        {Array.from({ length: 6 }, (_unused, index) => (
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
          <div className="k">{card.key}</div>
          <div className="n">{card.value}</div>
          <div className="s">{card.sub}</div>
          {card.sub2 ? <div className="s">{card.sub2}</div> : null}
        </div>
      ))}
    </div>
  )
}
