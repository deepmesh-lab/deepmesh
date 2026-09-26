import { verdictColor, verdictTextColor } from '../internal/theme'
import type { ByServiceResponse } from '../internal/types'
import { DISPLAY_CATEGORIES, displayCountOf } from '../internal/verdict'

type Props = {
  data: ByServiceResponse | null
  /** 주면 행이 클릭 가능해지고 Pod 상세가 열린다 */
  onSelect?: (serviceName: string) => void
}

export function ByServiceTable({ data, onSelect }: Props) {
  if (!data) {
    return <div className="center">불러오는 중입니다.</div>
  }

  if (data.rows.length === 0) {
    return <div className="center">집계된 서비스가 없습니다.</div>
  }

  return (
    <table>
      <thead>
        <tr>
          <th>서비스</th>
          <th>전체</th>
          <th>전달</th>
          <th>차단</th>
          <th>응답 대체</th>
        </tr>
      </thead>
      <tbody>
        {data.rows.map((row) => {
          const total = Math.max(row.total, 1)
          const forward = displayCountOf(row, 'forward')
          return (
            <tr
              key={row.serviceName}
              className={onSelect ? 'history-row' : undefined}
              onClick={onSelect ? () => onSelect(row.serviceName) : undefined}
            >
              <td>
                {row.serviceName}
                <div className="sbar">
                  {DISPLAY_CATEGORIES.map((display) => {
                    const count = displayCountOf(row, display)
                    return count ? (
                      <i
                        key={display}
                        style={{
                          width: `${(count / total) * 100}%`,
                          background: verdictColor(display),
                        }}
                      />
                    ) : null
                  })}
                </div>
              </td>
              <td>{row.total.toLocaleString()}</td>
              <td
                className={forward ? '' : 'mute'}
                style={forward ? { color: verdictColor('forward') } : undefined}
              >
                {forward.toLocaleString()}
              </td>
              <td
                className={row.drop ? '' : 'mute'}
                style={row.drop ? { color: verdictColor('drop') } : undefined}
              >
                {row.drop}
              </td>
              <td
                className={row.relay ? '' : 'mute'}
                style={row.relay ? { color: verdictTextColor('relay') } : undefined}
              >
                {row.relay}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
