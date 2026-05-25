import { useCallback, useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import * as echarts from "echarts";
import {
  tokenUsageApi,
  type TokenUsageDetailRecord,
  type TokenUsageStats,
  type TokenUsageSummary,
} from "../../api/tokenUsage";

type TokenUsagePanelProps = {
  pageTheme: "light" | "dark";
  currentEmployeeName: string;
};

type TokenUsageModelRow = TokenUsageStats & {
  key: string;
  total_tokens: number;
};

type TokenUsageDateRow = TokenUsageStats & {
  key: string;
  date: string;
  total_tokens: number;
};

type TokenUsageProviderRow = TokenUsageStats & {
  key: string;
  total_tokens: number;
};

function formatDateInput(date: Date) {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function buildDefaultDateRange() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - 30);
  return {
    startDate: formatDateInput(start),
    endDate: formatDateInput(end),
  };
}

function normalizeDateRange(startDate: string, endDate: string) {
  if (!startDate || !endDate || startDate <= endDate) {
    return { startDate, endDate };
  }
  return { startDate: endDate, endDate: startDate };
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: value >= 100000 ? 1 : 0,
  }).format(value);
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatDateLabel(value: string) {
  if (!value) {
    return "--";
  }
  const [, month = "", day = ""] = value.split("-");
  return `${month}/${day}`;
}

function buildDateRange(startDate: string, endDate: string) {
  if (!startDate || !endDate) {
    return [];
  }

  const dates: string[] = [];
  const current = new Date(`${startDate}T00:00:00`);
  const last = new Date(`${endDate}T00:00:00`);

  while (current <= last) {
    dates.push(formatDateInput(current));
    current.setDate(current.getDate() + 1);
  }

  return dates;
}

function formatTokenAxisLabel(value: number) {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `${Math.round(value / 1_000)}K`;
  }
  return String(value);
}

function totalTokens(stats: TokenUsageStats) {
  return stats.prompt_tokens + stats.completion_tokens;
}

export function TokenUsagePanel({
  pageTheme,
  currentEmployeeName,
}: TokenUsagePanelProps) {
  const defaultRange = useMemo(() => buildDefaultDateRange(), []);
  const [startDate, setStartDate] = useState(defaultRange.startDate);
  const [endDate, setEndDate] = useState(defaultRange.endDate);
  const [summary, setSummary] = useState<TokenUsageSummary | null>(null);
  const [details, setDetails] = useState<TokenUsageDetailRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadTokenUsage = useCallback(async (rangeStartDate: string, rangeEndDate: string) => {
    const range = normalizeDateRange(rangeStartDate, rangeEndDate);
    setLoading(true);
    setError("");

    try {
      const [nextSummary, nextDetails] = await Promise.all([
        tokenUsageApi.getTokenUsageSummary({
          start_date: range.startDate,
          end_date: range.endDate,
        }),
        tokenUsageApi.getTokenUsageDetails({
          start_date: range.startDate,
          end_date: range.endDate,
        }),
      ]);
      setSummary(nextSummary);
      setDetails(nextDetails);
      setStartDate(range.startDate);
      setEndDate(range.endDate);
    } catch (fetchError) {
      console.error("Failed to load token usage summary:", fetchError);
      setError(fetchError instanceof Error ? fetchError.message : "Token 统计加载失败");
      setSummary(null);
      setDetails([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchTokenUsage = useCallback(
    async () => loadTokenUsage(startDate, endDate),
    [endDate, loadTokenUsage, startDate],
  );

  const resetTokenUsage = useCallback(async () => {
    await loadTokenUsage(defaultRange.startDate, defaultRange.endDate);
  }, [defaultRange.endDate, defaultRange.startDate, loadTokenUsage]);

  useEffect(() => {
    void loadTokenUsage(defaultRange.startDate, defaultRange.endDate);
  }, [defaultRange.endDate, defaultRange.startDate, loadTokenUsage]);

  const byModelRows = useMemo<TokenUsageModelRow[]>(() => {
    const grouped = new Map<string, TokenUsageModelRow>();

    for (const record of details) {
      const providerId = record.provider_id || "默认";
      const modelId = record.model || "unknown";
      const key = `${providerId}:${modelId}`;
      const current = grouped.get(key);

      if (current) {
        current.prompt_tokens += record.prompt_tokens;
        current.completion_tokens += record.completion_tokens;
        current.call_count += record.call_count;
        current.total_tokens += totalTokens(record);
        continue;
      }

      grouped.set(key, {
        key,
        provider_id: record.provider_id || "默认",
        model: modelId,
        prompt_tokens: record.prompt_tokens,
        completion_tokens: record.completion_tokens,
        call_count: record.call_count,
        total_tokens: totalTokens(record),
      });
    }

    return [...grouped.values()].sort(
      (left, right) => right.total_tokens - left.total_tokens || right.call_count - left.call_count,
    );
  }, [details]);

  const byDateRowsAsc = useMemo<TokenUsageDateRow[]>(() => {
    return Object.entries(summary?.by_date || {})
      .map(([date, stats]) => ({
        ...stats,
        key: date,
        date,
        total_tokens: totalTokens(stats),
      }))
      .sort((left, right) => left.date.localeCompare(right.date));
  }, [summary?.by_date]);

  const byDateRowsDesc = useMemo(() => [...byDateRowsAsc].reverse(), [byDateRowsAsc]);

  const normalizedRange = useMemo(
    () => normalizeDateRange(startDate, endDate),
    [endDate, startDate],
  );

  const allDatesAsc = useMemo(
    () => buildDateRange(normalizedRange.startDate, normalizedRange.endDate),
    [normalizedRange.endDate, normalizedRange.startDate],
  );

  const byProviderRows = useMemo<TokenUsageProviderRow[]>(() => {
    const grouped = new Map<string, TokenUsageProviderRow>();

    for (const record of details) {
      const providerId = record.provider_id || "默认";
      const current = grouped.get(providerId);

      if (current) {
        current.prompt_tokens += record.prompt_tokens;
        current.completion_tokens += record.completion_tokens;
        current.call_count += record.call_count;
        current.total_tokens += totalTokens(record);
        continue;
      }

      grouped.set(providerId, {
        key: providerId,
        provider_id: providerId,
        prompt_tokens: record.prompt_tokens,
        completion_tokens: record.completion_tokens,
        call_count: record.call_count,
        total_tokens: totalTokens(record),
      });
    }

    return [...grouped.values()].sort(
      (left, right) => right.total_tokens - left.total_tokens || right.call_count - left.call_count,
    );
  }, [details]);

  const totalTokenCount = useMemo(
    () => (summary?.total_prompt_tokens || 0) + (summary?.total_completion_tokens || 0),
    [summary?.total_completion_tokens, summary?.total_prompt_tokens],
  );

  const byDateStatsMap = useMemo(() => {
    const map = new Map<string, TokenUsageStats>();
    for (const [date, stats] of Object.entries(summary?.by_date || {})) {
      map.set(date, stats);
    }
    return map;
  }, [summary?.by_date]);

  const byDateModelMap = useMemo(() => {
    const map = new Map<string, Map<string, TokenUsageStats>>();

    for (const record of details) {
      const providerId = record.provider_id || "默认";
      const modelId = record.model || "unknown";
      const modelKey = `${providerId}:${modelId}`;
      const dayMap = map.get(record.date) || new Map<string, TokenUsageStats>();
      const existing = dayMap.get(modelKey);

      if (existing) {
        existing.prompt_tokens += record.prompt_tokens;
        existing.completion_tokens += record.completion_tokens;
        existing.call_count += record.call_count;
      } else {
        dayMap.set(modelKey, {
          provider_id: providerId,
          model: modelId,
          prompt_tokens: record.prompt_tokens,
          completion_tokens: record.completion_tokens,
          call_count: record.call_count,
        });
      }

      map.set(record.date, dayMap);
    }

    return map;
  }, [details]);

  const statCards = useMemo(
    () => [
      {
        label: "输入 Token",
        value: formatCompact(summary?.total_prompt_tokens || 0),
        meta: `${formatNumber(summary?.total_prompt_tokens || 0)} tokens`,
        accent: "primary",
        icon: "fa-arrow-right-to-bracket",
      },
      {
        label: "输出 Token",
        value: formatCompact(summary?.total_completion_tokens || 0),
        meta: `${formatNumber(summary?.total_completion_tokens || 0)} tokens`,
        accent: "purple",
        icon: "fa-arrow-right-from-bracket",
      },
      {
        label: "总调用次数",
        value: formatCompact(summary?.total_calls || 0),
        meta: `${byProviderRows.length} 个模型源`,
        accent: "green",
        icon: "fa-bolt",
      },
      {
        label: "总 Token",
        value: formatCompact(totalTokenCount),
        meta: `${byModelRows.length} 个模型`,
        accent: "cyan",
        icon: "fa-chart-column",
      },
    ],
    [byModelRows.length, byProviderRows.length, summary?.total_calls, summary?.total_completion_tokens, summary?.total_prompt_tokens, totalTokenCount],
  );

  const tokenTrendOption = useMemo(() => {
    const isDark = pageTheme === "dark";

    return {
      backgroundColor: "transparent",
      animationDuration: 400,
      tooltip: {
        trigger: "axis",
        backgroundColor: isDark ? "rgba(20, 27, 45, 0.96)" : "rgba(255, 255, 255, 0.96)",
        borderColor: "rgba(79, 110, 247, 0.25)",
        textStyle: {
          color: isDark ? "#e2e8f0" : "#1e293b",
          fontSize: 12,
        },
      },
      legend: {
        data: ["输入 Token", "输出 Token"],
        bottom: 0,
        textStyle: {
          color: isDark ? "#94a3b8" : "#64748b",
        },
      },
      grid: {
        left: 48,
        right: 18,
        top: 18,
        bottom: 42,
      },
      xAxis: {
        type: "category",
        data: allDatesAsc.map((date) => formatDateLabel(date)),
        axisLine: {
          lineStyle: {
            color: "rgba(79, 110, 247, 0.15)",
          },
        },
        axisLabel: {
          color: isDark ? "#94a3b8" : "#94a3b8",
          fontSize: 11,
        },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        splitLine: {
          lineStyle: {
            color: isDark ? "rgba(79, 110, 247, 0.1)" : "rgba(79, 110, 247, 0.08)",
          },
        },
        axisLabel: {
          color: isDark ? "#94a3b8" : "#94a3b8",
          formatter: (value: number) => formatCompact(value),
        },
      },
      series: [
        {
          name: "输入 Token",
          type: "bar",
          stack: "total",
          barWidth: 22,
          itemStyle: {
            borderRadius: [0, 0, 0, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "#4f6ef7" },
              { offset: 1, color: "rgba(79, 110, 247, 0.45)" },
            ]),
          },
          data: allDatesAsc.map((date) => byDateStatsMap.get(date)?.prompt_tokens || 0),
        },
        {
          name: "输出 Token",
          type: "bar",
          stack: "total",
          barWidth: 22,
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "#a78bfa" },
              { offset: 1, color: "rgba(167, 139, 250, 0.42)" },
            ]),
          },
          data: allDatesAsc.map((date) => byDateStatsMap.get(date)?.completion_tokens || 0),
        },
      ],
    };
  }, [allDatesAsc, byDateStatsMap, pageTheme]);

  const modelTrendOption = useMemo(() => {
    const isDark = pageTheme === "dark";
    const legendColor = isDark ? "#cbd5e1" : "#475569";

    return {
      backgroundColor: "transparent",
      animationDuration: 400,
      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "line",
        },
        backgroundColor: isDark ? "rgba(20, 27, 45, 0.96)" : "rgba(255, 255, 255, 0.96)",
        borderColor: "rgba(79, 110, 247, 0.25)",
        textStyle: {
          color: isDark ? "#e2e8f0" : "#1e293b",
          fontSize: 12,
        },
        formatter: (params: Array<{ axisValue: string; seriesName: string; data: number; color: string }>) => {
          const lines = params
            .filter((item) => item.data > 0)
            .map((item) => `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${item.color};margin-right:6px;"></span>${item.seriesName}<span style="float:right;margin-left:20px;font-weight:600">${formatNumber(item.data || 0)}</span>`)
            .join("<br/>");
          return `<div style="min-width:180px">${params[0]?.axisValue || ""}<br/>${lines || '<span style="color:#94a3b8">暂无用量</span>'}</div>`;
        },
      },
      legend: {
        type: "scroll",
        top: 0,
        left: 0,
        right: 0,
        textStyle: {
          color: legendColor,
          fontSize: 12,
        },
      },
      grid: {
        left: 54,
        right: 18,
        top: 56,
        bottom: 30,
      },
      xAxis: {
        type: "category",
        data: allDatesAsc.map((date) => formatDateLabel(date)),
        boundaryGap: false,
        axisLine: {
          lineStyle: {
            color: "rgba(79, 110, 247, 0.15)",
          },
        },
        axisLabel: {
          color: isDark ? "#94a3b8" : "#94a3b8",
          fontSize: 11,
        },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        splitLine: {
          lineStyle: {
            color: isDark ? "rgba(79, 110, 247, 0.1)" : "rgba(79, 110, 247, 0.08)",
          },
        },
        axisLabel: {
          color: isDark ? "#94a3b8" : "#94a3b8",
          formatter: (value: number) => formatTokenAxisLabel(value),
        },
      },
      series: byModelRows.map((row) => ({
        name: row.key,
        type: "line",
        smooth: true,
        showSymbol: false,
        symbol: "circle",
        symbolSize: 6,
        lineStyle: {
          width: 3,
        },
        emphasis: {
          focus: "series",
        },
        data: allDatesAsc.map(
          (date) => byDateModelMap.get(date)?.get(row.key)?.prompt_tokens || 0,
        ),
      })),
    };
  }, [allDatesAsc, byDateModelMap, byModelRows, pageTheme]);

  const tokenTypeTrendOption = useMemo(() => {
    const isDark = pageTheme === "dark";

    return {
      backgroundColor: "transparent",
      animationDuration: 400,
      color: ["#4f6ef7", "#14b8c4", "#f97316"],
      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "line",
        },
        backgroundColor: isDark ? "rgba(20, 27, 45, 0.96)" : "rgba(255, 255, 255, 0.96)",
        borderColor: "rgba(79, 110, 247, 0.25)",
        textStyle: {
          color: isDark ? "#e2e8f0" : "#1e293b",
          fontSize: 12,
        },
        formatter: (params: Array<{ axisValue: string; seriesName: string; data: number; color: string }>) => {
          const lines = params
            .map((item) => `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${item.color};margin-right:6px;"></span>${item.seriesName}<span style="float:right;margin-left:20px;font-weight:600">${formatNumber(item.data || 0)}</span>`)
            .join("<br/>");
          return `<div style="min-width:180px">${params[0]?.axisValue || ""}<br/>${lines}</div>`;
        },
      },
      legend: {
        top: 0,
        left: 0,
        textStyle: {
          color: isDark ? "#cbd5e1" : "#475569",
          fontSize: 12,
        },
      },
      grid: {
        left: 54,
        right: 18,
        top: 56,
        bottom: 30,
      },
      xAxis: {
        type: "category",
        data: allDatesAsc.map((date) => formatDateLabel(date)),
        boundaryGap: false,
        axisLine: {
          lineStyle: {
            color: "rgba(79, 110, 247, 0.15)",
          },
        },
        axisLabel: {
          color: isDark ? "#94a3b8" : "#94a3b8",
          fontSize: 11,
        },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        splitLine: {
          lineStyle: {
            color: isDark ? "rgba(79, 110, 247, 0.1)" : "rgba(79, 110, 247, 0.08)",
          },
        },
        axisLabel: {
          color: isDark ? "#94a3b8" : "#94a3b8",
          formatter: (value: number) => formatTokenAxisLabel(value),
        },
      },
      series: [
        {
          name: "输入 Token",
          type: "line",
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 3 },
          data: allDatesAsc.map((date) => byDateStatsMap.get(date)?.prompt_tokens || 0),
        },
        {
          name: "输出 Token",
          type: "line",
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 3 },
          data: allDatesAsc.map((date) => byDateStatsMap.get(date)?.completion_tokens || 0),
        },
        {
          name: "总计 Token",
          type: "line",
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 3 },
          data: allDatesAsc.map((date) => {
            const stats = byDateStatsMap.get(date);
            return stats ? totalTokens(stats) : 0;
          }),
        },
      ],
    };
  }, [allDatesAsc, byDateStatsMap, pageTheme]);

  const hasData = Boolean(summary && summary.total_calls > 0);

  return (
    <div className="token-usage-page">
      <div className="token-usage-static">
        <div className="portal-model-page-header">
          <div className="portal-model-page-title">
            Token统计 <small>资源消耗分析</small>
          </div>
        </div>

        <div className="portal-model-scope-bar token-usage-scope-bar">
          <span>当前数字员工：{currentEmployeeName}</span>
          <span>统计范围：全局模型调用</span>
          <span>统计区间：{startDate} 至 {endDate}</span>
        </div>

        <div className="token-usage-filter-bar">
          <label className="token-usage-filter-field">
            <span>开始日期</span>
            <input
              type="date"
              value={startDate}
              max={endDate || undefined}
              onChange={(event) => setStartDate(event.target.value)}
            />
          </label>
          <label className="token-usage-filter-field">
            <span>结束日期</span>
            <input
              type="date"
              value={endDate}
              min={startDate || undefined}
              onChange={(event) => setEndDate(event.target.value)}
            />
          </label>
          <div className="token-usage-filter-actions">
            <button
              type="button"
              className="portal-model-btn token-usage-filter-action token-usage-filter-action-query"
              disabled={loading || !startDate || !endDate}
              onClick={() => void fetchTokenUsage()}
            >
              <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-magnifying-glass"}`} />
              查询
            </button>
            <button
              type="button"
              className="portal-model-btn secondary token-usage-filter-action token-usage-filter-action-reset"
              disabled={loading}
              onClick={() => void resetTokenUsage()}
            >
              <i className="fas fa-rotate-left" />
              重置
            </button>
          </div>
        </div>

        {error ? <div className="model-inline-notice error">{error}</div> : null}
      </div>

      <div className="token-usage-scroll">
        {loading && !summary ? (
          <div className="token-usage-empty">
            <i className="fas fa-chart-column" />
            <p>正在加载 Token 统计...</p>
          </div>
        ) : hasData ? (
          <>
            <div className="token-usage-stats-row">
              {statCards.map((item) => (
                <article
                  key={item.label}
                  className={`token-usage-stat-card token-usage-stat-card-${item.accent}`}
                >
                  <div className="token-usage-stat-icon">
                    <i className={`fas ${item.icon}`} />
                  </div>
                  <div className="token-usage-stat-label">{item.label}</div>
                  <div className="token-usage-stat-value">{item.value}</div>
                  <div className="token-usage-stat-meta">{item.meta}</div>
                </article>
              ))}
            </div>

            <section className="token-usage-chart-card">
              <div className="token-usage-card-head">
                <div>
                  <h4>每日 Token 消耗</h4>
                  <p>按日期展示输入 / 输出 token 消耗变化</p>
                </div>
              </div>
              <ReactECharts
                echarts={echarts}
                option={tokenTrendOption}
                style={{ height: 320, width: "100%" }}
                opts={{ renderer: "canvas" }}
                notMerge={true}
                lazyUpdate={true}
              />
            </section>

            <div className="token-usage-trend-grid">
              <section className="token-usage-chart-card">
                <div className="token-usage-card-head">
                  <div>
                    <h4>模型用量趋势</h4>
                  </div>
                </div>
                <ReactECharts
                  echarts={echarts}
                  option={modelTrendOption}
                  style={{ height: 320, width: "100%" }}
                  opts={{ renderer: "canvas" }}
                  notMerge={true}
                  lazyUpdate={true}
                />
              </section>

              <section className="token-usage-chart-card">
                <div className="token-usage-card-head">
                  <div>
                    <h4>Token 类型分布趋势</h4>
                  </div>
                </div>
                <ReactECharts
                  echarts={echarts}
                  option={tokenTypeTrendOption}
                  style={{ height: 320, width: "100%" }}
                  opts={{ renderer: "canvas" }}
                  notMerge={true}
                  lazyUpdate={true}
                />
              </section>
            </div>

            <div className="token-usage-detail-grid">
              <section className="token-usage-table-card token-usage-table-card-wide">
                <div className="token-usage-card-head">
                  <div>
                    <h4>模型明细</h4>
                    <p>按模型 / 模型源聚合的 token 消耗与调用次数</p>
                  </div>
                </div>
                <div className="token-usage-table-wrap">
                  <table className="token-usage-table">
                    <thead>
                      <tr>
                        <th>模型源</th>
                        <th>模型</th>
                        <th>输入 Token</th>
                        <th>输出 Token</th>
                        <th>总计</th>
                        <th>调用次数</th>
                      </tr>
                    </thead>
                    <tbody>
                      {byModelRows.map((row) => (
                        <tr key={row.key}>
                          <td>{row.provider_id || "默认"}</td>
                          <td>{row.model || row.key}</td>
                          <td>{formatNumber(row.prompt_tokens)}</td>
                          <td>{formatNumber(row.completion_tokens)}</td>
                          <td className="token-usage-emphasis">{formatNumber(row.total_tokens)}</td>
                          <td>{formatNumber(row.call_count)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="token-usage-table-card">
                <div className="token-usage-card-head">
                  <div>
                    <h4>模型源统计</h4>
                    <p>快速查看各模型源的整体消耗</p>
                  </div>
                </div>
                <div className="token-usage-provider-list">
                  {byProviderRows.map((row) => (
                    <div key={row.key} className="token-usage-provider-item">
                      <div>
                        <strong>{row.key || "默认"}</strong>
                        <span>{formatNumber(row.call_count)} 次调用</span>
                      </div>
                      <em>{formatNumber(row.total_tokens)} tokens</em>
                    </div>
                  ))}
                </div>
              </section>

              <section className="token-usage-table-card">
                <div className="token-usage-card-head">
                  <div>
                    <h4>每日明细</h4>
                    <p>用于回溯近一段时间的消耗峰值</p>
                  </div>
                </div>
                <div className="token-usage-table-wrap">
                  <table className="token-usage-table token-usage-table-compact">
                    <thead>
                      <tr>
                        <th>日期</th>
                        <th>输入 Token</th>
                        <th>输出 Token</th>
                        <th>总计</th>
                        <th>调用次数</th>
                      </tr>
                    </thead>
                    <tbody>
                      {byDateRowsDesc.map((row) => (
                        <tr key={row.key}>
                          <td>{row.date}</td>
                          <td>{formatNumber(row.prompt_tokens)}</td>
                          <td>{formatNumber(row.completion_tokens)}</td>
                          <td className="token-usage-emphasis">{formatNumber(row.total_tokens)}</td>
                          <td>{formatNumber(row.call_count)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          </>
        ) : (
          <div className="token-usage-empty">
            <i className="fas fa-chart-column" />
            <p>当前时间范围内暂无 Token 统计数据</p>
          </div>
        )}
      </div>
    </div>
  );
}
