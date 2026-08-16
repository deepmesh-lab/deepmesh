import { verdictColor, verdictTextColor } from '../internal/theme'
import { VERDICT_CATEGORIES, type ByServiceResponse } from '../internal/types'

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
          <th>serviceName</th>
          <th>total</th>
          <th>cleared</th>
          <th>drop</th>
          <th>relay</th>
        </tr>
      </thead>
      <tbody>
        {data.rows.map((row) => {
          const total = Math.max(row.total, 1)
          return (
            <tr
              key={row.serviceName}
              className={onSelect ? 'history-row' : undefined}
              onClick={onSelect ? () => onSelect(row.serviceName) : undefined}
            >
              <td>
                {row.serviceName}
                <div className="sbar">
                  {VERDICT_CATEGORIES.map((category) =>
                    row[category] ? (
                      <i
                        key={category}
                        style={{
                          width: `${(row[category] / total) * 100}%`,
                          background: verdictColor(category),
                        }}
                      />
                    ) : null,
                  )}
                </div>
              </td>
              <td>{row.total.toLocaleString()}</td>
              <td
                className={row.cleared ? '' : 'mute'}
                style={row.cleared ? { color: verdictColor('cleared') } : undefined}
              >
                {row.cleared}
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
