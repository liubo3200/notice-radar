const $ = (s) => document.querySelector(s);
const input = $("#input");
const runBtn = $("#run");
const content = $("#content");
const empty = $("#empty");
const engineTag = $("#engineTag");

let SAMPLES = {};
let last = null;

const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

/* ---------------- 知识库状态 ---------------- */
fetch("/api/health")
  .then((r) => r.json())
  .then((d) => {
    const el = document.getElementById("kbLine");
    if (el && d.kb_slices) {
      el.textContent = `知识库已加载 ${d.kb_files.length} 份文件 / ${d.kb_slices} 条条款切片`;
    }
  })
  .catch(() => {});

/* ---------------- 示例 ---------------- */
fetch("/api/samples")
  .then((r) => r.json())
  .then((data) => {
    SAMPLES = data;
    // 演示用：?demo=竞赛 自动填充并解析
    const key = new URLSearchParams(location.search).get("demo");
    if (key && SAMPLES[key]) {
      input.value = SAMPLES[key];
      run();
    }
  })
  .catch(() => {});

document.querySelectorAll(".chip").forEach((btn) => {
  btn.addEventListener("click", () => {
    const key = btn.dataset.key;
    if (SAMPLES[key]) input.value = SAMPLES[key];
    input.focus();
  });
});

$("#clear").addEventListener("click", () => {
  input.value = "";
  content.classList.add("hidden");
  empty.classList.remove("hidden");
  engineTag.className = "engine";
  engineTag.textContent = "待解析";
  input.focus();
});

/* ---------------- 解析 ---------------- */
runBtn.addEventListener("click", run);

async function run() {
  const text = input.value.trim();
  if (!text) { input.focus(); return; }

  const t = runBtn.querySelector(".btn-txt");
  runBtn.disabled = true;
  t.textContent = "三个 Agent 处理中…";

  try {
    const res = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "解析失败");
    render(data);
    last = data;
  } catch (e) {
    empty.classList.add("hidden");
    content.classList.remove("hidden");
    content.innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  } finally {
    runBtn.disabled = false;
    t.textContent = "开始解析";
  }
}

/* ---------------- 渲染 ---------------- */
function render(data) {
  const f = data.fields || {};
  const ev = data.evaluation || {};
  const ck = data.check || {};
  const cr = data.critic || { verdict: "pass", issues: [], rounds: 1 };

  empty.classList.add("hidden");
  content.classList.remove("hidden");

  engineTag.className = "engine " + (f.fallback ? "fallback" : "live");
  engineTag.textContent = data.engine;

  // 倒计时：有报名截止看截止，只有举办时间就看举办
  const dLeft = f.days_left;
  const dEvent = f.days_to_event;
  let num, unit, color;
  if (dLeft == null && dEvent != null) {
    if (dEvent < 0) { num = "0"; unit = "已举办"; color = "#8ba0bf"; }
    else { num = dEvent; unit = "天后举办"; color = dEvent <= 1 ? "#fbbf24" : "#22d3ee"; }
  } else if (dLeft == null) { num = "?"; unit = "无日期"; color = "#8ba0bf"; }
  else if (dLeft < 0) { num = "0"; unit = "已截止"; color = "#f87171"; }
  else if (dLeft === 0) { num = "今天"; unit = "截止"; color = "#f87171"; }
  else { num = dLeft; unit = "天后截止"; color = dLeft <= 3 ? "#fbbf24" : "#22d3ee"; }
  const dateTxt = f.deadline || f.event_date || "";

  const vClass = ev.worth === "强烈建议" ? "good" : (ev.worth === "可以考虑" || ev.worth === "待核实") ? "mid" : "bad";

  // 多个截止节点：只报一个会误导，全部列出来
  const dls = f.deadlines || [];
  const dlHtml = dls.length >= 2
    ? `<div class="dl-list">${dls.map((x) =>
        `<span class="dl-item${x.date === f.deadline ? " primary" : ""}">${esc(x.label)} ${esc(x.date)}</span>`
      ).join("")}</div>`
    : "";

  // 自审结果：拦截级红条，提示级黄条
  const errs = (cr.issues || []).filter((i) => i.level === "error");
  const warns = (cr.issues || []).filter((i) => i.level !== "error");
  const issueHtml = (list) => list.map((i) =>
    `<div class="cb-item">${esc(i.message)}${i.fix ? `<span class="cb-fix"> → ${esc(i.fix)}</span>` : ""}</div>`
  ).join("");
  const criticHtml = (cr.issues || []).length
    ? `<div class="critic-bar ${errs.length ? "error" : "warn"}">
         <div class="cb-head">
           <span>${errs.length ? "自审拦截 · 已打回重跑" : "自审提示"}</span>
           <span class="cb-rounds">${cr.rounds} 轮</span>
         </div>
         ${issueHtml(errs)}${issueHtml(warns)}
       </div>`
    : "";

  // 条款依据
  const basis = ev.basis || [];
  const basisHtml = basis.length
    ? `<div class="basis">
         <div class="section-title">判断依据 · 引用条款</div>
         ${basis.map((b) =>
           `<div class="basis-item">
              <div class="basis-src">${esc(b.source)}</div>
              <div class="basis-txt">${esc(b.excerpt)}</div>
            </div>`).join("")}
       </div>`
    : `<div class="no-basis">知识库未收录对应条款，本节未引用任何规定。</div>`;

  // 匹配度环
  const R = 26, C = 2 * Math.PI * R;
  const dash = ((ev.score || 0) / 100) * C;

  content.innerHTML = `
    <div class="tag-row">
      <span class="tag cat">${esc(f.category || "其他")}</span>
      <span class="tag">${esc(f.organizer || "主办未识别")}</span>
      <span class="tag max">${esc(f.target || "对象未识别")}</span>
    </div>

    <div class="event-name">${esc(f.event_name || "未识别到标题")}</div>

    <div class="countdown-row">
      <span class="countdown-num" style="color:${color}">${num}</span>
      <span class="countdown-unit">${unit}</span>
      <span class="countdown-date">${esc(dateTxt)}</span>
    </div>
    ${dlHtml}

    ${criticHtml}

    <div class="verdict ${vClass}">
      <div class="verdict-txt">
        <div class="verdict-label">${esc(ev.worth)}</div>
        <div class="verdict-sum">${esc(ev.summary)}</div>
      </div>
      <div class="ring">
        <svg width="62" height="62">
          <circle cx="31" cy="31" r="${R}" fill="none" stroke="rgba(120,180,255,.12)" stroke-width="5"/>
          <circle cx="31" cy="31" r="${R}" fill="none"
            stroke="${ev.score >= 70 ? "#34d399" : ev.score >= 50 ? "#fbbf24" : "#f87171"}"
            stroke-width="5" stroke-linecap="round"
            stroke-dasharray="${dash} ${C}"/>
        </svg>
        <div class="ring-num">${ev.score}<small>匹配度</small></div>
      </div>
    </div>

    ${(ev.reasons || []).length ? `
    <div class="section">
      <div class="section-title">为什么是这个判断</div>
      <ul>${ev.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    </div>` : ""}

    ${basisHtml}

    ${(ev.risks || []).length ? `
    <div class="section warn">
      <div class="section-title">要注意</div>
      <ul>${ev.risks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    </div>` : ""}

    <div class="section act">
      <div class="section-title">接下来做什么</div>
      <ul>${ev.actions.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    </div>

    <div class="footer-row">
      <button class="btn-ics" id="dl">下载日历事件（.ics）</button>
      <span class="conf">置信度 ${esc(ck.confidence)} · 完整度 ${Math.round((ck.completeness || 0) * 100)}%</span>
    </div>

    ${(ck.warnings || []).length ? `<div class="warn-box">${ck.warnings.map(esc).join("<br>")}</div>` : ""}
  `;

  $("#dl").addEventListener("click", () => downloadICS(f, ev));
}

/* ---------------- 下载 ---------------- */
async function downloadICS(fields, evaluation) {
  try {
    const res = await fetch("/api/ics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields, evaluation }),
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      throw new Error(j.error || "生成失败");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "reminder.ics";
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert("日历生成失败：" + e.message);
  }
}
