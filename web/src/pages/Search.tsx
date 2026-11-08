import { FormEvent, useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, Claim, ClaimFilters, exportUrl } from '../lib/api'
import { ClaimCard } from '../components/ClaimCard'
import { ClaimRow } from '../components/ClaimCard'
import { Empty, ErrorBox, Loading } from '../components/ui'

const TIER_CHOICES = [
  { value: '', label: '全部档位' },
  { value: 'P1', label: 'P1 原文此句' },
  { value: 'P2', label: 'P2 原文多次' },
  { value: 'P3', label: 'P3 近似原文' },
  { value: 'S', label: 'S 仅章节' },
  { value: 'C_no_section', label: 'C 未定位' },
] as const

// Defaults to in-scope. A claim from a paper whose full text never mentions
// Xist is about something else, and mixing those into every search would make
// the results look larger and less relevant than the corpus really is. The
// option to see them stays, because hiding rows without saying so would be
// worse than the noise. The server applies the same default when no scope
// parameter is sent, so the two cannot drift apart.
const SCOPE_CHOICES = [
  { value: 'in', label: '仅 XIST/XCI 相关（默认）' },
  { value: 'all', label: '全部论文（含背景性）' },
  { value: 'out', label: '只看范围外论文' },
] as const

const ALL_SCOPES = ['xist', 'phenomenon_only', 'out_of_scope', 'unknown']

/** Search and browse claims with the tier badge always visible. */
export function SearchPage() {
  const [text, setText] = useState('')
  const [tier, setTier] = useState('')
  const [topic, setTopic] = useState('')
  const [scopeMode, setScopeMode] = useState<string>('in')
  const [yearFrom, setYearFrom] = useState('')
  const [yearTo, setYearTo] = useState('')
  const [page, setPage] = useState(0)
  const [claims, setClaims] = useState<Claim[] | null>(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [topics, setTopics] = useState<{ topic: string; count: number }[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)

  const limit = 20

  useEffect(() => {
    api
      .stats()
      .then((s) => setTopics(s.topics.slice(0, 25)))
      .catch(() => setTopics([]))
  }, [])

  const filters: ClaimFilters = {
    text: text || undefined,
    tier: tier ? [tier] : undefined,
    topic: topic ? [topic] : undefined,
    scope:
      scopeMode === 'all' ? ALL_SCOPES : scopeMode === 'out' ? ['out_of_scope'] : undefined,
    year_from: yearFrom ? Number(yearFrom) : undefined,
    year_to: yearTo ? Number(yearTo) : undefined,
  }

  const load = useCallback(async () => {
    setClaims(null)
    setError(null)
    try {
      const result = await api.claims({ ...filters, limit, offset: page * limit })
      setClaims(result.items)
      setTotal(result.total)
    } catch (e) {
      setError((e as Error).message)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, tier, topic, scopeMode, yearFrom, yearTo, page])

  useEffect(() => {
    void load()
  }, [load])

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    setPage(0)
    void load()
  }

  return (
    <>
      <h1 className="page-title">检索</h1>
      <p className="page-sub">
        按主题、物种、年份或文本检索 claim。每条都标注了能否在原文中定位。
      </p>

      <form className="toolbar" onSubmit={onSubmit}>
        <input
          type="search"
          placeholder="搜索 claim 文本或引文…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <select value={tier} onChange={(e) => { setTier(e.target.value); setPage(0) }}>
          {TIER_CHOICES.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
        <select value={scopeMode} onChange={(e) => { setScopeMode(e.target.value); setPage(0) }}>
          {SCOPE_CHOICES.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
        <select value={topic} onChange={(e) => { setTopic(e.target.value); setPage(0) }}>
          <option value="">全部主题</option>
          {topics.map((t) => (
            <option key={t.topic} value={t.topic}>
              {t.topic} ({t.count.toLocaleString()})
            </option>
          ))}
        </select>
        <input
          type="number"
          placeholder="起始年"
          value={yearFrom}
          style={{ width: 88 }}
          onChange={(e) => { setYearFrom(e.target.value); setPage(0) }}
        />
        <input
          type="number"
          placeholder="结束年"
          value={yearTo}
          style={{ width: 88 }}
          onChange={(e) => { setYearTo(e.target.value); setPage(0) }}
        />
        <button type="submit">搜索</button>
        <a href={exportUrl(filters, 'csv')} download>
          <button type="button">导出 CSV</button>
        </a>
      </form>

      <ErrorBox error={error} />

      {claims && claims.length > 0 && (
        <p className="meta" style={{ marginBottom: 11 }}>
          共 {total.toLocaleString()} 条，显示第 {page * limit + 1}–{page * limit + claims.length} 条
        </p>
      )}

      {claims === null && <Loading what=" claim" />}
      {claims && claims.length === 0 && <Empty>没有符合条件的 claim。试试放宽筛选条件。</Empty>}
      {claims && claims.length > 0 && (
        <div className="claim-list">
          {claims.map((claim) =>
            expanded === claim.claim_id ? (
              <ClaimCard key={claim.claim_id} claim={claim} />
            ) : (
              <div
                key={claim.claim_id}
                onClick={() => setExpanded(claim.claim_id)}
                style={{ cursor: 'pointer' }}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && setExpanded(claim.claim_id)}
              >
                <ClaimRow claim={claim} />
              </div>
            ),
          )}
        </div>
      )}

      <div className="pager">
        <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
          上一页
        </button>
        <button disabled={(page + 1) * limit >= total} onClick={() => setPage((p) => p + 1)}>
          下一页
        </button>
      </div>

      <p className="meta" style={{ marginTop: 22 }}>
        想直接看论文原文？<Link to="/fulltext">全文检索</Link>
      </p>
    </>
  )
}
