import { Claim } from '../lib/api'
import { sectionLabel } from '../lib/tiers'
import { ContextPanel } from './ContextPanel'
import { Chips, SectionChip, TierBadge } from './ui'

export function ClaimCard({
  claim,
  onReview,
  showContext = true,
}: {
  claim: Claim
  onReview?: (verdict: 'correct' | 'wrong' | 'unsure', note: string) => void
  showContext?: boolean
}) {
  return (
    <article className="claim-card">
      <div className="claim-head">
        <TierBadge tier={claim.tier} renderable={claim.section_renderable} />
        <SectionChip section={claim.section} />
        <Chips
          items={[
            claim.topic,
            claim.confidence ? `置信度 ${claim.confidence}` : null,
            claim.species?.join('; '),
            claim.evidence_type,
          ]}
        />
      </div>

      <p className="claim-text">{claim.claim}</p>

      {claim.quote && (
        <blockquote className={claim.tier === 'P1' ? 'quote quote-located' : 'quote'}>
          {claim.quote}
        </blockquote>
      )}

      {claim.title && (
        <p className="meta" style={{ marginTop: 9, marginBottom: 0 }}>
          <a href={`#/paper/${encodeURIComponent(claim.paper_id)}`}>{claim.title}</a>
          {claim.year ? ` · ${claim.year}` : ''}
          {claim.journal ? ` · ${claim.journal}` : ''}
          {' · '}
          <span style={{ fontFamily: 'var(--mono)' }}>{claim.paper_id}</span>
        </p>
      )}

      {showContext && <ContextPanel claimId={claim.claim_id} />}

      {onReview && <ReviewBar claim={claim} onReview={onReview} />}
    </article>
  )
}

function ReviewBar({
  claim,
  onReview,
}: {
  claim: Claim
  onReview: (verdict: 'correct' | 'wrong' | 'unsure', note: string) => void
}) {
  const current = claim.annotation?.verdict
  return (
    <div className="verdict-bar">
      <button
        className={`verdict-correct${current === 'correct' ? ' verdict-active' : ''}`}
        onClick={() => onReview('correct', claim.annotation?.note ?? '')}
      >
        {current === 'correct' ? '✓ 已标正确' : '正确'}
      </button>
      <button
        className={`verdict-wrong${current === 'wrong' ? ' verdict-active' : ''}`}
        onClick={() => onReview('wrong', claim.annotation?.note ?? '')}
      >
        {current === 'wrong' ? '✕ 已标错误' : '错误'}
      </button>
      <button
        className={`verdict-unsure${current === 'unsure' ? ' verdict-active' : ''}`}
        onClick={() => onReview('unsure', claim.annotation?.note ?? '')}
      >
        {current === 'unsure' ? '? 已标存疑' : '存疑'}
      </button>
    </div>
  )
}

/** Compact one-line variant for search results and paper pages. */
export function ClaimRow({ claim }: { claim: Claim }) {
  return (
    <article className="claim-card">
      <div className="claim-head">
        <TierBadge tier={claim.tier} renderable={claim.section_renderable} />
        <SectionChip section={claim.section} />
        <Chips items={[claim.topic, claim.species?.join('; ')]} />
      </div>
      <p className="claim-text" style={{ marginBottom: 0 }}>
        {claim.claim}
      </p>
      <p className="meta" style={{ marginTop: 6, marginBottom: 0 }}>
        标注章节：{sectionLabel(claim.section)}
      </p>
    </article>
  )
}
