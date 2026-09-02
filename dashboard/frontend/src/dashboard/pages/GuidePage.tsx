/**
 * DeepMesh가 DROP, CLEARED, RELAY를 어떻게 판정하는지 설명하는 안내 페이지.
 *
 * 내용은 `servicemesh/control-plane/control_plane.py`를 그대로 풀어 쓴 것이다.
 * 코드를 고치면 이 문서도 같이 고쳐야 한다.
 */

type Step = {
  who: string
  what: string
  detail?: string
  verdict?: 'drop' | 'cleared' | 'relay' | 'wait'
}

function StepList({ steps }: { steps: Step[] }) {
  return (
    <ol className="guide-steps">
      {steps.map((step, index) => (
        <li key={index}>
          <span className="guide-step-no">{index + 1}</span>
          <div className="guide-step-body">
            <div className="guide-step-head">
              <b>{step.who}</b>
              {step.verdict ? (
                <span className={`guide-chip ${step.verdict}`}>
                  {step.verdict === 'wait' ? '보류' : step.verdict.toUpperCase()}
                </span>
              ) : null}
            </div>
            <p>{step.what}</p>
            {step.detail ? <p className="guide-step-detail">{step.detail}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  )
}

export function GuidePage() {
  return (
    <div className="page">
      <section className="panel">
        <div className="ph">
          <h2>동작 원리</h2>
          <span className="ep">
            DeepMesh가 DROP, CLEARED, RELAY를 판정하는 방법
          </span>
        </div>

        <div className="guide">
          {/* ── 1. 핵심 아이디어 ─────────────────────────────────── */}
          <h3>한 줄로 요약하면</h3>

          <blockquote className="guide-idea">
            같은 Deployment로 뜬 Pod들은 <b>똑같은 코드로 똑같은 일</b>을 합니다.
            그러니 정상적인 요청이라면 여러 Pod에서 똑같이 나와야 합니다.
            <br />
            <b>한 Pod에서만 나오는 요청은, 그 Pod가 장악당했다는 신호입니다.</b>
          </blockquote>

          <p>
            DeepMesh는 요청 내용이 위험한지를 직접 판단하지 않습니다. 대신 이렇게
            묻습니다. <b>&ldquo;이 요청, 옆에 있는 형제 Pod도 하던가?&rdquo;</b>{' '}
            아래 설명은 전부 이 한 가지 질문에 답하기 위한 준비 과정입니다.
          </p>

          {/* ── 2. 등장인물 ───────────────────────────────────── */}
          <h3>등장인물</h3>

          <p>
            <code>post-service</code>가 Pod 3개로 떠 있다고 하겠습니다. 편의상 A, B,
            C라고 부르겠습니다.
          </p>

          <div className="guide-cast">
            <div className="guide-card">
              <h4>Pod 안의 두 컨테이너</h4>
              <p>
                Pod 하나에는 실제 애플리케이션(<code>post-service</code>)과{' '}
                <b>사이드카 프록시</b>(<code>reverse-proxy</code>)가 함께 들어
                있습니다. 프록시가 드나드는 트래픽을 전부 가로챕니다. 애플리케이션은
                자기 앞에 프록시가 있다는 사실조차 모릅니다.
              </p>
            </div>

            <div className="guide-card">
              <h4>Pod Info Provider</h4>
              <p>
                클러스터 밖(마스터 노드)에서 도는 Control Plane의 첫 번째
                부품입니다. <b>&ldquo;지금 누가 누구의 형제인가&rdquo;</b>를
                관리합니다.
              </p>
            </div>

            <div className="guide-card">
              <h4>Request Verifier</h4>
              <p>
                Control Plane의 두 번째 부품입니다. 프록시가 물어보면{' '}
                <b>&ldquo;통과(allow)&rdquo;</b>인지 <b>&ldquo;차단(deny)&rdquo;</b>
                인지 답해 줍니다.
              </p>
            </div>
          </div>

          {/* ── 3. Pod Info Provider ─────────────────────────── */}
          <h3>준비 작업: Pod Info Provider가 10초마다 하는 일</h3>

          <p>
            판정을 하려면 먼저 <b>형제가 누구인지</b> 알아야 합니다. 이 부품이 10초에
            한 번씩 세 가지 일을 반복합니다.
          </p>

          <StepList
            steps={[
              {
                who: 'Kubernetes에 Pod 목록을 물어본다',
                what:
                  '아무 Pod이나 담지 않고 세 조건을 통과한 것만 고릅니다. (1) Running 상태이고 Pod IP가 있을 것, (2) reverse-proxy 사이드카가 있을 것, (3) app 라벨이 있을 것.',
                detail:
                  '사이드카가 없는 Pod은 애초에 물어볼 수단이 없어서 검증 대상이 아닙니다. app 라벨 값이 곧 서비스 이름이 됩니다.',
              },
              {
                who: '주소록을 만든다',
                what:
                  '서비스별로 Pod 이름과 IP를 묶어 둡니다. 동시에 "이 IP는 어느 서비스 소속인가"를 되찾는 역방향 색인도 만듭니다.',
                detail:
                  '잠시 뒤 Request Verifier가 이 역방향 색인을 씁니다. 여기 없는 IP에서 온 요청은 아예 400으로 거절됩니다.',
              },
              {
                who: '각 Pod에게 형제 목록을 보낸다',
                what:
                  'A에게는 [B, C]를, B에게는 [A, C]를, C에게는 [A, B]를 보냅니다. 자기 자신은 빼고 보냅니다.',
                detail:
                  'Pod이 죽고 새로 뜨면 IP가 바뀌는데, 10초마다 다시 돌기 때문에 자동으로 따라갑니다. 덕분에 모든 프록시는 자기 형제가 지금 어디 있는지 항상 알고 있습니다.',
              },
            ]}
          />

          <p className="guide-note">
            여기까지는 요청과 무관하게 백그라운드에서 계속 돕니다. 실제 판정은 지금부터
            시작합니다.
          </p>

          {/* ── 4. 장부 ──────────────────────────────────────── */}
          <h3>Request Verifier가 들고 있는 장부</h3>

          <p>
            Request Verifier는 메모리에 이런 장부를 하나 들고 있습니다. 이게 판정의
            전부입니다.
          </p>

          <pre className="guide-code">
            {`post-service
  └ "GET /api/comments?postId=12"
      관측된 Pod : { A, B }
      마지막 관측 : 3초 전`}
          </pre>

          <p>
            읽는 법은 이렇습니다. <b>&ldquo;post-service에서 이 요청이 A와 B, 두
            Pod에서 관측된 적 있다.&rdquo;</b>
          </p>

          <p>
            따옴표 안에 들어가는 <b>&ldquo;GET /api/comments?postId=12&rdquo;</b>를{' '}
            <b>시그니처</b>라고 부릅니다. 요청을 짧게 요약한 문자열이라고 보시면
            됩니다. 프록시가 만들어서 보냅니다.
          </p>

          <p className="guide-note">
            장부의 각 항목은 <b>600초(10분)</b> 동안만 유지됩니다. 10분간 아무도 같은
            요청을 하지 않으면 기록이 지워지고, 다음번엔 처음부터 다시 시작합니다.
          </p>

          {/* ── 5. 판정 규칙 ─────────────────────────────────── */}
          <h3>판정 규칙은 딱 세 줄입니다</h3>

          <div className="guide-table-wrap">
            <table className="guide-table">
              <thead>
                <tr>
                  <th>장부를 찾아봤더니</th>
                  <th>답</th>
                  <th>이유</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>시그니처가 아예 없다 (처음 보는 요청)</td>
                  <td>
                    <span className="guide-chip drop">deny</span>
                  </td>
                  <td>첫 관측이라 판단할 근거가 없음, 기록만 남기고 보류</td>
                </tr>
                <tr>
                  <td>관측된 Pod가 나 혼자뿐이다</td>
                  <td>
                    <span className="guide-chip drop">deny</span>
                  </td>
                  <td>같은 Pod에서만 나오는 요청, 장악 의심</td>
                </tr>
                <tr>
                  <td>관측된 Pod에 다른 IP가 있다</td>
                  <td>
                    <span className="guide-chip cleared">allow</span>
                  </td>
                  <td>다른 replica도 하는 요청, 정상으로 판단</td>
                </tr>
              </tbody>
            </table>
          </div>

          <blockquote className="guide-warn">
            <b>가장 많이 오해하는 부분입니다.</b>
            <br />
            Request Verifier는 <b>다른 Pod에게 아무것도 물어보지 않습니다.</b> 자기
            장부만 뒤집니다. &ldquo;다른 replica에게 물어본다&rdquo;가 아니라{' '}
            <b>&ldquo;다른 replica가 예전에 남기고 간 흔적을 확인한다&rdquo;</b>
            입니다. 그래서 판정이 네트워크 왕복 없이 즉시 끝납니다.
          </blockquote>

          {/* ── 5-1. 용어 ────────────────────────────────────── */}
          <h3>benign · cleared · forward — 셋을 정확히 구분합니다</h3>

          <p>
            화면에 나오는 말이 세 축에서 옵니다. 축을 섞어 읽으면 반드시 헷갈립니다.
          </p>

          <div className="guide-table-wrap">
            <table className="guide-table">
              <thead>
                <tr>
                  <th>축</th>
                  <th>값</th>
                  <th>무엇을 말하나</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>모델 판정</td>
                  <td>
                    <code>BENIGN</code> / <code>ATTACK</code>
                  </td>
                  <td>OCSVM이 이 시퀀스를 어떻게 봤나</td>
                </tr>
                <tr>
                  <td>집행</td>
                  <td>
                    <code>FORWARD</code> / <code>DROP</code> / <code>RELAY</code>
                  </td>
                  <td>프록시가 실제로 어떻게 했나</td>
                </tr>
                <tr>
                  <td>분류 (화면)</td>
                  <td>
                    <code>benign</code> / <code>cleared</code> / <code>drop</code> /{' '}
                    <code>relay</code>
                  </td>
                  <td>위 둘을 합쳐 네 갈래로 나눈 것</td>
                </tr>
              </tbody>
            </table>
          </div>

          <blockquote className="guide-warn">
            <b>
              <code>FORWARD</code>는 <code>benign</code>과 <code>cleared</code>를 둘 다
              포함합니다.
            </b>
            <br />
            cleared도 결국 전달된 트래픽이기 때문입니다. 그래서 화면의 네 분류에는{' '}
            <b>forward라는 말을 쓰지 않습니다</b> — 그렇게 쓰면 나란히 놓인 cleared가
            forward가 아닌 것처럼 읽힙니다. forward는 탐지 이벤트 상세의{' '}
            <code>verdict</code> 칸에서만 나옵니다.
          </blockquote>

          <div className="guide-table-wrap">
            <table className="guide-table">
              <thead>
                <tr>
                  <th>분류</th>
                  <th>모델</th>
                  <th>집행</th>
                  <th>뜻</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <span className="guide-chip benign">benign</span>
                  </td>
                  <td>BENIGN</td>
                  <td>FORWARD</td>
                  <td>모델이 정상으로 봄. 교차 검증을 돌리지 않음</td>
                </tr>
                <tr>
                  <td>
                    <span className="guide-chip cleared">cleared</span>
                  </td>
                  <td>ATTACK</td>
                  <td>FORWARD</td>
                  <td>모델은 이상으로 봤으나 교차 검증이 뒤집음</td>
                </tr>
                <tr>
                  <td>
                    <span className="guide-chip drop">drop</span>
                  </td>
                  <td>ATTACK</td>
                  <td>DROP</td>
                  <td>검증도 통과 못 함. 요청을 버림</td>
                </tr>
                <tr>
                  <td>
                    <span className="guide-chip relay">relay</span>
                  </td>
                  <td>ATTACK</td>
                  <td>RELAY</td>
                  <td>응답이 참조와 다름. 정상 replica 응답으로 교체</td>
                </tr>
              </tbody>
            </table>
          </div>

          <p>
            네 분류 모두 <b>HTTP 메시지 1건당 1개</b>로 셉니다. 개요 카드의 숫자와 로그
            조회의 행 수가 같은 단위를 가리킵니다.
          </p>

          {/* ── 6. CLEARED ───────────────────────────────────── */}
          <h3>
            <span className="guide-chip cleared">CLEARED</span> 정상 요청이 통과되는
            과정
          </h3>

          <p>
            사용자 요청이 A에게 들어왔고, A가 <code>comment-service</code>를 호출하려
            합니다.
          </p>

          <StepList
            steps={[
              {
                who: 'A의 프록시가 요청을 붙잡는다',
                what:
                  '애플리케이션이 보내려는 요청을 그대로 통과시키지 않고, 먼저 Control Plane에 물어봅니다. "출발지는 A의 IP, 시그니처는 GET /api/comments?postId=12입니다."',
              },
              {
                who: 'Verifier가 출발지의 소속을 확인한다',
                what:
                  '아까 만들어 둔 역방향 색인에서 A의 IP를 찾습니다. post-service 소속임을 확인합니다.',
                detail:
                  '주소록에 없는 IP라면 여기서 400으로 끝납니다. 사이드카가 없는 곳에서 온 요청은 검증 자체가 불가능하기 때문입니다.',
              },
              {
                who: '장부를 찾아본다 (없음)',
                what:
                  '처음 보는 시그니처입니다. 장부에 "관측된 Pod = { A }"라고 적어두고 이번 요청은 막습니다.',
                verdict: 'wait',
                detail:
                  '정상 요청인데도 막힙니다. 아직 "혼자만 하는 요청"인지 "다들 하는 요청"인지 구분할 방법이 없기 때문입니다.',
              },
              {
                who: '잠시 후 같은 요청이 B에게 들어온다',
                what:
                  '로드밸런서가 다음 요청을 B에게 보냈습니다. B의 프록시도 똑같이 물어봅니다. 시그니처는 같고 출발지 IP만 B로 다릅니다.',
              },
              {
                who: '장부를 찾아본다 (있음, 그런데 나는 없음)',
                what:
                  '장부에는 { A }가 적혀 있는데 지금 물어본 건 B입니다. 다릅니다. 장부에 B를 추가하고 통과시킵니다.',
                verdict: 'cleared',
                detail:
                  '대시보드에는 CLEARED로 기록됩니다. 이제 장부는 { A, B }가 되었습니다.',
              },
              {
                who: '그 뒤로는 계속 통과',
                what:
                  'A가 같은 요청을 또 보내도 장부가 { A, B }라 "나 혼자"가 아닙니다. 곧바로 통과됩니다.',
                verdict: 'cleared',
              },
            ]}
          />

          {/* ── 7. DROP ──────────────────────────────────────── */}
          <h3>
            <span className="guide-chip drop">DROP</span> 장악된 Pod가 차단되는 과정
          </h3>

          <p>
            이번엔 공격자가 <b>A만</b> 장악했습니다. A에서 Kubernetes API로 시크릿을
            훔치려 합니다. B와 C는 멀쩡합니다.
          </p>

          <StepList
            steps={[
              {
                who: '1회차',
                what:
                  '처음 보는 시그니처입니다. 장부에 { A }를 적어두고 막습니다. 여기까지는 정상 요청과 똑같습니다.',
                verdict: 'wait',
              },
              {
                who: '2회차',
                what:
                  '장부에 { A }가 있는데 지금 물어본 것도 A입니다. 완전히 같습니다. "같은 Pod에서만 관측된 요청"으로 차단합니다.',
                verdict: 'drop',
              },
              {
                who: '3회차, 4회차, 100회차',
                what:
                  'B와 C는 이런 요청을 할 이유가 없으니 장부는 영원히 { A }입니다. 계속 차단됩니다.',
                verdict: 'drop',
                detail:
                  '공격자가 요청을 반복할수록 대시보드에 DROP이 쌓이고, 어느 Pod가 문제인지 그대로 드러납니다.',
              },
            ]}
          />

          <p>정상 트래픽과 공격 트래픽은 여기서 갈립니다.</p>

          <div className="guide-table-wrap">
            <table className="guide-table">
              <thead>
                <tr>
                  <th />
                  <th>정상 요청</th>
                  <th>공격 요청</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>누가 보내나</td>
                  <td>로드밸런서가 나눠줌, 여러 Pod</td>
                  <td>장악된 한 Pod만</td>
                </tr>
                <tr>
                  <td>장부의 Pod 집합</td>
                  <td>
                    <code>{'{ A }'}</code> → <code>{'{ A, B }'}</code>로 커짐
                  </td>
                  <td>
                    <code>{'{ A }'}</code>에서 안 커짐
                  </td>
                </tr>
                <tr>
                  <td>결과</td>
                  <td>
                    <span className="guide-chip cleared">2회차부터 통과</span>
                  </td>
                  <td>
                    <span className="guide-chip drop">계속 차단</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* ── 8. RELAY ─────────────────────────────────────── */}
          <h3>
            <span className="guide-chip relay">RELAY</span> 응답을 바꿔치기
          </h3>

          <p>
            앞의 둘은 <b>나가는 요청</b>을 검사했습니다. RELAY는 <b>돌아가는 응답</b>
            을 검사합니다.
          </p>

          <p>
            요청은 정상이었는데 응답이 이상한 경우가 있습니다. 예를 들어 A가 장악당해
            응답 본문에 악성 스크립트가 끼워졌다면, 요청만 봐서는 알 수 없습니다.
            그래서 응답을 내보내기 직전에 한 번 더 확인합니다.
          </p>

          <StepList
            steps={[
              {
                who: 'A의 프록시가 응답을 붙잡는다',
                what:
                  'A가 만든 응답을 사용자에게 보내기 직전에 멈춰 세웁니다.',
              },
              {
                who: '형제에게 직접 물어본다',
                what:
                  'Pod Info Provider가 미리 내려준 형제 목록을 보고, B에게 "너도 이 요청에 답해봐"라고 직접 요청합니다.',
                detail:
                  'Control Plane을 거치지 않습니다. 형제 목록을 미리 받아두는 이유가 바로 이것입니다.',
              },
              {
                who: '두 응답의 본문을 비교한다',
                what:
                  'A의 응답과 B의 응답이 같으면 A의 응답을 그대로 내보냅니다. 이 경우도 CLEARED입니다.',
                verdict: 'cleared',
              },
              {
                who: '다르면 B의 응답으로 대체한다',
                what:
                  'A의 응답을 버리고 B가 만든 정상 응답을 대신 내보냅니다. 이게 RELAY입니다.',
                verdict: 'relay',
                detail:
                  '사용자 입장에서는 서비스가 끊기지 않고 정상 응답을 받습니다. 차단(DROP)과 달리 사용자 경험을 해치지 않는다는 것이 RELAY의 핵심 가치입니다.',
              },
            ]}
          />

          <blockquote className="guide-warn">
            <b>구현 위치 안내.</b>
            <br />
            DROP과 CLEARED 판정은 Control Plane 코드(
            <code>control_plane.py</code>)에 그대로 들어 있어 확인할 수 있습니다.
            하지만 RELAY는 사이드카 프록시 쪽에서 처리하며, 프록시는 컨테이너
            이미지로만 배포되어 이 저장소에 소스가 없습니다. 위 설명은 Pod Info
            Provider가 형제 목록을 프록시에 내려보내는 구조로부터 정리한 것입니다.
          </blockquote>

          {/* ── 9. 한눈에 ────────────────────────────────────── */}
          <h3>세 판정 한눈에 보기</h3>

          <div className="guide-table-wrap">
            <table className="guide-table">
              <thead>
                <tr>
                  <th>판정</th>
                  <th>무엇을 검사하나</th>
                  <th>언제 나오나</th>
                  <th>결과</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <span className="guide-chip cleared">CLEARED</span>
                  </td>
                  <td>나가는 요청, 또는 돌아가는 응답</td>
                  <td>다른 replica도 같은 요청을 했거나, 응답 본문이 형제와 일치</td>
                  <td>원래 트래픽을 그대로 전달</td>
                </tr>
                <tr>
                  <td>
                    <span className="guide-chip drop">DROP</span>
                  </td>
                  <td>나가는 요청</td>
                  <td>그 Pod에서만 관측된 요청</td>
                  <td>요청을 아예 보내지 않고 차단</td>
                </tr>
                <tr>
                  <td>
                    <span className="guide-chip relay">RELAY</span>
                  </td>
                  <td>돌아가는 응답</td>
                  <td>응답 본문이 형제의 응답과 다름</td>
                  <td>형제의 정상 응답으로 바꿔서 전달</td>
                </tr>
              </tbody>
            </table>
          </div>

          <p className="guide-note">
            토폴로지 그래프에서 CLEARED, DROP, RELAY로 표시된 선을 클릭하면, 위에서
            설명한 절차가 실제 Pod와 Control Plane 위에 순서대로 그려집니다.
          </p>

          {/* ── 10. 한계 ─────────────────────────────────────── */}
          <h3>알아둘 점</h3>

          <p>
            이 방식은 만능이 아닙니다. 설계상 다음 한계를 함께 이해해야 결과를 올바로
            읽을 수 있습니다.
          </p>

          <ul className="guide-limits">
            <li>
              <b>첫 요청은 무조건 막힙니다.</b> 정상 요청이어도 그렇습니다. 새로
              배포한 기능의 첫 호출은 한 번 실패할 수 있습니다.
            </li>
            <li>
              <b>한 번만 일어나는 요청은 계속 막힙니다.</b> 다른 Pod가 똑같은 요청을
              할 일이 없으면 장부의 Pod 집합이 절대 커지지 않습니다.
            </li>
            <li>
              <b>Pod를 2개 이상 장악하면 뚫립니다.</b> 여러 replica에서 같은 요청을
              보내면 &ldquo;정상&rdquo;의 조건을 공격자가 직접 만족시켜 버립니다.
            </li>
            <li>
              <b>교차 검증 통과가 안전을 보증하지는 않습니다.</b> CLEARED는
              &ldquo;여러 replica가 하는 요청이다&rdquo;라는 뜻일 뿐, 그 요청이
              무해하다는 뜻이 아닙니다.
            </li>
            <li>
              <b>replica가 1개면 검증이 성립하지 않습니다.</b> 비교할 형제가 없기
              때문입니다.
            </li>
          </ul>
        </div>
      </section>
    </div>
  )
}
