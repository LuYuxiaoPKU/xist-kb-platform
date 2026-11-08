import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'

import App from './App'
import './styles.css'

// HashRouter, not BrowserRouter: FastAPI's StaticFiles serves index.html for
// any path, but a hash route needs no server cooperation at all -- which
// matters because the deployment has no nginx to rewrite URLs.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>,
)
