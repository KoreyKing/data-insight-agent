import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// 字体随应用打包、由本服务提供，页面不请求任何第三方字体服务
import '@fontsource-variable/source-serif-4/opsz.css'
import '@fontsource-variable/source-serif-4/opsz-italic.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '@fontsource/jetbrains-mono/600.css'
import './styles/tokens.css'
import './styles/app.css'
import AppShell from './AppShell'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppShell />
  </StrictMode>,
)
