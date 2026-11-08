import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

import { api, Paper } from '../lib/api'
import { ClaimRow } from '../components/ClaimCard'
import { ErrorBox, Loading } from '../components/ui'

export function PaperPage() {
  const { paperId = '' } = useParams()
  const [paper, setPaper] = useState<Paper | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setPaper(null)
    setError(null)
    api
      .paper(paperId)
      .then((p) => {
        if ('error' in p) setError(`${paperId} 不在知识库中`)
        else setPaper(p)
      })
      .catch((e: Error) => setError(e.message))
  }, [paperId])

  if (error) return <ErrorBox error={error} />
  if (!paper) return <Loading what="论文" />

  return (
    <>
      <h1 className="page-title">{paper.title || paper.paper_id}</h1>
      <p className="page-sub">
        {[paper.first_author, paper.year, paper.journal].filter(Boolean).join(' · ')}
        {paper.doi && (
          <>
            {' · '}
            <a href={`https://doi.org/${paper.doi}`} target="_blank" rel="noreferrer">
              doi:{paper.doi}
            </a>
          </>
        )}
      </p>

      <table className="plain" style={{ marginBottom: 22 }}>
        <tbody>
          <tr>
            <th style={{ width: 120 }}>paper_id</th>
            <td style={{ fontFamily: 'var(--mono)' }}>{paper.paper_id}</td>
          </tr>
          <tr>
            <th>状态</th>
            <td>
              {paper.status}
              {paper.has_text ? ' · 有全文' : ' · 无全文'}
              {paper.has_annotation ? ' · 有注释' : ''}
            </td>
          </tr>
          <tr>
            <th>物种</th>
            <td>{paper.species?.join('; ') || '未记录'}</td>
          </tr>
          <tr>
            <th>claims</th>
            <td>{paper.claims?.length ?? 0}</td>
          </tr>
        </tbody>
      </table>

      {paper.claims && paper.claims.length > 0 ? (
        <div className="claim-list">
          {paper.claims.map((claim) => (
            <ClaimRow key={claim.claim_id} claim={claim} />
          ))}
        </div>
      ) : (
        <p className="meta">这篇论文还没有提取出 claims。</p>
      )}
    </>
  )
}
