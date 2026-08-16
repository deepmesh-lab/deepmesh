import type { AlertPayload } from '../internal/types'

type Props = {
  alerts: AlertPayload[]
  onSelect: (eventId: string) => void
}

export function AlertToasts({ alerts, onSelect }: Props) {
  return (
    <div className="toasts">
      {alerts.map((alert) => (
        <button
          type="button"
          className={`toast ${alert.severity}`}
          key={alert.eventId}
          onClick={() => onSelect(alert.eventId)}
        >
          <div className="th">
            {alert.verdict} ({alert.severity})
          </div>
          <div className="tt">{alert.title}</div>
          <div className="tm">{alert.message}</div>
        </button>
      ))}
    </div>
  )
}
