import { useEffect, useState } from 'react'

import { api, ClaimContext } from '../lib/api'
import { sectionLabel } from '../lib/tiers'
import { ErrorBox, Loading } from './ui'

/**
 * Shows the paper's own words for a claim.
 *
 * Three outcomes, and the panel must not blur them:
 *
 *   quote   -> the located character intervals, highlighted in context
 *   section -> the whole section body, with its size stated up front
 *   none    -> the reason, in plain language
 *
 * The section body is intentionally not framed as "the source of this claim".
 * It is the section the annotation named, and the header says how large that
 * section is, because 85% of them exceed 10,000 characters -- a reader who
 * expects one sentence must be told they are getting a section.
 */
export function ContextPanel({ claimId }: { claimId: string }) {
  const [context, setContext] = useState<ClaimContext | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    let cancelled = false
    setContext(null)
    setError(null)
    setExpanded(false)
    api
      .claimContext(claimId)
      .then((c) => {
        if (!cancelled) setContext(c)
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message)
      })
    return () => {
      cancelled = true
    }
  }, [claimId])

  if (error) return <ErrorBox error={error} />
  if (!context) return <Loading what="原文" />

  if (context.kind === 'none') {
    return (
      <div className="context">
        <div className="context-head">
          <span className="meta">没有可定位的原文：{context.reason}</span>
        </div>
      </div>
    )
  }

  if (context.kind === 'quote') {
    const span = context.spans[0]
    return (
      <div className="context">
        <div className="context-head">
          <TierChip text={context.spans.length > 1 ? `原文出现 ${context.spans.length} 处` : '原文此句'} />
          <span className="meta">
            字符 {span.start}–{span.end}
          </span>
        </div>
        <div className="context-body">
          <mark>{span.text}</mark>
        </div>
      </div>
    )
  }

  const body = context.section
  if (!body) return null
  const pct = Math.round(body.fraction_of_paper * 100)

  return (
    <div className="context">
      <div className="context-head">
        <span className="chip">{sectionLabel(body.name)}节</span>
        <span className="meta">
          {body.char_count.toLocaleString()} 字符 · 占全文 {pct}%
          {body.truncated && ' · 已截断'}
        </span>
        <button onClick={() => setExpanded((v) => !v)}>
          {expanded ? '收起' : '查看该节全文'}
        </button>
      </div>
      {expanded ? (
        <div className="context-body">{body.text}</div>
      ) : (
        <p className="meta" style={{ margin: 0 }}>
          注释记录了这条论断出自{sectionLabel(body.name)}节，但没有可定位的引文。展开后可读该节全文并自行查找。
        </p>
      )}
    </div>
  )
}

function TierChip({ text }: { text: string }) {
  return <span className="chip">{text}</span>
}
