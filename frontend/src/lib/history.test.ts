import { describe, expect, it } from 'vitest'
import type { ReportPayload } from '../api/client'
import { formatClock, formatDateTime, formatHistoryDate } from './history'
import { reportRunInfo } from './view'

// 后端对外一律输出带偏移的 UTC 串（architecture.md §2.4）。
// Docker（容器 UTC）生成的存量报告的运行时刻：
const DOCKER_RUN = '2026-09-21T11:46:52+00:00'
// 本地 dev（Asia/Shanghai）生成的存量报告，按 created_at 推断偏移换算后的运行时刻：
const LOCAL_RUN = '2026-09-15T09:52:33+00:00'
const SHANGHAI = { timeZone: 'Asia/Shanghai' }

describe('时刻按查看者时区格式化', () => {
  it('同一 UTC 瞬间在不同时区显示各自的本地时间', () => {
    expect(formatDateTime(DOCKER_RUN, SHANGHAI)).toBe('2026-09-21 19:46:52')
    expect(formatDateTime(DOCKER_RUN, { timeZone: 'UTC' })).toBe('2026-09-21 11:46:52')
    expect(formatDateTime(DOCKER_RUN, { timeZone: 'America/New_York' })).toBe('2026-09-21 07:46:52')
    expect(formatHistoryDate(DOCKER_RUN, SHANGHAI)).toBe('09/21 19:46')
    expect(formatClock(DOCKER_RUN, SHANGHAI)).toBe('19:46:52')
  })

  it('本地 dev 与 Docker 生成的报告按同一口径显示', () => {
    expect(formatHistoryDate(LOCAL_RUN, SHANGHAI)).toBe('09/15 17:52')
    expect(formatHistoryDate(DOCKER_RUN, SHANGHAI)).toBe('09/21 19:46')
  })

  it('库列带微秒与 Z 结尾的时刻照常解析', () => {
    expect(formatDateTime('2026-09-21T12:23:00.891052+00:00', SHANGHAI)).toBe('2026-09-21 20:23:00')
    expect(formatDateTime('2026-09-21T11:46:52Z', SHANGHAI)).toBe('2026-09-21 19:46:52')
  })

  it('跨午夜时日期随时区进位，小时不出现 24', () => {
    const midnight = '2026-09-21T16:00:00+00:00'
    expect(formatDateTime(midnight, SHANGHAI)).toBe('2026-09-22 00:00:00')
    expect(formatHistoryDate(midnight, SHANGHAI)).toBe('09/22 00:00')
    expect(formatClock(midnight, SHANGHAI)).toBe('00:00:00')
  })

  it('空值显示占位，无法解析或不带偏移的串原样返回', () => {
    for (const format of [formatDateTime, formatClock, formatHistoryDate]) {
      expect(format(null)).toBe('—')
      expect(format(undefined)).toBe('—')
      expect(format('')).toBe('—')
      expect(format('not-a-time')).toBe('not-a-time')
      // 契约外的无偏移串：时区无从判断，不做换算
      expect(format('2026-09-21T11:46:52')).toBe('2026-09-21T11:46:52')
    }
  })

  it('直接作为数组回调使用时，下标不会被当成时区', () => {
    expect(() => [DOCKER_RUN].map(formatDateTime as (value: string) => string)).not.toThrow()
  })
})

describe('报告运行信息', () => {
  const report = (ranAt?: string) =>
    ({
      metadata: {
        data_source: { id: 'sample-retail', type: 'csv', name: 'sample.csv', location: 'sample.csv' },
        row_count: 10,
        ran_at: ranAt,
        model: 'deepseek-flash',
        iterations_used: 3,
        token_used: 100,
      },
    }) as unknown as ReportPayload

  it('生成时间经本地时区格式化，不再透出原始 ISO 串', () => {
    const info = reportRunInfo(report(DOCKER_RUN))
    expect(info.ranAt).toBe(formatDateTime(DOCKER_RUN))
    expect(info.ranAt).not.toContain('T')
    expect(info.ranAt).not.toContain('+00:00')
  })

  it('缺少生成时间时显示占位', () => {
    expect(reportRunInfo(report()).ranAt).toBe('—')
  })
})
