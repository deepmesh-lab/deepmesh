/**
 * 화면 전역 설정.
 *
 * 명세 1-1의 API 기본값은 `default`지만, 이 프로젝트의 k8s 매니페스트는 전부
 * `deepmesh` 네임스페이스에 배포된다(`k8s/namespace.yaml`). 기본값을 `default`로 두면
 * 실제 클러스터에 붙였을 때 빈 화면이 나오므로, 이 앱의 기본값은 `deepmesh`로 둔다.
 * 다른 네임스페이스를 보려면 `VITE_DASHBOARD_NAMESPACE`로 덮어쓴다.
 */
export const NAMESPACE = import.meta.env.VITE_DASHBOARD_NAMESPACE ?? 'deepmesh'
