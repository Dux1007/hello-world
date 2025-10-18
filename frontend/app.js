const form = document.getElementById("fetch-form");
const statusEl = document.getElementById("form-status");
const dailyTableBody = document.querySelector("#daily-table tbody");
const annualTableBody = document.querySelector("#annual-table tbody");
const chartCanvas = document.getElementById("daily-chart");
let chart;

const INDEX_LABELS = {
  search: "搜索指数",
  news: "资讯指数"
};

function parseLines(input) {
  return input
    .split(/\r?\n|[,;]/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function buildPayload(formData) {
  const keywords = parseLines(formData.get("keywords") ?? "");
  const cities = parseLines(formData.get("cities") ?? "");
  const indexTypes = formData.getAll("index-type");
  const payload = {
    keywords,
    cities,
    start_date: formData.get("start-date"),
    end_date: formData.get("end-date"),
    index_types: indexTypes.length ? indexTypes : ["search"],
  };
  const cookie = formData.get("cookie");
  if (cookie && cookie.trim().length) {
    payload.cookie = cookie.trim();
  }
  return payload;
}

function formatNumber(value) {
  if (value === null || value === undefined) return "-";
  const formatter = new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: value % 1 === 0 ? 0 : 2
  });
  return formatter.format(Number(value));
}

function formatDate(dateString) {
  return new Date(dateString).toLocaleDateString("zh-CN");
}

function resetTables() {
  dailyTableBody.innerHTML = "";
  annualTableBody.innerHTML = "";
}

function updateStatus(message, type = "info") {
  statusEl.textContent = message;
  statusEl.classList.remove("success", "error");
  if (type !== "info") {
    statusEl.classList.add(type);
  }
}

function renderDailyTable(dailySeries) {
  const rows = [];
  dailySeries.forEach((series) => {
    series.points.forEach((point) => {
      rows.push({
        indexType: series.index_type,
        keyword: series.keyword,
        city: series.city,
        date: point.date,
        value: point.value
      });
    });
  });
  rows.sort((a, b) => {
    if (a.keyword === b.keyword) {
      if (a.city === b.city) {
        if (a.indexType === b.indexType) {
          return new Date(a.date) - new Date(b.date);
        }
        return a.indexType.localeCompare(b.indexType);
      }
      return a.city.localeCompare(b.city, "zh-CN");
    }
    return a.keyword.localeCompare(b.keyword, "zh-CN");
  });
  dailyTableBody.innerHTML = rows
    .map(
      (row) =>
        `<tr><td>${INDEX_LABELS[row.indexType] ?? row.indexType}</td><td>${row.keyword}</td><td>${row.city}</td><td>${formatDate(row.date)}</td><td>${formatNumber(row.value)}</td></tr>`
    )
    .join("");
}

function renderAnnualTable(annualSeries) {
  const rows = annualSeries
    .slice()
    .sort((a, b) => {
      if (a.keyword === b.keyword) {
        if (a.city === b.city) {
          if (a.index_type === b.index_type) {
            return a.year - b.year;
          }
          return a.index_type.localeCompare(b.index_type);
        }
        return a.city.localeCompare(b.city, "zh-CN");
      }
      return a.keyword.localeCompare(b.keyword, "zh-CN");
    })
    .map(
      (item) =>
        `<tr><td>${INDEX_LABELS[item.index_type] ?? item.index_type}</td><td>${item.keyword}</td><td>${item.city}</td><td>${item.year}</td><td>${formatNumber(item.average)}</td><td>${formatNumber(item.total)}</td><td>${item.non_null_days}</td></tr>`
    )
    .join("");
  annualTableBody.innerHTML = rows;
}

function generateColor(index) {
  const palette = [
    "#2563eb",
    "#16a34a",
    "#f97316",
    "#dc2626",
    "#7c3aed",
    "#0ea5e9",
    "#f59e0b",
    "#14b8a6"
  ];
  return palette[index % palette.length];
}

function renderChart(dailySeries) {
  if (!chartCanvas) return;
  if (!dailySeries.length) {
    if (chart) {
      chart.destroy();
      chart = null;
    }
    return;
  }
  const datasets = dailySeries.map((series, idx) => ({
    label: `${INDEX_LABELS[series.index_type] ?? series.index_type} · ${series.keyword} · ${series.city}`,
    data: series.points.map((point) => ({ x: point.date, y: point.value })),
    borderColor: generateColor(idx),
    backgroundColor: generateColor(idx),
    tension: 0.25,
    spanGaps: true
  }));
  if (chart) {
    chart.destroy();
  }
  chart = new Chart(chartCanvas, {
    type: "line",
    data: {
      datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      scales: {
        x: {
          type: "time",
          time: {
            unit: "month",
            tooltipFormat: "yyyy-MM-dd"
          },
          ticks: {
            autoSkip: true,
            maxTicksLimit: 12
          }
        },
        y: {
          beginAtZero: true,
          ticks: {
            precision: 0
          }
        }
      },
      plugins: {
        legend: {
          position: "bottom"
        },
        tooltip: {
          mode: "nearest",
          intersect: false,
          callbacks: {
            title(items) {
              if (!items.length) return "";
              const { raw } = items[0];
              return formatDate(raw.x);
            },
            label(item) {
              const { dataset } = item;
              return `${dataset.label}: ${formatNumber(item.raw.y)}`;
            }
          }
        }
      }
    }
  });
}

async function submitHandler(event) {
  event.preventDefault();
  const formData = new FormData(form);
  const payload = buildPayload(formData);

  if (!payload.keywords.length || !payload.cities.length) {
    updateStatus("请至少输入一个关键词和一个城市", "error");
    return;
  }

  updateStatus("正在抓取数据，请稍候...");
  form.querySelectorAll("button").forEach((button) => (button.disabled = true));

  try {
    const response = await fetch("/api/fetch", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      const detail = errorBody.detail || response.statusText;
      throw new Error(detail);
    }

    const data = await response.json();
    renderDailyTable(data.daily);
    renderAnnualTable(data.annual);
    renderChart(data.daily);
    updateStatus(`抓取完成，共生成 ${data.daily.length} 条序列。`, "success");
  } catch (error) {
    console.error(error);
    updateStatus(`抓取失败：${error.message}`, "error");
    resetTables();
    if (chart) {
      chart.destroy();
      chart = null;
    }
  } finally {
    form.querySelectorAll("button").forEach((button) => (button.disabled = false));
  }
}

form.addEventListener("submit", submitHandler);
form.addEventListener("reset", () => {
  resetTables();
  updateStatus("参数已重置。");
  if (chart) {
    chart.destroy();
    chart = null;
  }
});

// 提供一些默认值，便于快速体验
(function prefill() {
  const end = new Date();
  const start = new Date();
  start.setMonth(start.getMonth() - 3);
  const toDateInput = (value) => value.toISOString().slice(0, 10);
  document.getElementById("start-date").value = toDateInput(start);
  document.getElementById("end-date").value = toDateInput(end);
})();
