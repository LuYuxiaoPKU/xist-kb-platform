/**
 * Tier presentation.
 *
 * The colours are the honest part of this UI. A green badge means the system
 * located the paper's own words; a grey badge means it did not. Nothing in
 * between is allowed to borrow the green.
 *
 *   P1  solid green    "原文此句"      one exact occurrence
 *   P2  dashed green   "原文出现 N 次" several exact occurrences
 *   P3  teal           "近似原文"      fuzzy alignment, score shown
 *   S   grey           "标注为 X 节"   section known, not located
 *   C   dark grey      "未定位"        nothing known
 *   K   faint          rule tag        not a claim at all
 */

export type Tier = 'P1' | 'P2' | 'P3' | 'S' | 'C_no_section' | 'C_no_text' | 'K'

export interface TierStyle {
  label: string
  detail: string
  className: string
  located: boolean
}

export const TIER_STYLES: Record<Tier, TierStyle> = {
  P1: {
    label: '原文此句',
    detail: '在论文原文中找到唯一一处',
    className: 'tier tier-p1',
    located: true,
  },
  P2: {
    label: '原文出现多次',
    detail: '在全文中出现不止一处，需人工确认是哪一处',
    className: 'tier tier-p2',
    located: true,
  },
  P3: {
    label: '近似原文',
    detail: '原文措辞相近但不完全一致',
    className: 'tier tier-p3',
    located: true,
  },
  S: {
    label: '仅标注所属章节',
    detail: '注释记录了章节，但没有可定位的引文',
    className: 'tier tier-s',
    located: false,
  },
  C_no_section: {
    label: '未定位',
    detail: '注释既没有引文也没有章节',
    className: 'tier tier-c',
    located: false,
  },
  C_no_text: {
    label: '无全文',
    detail: '这篇论文没有可检索的全文',
    className: 'tier tier-c',
    located: false,
  },
  K: {
    label: '关键词标签',
    detail: '规则提取产生，不是一条科学论断',
    className: 'tier tier-k',
    located: false,
  },
}

export function tierStyle(tier: string | null | undefined): TierStyle {
  if (tier && tier in TIER_STYLES) return TIER_STYLES[tier as Tier]
  return {
    label: '未知',
    detail: '这条记录没有溯源信息',
    className: 'tier tier-c',
    located: false,
  }
}

/** Section name → what a reader calls it. */
export const SECTION_LABELS: Record<string, string> = {
  abstract: '摘要',
  introduction: '引言',
  results: '结果',
  discussion: '讨论',
  methods: '方法',
  conclusion: '结论',
  not_reported: '未记录',
  figure_legend: '图注',
}

export function sectionLabel(section: string | null | undefined): string {
  if (!section) return '未记录'
  return SECTION_LABELS[section.toLowerCase()] ?? section
}
