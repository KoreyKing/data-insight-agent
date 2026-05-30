// Icons — line-style, 16px default. Single-stroke aesthetic. Ported from design icons.jsx.
import type { JSX } from 'react'

type IconProps = { size?: number }

export const Ico: Record<string, (p: IconProps) => JSX.Element> = {
  Logo: (p) => (
    <svg viewBox="0 0 24 24" width={p.size || 16} height={p.size || 16} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 17 L9 11 L13 14 L21 6" />
      <circle cx="9" cy="11" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="13" cy="14" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="21" cy="6" r="1.3" fill="currentColor" stroke="none" />
      <path d="M3 20 H21" />
    </svg>
  ),
  Plus: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M8 3v10M3 8h10" /></svg>),
  X: (p) => (<svg viewBox="0 0 16 16" width={p.size || 10} height={p.size || 10} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M4 4l8 8M12 4l-8 8" /></svg>),
  Chat: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M2.5 4.5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2H7l-3 2.5V11.5H4.5a2 2 0 0 1-2-2z" /></svg>),
  Doc: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M3.5 2h6L13 5.5V14H3.5z" /><path d="M9.5 2v3.5H13" /><path d="M5.5 8h5M5.5 10.5h5M5.5 6h2" /></svg>),
  Template: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="2.5" y="2.5" width="11" height="11" rx="1" /><path d="M2.5 6h11M6 6v7.5" /></svg>),
  Database: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="8" cy="3.5" rx="5" ry="1.5" /><path d="M3 3.5v9c0 .8 2.2 1.5 5 1.5s5-.7 5-1.5v-9" /><path d="M3 8c0 .8 2.2 1.5 5 1.5s5-.7 5-1.5" /></svg>),
  Cog: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="8" cy="8" r="2" /><path d="M8 1.5v1.5M8 13v1.5M3.4 3.4l1 1M11.6 11.6l1 1M1.5 8h1.5M13 8h1.5M3.4 12.6l1-1M11.6 4.4l1-1" /></svg>),
  Sparkle: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><path d="M8 2 L9.2 6.8 L14 8 L9.2 9.2 L8 14 L6.8 9.2 L2 8 L6.8 6.8 Z" /></svg>),
  Upload: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M8 10V2.5M5 5.5L8 2.5l3 3" /><path d="M2.5 11v1.5A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V11" /></svg>),
  Sample: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="2.5" y="3" width="11" height="10" rx="1" /><path d="M2.5 6h11M6 13V6" /></svg>),
  ArrowDown: (p) => (<svg viewBox="0 0 12 12" width={p.size || 10} height={p.size || 10} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M6 2v8M3 7l3 3 3-3" /></svg>),
  ArrowUp: (p) => (<svg viewBox="0 0 12 12" width={p.size || 10} height={p.size || 10} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M6 10V2M3 5l3-3 3 3" /></svg>),
  Check: (p) => (<svg viewBox="0 0 16 16" width={p.size || 12} height={p.size || 12} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 8.5l3.5 3.5L13 4.5" /></svg>),
  Warn: (p) => (<svg viewBox="0 0 16 16" width={p.size || 12} height={p.size || 12} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M8 2l6.5 11h-13z" /><path d="M8 6v3.5" /><circle cx="8" cy="11.5" r=".5" fill="currentColor" /></svg>),
  Send: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M2.5 8h11M9 3.5L13.5 8 9 12.5" /></svg>),
  Loop: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M3 8a5 5 0 0 1 8.5-3.5L13 6" /><path d="M13 3v3h-3" /><path d="M13 8a5 5 0 0 1-8.5 3.5L3 10" /><path d="M3 13v-3h3" /></svg>),
  Code: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M6 4L2 8l4 4M10 4l4 4-4 4" /></svg>),
  Eye: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5"><ellipse cx="8" cy="8" rx="6" ry="3.8" /><circle cx="8" cy="8" r="1.6" fill="currentColor" /></svg>),
  Table: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="12" height="10" rx="1" /><path d="M2 7h12M2 10h12M6 3v10" /></svg>),
  Filter: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M2 3h12L9.5 8.5V13l-3-1.5V8.5z" /></svg>),
  Share: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="4" cy="8" r="1.5" /><circle cx="12" cy="3.5" r="1.5" /><circle cx="12" cy="12.5" r="1.5" /><path d="M5.3 7.2l5.4-3M5.3 8.8l5.4 3" /></svg>),
  Download: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M8 2.5v8M4.5 7L8 10.5 11.5 7" /><path d="M2.5 12.5V14h11v-1.5" /></svg>),
  More: (p) => (<svg viewBox="0 0 16 16" width={p.size || 14} height={p.size || 14} fill="currentColor"><circle cx="3.5" cy="8" r="1.2" /><circle cx="8" cy="8" r="1.2" /><circle cx="12.5" cy="8" r="1.2" /></svg>),
  Bullet: (p) => (<svg viewBox="0 0 10 10" width={p.size || 8} height={p.size || 8} fill="currentColor"><circle cx="5" cy="5" r="2.2" /></svg>),
  Calendar: (p) => (<svg viewBox="0 0 16 16" width={p.size || 13} height={p.size || 13} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="2.5" y="3.5" width="11" height="10" rx="1" /><path d="M2.5 6.5h11M5.5 2v3M10.5 2v3" /></svg>),
  Clock: (p) => (<svg viewBox="0 0 16 16" width={p.size || 13} height={p.size || 13} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><circle cx="8" cy="8" r="5.5" /><path d="M8 5v3l2 1.5" /></svg>),
  Pin: (p) => (<svg viewBox="0 0 16 16" width={p.size || 13} height={p.size || 13} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M8 2l3 3-1 1 1.5 4-7-7 4 1.5 1-1z" /><path d="M5 11l-2.5 2.5" /></svg>),
  Caret: (p) => (<svg viewBox="0 0 12 12" width={p.size || 10} height={p.size || 10} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 3l3 3-3 3" /></svg>),
  Dot: (p) => (<svg viewBox="0 0 10 10" width={p.size || 8} height={p.size || 8} fill="currentColor"><circle cx="5" cy="5" r="2" /></svg>),
}
