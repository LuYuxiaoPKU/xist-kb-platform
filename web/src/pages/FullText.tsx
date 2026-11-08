import { FormEvent, useEffect, useState } from 'react'

import { api, Chunk } from '../lib/api'
import { Empty, ErrorBox, Loading } from '../components/ui'

/**
 * Full-text search over sentence windows, not claims.
 *
 * This exists because 68% of claims carry no locatable quote: for those, the
 * honest answer to "where does this come from" is the paper itself. A reader
 * who wants to check something can search the full text directly instead of
 * paging through a section.
 */
export function FullTextPage() {
  const [text, setText] = useState('')
  const [chunks, setChunks] = useState<Chunk[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  useEffect(() => {
    setChunks(null)
    setError(null)
  }, [])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (text.trim().length < 2) return
    setPending(true)
    setError(null)
    try {
      const result = await api.chunks(text.trim(), 30)
      setChunks(result.items)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPending(false)
    }
  }

  return (
    <>
      <h1 className="page-title">全文检索</h1>
      <p className="page-sub">
        直接检索论文原文（按句子窗口索引，共约 80 万段）。结果按 BM25 相关度排序。
      </p>

      <form className="toolbar" onSubmit={onSubmit}>
        <input
          type="search"
          placeholder="例如：A-repeat、dosage compensation、Xist AND Polycomb"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" disabled={pending || text.trim().length < 2}>
          {pending ? '检索中…' : '检索'}
        </button>
      </form>

      <ErrorBox error={error} />
      {pending && <Loading what="原文" />}

      {chunks && chunks.length === 0 && (
        <Empty>没有匹配的段落。检索支持 AND、OR 与引号短语。</Empty>
      )}

      {chunks && chunks.length > 0 && (
        <div className="claim-list">
          {chunks.map((chunk) => (
            <article className="claim-card" key={chunk.chunk_id}>
              <div className="claim-head">
                <span className="chip">第 {chunk.chunk_index + 1} 段</span>
                <span className="meta" style={{ fontFamily: 'var(--mono)' }}>
                  {chunk.paper_id}
                </span>
                {chunk.score !== null && (
                  <span className="meta">相关度 {chunk.score.toFixed(2)}</span>
                )}
              </div>
              <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{chunk.text}</p>
            </article>
          ))}
        </div>
      )}

      {!chunks && !pending && (
        <Empty>输入关键词后回车。检索的是论文原文，不是 claim。</Empty>
      )}
    </>
  )
}
