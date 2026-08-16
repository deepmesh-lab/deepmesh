import { ByServiceTable } from '../components/ByServiceTable'
import { useDashboard } from '../internal/DashboardProvider'

export function ServicesPage() {
  const { byService, topology, openService } = useDashboard()

  const monitored = topology.nodes.filter((node) => node.proxyEnabled)
  const unmonitored = topology.nodes.filter((node) => !node.proxyEnabled)

  return (
    <div className="page">
      <section className="panel">
        <div className="ph">
          <h2>서비스별 판정 분포</h2>
          <span className="api">GET /dashboard/stats/by-service</span>
          <div className="tools">
            <span className="ep">blockRate 내림차순</span>
          </div>
        </div>
        <div className="pb">
          <ByServiceTable data={byService.data} onSelect={openService} />
        </div>
      </section>

      <section className="panel">
        <div className="ph">
          <h2>프록시 미부착 노드</h2>
          <span className="api">counts: null</span>
        </div>
        <div className="pb">
          {unmonitored.length === 0 ? (
            <div className="center">없습니다.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>serviceName</th>
                  <th style={{ textAlign: 'left' }}>kind</th>
                  <th style={{ textAlign: 'left' }}>status</th>
                </tr>
              </thead>
              <tbody>
                {unmonitored.map((node) => (
                  <tr
                    className="history-row"
                    key={node.id}
                    onClick={() => openService(node.id)}
                  >
                    <td>{node.serviceName}</td>
                    <td style={{ textAlign: 'left' }}>{node.kind}</td>
                    <td style={{ textAlign: 'left' }}>{node.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="note">
            프록시 사이드카가 없어 관측 주체가 없는 노드입니다. <code>0</code>은 “감시했으나
            사건 없음”, <code>null</code>은 “감시 대상 아님”으로 의미가 다릅니다. 감시 대상은
            현재 {monitored.length}개입니다.
          </div>
        </div>
      </section>
    </div>
  )
}
