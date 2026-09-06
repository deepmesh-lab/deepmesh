import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
// Noto Sans KR을 직접 번들한다. 클러스터 안에서 외부 폰트 CDN에 못 나가도 동일하게 보인다.
// 쓰는 굵기만 가져온다 — 600/800은 브라우저가 700으로 맞춘다.
import '@fontsource/noto-sans-kr/latin-400.css'
import '@fontsource/noto-sans-kr/korean-400.css'
import '@fontsource/noto-sans-kr/latin-700.css'
import '@fontsource/noto-sans-kr/korean-700.css'
import './index.css'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
