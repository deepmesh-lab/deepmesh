import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatKstTime } from '../internal/time'
import { VERDICT_CATEGORIES, type TimeseriesResponse } from '../internal/types'
import { latencyColor, verdictColor } from '../internal/theme'
import { VERDICT_LABEL } from '../internal/verdict'

const AXIS_STYLE = {
  fontSize: 10,
  fontFamily: 'var(--sans)',
  fill: 'var(--color-text-subtle)',
}

const TOOLTIP_STYLE = {
  fontSize: 11.5,
  fontFamily: 'var(--sans)',
  borderRadius: 8,
  border: '1px solid var(--color-border)',
  boxShadow: '0 6px 20px rgba(0,48,77,.14)',
}

type Props = {
  data: TimeseriesResponse | null
  height?: number
}

export function VerdictTimeseriesChart({ data, height = 200 }: Props) {
  if (!data || data.buckets.length === 0) {
    return <div className="center">시계열 데이터를 불러오는 중입니다.</div>
  }

  if (data.metric === 'latency') {
    // 데이터가 없는 버킷은 null이라 선이 끊긴다. 0으로 채우면 바닥으로 떨어져 오해를 부른다.
    const rows = data.buckets.map((bucket) => ({
      ts: formatKstTime(bucket.ts),
      p50: bucket.p50,
      p95: bucket.p95,
      p99: bucket.p99,
    }))

    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--color-border-subtle)" vertical={false} />
          <XAxis dataKey="ts" tick={AXIS_STYLE} minTickGap={48} tickLine={false} />
          <YAxis
            tick={AXIS_STYLE}
            tickLine={false}
            axisLine={false}
            unit="ms"
            width={62}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 11, fontFamily: 'var(--sans)' }} />
          <Line
            type="linear"
            dataKey="p50"
            stroke={latencyColor('p50')}
            dot={false}
            strokeWidth={1.6}
            connectNulls={false}
          />
          <Line
            type="linear"
            dataKey="p95"
            stroke={latencyColor('p95')}
            dot={false}
            strokeWidth={1.6}
            connectNulls={false}
          />
          <Line
            type="linear"
            dataKey="p99"
            stroke={latencyColor('p99')}
            dot={false}
            strokeWidth={1.6}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    )
  }

  // 4개 분류가 상호 배타적이므로 그대로 스택으로 쌓을 수 있다. (명세 1-5)
  const rows = data.buckets.map((bucket) => ({
    ts: formatKstTime(bucket.ts),
    benign: bucket.benign,
    cleared: bucket.cleared,
    drop: bucket.drop,
    relay: bucket.relay,
  }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
        <CartesianGrid stroke="var(--color-border-subtle)" vertical={false} />
        <XAxis dataKey="ts" tick={AXIS_STYLE} minTickGap={48} tickLine={false} />
        <YAxis tick={AXIS_STYLE} tickLine={false} axisLine={false} width={46} />
        <Tooltip contentStyle={TOOLTIP_STYLE} />
        <Legend wrapperStyle={{ fontSize: 11, fontFamily: 'var(--sans)' }} />
        {VERDICT_CATEGORIES.map((category) => (
          <Area
            key={category}
            type="linear"
            dataKey={category}
            name={`${category} (${VERDICT_LABEL[category]})`}
            stackId="verdict"
            stroke={verdictColor(category)}
            fill={verdictColor(category)}
            fillOpacity={category === 'benign' ? 0.16 : 0.7}
            strokeWidth={1.6}
            isAnimationActive={false}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  )
}
