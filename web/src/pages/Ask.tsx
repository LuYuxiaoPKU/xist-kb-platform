import { FormEvent, useEffect, useState } from 'react'

import { api, AskResult } from '../lib/api'
import { TierBadge } from '../components/ui'
import { ErrorBox, Loading } from '../components/ui'

/**
 * Q&A over the knowledge base.
 *
 * The retrieved evidence is shown *before* the generated answer, and stays
 * visible when no answer is produced at all. A reader must be able to check
 * what the model was given -- without that, a fluent answer is indistinguishable
 * from an invented one.
 */
export function AskPage() {
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<AskResult | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [budget, setBudget] = useState<{ remaining_usd: number; limit_usd: number } | null>(null)

  useEffect(() => {
    api
      .askBudget()
      .then(setBudget)
      .catch(() => setBudget(null))
  }, [])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (question.trim().length < 3) return
    setPending(true)
    setError(null)
    setResult(null)
    try {
      setResult(await api.ask(question.trim()))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPending(false)
    }
  }

  return (
    <>
      <h1 className="page-title">提问</h1>
      <p className="page-sub">
        从知识库检索证据后作答。检索到的 claim 与原文段落会一并列出，可自行核对。
        {budget && (
          <>
            {' '}今日预算剩余 ${budget.remaining_usd.toFixed(2)} / ${budget.limit_usd.toFixed(2)}。
          </>
        )}
      </p>

      <form className="toolbar" onSubmit={onSubmit}>
        <input
          type="search"
          placeholder="例如：A-repeat 在 Xist 沉默中起什么作用？"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button type="submit" disabled={pending || question.trim().length < 3}>
          {pending ? '处理中…' : '提问'}
        </button>
      </form>

      <ErrorBox error={error} />
      {pending && <Loading what="证据与回答" />}

      {result && (
        <>
          {result.answer ? (
            <section
              style={{
                background: 'var(--bg-raised)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                padding: '14px 17px',
                marginBottom: 22,
              }}
            >
              <p className="side-title" style={{ marginBottom: 8 }}>
                回答
                {result.usage && (
                  <span className="meta" style={{ fontWeight: 400, marginLeft: 10 }}>
                    {result.usage.input_tokens + result.usage.output_tokens} tokens · $
                    {result.usage.cost_usd.toFixed(4)}
                  </span>
                )}
              </p>
              <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{result.answer}</p>
            </section>
          ) : (
            <div className="error" style={{ background: '#fff8e1', borderColor: '#f0dca0', color: 'var(--warn)' }}>
              {result.error ?? '未生成回答。'}
            </div>
          )}

          <section style={{ marginBottom: 22 }}>
            <p className="side-title">检索到的 claim（{result.claims.length}）</p>
            {result.claims.length === 0 ? (
              <p className="meta">没有匹配的 claim。</p>
            ) : (
              <div className="claim-list">
                {result.claims.map((c) => (
                  <article className="claim-card" key={c.claim_id}>
                    <div className="claim-head">
                      <TierBadge tier={c.tier} renderable={c.section_renderable} />
                      <span className="meta" style={{ fontFamily: 'var(--mono)' }}>
                        {c.paper_id}
                      </span>
                    </div>
                    <p className="claim-text" style={{ marginBottom: 0 }}>
                      {c.claim}
                    </p>
                    {c.quote && <blockquote className="quote">{c.quote}</blockquote>}
                  </article>
                ))}
              </div>
            )}
          </section>

          <section>
            <p className="side-title">原文段落（{result.chunks.length}）</p>
            <div className="claim-list">
              {result.chunks.map((chunk) => (
                <article className="claim-card" key={chunk.chunk_id}>
                  <div className="claim-head">
                    <span className="meta" style={{ fontFamily: 'var(--mono)' }}>
                      {chunk.paper_id}
                    </span>
                    <span className="chip">第 {chunk.chunk_index + 1} 段</span>
                  </div>
                  <p style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 13.5 }}>{chunk.text}</p>
                </article>
              ))}
            </div>
          </section>
        </>
      )}

      {!result && !pending && (
        <div className="empty">
          提问后会先显示检索到的证据，再显示由模型生成的回答（若已配置 API key）。
        </div>
      )}
    </>
  )
}
