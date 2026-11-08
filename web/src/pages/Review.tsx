import { useCallback, useEffect, useState } from 'react'

import { api, AnnotationRow, Claim } from '../lib/api'
import { ClaimCard } from '../components/ClaimCard'
import { Empty, ErrorBox, Loading } from '../components/ui'

/**
 * The review page: read claims, mark them correct / wrong / unsure.
 *
 * This is the first page built on purpose. Its annotations are what will later
 * measure whether the automatic tiers are trustworthy -- the plan's acceptance
 * criterion ("P1 sampled 100, error rate <= 3%") can only be checked against
 * human verdicts, so collecting them has to start before anything else ships.
 *
 * The queue is ordered so that every tier is reachable: filtering by tier is
 * how a reviewer audits one tier at a time.
 */
const VERDICTS = [
  { value: 'correct', label: '正确' },
  { value: 'wrong', label: '错误' },
  { value: 'unsure', label: '存疑' },
] as const

const TIER_CHOICES = [
  { value: '', label: '全部档位' },
  { value: 'P1', label: 'P1 原文此句' },
  { value: 'P2', label: 'P2 原文多次' },
  { value: 'P3', label: 'P3 近似原文' },
  { value: 'S', label: 'S 仅章节' },
  { value: 'C_no_section', label: 'C 未定位' },
] as const

export function ReviewPage() {
  const [tier, setTier] = useState<string>('P1')
  const [text, setText] = useState('')
  const [page, setPage] = useState(0)
  const [claims, setClaims] = useState<Claim[] | null>(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [saving, setSaving] = useState<string | null>(null)

  const limit = 20

  const load = useCallback(async () => {
    setClaims(null)
    setError(null)
    try {
      const result = await api.claims({
        tier: tier ? [tier] : undefined,
        text: text || undefined,
        limit,
        offset: page * limit,
      })
      setClaims(result.items)
      setTotal(result.total)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [tier, text, page])

  const loadCounts = useCallback(async () => {
    try {
      const listing = await api.annotations()
      setCounts(listing.counts)
    } catch {
      /* the counts are a convenience; a failure must not block reviewing */
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    void loadCounts()
  }, [loadCounts])

  async function review(claim: Claim, verdict: 'correct' | 'wrong' | 'unsure') {
    setSaving(claim.claim_id)
    try {
      await api.annotate(claim.claim_id, verdict, claim.annotation?.note ?? '', '')
      setClaims((prev) =>
        prev
          ? prev.map((c) =>
              c.claim_id === claim.claim_id
                ? { ...c, annotation: { ...(c.annotation ?? { note: '', created_at: '' }), verdict, note: c.annotation?.note ?? '', annotator: '' } }
                : c,
            )
          : prev,
      )
      void loadCounts()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(null)
    }
  }

  const annotated = Object.values(counts).reduce((a, b) => a + b, 0) - (counts.total ?? 0)

  return (
    <>
      <h1 className="page-title">证据审阅</h1>
      <p className="page-sub">
        逐条判断 claim 是否准确。标注以内容指纹保存，claim_id 重算不会丢失。
      </p>

      <div className="review-layout">
        <div>
          <div className="toolbar">
            <select value={tier} onChange={(e) => { setTier(e.target.value); setPage(0) }}>
              {TIER_CHOICES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
            <input
              type="search"
              placeholder="在 claim 与引文中搜索…"
              value={text}
              onChange={(e) => { setText(e.target.value); setPage(0) }}
            />
          </div>

          <ErrorBox error={error} />

          {claims === null && <Loading what=" claim" />}
          {claims && claims.length === 0 && <Empty>没有符合条件的 claim。</Empty>}
          {claims && claims.length > 0 && (
            <div className="claim-list">
              {claims.map((claim) => (
                <ClaimCard
                  key={claim.claim_id}
                  claim={claim}
                  onReview={
                    saving === claim.claim_id ? undefined : (v) => void review(claim, v)
                  }
                />
              ))}
            </div>
          )}

          <div className="pager">
            <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
              上一页
            </button>
            <span className="meta">
              第 {page * limit + 1}–{page * limit + (claims?.length ?? 0)} 条
              {tier ? ` · 共 ${total.toLocaleString()} 条` : ''}
            </span>
            <button
              disabled={(page + 1) * limit >= total}
              onClick={() => setPage((p) => p + 1)}
            >
              下一页
            </button>
          </div>
        </div>

        <aside className="review-side">
          <p className="side-title">标注进度</p>
          {VERDICTS.map((v) => (
            <div className="side-row" key={v.value}>
              <span>{v.label}</span>
              <b>{(counts[v.value] ?? 0).toLocaleString()}</b>
            </div>
          ))}
          <div className="side-row" style={{ borderTop: '1px solid var(--border)', marginTop: 6, paddingTop: 8 }}>
            <span>已标注（去重）</span>
            <b>{(counts.total ?? 0).toLocaleString()}</b>
          </div>
          {annotated > 0 && (
            <p className="meta" style={{ marginBottom: 0 }}>
              其中重复标注 {annotated} 条被覆盖。
            </p>
          )}

          <p className="side-title" style={{ marginTop: 18 }}>
            徽标含义
          </p>
          <div className="legend" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 7 }}>
            <span><span className="tier tier-p1">原文此句</span> 可跳到原句</span>
            <span><span className="tier tier-p2">原文多次</span> 出现多处</span>
            <span><span className="tier tier-p3">近似原文</span> 措辞相近</span>
            <span><span className="tier tier-s">仅章节</span> 需自行查找</span>
            <span><span className="tier tier-c">未定位</span> 无位置信息</span>
          </div>
        </aside>
      </div>
    </>
  )
}

export type { AnnotationRow }
