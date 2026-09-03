/* 币透 CoinLens 前端逻辑：任务轮询 + 报告渲染（纯原生 JS，无外部依赖） */
"use strict";

const $ = (s) => document.querySelector(s);

const state = { pollTimer: null, running: false };

/* ---------- 工具 ---------- */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtNum(v, digits) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  const d = digits != null ? digits : (Math.abs(n) >= 1000 ? 2 : Math.abs(n) >= 1 ? 2 : 4);
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

function pctClass(v) { return Number(v) >= 0 ? "up" : "down"; }

function fmtPct(v, digits = 2) {
  if (v == null) return "—";
  return `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(digits)}%`;
}

function timeLabel(iso) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

const BIAS_TEXT = { "偏多": "多", "偏空": "空", "震荡": "震", "观望": "望" };

/* ---------- 初始化 ---------- */
async function loadStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    const chip = $("#llm-chip");
    if (s.llm.configured) {
      chip.textContent = `◉ ${s.llm.model}`;
      chip.classList.add("chip-ok");
      $("#llm-banner").hidden = true;
    } else {
      chip.textContent = "◌ LLM 未配置";
      $("#llm-banner").hidden = false;
    }
  } catch { $("#llm-chip").textContent = "服务未连接"; }
}

async function loadHistory() {
  const ul = $("#history-list");
  try {
    const list = await (await fetch("/api/reports")).json();
    if (!list.length) {
      ul.innerHTML = '<li class="history-empty">还没有报告，先跑一次研究。</li>';
      return;
    }
    ul.innerHTML = list.map((r) => `
      <li><button data-id="${esc(r.id)}">
        <span><span class="h-sym">${esc(r.symbol)}</span>
          <span class="h-bias">${esc(r.bias || "数据简报")}</span></span>
        <span class="h-date">${timeLabel(r.generated_at)}</span>
      </button></li>`).join("");
    ul.querySelectorAll("button").forEach((b) =>
      b.addEventListener("click", () => fetchReport(b.dataset.id)));
  } catch {
    ul.innerHTML = '<li class="history-empty">历史加载失败。</li>';
  }
}

/* ---------- 研究任务 ---------- */
async function startResearch() {
  if (state.running) return;
  const symbol = $("#symbol-input").value.trim().toUpperCase();
  const question = $("#question-input").value.trim();
  if (!/^[A-Z0-9]{2,10}$/.test(symbol)) {
    alert("请输入有效的交易对，例如 BTC、ETH、SOL");
    $("#symbol-input").focus();
    return;
  }

  state.running = true;
  $("#run-btn").disabled = true;
  $("#run-btn").textContent = "研究中…";
  $("#empty-state").hidden = true;
  $("#error-panel").hidden = true;
  $("#report").hidden = true;
  $("#progress-symbol").textContent = symbol + "USDT";
  $("#progress-panel").hidden = false;

  try {
    const res = await fetch("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, question }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
    const { job_id } = await res.json();
    pollJob(job_id);
  } catch (e) {
    showError("任务提交失败", e.message);
    resetRun();
  }
}

function pollJob(jobId) {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      const job = await (await fetch(`/api/jobs/${jobId}`)).json();
      renderStages(job);
      if (job.status === "done") {
        clearInterval(state.pollTimer);
        resetRun();
        fetchReport(job.report_id);
      } else if (job.status === "error") {
        clearInterval(state.pollTimer);
        showError("研究失败", job.error);
        resetRun();
      }
    } catch (e) {
      clearInterval(state.pollTimer);
      showError("连接中断", e.message);
      resetRun();
    }
  }, 1500);
}

function renderStages(job) {
  $("#stage-list").innerHTML = job.stages.map((s) => {
    const cls = s.done ? "done" : (s.key === job.stage ? "current" : "");
    return `<li class="${cls}">${esc(s.label)}</li>`;
  }).join("");
  $("#progress-hint").textContent = job.stage_detail || "";
}

function resetRun() {
  state.running = false;
  $("#run-btn").disabled = false;
  $("#run-btn").textContent = "开始研究";
}

function showError(title, detail) {
  $("#progress-panel").hidden = true;
  const p = $("#error-panel");
  p.innerHTML = `<h3>${esc(title)}</h3><p>${esc(detail || "")}</p>`;
  p.hidden = false;
}

/* ---------- 报告渲染 ---------- */
async function fetchReport(id) {
  try {
    const rep = await (await fetch(`/api/reports/${id}`)).json();
    renderReport(rep);
    loadHistory();
  } catch (e) {
    showError("报告加载失败", e.message);
  }
}

function renderReport(rep) {
  $("#progress-panel").hidden = true;
  $("#error-panel").hidden = true;
  $("#empty-state").hidden = true;
  const el = $("#report");
  el.innerHTML = buildReportHTML(rep);
  el.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function buildReportHTML(rep) {
  const t = rep.ticker || {};
  const syn = rep.synthesis;
  const ind = rep.indicators || {};
  const fg = rep.fear_greed;
  const dv = rep.derivatives;
  const bias = syn ? syn.bias : null;
  const biasCls = bias ? `bias-${bias}` : "";
  const price = t.last ?? ind.last_close;

  const parts = [];

  /* 头部 */
  parts.push(`
    <div class="rep-head">
      <span class="rep-symbol">${esc(rep.symbol)}</span>
      <span class="rep-price num">${fmtNum(price)}</span>
      <span class="rep-change num ${pctClass(t.change_pct_24h)}">${fmtPct(t.change_pct_24h)} / 24h</span>
      ${bias ? `<span class="bias-badge ${biasCls}">${esc(bias)}</span>` : ""}
      <span class="rep-meta">${timeLabel(rep.generated_at)} · 置信 ${syn ? syn.confidence : "—"}/100</span>
    </div>`);

  if (rep.question) {
    parts.push(`<p class="rep-question"><b>关注问题：</b>${esc(rep.question)}</p>`);
  }

  /* 结论 */
  if (syn) {
    parts.push(`<h2 class="headline">${esc(syn.headline)}</h2>
      <p class="synth-summary">${esc(syn.summary)}</p>`);
  } else {
    parts.push(`<h2 class="headline">数据简报</h2>
      <p class="synth-summary">未配置 LLM 或模型分析失败，以下为程序计算的客观数据摘要。</p>`);
  }

  /* 四维罗盘 + 读数 */
  const roles = Object.entries(rep.roles || {});
  if (roles.length) {
    const cells = roles.map(([name, r]) => {
      const b = (r.bullish || []).length, s = (r.bearish || []).length;
      const bar = b + s
        ? `<div class="balance"><div class="b-up" style="width:${(b / (b + s)) * 100}%"></div><div class="b-down"></div></div>`
        : `<div class="balance"><div class="b-none"></div></div>`;
      return `<div class="compass-cell">
        <div class="c-dim">${esc(name)}</div>
        <div class="c-conf">${r.confidence ?? "—"}<small> /100</small></div>
        ${bar}
        <div class="c-counts">多 ${b} · 空 ${s}</div>
      </div>`;
    }).join("");
    const center = bias ? `<div class="compass-center ${biasCls}">${BIAS_TEXT[bias] || "？"}</div>` : "";
    const readings = [
      ["趋势", esc(ind.trend_label || "—")],
      ["RSI · 日线", ind.rsi14 != null ? Number(ind.rsi14).toFixed(1) : "—"],
      ["恐贪指数", fg ? `${fg.current.value} · ${esc(fg.current.label)}` : "—"],
      ["资金费率 8h", dv && dv.funding_current_pct != null ? `${dv.funding_current_pct.toFixed(4)}%` : "—"],
      ["30日年化波动", ind.realized_vol_30d_annualized_pct != null ? `${ind.realized_vol_30d_annualized_pct.toFixed(0)}%` : "—"],
      ["ATR 占比", ind.atr_pct != null ? `${ind.atr_pct.toFixed(2)}%` : "—"],
    ].map(([l, v]) => `<div class="reading"><div class="r-label">${l}</div><div class="r-value">${v}</div></div>`).join("");
    parts.push(`
      <div class="compass-wrap">
        <div>
          <div class="compass">${cells}${center}</div>
          <p class="compass-note">罗盘：每格一维——数字为信号明确度，色条为多空因素对比（红=多，绿=空）</p>
        </div>
        <div class="readings">${readings}</div>
      </div>`);
  }

  /* 操作参考 */
  if (syn && syn.plan) {
    const p = syn.plan;
    const tp = Array.isArray(p.take_profit) ? p.take_profit : [p.take_profit];
    const er = Array.isArray(p.entry_range) ? p.entry_range : null;
    parts.push(`
      <div class="section-title">操作参考（模型给出，非投资建议）</div>
      <div class="plan-strip">
        <div class="plan-cell"><div class="p-label">入场区间</div>
          <div class="p-value">${er ? `${fmtNum(er[0])} – ${fmtNum(er[1])}` : "—"}</div></div>
        <div class="plan-cell"><div class="p-label">止损</div>
          <div class="p-value down">${fmtNum(p.stop_loss)}</div></div>
        <div class="plan-cell"><div class="p-label">目标</div>
          <div class="p-value up">${tp.filter((x) => x != null).map((x) => fmtNum(x)).join(" → ") || "—"}</div></div>
        <div class="plan-cell"><div class="p-label">仓位建议</div>
          <div class="p-value text">${esc(p.position_advice || "—")}</div></div>
        <div class="plan-cell plan-invalidation"><div class="p-label">失效条件</div>
          <div class="p-value text">${esc(p.invalidation || "—")}</div></div>
      </div>`);
  }

  /* 情景 */
  if (syn && syn.scenarios) {
    const sc = syn.scenarios;
    parts.push(`
      <div class="section-title">情景推演</div>
      <div class="scenarios">
        <div class="scenario sc-bull"><h4>乐观</h4><p>${esc(sc.bull)}</p></div>
        <div class="scenario sc-base"><h4>中性</h4><p>${esc(sc.base)}</p></div>
        <div class="scenario sc-bear"><h4>悲观</h4><p>${esc(sc.bear)}</p></div>
      </div>`);
  }

  /* 关键风险 */
  if (syn && syn.key_risks && syn.key_risks.length) {
    parts.push(`<div class="section-title">关键风险</div>
      <ul class="risks">${syn.key_risks.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>`);
  }

  /* 四维详情 */
  if (roles.length) {
    parts.push(`<div class="section-title">四维分析详情</div><div class="role-grid">`);
    for (const [name, r] of roles) {
      const bull = (r.bullish || []).length
        ? `<ul class="factors f-up">${r.bullish.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
        : `<p class="f-none">无明确看多因素</p>`;
      const bear = (r.bearish || []).length
        ? `<ul class="factors f-down">${r.bearish.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
        : `<p class="f-none">无明确看空因素</p>`;
      parts.push(`<div class="role-card">
        <h3>${esc(name)}</h3>
        <div class="role-conf">信号明确度 ${r.confidence ?? "—"}/100</div>
        <p>${esc(r.summary)}</p>
        ${bull}${bear}
      </div>`);
    }
    parts.push(`</div>`);
  }

  /* 支撑阻力 */
  if (ind.levels && (ind.levels.supports?.length || ind.levels.resistances?.length)) {
    parts.push(`<div class="section-title">关键位（日线摆动点）</div>
      <div class="readings">
        <div class="reading"><div class="r-label">阻力</div>
          <div class="r-value up">${ind.levels.resistances.map((x) => fmtNum(x)).join(" / ") || "—"}</div></div>
        <div class="reading"><div class="r-label">支撑</div>
          <div class="r-value down">${ind.levels.supports.map((x) => fmtNum(x)).join(" / ") || "—"}</div></div>
      </div>`);
  }

  /* 新闻 */
  if (rep.news && rep.news.items && rep.news.items.length) {
    parts.push(`<details class="news"><summary>参考新闻标题（${rep.news.items.length} 条 · ${esc(rep.news.source)}）</summary>
      <ul>${rep.news.items.map((n) => `<li>${esc(n.title)} <span class="h-date">${esc(n.published)}</span></li>`).join("")}</ul>
    </details>`);
  }

  /* 数据状态 + 免责 */
  const ds = Object.entries(rep.data_status || {}).map(([k, v]) =>
    `<span class="status-chip ${String(v).startsWith("ok") ? "ok" : "bad"}">${k}: ${esc(v)}</span>`).join("");
  parts.push(`<div class="section-title">数据源状态</div><div class="status-row">${ds}</div>
    <p class="disclaimer">${esc(rep.disclaimer)}</p>`);

  return parts.join("\n");
}

/* ---------- 事件绑定 ---------- */
$("#run-btn").addEventListener("click", startResearch);
$("#symbol-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") startResearch();
});
document.querySelectorAll("#symbol-chips button").forEach((b) =>
  b.addEventListener("click", () => {
    $("#symbol-input").value = b.dataset.sym;
    document.querySelectorAll("#symbol-chips button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
  }));

loadStatus();
loadHistory();
