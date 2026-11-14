import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.tsx'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Registered after load so the service worker never competes with the first render for
// bandwidth. Failure is ignored: the app works without it, only the offline shell is lost.
//
// The path must go through BASE_URL. A GitHub Pages project site lives at /<repo>/, so a
// hard-coded "/sw.js" asks the domain root and gets a 404 - which is what the deployed site
// did, silently, because registration failures are swallowed by design.
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    const base = import.meta.env.BASE_URL
    void navigator.serviceWorker
      .register(`${base}sw.js`, { scope: base })
      .catch(() => {})
  })
}
