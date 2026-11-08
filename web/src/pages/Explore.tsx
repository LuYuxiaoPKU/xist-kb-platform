import { useEffect, useState } from 'react'

import { api, Stats } from '../lib/api'
import { ErrorBox, Loading } from '../components/ui'
import { TIER_STYLES, Tier } from '../lib/tiers'

/**
 * Overview: what is in the knowledge base and how much of it can be trusted.
 *
 * The tier distribution is the headline, not a footnote. A visitor should see
 * immediately that 30% of claims were located and 60% were not, rather than
 * discovering it from a badge on some later page.
 */
export function ExplorePage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .stats()
      .then(setStats)
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <ErrorBox error={error} />
  if (!stats) return <Loading what="统计" />

  const tierTotal = stats.tiers.reduce((sum, t) => sum + t.count, 0) || 1
  const located = stats.tiers
    .filter((t) => ['P1', 'P2', 'P3'].includes(t.tier))
    .reduce((sum, t) => sum + t.count, 0)

  const claimScopeTotal = stats.scope_claims.reduce((sum, s) => sum + s.count, 0) || 1
  const outScope = stats.scope_claims.find((s) => s.scope === 'out_of_scope')

  return (
    <>
      <h1 className="page-title">知识库概览</h1>
      <p className="page-sub">文献规模、claim 分布与溯源可信度。</p>

      {stats.scope_claims.length > 0 && (
        <section style={{ marginBottom: 26 }}>
          <p className="side-title">这些 claim 是否在讲 XIST/XCI</p>
          <div className="claim-list">
            {stats.scope_claims.map((s) => {
              const pct = (100 * s.count) / claimScopeTotal
              return (
                <div key={s.scope} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ width: 240, flexShrink: 0 }} className="meta">
                    {s.label}
                  </span>
                  <span style={{ flex: 1, height: 8, background: 'var(--bg-sunk)', borderRadius: 4 }}>
                    <span
                      style={{
                        display: 'block',
                        width: `${pct}%`,
                        height: '100%',
                        borderRadius: 4,
                        background:
                          s.scope === 'out_of_scope'
                            ? 'var(--warn)'
                            : s.scope === 'unknown'
                              ? 'var(--border)'
                              : 'var(--accent)',
                      }}
                    />
                  </span>
                  <span className="meta" style={{ width: 150, textAlign: 'right' }}>
                    {s.count.toLocaleString()} · {pct.toFixed(1)}%
                  </span>
                </div>
              )
            })}
          </div>
          <p className="meta" style={{ marginTop: 11 }}>
            判定依据是论文全文，不是单条 claim：全文从不提 Xist 的论文，其 claim 无论怎么标注都
            不会是在讲这个主题。
            {outScope && outScope.count > 0 && (
              <>
                {' '}
                当前有 <b>{outScope.count.toLocaleString()}</b> 条 claim 来自这类论文
                （{((100 * outScope.count) / claimScopeTotal).toFixed(1)}%），
                检索与问答默认排除它们。
              </>
            )}
          </p>
        </section>
      )}

      <section style={{ marginBottom: 26 }}>
        <p className="side-title">溯源能到什么程度</p>
        <div className="claim-list">
          {stats.tiers.map((t) => {
            const style = TIER_STYLES[t.tier as Tier]
            const pct = (100 * t.count) / tierTotal
            return (
              <div key={t.tier} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ width: 150, flexShrink: 0 }}>
                  <span className={style?.className ?? 'tier tier-c'}>
                    {style?.label ?? t.tier}
                  </span>
                </span>
                <span
                  style={{
                    flex: 1,
                    height: 18,
                    background: 'var(--bg-raised)',
                    border: '1px solid var(--border)',
                    borderRadius: 4,
                    overflow: 'hidden',
                  }}
                >
                  <span
                    style={{
                      display: 'block',
                      height: '100%',
                      width: `${pct}%`,
                      background: style?.located ? 'var(--p1)' : 'var(--c)',
                      opacity: style?.located ? 1 : 0.5,
                    }}
                  />
                </span>
                <span className="meta" style={{ width: 150, textAlign: 'right' }}>
                  {t.count.toLocaleString()} · {pct.toFixed(1)}%
                </span>
              </div>
            )
          })}
        </div>
        <p className="meta" style={{ marginTop: 11 }}>
          <b>{((100 * located) / tierTotal).toFixed(1)}%</b> 的 claim 能在原文中定位到具体语句；
          其余只能给出所属章节或标记为未定位。
        </p>
      </section>

      <section style={{ marginBottom: 26 }}>
        <p className="side-title">规模</p>
        <table className="plain">
          <tbody>
            {Object.entries(stats.tables).map(([name, count]) => (
              <tr key={name}>
                <th style={{ width: 180 }}>{name}</th>
                <td>{count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section style={{ marginBottom: 26 }}>
        <p className="side-title">主题分布（前 15）</p>
        <table className="plain">
          <tbody>
            {stats.topics.slice(0, 15).map((t) => (
              <tr key={t.topic}>
                <th style={{ width: 260 }}>{t.topic}</th>
                <td>{t.count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <p className="side-title">置信度分布</p>
        <table className="plain">
          <tbody>
            {stats.confidence.map((c) => (
              <tr key={c.confidence}>
                <th style={{ width: 180 }}>{c.confidence}</th>
                <td>{c.count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}
