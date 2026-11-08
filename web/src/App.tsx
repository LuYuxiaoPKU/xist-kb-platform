import { useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'

import { api, apiKey, setApiKey } from './lib/api'
import { ExplorePage } from './pages/Explore'
import { FullTextPage } from './pages/FullText'
import { PaperPage } from './pages/Paper'
import { ReviewPage } from './pages/Review'
import { SearchPage } from './pages/Search'

export default function App() {
  const [key, setKey] = useState(apiKey())
  const [showKey, setShowKey] = useState(false)

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">
          <a href="#/">XIST 知识库</a>
        </span>
        <nav className="nav">
          <NavLink to="/" end>
            概览
          </NavLink>
          <NavLink to="/search">检索</NavLink>
          <NavLink to="/fulltext">全文</NavLink>
          <NavLink to="/review">审阅</NavLink>
        </nav>
        <span style={{ flex: 1 }} />
        <button onClick={() => setShowKey((v) => !v)} style={{ fontSize: 12.5 }}>
          {showKey ? '收起' : '访问密钥'}
        </button>
      </header>

      {showKey && (
        <div style={{ background: 'var(--bg-raised)', borderBottom: '1px solid var(--border)' }}>
          <div className="main" style={{ paddingTop: 12, paddingBottom: 12 }}>
            <p className="meta" style={{ marginTop: 0 }}>
              服务端设置了 <code>XIST_KB_API_KEY</code> 时需要填写；未设置时留空即可。
            </p>
            <div className="toolbar" style={{ marginBottom: 0 }}>
              <input
                type="password"
                placeholder="X-API-Key"
                value={key}
                style={{ maxWidth: 320 }}
                onChange={(e) => {
                  setKey(e.target.value)
                  setApiKey(e.target.value)
                }}
              />
              <button onClick={() => void api.health().then(() => alert('连接正常')).catch((e) => alert(`连接失败：${e.message}`))}>
                测试连接
              </button>
            </div>
          </div>
        </div>
      )}

      <main className="main">
        <Routes>
          <Route path="/" element={<ExplorePage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/fulltext" element={<FullTextPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/paper/:paperId" element={<PaperPage />} />
        </Routes>
      </main>
    </div>
  )
}
