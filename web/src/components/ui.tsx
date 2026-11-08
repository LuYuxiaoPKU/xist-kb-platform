import { TierStyle, sectionLabel, tierStyle } from '../lib/tiers'

/** Small coloured badge. Colour encodes whether the claim was located. */
export function TierBadge({ tier, renderable }: { tier?: string | null; renderable?: boolean | null }) {
  const style: TierStyle = tierStyle(tier)
  // S tier only: say whether the section body can actually be opened.
  const label = tier === 'S' && renderable === false ? `${style.label}（无该节标题）` : style.label
  return (
    <span className={style.className} title={style.detail}>
      {label}
    </span>
  )
}

export function Chips({ items }: { items: (string | null | undefined)[] }) {
  const shown = items.filter((v): v is string => Boolean(v))
  if (!shown.length) return null
  return (
    <>
      {shown.map((item, i) => (
        <span className="chip" key={`${item}-${i}`}>
          {item}
        </span>
      ))}
    </>
  )
}

export function SectionChip({ section }: { section?: string | null }) {
  return <span className="chip">{sectionLabel(section)}</span>
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null
  return <div className="error">{error}</div>
}

export function Loading({ what }: { what?: string }) {
  return <div className="loading">正在加载{what ?? ''}…</div>
}
