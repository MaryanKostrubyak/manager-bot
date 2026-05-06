// App analytics: charts, thresholds, insights, and heatmap rendering.
async function loadChartData() {
  if (!elements.chartCanvas) return;
  const requestId = state.chartRequestId + 1;
  state.chartRequestId = requestId;
  try {
    const params = buildPeriodParams();
    params.set("chart_type", state.chartType);
    const data = await authorizedFetch(`/api/v1/web/charts?${params.toString()}`, {
      cancelKey: "charts:data",
      cancelPrevious: true,
    });
    if (requestId !== state.chartRequestId) return;
    renderChart(data);
  } catch (error) {
    if (isAbortError(error)) return;
    console.error(error);
    if (requestId !== state.chartRequestId) return;
    renderChart({ labels: [], series: [] });
  }
}

function isCompactChartLayout() {
  if (!window.matchMedia) return false;
  return window.matchMedia("(max-width: 640px)").matches;
}

function trimChartLabel(value, maxLength) {
  const text = String(value ?? "");
  const limit = Number(maxLength) || 12;
  if (text.length <= limit) return text;
  const cut = Math.max(0, limit - 3);
  return `${text.slice(0, cut)}...`;
}

function buildChartConfig(chartData, convertedSeries, palette) {
  const isCompact = isCompactChartLayout();
  const labelLimit = isCompact ? 12 : 18;
  const axisFont = { size: isCompact ? 10 : 11 };
  const legend = {
    position: "bottom",
    align: "start",
    labels: {
      boxWidth: isCompact ? 12 : 14,
      boxHeight: isCompact ? 8 : 10,
      padding: isCompact ? 10 : 12,
      font: { size: isCompact ? 11 : 12 },
    },
  };
  const animation = isCompact ? false : { duration: 500, easing: "easeOutQuart" };
  const layout = isCompact
    ? { padding: { top: 4, bottom: 8, left: 6, right: 6 } }
    : { padding: { top: 6, bottom: 10, left: 8, right: 8 } };

  if (chartData.type === "category_pie") {
    return {
      type: "doughnut",
      data: {
        labels: chartData.labels,
        datasets: [
          {
            data: (convertedSeries[0] && convertedSeries[0].data) || [],
            backgroundColor: ((convertedSeries[0] && convertedSeries[0].data) || []).map((_, index) => palette[index % palette.length]),
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: isCompact ? "62%" : "68%",
        animation,
        layout,
        plugins: {
          legend,
          tooltip: {
            callbacks: {
              label: (context) => {
                const label = context.label || "";
                const value = context.formattedValue || "0";
                return `${label}: ${value} ${state.currency}`;
              },
            },
          },
        },
      },
    };
  }

  if (chartData.type === "trend_line" || chartData.type === "balance_line") {
    return {
      type: "line",
      data: { labels: chartData.labels, datasets: convertedSeries.map((serie) => ({ ...serie, fill: false })) },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation,
        layout,
        plugins: { legend },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              callback: (value) => `${value} ${state.currency}`,
              font: axisFont,
            },
          },
          x: {
            ticks: {
              font: axisFont,
              maxRotation: 0,
              autoSkip: true,
              callback: (value, index) => trimChartLabel(chartData.labels?.[index] ?? value, labelLimit),
            },
          },
        },
      },
    };
  }

  const isHorizontal = isCompact;
  const categoryAxis = isHorizontal ? "y" : "x";
  const valueAxis = isHorizontal ? "x" : "y";
  const autoSkip = (chartData.labels || []).length > (isCompact ? 12 : 16);

  return {
    type: "bar",
    data: { labels: chartData.labels, datasets: convertedSeries },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: isHorizontal ? "y" : "x",
      animation,
      layout,
      plugins: { legend },
      scales: {
        [valueAxis]: {
          beginAtZero: true,
          ticks: {
            callback: (value) => `${value} ${state.currency}`,
            font: axisFont,
          },
        },
        [categoryAxis]: {
          ticks: {
            autoSkip,
            font: axisFont,
            maxRotation: isHorizontal ? 0 : 45,
            minRotation: isHorizontal ? 0 : 20,
            callback: (value, index) => trimChartLabel(chartData.labels?.[index] ?? value, labelLimit),
          },
        },
      },
    },
  };
}

function renderChart(chartData) {
  if (!elements.chartCanvas || !window.Chart) return;
  const hasLabels = Array.isArray(chartData.labels) && chartData.labels.length > 0;
  const hasSeries =
    Array.isArray(chartData.series) &&
    chartData.series.some((serie) => Array.isArray(serie.data) && serie.data.some((value) => value !== null));
  const hasData = hasLabels && hasSeries;
  if (!hasData) {
    elements.chartCanvas.style.display = "none";
    if (elements.chartEmpty) {
      elements.chartEmpty.innerHTML = `
        <div class="chart-empty-state">
          <p>${t("chart_empty_copy")}</p>
          <div class="chart-empty-actions">
            <button type="button" class="ghost-btn small" data-scroll-target="#transaction-form">${t("chart_empty_add")}</button>
            <button type="button" class="ghost-btn small" data-scroll-target="#month-select">${t("chart_empty_month")}</button>
          </div>
        </div>
      `;
    }
    if (elements.chartMetrics) elements.chartMetrics.innerHTML = "";
    if (elements.chartInsights) elements.chartInsights.innerHTML = "";
    if (elements.chartThreshold) elements.chartThreshold.innerHTML = "";
    if (state.chartInstance) state.chartInstance.destroy();
    state.chartInstance = null;
    return;
  }
  elements.chartCanvas.style.display = "block";
  if (elements.chartEmpty) elements.chartEmpty.textContent = "";

  const palette = ["#4ee1b4", "#f3b36b", "#6bc2ff", "#ff7a7a", "#c2b3ff", "#9ad29a"];
  const isCompact = isCompactChartLayout();
  const isHorizontalBars = isCompact && chartData.type === "category_bar";
  const convertedSeries = (chartData.series || []).map((serie, index) => ({
    label: serie.label,
    data: (serie.data || []).map((value) => (value === null ? null : convertAmount(value, chartData.currency))),
    backgroundColor: palette[index % palette.length],
    borderColor: palette[index % palette.length],
    borderWidth: isCompact ? 1.5 : 2,
    borderRadius: 8,
    tension: 0.3,
    fill: chartData.type !== "trend_line" && chartData.type !== "balance_line",
  }));
  if (chartData.type === "category_bar") {
    convertedSeries.forEach((serie) => {
      if (isHorizontalBars) {
        serie.maxBarThickness = 14;
        serie.categoryPercentage = 0.7;
        serie.barPercentage = 0.6;
        serie.borderRadius = 6;
      } else {
        serie.barThickness = isCompact ? 14 : 18;
        serie.maxBarThickness = isCompact ? 18 : 26;
        serie.categoryPercentage = isCompact ? 0.8 : 0.7;
        serie.barPercentage = isCompact ? 0.8 : 0.7;
      }
    });
  }
  if (chartData.type === "trend_line" || chartData.type === "balance_line") {
    convertedSeries.forEach((serie) => {
      serie.pointRadius = isCompact ? 3 : 2;
      serie.pointHoverRadius = isCompact ? 4 : 3;
    });
  }

  const config = buildChartConfig(chartData, convertedSeries, palette);
  if (state.chartInstance && state.chartInstance.config?.type === config.type) {
    state.chartInstance.data = config.data;
    state.chartInstance.options = config.options;
    state.chartInstance.update("none");
  } else {
    if (state.chartInstance) state.chartInstance.destroy();
    state.chartInstance = new Chart(elements.chartCanvas.getContext("2d"), config);
  }
  renderChartMetrics(chartData, convertedSeries);
  renderChartInsights(chartData, convertedSeries);
  renderChartThreshold();
}

function renderChartMetrics(chartData, convertedSeries) {
  if (!elements.chartMetrics) return;
  const labels = chartData.labels || [];
  if (!labels.length || !convertedSeries.length) {
    elements.chartMetrics.innerHTML = "";
    return;
  }
  const valuesPerLabel = labels.map((_, index) =>
    convertedSeries.reduce((sum, serie) => sum + (Number(serie.data?.[index]) || 0), 0)
  );
  const total = valuesPerLabel.reduce((sum, value) => sum + value, 0);
  const avg = valuesPerLabel.length ? total / valuesPerLabel.length : 0;
  const peak = Math.max(...valuesPerLabel.map((value) => Math.abs(value)));
  const format = (value) => formatCurrency(value);

  elements.chartMetrics.innerHTML = `
    <div class="chart-metric">
      <span class="muted">${t("chart_metric_total")}</span>
      <strong>${format(total)}</strong>
    </div>
    <div class="chart-metric">
      <span class="muted">${t("chart_metric_avg")}</span>
      <strong>${format(avg)}</strong>
    </div>
    <div class="chart-metric">
      <span class="muted">${t("chart_metric_peak")}</span>
      <strong>${format(peak)}</strong>
    </div>
  `;
}

function renderChartThreshold() {
  if (!elements.chartThreshold) return;
  const budgets = state.budgets || [];
  const totals = budgets.reduce(
    (acc, item) => {
      const limit = item.limit && item.limit.amount ? Number(item.limit.amount) : 0;
      const spent = item.spent ? Number(item.spent) : 0;
      acc.limit += limit;
      acc.spent += spent;
      return acc;
    },
    { limit: 0, spent: 0 }
  );
  if (!totals.limit) {
    elements.chartThreshold.innerHTML = "";
    return;
  }
  const limitLabel = formatCurrency(convertAmount(totals.limit, state.baseCurrency));
  const spentLabel = formatCurrency(convertAmount(totals.spent, state.baseCurrency));
  const percent = Math.round((totals.spent / totals.limit) * 100);
  elements.chartThreshold.innerHTML = `
    <span class="muted">${t("chart_threshold_title")}</span>
    <strong>${t("chart_threshold_spent")}: ${spentLabel} · ${percent}%</strong>
    <span class="muted">${t("chart_threshold_limit")}: ${limitLabel}</span>
  `;
}


async function loadInsights() {
  if (!elements.heatmap) return;
  const requestId = state.insightsRequestId + 1;
  state.insightsRequestId = requestId;
  try {
    const params = buildPeriodParams();
    const data = await authorizedFetch(`/api/v1/web/insights?${params.toString()}`, {
      cancelKey: "insights:data",
      cancelPrevious: true,
    });
    if (requestId !== state.insightsRequestId) return;
    state.lastHeatmap = { cells: data.heatmap || [], currency: data.currency || state.baseCurrency };
    renderHeatmap(state.lastHeatmap.cells, state.lastHeatmap.currency);
  } catch (error) {
    if (isAbortError(error)) return;
    console.error(error);
  }
}

function renderHeatmap(cells, currency, target = elements.heatmap) {
  if (!target) return;
  if (!cells || !cells.length) {
    target.innerHTML = `<p class="muted">${t("chart_empty_copy")}</p>`;
    return;
  }
  const map = new Map();
  let maxValue = 0;
  cells.forEach((cell) => {
    const key = `${cell.weekday}-${cell.hour}`;
    const total = Number(cell.total) || 0;
    map.set(key, total);
    if (total > maxValue) maxValue = total;
  });
  const lang = state.language === "en" ? "en-US" : "uk-UA";
  const dayLabels = [];
  for (let weekday = 0; weekday < 7; weekday += 1) {
    const labelDate = new Date(Date.UTC(2024, 0, 1 + weekday));
    const dayLabel = labelDate.toLocaleDateString(lang, { weekday: "short" });
    dayLabels.push(dayLabel);
  }
  const hourLabels = ["00", "06", "12", "18"];
  const matrix = [];
  for (let weekday = 0; weekday < 7; weekday += 1) {
    for (let hour = 0; hour < 24; hour += 1) {
      const key = `${weekday}-${hour}`;
      const total = map.get(key) || 0;
      const level = maxValue ? Math.min(5, Math.ceil((total / maxValue) * 5)) : 0;
      const tooltip = `${dayLabels[weekday]} ${String(hour).padStart(2, "0")}:00 - ${formatCurrency(
        convertAmount(total, currency)
      )}`;
      matrix.push(`<span class="heatmap-cell" data-level="${level}" data-day="${weekday}" data-hour="${hour}" title="${tooltip}"></span>`);
    }
  }
  const topAxis = hourLabels
    .map((label) => `<span class="heatmap-axis-label heatmap-axis-label--hour">${label}</span>`)
    .join("");
  const leftAxis = dayLabels
    .map((label, index) => `<span class="heatmap-axis-label heatmap-axis-label--day" data-day="${index}">${label}</span>`)
    .join("");
  target.innerHTML = `
    <div class="heatmap-grid" role="grid" aria-label="${t("heatmap_title")}">
      <div class="heatmap-axis heatmap-axis--top">${topAxis}</div>
      <div class="heatmap-axis heatmap-axis--left">${leftAxis}</div>
      <div class="heatmap-matrix">${matrix.join("")}</div>
    </div>
  `;
}

function openHeatmapModal() {
  if (!elements.heatmapModal || !elements.heatmapModalBody) return;
  elements.heatmapModal.removeAttribute("hidden");
  document.body.style.overflow = "hidden";
  renderHeatmap(state.lastHeatmap.cells || [], state.lastHeatmap.currency || state.baseCurrency, elements.heatmapModalBody);
}

function closeHeatmapModal() {
  if (!elements.heatmapModal) return;
  elements.heatmapModal.setAttribute("hidden", "hidden");
  document.body.style.overflow = "";
}

function renderChartInsights(chartData, convertedSeries) {
  if (!elements.chartInsights) return;
  const labels = chartData.labels || [];
  if (!labels.length || !convertedSeries.length) {
    elements.chartInsights.innerHTML = "";
    return;
  }
  const totals = labels.map((_, index) =>
    convertedSeries.reduce((sum, serie) => sum + (Number(serie.data?.[index]) || 0), 0)
  );
  const totalSum = totals.reduce((sum, value) => sum + value, 0);
  const insights = [];

  if (chartData.type === "category_bar" || chartData.type === "category_pie") {
    const maxValue = Math.max(...totals.map((value) => Math.abs(value)));
    const maxIndex = totals.findIndex((value) => Math.abs(value) === maxValue);
    if (maxIndex >= 0) {
      const topLabel = labels[maxIndex] || "";
      const topShare = totalSum ? Math.round((Math.abs(totals[maxIndex]) / totalSum) * 100) : 0;
      insights.push({ label: t("chart_insight_top_category"), value: escapeHtml(String(topLabel)) });
      insights.push({ label: t("chart_insight_share"), value: `${topShare}%` });
    }
  }

  if (chartData.type === "trend_line") {
    const series = (convertedSeries[0] && convertedSeries[0].data) || [];
    const first = Number(series[0]) || 0;
    const last = Number(series[series.length - 1]) || 0;
    const delta = last - first;
    const direction =
      delta > 0 ? t("chart_insight_trend_up") : delta < 0 ? t("chart_insight_trend_down") : t("chart_insight_trend_flat");
    insights.push({ label: t("chart_insight_trend"), value: direction });
    if (series.length > 1) {
      const sign = delta > 0 ? "+" : delta < 0 ? "-" : "";
      insights.push({ label: t("chart_insight_change"), value: `${sign}${formatCurrency(Math.abs(delta))}` });
    }
  }

  elements.chartInsights.innerHTML = insights
    .map(
      (insight) => `
        <div class="chart-insight">
          <span>${insight.label}</span>
          <strong>${insight.value}</strong>
        </div>
      `
    )
    .join("");
}

