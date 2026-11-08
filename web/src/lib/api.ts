/** API client. One place that knows the wire format and the auth header. */

const API_KEY_STORAGE = 'xist-kb-api-key'

export function apiKey(): string {
  return localStorage.getItem(API_KEY_STORAGE) ?? ''
}

export function setApiKey(key: string): void {
  if (key) localStorage.setItem(API_KEY_STORAGE, key)
  else localStorage.removeItem(API_KEY_STORAGE)
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  }
  const key = apiKey()
  if (key) headers['X-API-Key'] = key

  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch {
      /* the body was not JSON */
    }
    throw new ApiError(detail, response.status)
  }
  return (await response.json()) as T
}

function qs(params: Record<string, string | number | string[] | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, item)
    } else {
      search.set(key, String(value))
    }
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

export interface Claim {
  claim_id: string
  paper_id: string
  claim: string
  topic: string | null
  evidence_type: string | null
  directness: string | null
  section: string | null
  confidence: string | null
  species: string[] | null
  quote: string | null
  figure_or_table: string | null
  caveat: string | null
  title?: string | null
  year?: number | null
  journal?: string | null
  doi?: string | null
  tier?: string | null
  scope?: string | null
  annotation_method?: string | null
  annotation?: Annotation | null
  span_count?: number | null
  fuzzy_score?: number | null
  section_renderable?: boolean | null
}

export interface Annotation {
  verdict: 'correct' | 'wrong' | 'unsure'
  note: string
  annotator: string
  created_at: string
}

export interface Span {
  start: number
  end: number
  text: string
}

export interface SectionBody {
  name: string
  heading: string | null
  text: string
  char_count: number
  truncated: boolean
  fraction_of_paper: number
}

export interface ClaimContext {
  claim_id: string
  paper_id: string
  kind: 'quote' | 'section' | 'none'
  spans: Span[]
  section: SectionBody | null
  reason: string | null
}

export interface Page<T> {
  total: number
  limit: number
  offset: number
  items: T[]
}

export interface Chunk {
  chunk_id: string
  paper_id: string
  chunk_index: number
  start: number
  end: number
  text: string
  score: number | null
}

export interface Paper {
  paper_id: string
  title: string
  year: number | null
  journal: string | null
  doi: string | null
  first_author: string | null
  species: string[] | null
  status: string
  has_text: boolean
  has_annotation: boolean
  claims?: Claim[]
}

export interface Stats {
  topics: { topic: string; count: number }[]
  statuses: { status: string; count: number }[]
  confidence: { confidence: string; count: number }[]
  years: { year: number; count: number }[]
  species: { species: string; count: number }[]
  tables: Record<string, number>
  tiers: { tier: string; count: number }[]
  scopes: { scope: string; label: string; count: number }[]
  scope_claims: { scope: string; label: string; count: number }[]
}

export interface AskResult {
  question: string
  claims: Claim[]
  chunks: Chunk[]
  answer: string | null
  model: string | null
  usage: { input_tokens: number; output_tokens: number; cost_usd: number } | null
  error: string | null
}

export interface Visualize {
  interactors: { protein: string; claims: number; papers: number }[]
  species: { species: string; count: number }[]
  years: { year: number; count: number }[]
  xci_types: { xci_type: string; count: number }[]
  chromatin_marks: { mark: string; papers: number }[]
  chromatin_mark_papers: number
  regulators: {
    regulator: string
    papers: number
    repression: number
    activation: number
  }[]
}

export interface ClaimFilters {
  topic?: string[]
  confidence?: string[]
  tier?: string[]
  scope?: string[]
  species?: string[]
  year_from?: number
  year_to?: number
  text?: string
  limit?: number
  offset?: number
}

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),
  stats: () => request<Stats>('/api/stats'),
  visualize: () => request<Visualize>('/api/visualize'),
  ask: (q: string) => request<AskResult>(`/api/ask?q=${encodeURIComponent(q)}`),
  askBudget: () =>
    request<{ date: string; spent_usd: number; limit_usd: number; remaining_usd: number }>(
      '/api/ask/budget',
    ),
  claims: (f: ClaimFilters) => request<Page<Claim>>(`/api/claims${qs({ ...f })}`),
  claim: (id: string) => request<Claim>(`/api/claims/${encodeURIComponent(id)}`),
  claimContext: (id: string) =>
    request<ClaimContext>(`/api/claims/${encodeURIComponent(id)}/context`),
  annotate: (id: string, verdict: string, note: string, annotator: string) =>
    request<{ annotation_key: string; verdict: string }>(
      `/api/claims/${encodeURIComponent(id)}/annotations`,
      { method: 'POST', body: JSON.stringify({ verdict, note, annotator }) },
    ),
  paper: (id: string) => request<Paper>(`/api/papers/${encodeURIComponent(id)}`),
  chunks: (text: string, limit = 20) =>
    request<Page<Chunk>>(`/api/chunks${qs({ text, limit })}`),
  annotations: (paperId?: string) =>
    request<{ total: number; items: AnnotationRow[]; counts: Record<string, number> }>(
      `/api/annotations${qs({ paper_id: paperId })}`,
    ),
}

export interface AnnotationRow extends Annotation {
  annotation_key: string
  claim_id: string
  paper_id: string
}

export function exportUrl(filters: ClaimFilters, format: 'csv' | 'json'): string {
  const params: Record<string, string | number | string[]> = { format }
  if (filters.topic?.length) params.topic = filters.topic
  if (filters.tier?.length) params.tier = filters.tier
  if (filters.scope?.length) params.scope = filters.scope
  if (filters.species?.length) params.species = filters.species
  if (filters.text) params.text = filters.text
  const key = apiKey()
  const base = `/api/export${qs(params)}`
  return key ? `${base}${base.includes('?') ? '&' : '?'}key=${encodeURIComponent(key)}` : base
}
