import { useEffect, useState } from 'react'

import { api, Visualize } from '../lib/api'
import { ErrorBox, Loading } from '../components/ui'

/** Horizontal bar chart. No chart library: the data is one numeric column. */
function Bars({
  rows,
  label,
  value,
  unit,
}: {
  rows: { [key: string]: string | number }[]
  label: string
  value: string
  unit?: string
}) {
  const max = Math.max(...rows.map((r) => Number(r[value])), 1)
  return (
    <div className="claim-list">
      {rows.map((row) => {
        const n = Number(row[value])
        return (
          <div key={String(row[label])} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 190, flexShrink: 0, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  title={String(row[label])}>
              {String(row[label])}
            </span>
            <span style={{ flex: 1, height: 16, background: 'var(--bg-subtle)', borderRadius: 3, overflow: 'hidden' }}>
              <span style={{ display: 'block', height: '100%', width: `${(100 * n) / max}%`, background: 'var(--accent)', opacity: 0.75 }} />
            </span>
            <span className="meta" style={{ width: 92, textAlign: 'right' }}>
              {n.toLocaleString()}
              {unit ? ` ${unit}` : ''}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export function VisualizePage() {
  const [data, setData] = useState<Visualize | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .visualize()
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <ErrorBox error={error} />
  if (!data) return <Loading what="图表数据" />

  return (
    <>
      <h1 className="page-title">可视化</h1>
      <p className="page-sub">XIST 互作蛋白、物种分布、文献年份与表观标记。</p>

      <section style={{ marginBottom: 30 }}>
        <p className="side-title">XIST 互作蛋白（按记载次数）</p>
        <Bars rows={data.interactors} label="protein" value="claims" unit="条" />
      </section>

      <section style={{ marginBottom: 30 }}>
        <p className="side-title">研究物种</p>
        <Bars rows={data.species} label="species" value="count" unit="篇" />
      </section>

      <section style={{ marginBottom: 30 }}>
        <p className="side-title">
          表观标记（{data.chromatin_mark_papers.toLocaleString()} 条记录中提到）
        </p>
        <Bars rows={data.chromatin_marks} label="mark" value="papers" unit="条" />
        <p className="meta" style={{ marginTop: 8 }}>
          只统计明确记录该标记存在的条目；「未报道」不计入。
        </p>
      </section>

      <section style={{ marginBottom: 30 }}>
        <p className="side-title">XCI 类型</p>
        <Bars rows={data.xci_types} label="xci_type" value="count" unit="条" />
      </section>

      <section>
        <p className="side-title">文献年份分布</p>
        <Bars rows={data.years.slice(-30)} label="year" value="count" unit="篇" />
        <p className="meta" style={{ marginTop: 8 }}>
          显示最近 30 年。知识库共 {data.years.reduce((s, y) => s + y.count, 0).toLocaleString()} 篇有年份记录。
        </p>
      </section>
    </>
  )
}
