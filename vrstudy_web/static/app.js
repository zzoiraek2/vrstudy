const state = {
  dashboard: null,
  vrProfiles: [],
  infiniteProfiles: [],
  selectedVr: "",
  selectedInfinite: "",
  profileCreateKind: "",
  vrDetail: null,
  vrOrderPreview: null,
  vrOrderResult: null,
  infiniteDetail: null,
  infiniteExecutionPreview: null,
  infiniteOrderResult: null,
  dashboardCharts: {
    vrProfile: "",
    infiniteProfile: "",
    instances: {},
    echartsPromise: null,
  },
};

const ECHARTS_SRC = "/vendor/echarts/echarts.min.js?v=20260707";

const loginView = document.getElementById("login-view");
const appView = document.getElementById("app-view");
const loginForm = document.getElementById("login-form");
const loginMessage = document.getElementById("login-message");
const logoutButton = document.getElementById("logout-button");

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    let message = "요청을 처리하지 못했습니다.";
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Keep the default message.
    }
    throw new Error(message);
  }
  return response.json();
}

function setVisible(view) {
  loginView.hidden = view !== "login";
  appView.hidden = view !== "app";
}

function arrangeDashboardLayout() {
  const grid = document.querySelector("#dashboard-tab .dashboard-grid");
  const charts = document.querySelector("#dashboard-tab .dashboard-charts");
  const details = document.querySelector("#dashboard-tab .dashboard-details");
  const duePanel = document.getElementById("dashboard-due-items")?.closest(".panel");
  if (!grid || !charts || !details || !duePanel || charts.parentElement === grid) return;
  duePanel.after(charts);
  charts.after(details);
}

function text(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value ?? "";
}

function number(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "-";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return parsed.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function pct(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${number(Number(value) * 100, 2)}%`;
}

function won(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${number(value, 0)}원`;
}

function renderEmpty(tbody, colspan) {
  tbody.innerHTML = "";
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.className = "empty";
  cell.colSpan = colspan;
  cell.textContent = "데이터가 없습니다.";
  row.appendChild(cell);
  tbody.appendChild(row);
}

function appendCells(row, values) {
  values.forEach((value) => {
    const cell = document.createElement("td");
    cell.textContent = value === 0 ? "0" : value || "-";
    row.appendChild(cell);
  });
}

function rows(tbodyId, rowsData, colspan, mapper, options = {}) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  if (!rowsData.length) {
    renderEmpty(tbody, colspan);
    return;
  }
  tbody.innerHTML = "";
  rowsData.forEach((item) => {
    const row = document.createElement("tr");
    appendCells(row, mapper(item));
    if (options.rowClass) row.classList.add(options.rowClass);
    if (options.title) row.title = options.title(item) || "";
    if (options.onDblClick) {
      row.addEventListener("dblclick", () => options.onDblClick(item));
    }
    tbody.appendChild(row);
  });
}

function activateMainTab(tabId) {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tabId);
  });
  document.querySelectorAll(".tab-page").forEach((page) => {
    page.classList.toggle("active", page.id === tabId);
  });
  if (tabId === "dashboard-tab") {
    refreshDashboardCharts();
  }
}

function activateInnerPanel(panelId) {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  const group = panel.closest(".strategy-layout")?.querySelector(".inner-tabs");
  if (group) {
    group.querySelectorAll(".inner-tab").forEach((button) => {
      button.classList.toggle("active", button.dataset.panel === panelId);
    });
  }
  const leftPane = panel.closest(".left-pane");
  if (leftPane) {
    leftPane.querySelectorAll(".inner-panel").forEach((item) => {
      item.classList.toggle("active", item.id === panelId);
    });
  }
}

function focusFormField(formSelector, fieldName) {
  const form = document.querySelector(formSelector);
  const field = form?.elements?.[fieldName];
  if (!field) return;
  field.focus();
  if (typeof field.select === "function") field.select();
}

function renderInfiniteOrderPlan(plan) {
  const info = document.getElementById("infinite-order-info");
  if (info) {
    const title = plan?.title || "-";
    const perBuy = plan?.per_buy_amount ? ` / 1회매수금 ${number(plan.per_buy_amount)}` : "";
    info.textContent = `${title}${perBuy}`;
  }
  rows("infinite-buy-order-table", plan?.buy || [], 3, (row) => [
    row.order_type,
    row.price === null || row.price === undefined ? "-" : number(row.price),
    number(row.quantity, 0),
  ]);
  rows("infinite-sell-order-table", plan?.sell || [], 3, (row) => [
    row.order_type,
    row.price === null || row.price === undefined ? "-" : number(row.price),
    number(row.quantity, 0),
  ]);
}

function renderVrOrderLevels(orderLevels) {
  const isBuy = (row) => ["BUY", "buy"].includes(String(row.side || ""));
  const isSell = (row) => ["SELL", "sell"].includes(String(row.side || ""));
  const quantity = (row) => row.quantity ?? row.quantity_step;
  const buyRows = (orderLevels || []).filter(isBuy);
  const sellRows = (orderLevels || []).filter(isSell);
  rows("vr-buy-order-levels", buyRows, 3, (row) => [
    row.level_no,
    number(row.price),
    number(quantity(row), 0),
  ]);
  rows("vr-sell-order-levels", sellRows, 3, (row) => [
    row.level_no,
    number(row.price),
    number(quantity(row), 0),
  ]);
}

function renderVrFillHistory(fills) {
  rows("vr-fill-history", fills || [], 5, (row) => [
    row.display_date || row.date,
    row.side_label,
    number(row.price),
    number(row.quantity, 0),
    number(row.amount),
  ]);
}

function renderVrPeriodPreview(preview) {
  renderFields("vr-api-period-preview", preview || {}, [
    ["매도수량 합계", "sell_qty", (v) => number(v, 0)],
    ["매도액 USD", "sell_amount"],
    ["매수수량 합계", "buy_qty", (v) => number(v, 0)],
    ["매수액 USD", "buy_amount"],
    ["현재 보유개수", "holding_qty", (v) => number(v, 0)],
    ["기간말 추정보유개수", "period_end_holding_qty", (v) => number(v, 0)],
  ]);
}

function renderFields(containerId, data, fields) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";
  fields.forEach(([label, key, formatter]) => {
    const item = document.createElement("div");
    item.className = "readonly-field";
    const caption = document.createElement("span");
    caption.textContent = label;
    const value = document.createElement("strong");
    value.textContent = formatter ? formatter(data?.[key]) : data?.[key] ?? "-";
    item.append(caption, value);
    container.appendChild(item);
  });
}

function settingValue(data, key, formatter) {
  const value = data?.[key];
  if (formatter) return formatter(value);
  return value ?? "";
}

function percentInput(value) {
  if (value === null || value === undefined || value === "") return "";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return `${Number((parsed * 100).toFixed(6))}%`;
}

function parseInputValue(value, kind) {
  const text = String(value ?? "").trim();
  if (kind === "int") return Number.parseInt(text || "0", 10);
  if (kind === "float") return Number(text || "0");
  if (kind === "percent") {
    if (text.endsWith("%")) return Number(text.slice(0, -1).trim() || "0") / 100;
    return Number(text || "0");
  }
  return text;
}

function renderSettingsForm(containerId, data, fields, onSubmit) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";
  const form = document.createElement("form");
  form.className = "settings-form one-col embedded-settings-form";
  fields.forEach((field) => {
    const label = document.createElement("label");
    const caption = document.createElement("span");
    caption.textContent = field.label;
    let input;
    if (field.options) {
      input = document.createElement("select");
      field.options.forEach((optionValue) => {
        const option = document.createElement("option");
        option.value = optionValue;
        option.textContent = optionValue;
        input.appendChild(option);
      });
    } else {
      input = document.createElement("input");
      input.type = "text";
    }
    input.name = field.name;
    input.value = settingValue(data, field.name, field.formatter);
    label.append(caption, input);
    form.appendChild(label);
  });
  const actions = document.createElement("div");
  actions.className = "form-actions";
  const saveButton = document.createElement("button");
  saveButton.type = "submit";
  saveButton.textContent = "설정 저장/재계산";
  const message = document.createElement("p");
  message.className = "message muted-message";
  actions.appendChild(saveButton);
  form.append(actions, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {};
    fields.forEach((field) => {
      payload[field.name] = parseInputValue(form.elements[field.name].value, field.kind);
    });
    try {
      message.textContent = "저장 중...";
      await onSubmit(payload);
      message.textContent = "설정 저장/재계산 완료";
    } catch (error) {
      message.textContent = error.message;
    }
  });
  form.addEventListener("input", updateInfiniteOrderButtons);
  container.appendChild(form);
}

function renderInfiniteExecutionForm(data, onSubmit) {
  const container = document.getElementById("infinite-execution-preview");
  if (!container) return;
  const fields = [
    { name: "trade_date", label: "입력일" },
    { name: "avg_price", label: "평균단가", kind: "float" },
    { name: "buy_qty", label: "매수개수", kind: "int" },
    { name: "sell_qty", label: "매도개수", kind: "int" },
    { name: "cash_flow_amount", label: "입출금액 (+입금, -출금)", kind: "float" },
  ];
  container.innerHTML = "";
  const form = document.createElement("form");
  form.className = "settings-form one-col embedded-settings-form";
  fields.forEach((field) => {
    const label = document.createElement("label");
    const caption = document.createElement("span");
    const input = document.createElement("input");
    caption.textContent = field.label;
    input.name = field.name;
    input.type = "text";
    input.value = data?.[field.name] ?? "";
    label.append(caption, input);
    form.appendChild(label);
  });
  const actions = document.createElement("div");
  actions.className = "form-actions";
  const saveButton = document.createElement("button");
  saveButton.type = "submit";
  saveButton.textContent = "체결 저장하고 주문표 보기";
  saveButton.disabled = !data?.allowed;
  const message = document.createElement("p");
  message.className = "message muted-message";
  if (!data?.allowed) {
    message.textContent = "저장 가능한 입력일이 아닙니다.";
  }
  actions.appendChild(saveButton);
  form.append(actions, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {};
    fields.forEach((field) => {
      payload[field.name] = parseInputValue(form.elements[field.name].value, field.kind);
    });
    try {
      message.textContent = "저장 중...";
      await onSubmit(payload);
      message.textContent = "체결 저장 완료";
    } catch (error) {
      message.textContent = error.message;
    }
  });
  container.appendChild(form);
}

function renderVrCycleInputForm(data, onSubmit) {
  const container = document.getElementById("vr-latest-input");
  if (!container) return;
  const fields = [
    { name: "cycle_no", label: "차수", kind: "int" },
    { name: "week_no", label: "주차", readonly: true },
    { name: "result_period", label: "결과구간", readonly: true },
    { name: "next_period", label: "다음 주문구간", readonly: true },
    { name: "close_price", label: "종가" },
    { name: "trade_amount", label: "매매액", kind: "float" },
    { name: "shares", label: "보유수량", kind: "int" },
    { name: "dividend", label: "배당", kind: "float" },
    { name: "contribution_amount", label: "입금액", kind: "float" },
    { name: "g_config", label: "G 조건" },
    { name: "g_start_cycle_no", label: "G 기준주차", kind: "int" },
    { name: "buy_limit_config", label: "매수한도 조건" },
    { name: "buy_limit_start_week_no", label: "매수한도 시작주차", kind: "int" },
  ];
  container.innerHTML = "";
  const form = document.createElement("form");
  form.className = "settings-form one-col embedded-settings-form";
  fields.forEach((field) => {
    const label = document.createElement("label");
    const caption = document.createElement("span");
    const input = document.createElement("input");
    caption.textContent = field.label;
    input.name = field.name;
    input.type = "text";
    input.value = data?.[field.name] ?? "";
    if (field.readonly) input.readOnly = true;
    label.append(caption, input);
    form.appendChild(label);
  });
  const actions = document.createElement("div");
  actions.className = "form-actions";
  const saveButton = document.createElement("button");
  saveButton.type = "submit";
  const isRecalculate = data?.mode === "recalculate";
  const profilePaused = Boolean(state.vrDetail?.profile?.calculation_paused);
  const canSubmit = isRecalculate ? !profilePaused : Boolean(data?.allowed);
  saveButton.textContent = isRecalculate ? "수정값 저장/재계산" : "저장하고 다음 주차 매수/매도점 보기";
  saveButton.disabled = !canSubmit;
  actions.appendChild(saveButton);
  form.appendChild(actions);
  if (profilePaused) {
    text("vr-cycle-message", "산출 중단 상태에서는 저장/재계산할 수 없습니다.");
  } else if (isRecalculate) {
    text("vr-cycle-message", `${data?.cycle_no ?? ""}차수 수정값 재계산 가능`);
  } else if (!data?.allowed) {
    text("vr-cycle-message", data?.available_date ? `${data.available_date}부터 입력 가능합니다.` : "저장 가능한 입력일이 아닙니다.");
  } else {
    text("vr-cycle-message", "입력 가능");
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {};
    fields.forEach((field) => {
      if (field.readonly) return;
      payload[field.name] = parseInputValue(form.elements[field.name].value, field.kind);
    });
    try {
      text("vr-cycle-message", "저장 중...");
      await onSubmit(payload);
      text("vr-cycle-message", "저장/재계산 완료");
    } catch (error) {
      text("vr-cycle-message", error.message);
    }
  });
  container.appendChild(form);
}

function setSelectOptions(selectId, profiles, selected) {
  const select = document.getElementById(selectId);
  select.innerHTML = "";
  profiles.forEach((profile) => {
    const option = document.createElement("option");
    option.value = profile.name;
    option.textContent = profile.name;
    select.appendChild(option);
  });
  if (profiles.some((profile) => profile.name === selected)) {
    select.value = selected;
  } else if (profiles[0]) {
    select.value = profiles[0].name;
  }
  return select.value;
}

function setFormValues(form, values) {
  for (const element of form.elements) {
    if (!element.name) continue;
    if (element.type === "checkbox") {
      element.checked = Boolean(values[element.name]);
    } else {
      element.value = values[element.name] ?? "";
    }
  }
}

function formValues(form) {
  const values = {};
  for (const element of form.elements) {
    if (!element.name) continue;
    if (element.type === "checkbox") values[element.name] = element.checked;
    else if (element.type === "number") values[element.name] = Number(element.value || 0);
    else values[element.name] = element.value;
  }
  return values;
}

function currentProfile(kind) {
  return kind === "vr" ? state.selectedVr : state.selectedInfinite;
}

function currentDetail(kind) {
  return kind === "vr" ? state.vrDetail : state.infiniteDetail;
}

function profileLabel(kind) {
  return kind === "vr" ? "VR" : "무한매수법";
}

function updateProfileActionButtons(kind) {
  const profile = currentProfile(kind);
  const detail = currentDetail(kind);
  const profileData = detail?.profile || {};
  ["rename", "delete", "current", "pause"].forEach((action) => {
    const button = document.getElementById(`${action}-${kind}`);
    if (button) button.disabled = !profile;
  });
  const pauseButton = document.getElementById(`pause-${kind}`);
  if (pauseButton) {
    pauseButton.textContent = profileData.calculation_paused ? "산출 재개" : "산출 중단";
  }
}

function markTableRow(tbodyId, index) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  tbody.querySelectorAll("tr").forEach((row) => row.classList.remove("selected-data-row"));
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const target = rows[Math.max(0, index)] || rows[0];
  if (!target) return;
  target.classList.add("selected-data-row");
  target.scrollIntoView({ block: "center", behavior: "smooth" });
}

function gotoCurrentProfileRow(kind) {
  if (kind === "vr") {
    const targetCycle = state.vrDetail?.cycle_input?.cycle_no;
    const rowsData = visibleVrSnapshots(state.vrDetail);
    const index = rowsData.findIndex((row) => Number(row.cycle_no) === Number(targetCycle));
    markTableRow("vr-snapshots", index >= 0 ? index : 0);
    return;
  }
  const targetDate = state.infiniteDetail?.execution_input?.trade_date;
  const rowsData = visibleInfiniteRows(state.infiniteDetail);
  const index = rowsData.findIndex((row) => String(row.trade_date) === String(targetDate));
  markTableRow("infinite-rows", index >= 0 ? index : 0);
}

async function openDueItem(item) {
  const strategy = item.strategy || (item.kind === "VR" ? "vr" : "infinite");
  const profileName = item.profile_name;
  if (!profileName) return;

  if (strategy === "vr") {
    activateMainTab("vr-tab");
    await loadVrDetail(profileName);
    await loadKiwoomForm("vr");
    activateInnerPanel("vr-cycle-panel");
    const targetCycle = item.target_cycle_no ?? state.vrDetail?.cycle_input?.cycle_no;
    const rowsData = visibleVrSnapshots(state.vrDetail);
    const index = rowsData.findIndex((row) => Number(row.cycle_no) === Number(targetCycle));
    markTableRow("vr-snapshots", index >= 0 ? index : 0);
    text("vr-cycle-message", targetCycle === undefined || targetCycle === null
      ? "입력이 필요한 주차로 이동했습니다."
      : `${targetCycle}차수 입력이 필요합니다.`);
    focusFormField("#vr-latest-input form", "close_price");
    return;
  }

  activateMainTab("infinite-tab");
  await loadInfiniteDetail(profileName);
  await loadKiwoomForm("infinite");
  activateInnerPanel("infinite-execution-panel");
  const targetDate = item.target_trade_date || state.infiniteDetail?.execution_input?.trade_date;
  const rowsData = visibleInfiniteRows(state.infiniteDetail);
  const index = rowsData.findIndex((row) => String(row.trade_date) === String(targetDate));
  markTableRow("infinite-rows", index >= 0 ? index : 0);
  text("infinite-execution-message", targetDate
    ? `${targetDate} 체결 입력이 필요합니다.`
    : "입력이 필요한 날짜로 이동했습니다.");
  focusFormField("#infinite-execution-preview form", "avg_price");
}

async function renameProfile(kind) {
  const profile = currentProfile(kind);
  if (!profile) return;
  const newName = window.prompt(`${profileLabel(kind)} 프로필 새 이름`, profile);
  if (!newName || !newName.trim() || newName.trim() === profile) return;
  try {
    await api(`/api/${kind}/profiles/${encodeURIComponent(profile)}/rename`, {
      method: "PATCH",
      body: JSON.stringify({ new_name: newName.trim() }),
    });
    if (kind === "vr") state.selectedVr = newName.trim();
    else state.selectedInfinite = newName.trim();
    await loadDashboard();
  } catch (error) {
    window.alert(error.message);
  }
}

async function deleteSelectedProfile(kind) {
  const profile = currentProfile(kind);
  if (!profile) return;
  const confirmed = window.confirm(
    `${profileLabel(kind)} 프로필 '${profile}'을 삭제할까요?\n\n저장 데이터, API 키, 토큰 캐시도 함께 정리됩니다.`
  );
  if (!confirmed) return;
  try {
    await api(`/api/${kind}/profiles/${encodeURIComponent(profile)}`, {
      method: "DELETE",
    });
    if (kind === "vr") state.selectedVr = "";
    else state.selectedInfinite = "";
    await loadDashboard();
  } catch (error) {
    window.alert(error.message);
  }
}

async function toggleProfilePause(kind) {
  const profile = currentProfile(kind);
  if (!profile) return;
  try {
    const result = await api(`/api/${kind}/profiles/${encodeURIComponent(profile)}/toggle-pause`, {
      method: "POST",
      body: "{}",
    });
    if (kind === "vr") {
      state.vrDetail = { ...(state.vrDetail || {}), profile: result.profile };
    } else {
      state.infiniteDetail = { ...(state.infiniteDetail || {}), profile: result.profile };
    }
    await loadDashboard();
  } catch (error) {
    window.alert(error.message);
  }
}

function formForKind(kind) {
  return document.getElementById(`${kind}-api-form`);
}

function messageIdForKind(kind) {
  return `${kind}-api-message`;
}

function chartValue(value) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function infiniteChartPoint(row) {
  const principal = chartValue(row.principal_after_withdrawal);
  const invested = chartValue(row.cumulative_amount);
  const marketValue = chartValue(row.cumulative_qty) * chartValue(row.close_price || row.avg_price);
  const cash = Math.max(principal - invested, 0);
  const totalAsset = marketValue + cash;
  const profit = totalAsset - principal;
  const returnRate = principal ? profit / principal : 0;
  return { principal, invested, marketValue, cash, totalAsset, profit, returnRate };
}

function markChartBoxes(message) {
  [
    "dashboard-vr-band-chart",
    "dashboard-vr-profit-chart",
    "dashboard-infinite-asset-chart",
    "dashboard-infinite-profit-chart",
  ].forEach((id) => {
    const element = document.getElementById(id);
    if (!element || element.children.length) return;
    element.classList.add("chart-empty");
    element.textContent = message;
  });
}

function ensureEcharts() {
  if (window.echarts) return Promise.resolve(window.echarts);
  if (state.dashboardCharts.echartsPromise) return state.dashboardCharts.echartsPromise;
  markChartBoxes("ECharts 로딩 중");
  state.dashboardCharts.echartsPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `${ECHARTS_SRC}&retry=${Date.now()}`;
    script.async = true;
    script.onload = () => {
      if (window.echarts) {
        resolve(window.echarts);
        return;
      }
      reject(new Error("ECharts가 로드되었지만 초기화되지 않았습니다."));
    };
    script.onerror = () => reject(new Error("ECharts 파일을 불러오지 못했습니다."));
    document.head.appendChild(script);
  }).catch((error) => {
    state.dashboardCharts.echartsPromise = null;
    markChartBoxes(error.message);
    throw error;
  });
  return state.dashboardCharts.echartsPromise;
}

function resizeDashboardCharts() {
  requestAnimationFrame(() => {
    Object.values(state.dashboardCharts.instances).forEach((chart) => chart.resize());
  });
  setTimeout(() => {
    Object.values(state.dashboardCharts.instances).forEach((chart) => chart.resize());
  }, 120);
  setTimeout(() => {
    Object.values(state.dashboardCharts.instances).forEach((chart) => chart.resize());
  }, 450);
}

function chartInstance(id) {
  const element = document.getElementById(id);
  if (!element || !window.echarts) {
    if (element) {
      element.classList.add("chart-empty");
      element.textContent = window.echarts ? "데이터 없음" : "ECharts 로딩 중";
    }
    return null;
  }
  const rect = element.getBoundingClientRect();
  if (rect.width < 10 || rect.height < 10) {
    element.classList.add("chart-empty");
    element.textContent = "차트 영역 준비 중";
    return null;
  }
  element.classList.remove("chart-empty");
  element.textContent = "";
  const current = state.dashboardCharts.instances[id];
  if (current && element.children.length === 0) {
    try {
      current.dispose();
    } catch {
      // Recreate below.
    }
    delete state.dashboardCharts.instances[id];
  }
  if (!state.dashboardCharts.instances[id]) {
    try {
      state.dashboardCharts.instances[id] = window.echarts.init(element, null, {
        renderer: "canvas",
        useDirtyRect: true,
      });
    } catch (error) {
      element.classList.add("chart-empty");
      element.textContent = `차트 초기화 실패: ${error.message}`;
      return null;
    }
  }
  return state.dashboardCharts.instances[id];
}

function commonChartOption(title, dates) {
  return {
    title: { text: title, left: 8, top: 4, textStyle: { fontSize: 13, fontWeight: 700 } },
    tooltip: { trigger: "axis", valueFormatter: (value) => number(value) },
    legend: { top: 28, type: "scroll", textStyle: { fontSize: 11 } },
    grid: { left: 54, right: 18, top: 68, bottom: 42 },
    xAxis: { type: "category", data: dates, axisLabel: { fontSize: 10 } },
    yAxis: { type: "value", axisLabel: { formatter: (value) => Number(value).toLocaleString() } },
  };
}

function renderDashboardVrCharts(data) {
  const rowsData = [...(data?.rows || [])].sort((left, right) => String(left.end_date).localeCompare(String(right.end_date)));
  text("dashboard-vr-chart-label", data?.label || "-");
  const dates = rowsData.map((row) => row.end_date);
  const bandChart = chartInstance("dashboard-vr-band-chart");
  const profitChart = chartInstance("dashboard-vr-profit-chart");
  if (!rowsData.length) return;
  if (bandChart) {
    const lowerBand = rowsData.map((row) => chartValue(row.min_value));
    const upperBand = rowsData.map((row) => chartValue(row.max_value));
    bandChart.setOption({
      ...commonChartOption("밴드와 자산", dates),
      legend: { top: 28, data: ["하단", "상단", "계좌총액", "평가금"], textStyle: { fontSize: 11 } },
      series: [
        { name: "밴드 하단", type: "line", data: lowerBand, stack: "band", lineStyle: { opacity: 0 }, symbol: "none", areaStyle: { opacity: 0 }, itemStyle: { opacity: 0 }, tooltip: { show: false } },
        { name: "밴드 영역", type: "line", data: upperBand.map((value, index) => value - lowerBand[index]), stack: "band", lineStyle: { opacity: 0 }, symbol: "none", areaStyle: { color: "rgba(79, 125, 243, 0.26)" }, itemStyle: { opacity: 0 }, tooltip: { show: false } },
        { name: "하단", type: "line", data: lowerBand, lineStyle: { type: "dashed", color: "#4f7df3" }, itemStyle: { color: "#4f7df3" } },
        { name: "상단", type: "line", data: upperBand, lineStyle: { type: "dashed", color: "#f0b429" }, itemStyle: { color: "#f0b429" } },
        { name: "계좌총액", type: "line", data: rowsData.map((row) => chartValue(row.account_total)), smooth: true, itemStyle: { color: "#2f9e44" } },
        { name: "평가금", type: "line", data: rowsData.map((row) => chartValue(row.valuation)), smooth: true, itemStyle: { color: "#e03131" } },
      ],
    });
  }
  if (profitChart) {
    profitChart.setOption({
      ...commonChartOption("원금/계좌총액/손익", dates),
      series: [
        { name: "원금", type: "line", data: rowsData.map((row) => chartValue(row.principal)), itemStyle: { color: "#555" } },
        { name: "계좌총액", type: "line", data: rowsData.map((row) => chartValue(row.account_total)), smooth: true, itemStyle: { color: "#2f9e44" } },
        { name: "손익", type: "bar", data: rowsData.map((row) => chartValue(row.profit)), itemStyle: { color: (item) => (item.value >= 0 ? "#36a269" : "#e03131") } },
      ],
    });
  }
}

function renderDashboardInfiniteCharts(data) {
  const rowsData = [...(data?.rows || [])].sort((left, right) => String(left.trade_date).localeCompare(String(right.trade_date)));
  text("dashboard-infinite-chart-label", data?.label || "-");
  const dates = rowsData.map((row) => row.trade_date);
  const assetChart = chartInstance("dashboard-infinite-asset-chart");
  const profitChart = chartInstance("dashboard-infinite-profit-chart");
  if (!rowsData.length) return;
  const points = rowsData.map(infiniteChartPoint);
  let stopLossTotal = 0;
  let feeTotal = 0;
  let cashFlowTotal = 0;
  const stopLosses = [];
  const fees = [];
  const cashFlows = [];
  const netProfits = [];
  rowsData.forEach((row) => {
    stopLossTotal += chartValue(row.stop_loss);
    feeTotal += chartValue(row.fee);
    cashFlowTotal += chartValue(row.cash_flow_amount);
    stopLosses.push(stopLossTotal);
    fees.push(feeTotal);
    cashFlows.push(cashFlowTotal);
    netProfits.push(stopLossTotal - feeTotal);
  });
  if (assetChart) {
    assetChart.setOption({
      ...commonChartOption("기준원금 대비 현재 총자산", dates),
      series: [
        { name: "기준원금", type: "line", data: points.map((point) => point.principal), itemStyle: { color: "#555" } },
        { name: "현재 총자산", type: "line", data: points.map((point) => point.totalAsset), smooth: true, itemStyle: { color: "#2f9e44" } },
        { name: "보유평가액", type: "line", data: points.map((point) => point.marketValue), smooth: true, lineStyle: { type: "dashed" }, itemStyle: { color: "#4f7df3" } },
        { name: "잔여현금", type: "line", data: points.map((point) => point.cash), lineStyle: { type: "dashed" }, itemStyle: { color: "#f08c00" } },
      ],
    });
  }
  if (profitChart) {
    profitChart.setOption({
      ...commonChartOption("누적손익 / 수익률", dates),
      tooltip: {
        trigger: "axis",
        valueFormatter: (value) => number(value),
      },
      yAxis: [
        { type: "value", name: "손익", axisLabel: { formatter: (value) => Number(value).toLocaleString() } },
        { type: "value", name: "수익률", axisLabel: { formatter: (value) => `${Number(value).toFixed(1)}%` } },
      ],
      series: [
        { name: "누적손익", type: "bar", data: points.map((point) => point.profit), itemStyle: { color: (item) => (item.value >= 0 ? "#36a269" : "#e03131") } },
        { name: "수익률", type: "line", yAxisIndex: 1, data: points.map((point) => point.returnRate * 100), smooth: true, itemStyle: { color: "#7c3aed" }, tooltip: { valueFormatter: (value) => `${number(value)}%` } },
        { name: "실현손익-수수료", type: "line", data: netProfits, lineStyle: { type: "dashed" }, itemStyle: { color: "#4f7df3" } },
        { name: "누적수수료", type: "line", data: fees, lineStyle: { type: "dashed" }, itemStyle: { color: "#e03131" } },
        { name: "누적입출금", type: "line", data: cashFlows, itemStyle: { color: "#f08c00" } },
      ],
    });
  }
}

function selectedDashboardVrProfile() {
  const profiles = state.dashboard?.vr_profile_rows || [];
  return profiles.find((profile) => profile.name === state.dashboardCharts.vrProfile) || profiles[0] || null;
}

function selectedDashboardInfiniteProfile() {
  const profiles = state.dashboard?.infinite_profile_rows || [];
  return profiles.find((profile) => profile.name === state.dashboardCharts.infiniteProfile) || profiles[0] || null;
}

function renderDashboardVrDetail(profile, chartData = null) {
  text("dashboard-vr-detail-label", profile?.label || "VR 표에서 프로필을 더블클릭");
  if (!profile) {
    rows("dashboard-vr-detail-rows", [["VR 선택", "VR 표에서 프로필을 더블클릭"]], 2, (row) => row);
    return;
  }
  const chartRows = [...(chartData?.rows || [])].sort((left, right) =>
    String(left.end_date || left.start_date || "").localeCompare(String(right.end_date || right.start_date || "")),
  );
  const latest = chartRows.length ? chartRows[chartRows.length - 1] : null;
  const detailRows = [
    ["VR 선택", profile.label],
    ["계좌총액", number(profile.account_total)],
    ["손익 / 수익률", `${number(profile.profit)} / ${pct(profile.return_rate)}`],
    ["완료주차 / 미입력", `${profile.last_done_text || "-"} / ${profile.missing_text || "없음"}`],
  ];
  if (latest) {
    detailRows.push(
      ["밴드 하단/상단", `${number(latest.min_value)} / ${number(latest.max_value)}`],
      ["평가금", number(latest.valuation)],
    );
  }
  rows("dashboard-vr-detail-rows", detailRows, 2, (row) => row);
}

function renderDashboardInfiniteDetail(profile, chartData = null) {
  text("dashboard-infinite-detail-label", profile?.label || "무한매수법 표에서 프로필을 더블클릭");
  if (!profile) {
    rows("dashboard-infinite-detail-rows", [["무매 선택", "무한매수법 표에서 프로필을 더블클릭"]], 2, (row) => row);
    return;
  }
  const chartRows = [...(chartData?.rows || [])].sort((left, right) =>
    String(left.trade_date || "").localeCompare(String(right.trade_date || "")),
  );
  const latest = chartRows.length ? chartRows[chartRows.length - 1] : null;
  const point = latest ? infiniteChartPoint(latest) : null;
  const detailRows = [
    ["무매 선택", profile.label],
    ["현재 총자산", point ? number(point.totalAsset) : number(profile.cumulative_value)],
    ["기준원금", point ? number(point.principal) : number(profile.principal)],
    ["누적손익 / 수익률", point ? `${number(point.profit)} / ${pct(point.returnRate)}` : "-"],
    ["평단 / 보유수익률", `${number(profile.avg_price)} / ${pct(profile.return_rate)}`],
    ["투입 진행률", profile.progress_text || "-"],
    ["누적투입 / 보유수량", `${number(profile.cumulative_amount)} / ${number(profile.cumulative_qty, 0)}`],
  ];
  rows("dashboard-infinite-detail-rows", detailRows, 2, (row) => row);
}

async function loadDashboardVrChart(profileName) {
  if (!profileName) return;
  state.dashboardCharts.vrProfile = profileName;
  const data = await api(`/api/dashboard/charts/vr/${encodeURIComponent(profileName)}`);
  renderDashboardVrDetail(selectedDashboardVrProfile(), data);
  try {
    await ensureEcharts();
  } catch {
    return;
  }
  renderDashboardVrCharts(data);
  resizeDashboardCharts();
}

async function loadDashboardInfiniteChart(profileName) {
  if (!profileName) return;
  state.dashboardCharts.infiniteProfile = profileName;
  const data = await api(`/api/dashboard/charts/infinite/${encodeURIComponent(profileName)}`);
  renderDashboardInfiniteDetail(selectedDashboardInfiniteProfile(), data);
  try {
    await ensureEcharts();
  } catch {
    return;
  }
  renderDashboardInfiniteCharts(data);
  resizeDashboardCharts();
}

function refreshDashboardCharts() {
  const vrProfiles = state.dashboard?.vr_profile_rows || [];
  const infiniteProfiles = state.dashboard?.infinite_profile_rows || [];
  const vrProfile = state.dashboardCharts.vrProfile || vrProfiles[0]?.name;
  const infiniteProfile = state.dashboardCharts.infiniteProfile || infiniteProfiles[0]?.name;
  state.dashboardCharts.vrProfile = vrProfile || "";
  state.dashboardCharts.infiniteProfile = infiniteProfile || "";
  renderDashboardVrDetail(selectedDashboardVrProfile());
  renderDashboardInfiniteDetail(selectedDashboardInfiniteProfile());
  if (vrProfile) void loadDashboardVrChart(vrProfile);
  if (infiniteProfile) void loadDashboardInfiniteChart(infiniteProfile);
  resizeDashboardCharts();
}

function renderDashboard(data) {
  state.dashboard = data;
  text("session-user", data.username);
  text("today-label", data.today ? `오늘: ${data.today}` : "");
  const summary = data.summary || {};
  const dueItems = data.due_items || [];
  text("dashboard-total-value", won(summary.total_value_krw));
  text(
    "dashboard-total-profit",
    `${won(summary.total_profit_krw)} / ${pct(summary.total_return_rate)}`
  );
  text("dashboard-due-count", `${dueItems.length}개`);
  text("dashboard-due-label", `${dueItems.length}개`);
  text("dashboard-fx-rate", number(summary.fx_rate));

  rows("dashboard-summary-rows", [
    ["운용 프로필", `VR ${(data.vr_profile_rows || []).length}개 / 무매 ${(data.infinite_profile_rows || []).length}개`],
    ["적용 환율", number(summary.fx_rate)],
    ["합산 현재자산(원화)", won(summary.total_value_krw)],
    ["합산 원금(원화)", won(summary.total_principal_krw)],
    ["합산 손익(원화) / 수익률", `${won(summary.total_profit_krw)} / ${pct(summary.total_return_rate)}`],
    ["총 매수금(원화)", won(summary.total_bought_krw)],
    ["총 예수금(원화) / 비율", `${won(summary.total_cash_krw)} / ${pct(summary.total_cash_ratio)}`],
  ], 2, (row) => row);

  rows(
    "dashboard-due-items",
    dueItems,
    3,
    (item) => [
      item.kind,
      item.profile,
      item.issue,
    ],
    {
      rowClass: "action-row",
      title: () => "더블클릭하면 입력 화면으로 이동합니다.",
      onDblClick: openDueItem,
    },
  );

  const vrProfiles = data.vr_profile_rows || [];
  text("vr-profile-count", `${vrProfiles.length}개`);
  rows(
    "dashboard-vr-profiles",
    vrProfiles,
    7,
    (profile) => [
      profile.label,
      number(profile.principal),
      number(profile.account_total),
      number(profile.profit),
      pct(profile.return_rate),
      profile.last_done_text,
      profile.missing_text,
    ],
    {
      rowClass: "action-row",
      title: () => "더블클릭하면 이 프로필 그래프를 표시합니다.",
      onDblClick: (profile) => loadDashboardVrChart(profile.name),
    },
  );

  const infiniteProfiles = data.infinite_profile_rows || [];
  text("infinite-profile-count", `${infiniteProfiles.length}개`);
  rows(
    "dashboard-infinite-profiles",
    infiniteProfiles,
    8,
    (profile) => [
      profile.label,
      number(profile.principal),
      number(profile.cumulative_amount),
      number(profile.cumulative_value, 0),
      pct(profile.return_rate),
      number(profile.avg_price),
      profile.progress_text,
      profile.missing_text,
    ],
    {
      rowClass: "action-row",
      title: () => "더블클릭하면 이 프로필 그래프를 표시합니다.",
      onDblClick: (profile) => loadDashboardInfiniteChart(profile.name),
    },
  );
  const defaultVrProfile = vrProfiles.find((profile) => profile.name === state.dashboardCharts.vrProfile)?.name || vrProfiles[0]?.name;
  const defaultInfiniteProfile = infiniteProfiles.find((profile) => profile.name === state.dashboardCharts.infiniteProfile)?.name || infiniteProfiles[0]?.name;
  state.dashboardCharts.vrProfile = defaultVrProfile || "";
  state.dashboardCharts.infiniteProfile = defaultInfiniteProfile || "";
}

function profileCreateNodes() {
  return {
    modal: document.getElementById("profile-create-modal"),
    form: document.getElementById("profile-create-form"),
    title: document.getElementById("profile-create-title"),
    input: document.getElementById("profile-create-name"),
    message: document.getElementById("profile-create-message"),
    submit: document.getElementById("profile-create-submit"),
  };
}

function openProfileCreateModal(kind) {
  const nodes = profileCreateNodes();
  state.profileCreateKind = kind;
  if (nodes.title) nodes.title.textContent = kind === "vr" ? "VR 새 프로필" : "무한매수법 새 프로필";
  if (nodes.input) nodes.input.value = "";
  if (nodes.message) nodes.message.textContent = "";
  if (nodes.submit) nodes.submit.disabled = false;
  if (nodes.modal) nodes.modal.hidden = false;
  setTimeout(() => nodes.input?.focus(), 0);
}

function closeProfileCreateModal() {
  const nodes = profileCreateNodes();
  state.profileCreateKind = "";
  if (nodes.modal) nodes.modal.hidden = true;
  if (nodes.form) nodes.form.reset();
  if (nodes.message) nodes.message.textContent = "";
  if (nodes.submit) nodes.submit.disabled = false;
}

async function submitProfileCreate(event) {
  event.preventDefault();
  const nodes = profileCreateNodes();
  const kind = state.profileCreateKind;
  const name = String(nodes.input?.value || "").trim();
  if (!kind) return;
  if (!name) {
    if (nodes.message) nodes.message.textContent = "프로필명을 입력하세요.";
    nodes.input?.focus();
    return;
  }
  if (nodes.submit) nodes.submit.disabled = true;
  if (nodes.message) nodes.message.textContent = "프로필 생성 중...";
  try {
    await api(`/api/${kind}/profiles`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    if (kind === "vr") state.selectedVr = name;
    else state.selectedInfinite = name;
    closeProfileCreateModal();
    await loadDashboard();
  } catch (error) {
    if (nodes.submit) nodes.submit.disabled = false;
    if (nodes.message) nodes.message.textContent = error.message || "프로필 생성에 실패했습니다.";
    nodes.input?.focus();
  }
}

async function loadVrProfiles() {
  const body = await api("/api/vr/profiles");
  state.vrProfiles = body.profiles || [];
  state.selectedVr = setSelectOptions("vr-profile-select", state.vrProfiles, state.selectedVr);
  if (state.selectedVr) await loadVrDetail(state.selectedVr);
  else updateProfileActionButtons("vr");
  await loadKiwoomForm("vr");
}

async function createVrProfile() {
  openProfileCreateModal("vr");
  return;
  const name = window.prompt("새 VR 프로필 이름");
  if (!name || !name.trim()) return;
  await api("/api/vr/profiles", {
    method: "POST",
    body: JSON.stringify({ name: name.trim() }),
  });
  state.selectedVr = name.trim();
  await loadDashboard();
}

async function saveVrSettings(payload) {
  const profile = state.selectedVr;
  if (!profile) return;
  await api(`/api/vr/profiles/${encodeURIComponent(profile)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  await loadDashboard();
  await loadVrDetail(profile);
  await loadKiwoomForm("vr");
  activateInnerPanel("vr-cycle-panel");
  focusFormField("#vr-latest-input form", "close_price");
}

async function saveVrCycleInput(payload) {
  const profile = state.selectedVr;
  if (!profile) return;
  const result = await api(`/api/vr/profiles/${encodeURIComponent(profile)}/cycle-input`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  await loadDashboard();
  await loadVrDetail(profile);
  text("vr-cycle-message", result.cycle_save?.message || "저장/재계산 완료");
  if (result.cycle_save?.mode === "save") {
    activateInnerPanel("vr-order-panel");
  } else {
    activateInnerPanel("vr-cycle-panel");
  }
}

async function loadInfiniteProfiles() {
  const body = await api("/api/infinite/profiles");
  state.infiniteProfiles = body.profiles || [];
  state.selectedInfinite = setSelectOptions(
    "infinite-profile-select",
    state.infiniteProfiles,
    state.selectedInfinite,
  );
  if (state.selectedInfinite) await loadInfiniteDetail(state.selectedInfinite);
  else updateProfileActionButtons("infinite");
  await loadKiwoomForm("infinite");
}

async function createInfiniteProfile() {
  openProfileCreateModal("infinite");
  return;
  const name = window.prompt("새 무한매수법 프로필 이름");
  if (!name || !name.trim()) return;
  await api("/api/infinite/profiles", {
    method: "POST",
    body: JSON.stringify({ name: name.trim() }),
  });
  state.selectedInfinite = name.trim();
  await loadDashboard();
}

async function saveInfiniteSettings(payload) {
  const profile = state.selectedInfinite;
  if (!profile) return;
  await api(`/api/infinite/profiles/${encodeURIComponent(profile)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  await loadDashboard();
  await loadInfiniteDetail(profile);
  await loadKiwoomForm("infinite");
}

async function saveInfiniteExecution(payload) {
  const profile = state.selectedInfinite;
  if (!profile) return;
  const result = await api(`/api/infinite/profiles/${encodeURIComponent(profile)}/execution`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  await loadDashboard();
  await loadInfiniteDetail(profile);
  text("infinite-execution-message", result.telegram_auto?.message || "체결 저장 완료");
}

async function lookupInfiniteExecutionPreview() {
  const profile = state.selectedInfinite;
  if (!profile) return;
  text("infinite-api-preview-message", "체결입력정보 조회 중...");
  const result = await api(`/api/kiwoom/infinite/${encodeURIComponent(profile)}/execution-preview`, {
    method: "POST",
    body: "{}",
  });
  state.infiniteExecutionPreview = result;
  if (result.preview) {
    renderFields("infinite-api-preview", result.preview, [
      ["입력일", "trade_date"],
      ["평균단가", "avg_price"],
      ["매수개수", "buy_qty", (v) => number(v, 0)],
      ["매도개수", "sell_qty", (v) => number(v, 0)],
    ]);
  }
  text("infinite-api-preview-message", result.message || (result.ok ? "조회 성공" : "조회 실패"));
  updateInfiniteOrderButtons();
}

async function lookupInfiniteBalance() {
  const profile = state.selectedInfinite;
  if (!profile) return;
  const resultBox = document.getElementById("infinite-balance-result");
  text("infinite-balance-message", "잔고조회 요청 중...");
  if (resultBox) resultBox.textContent = "";
  const result = await api(`/api/kiwoom/infinite/${encodeURIComponent(profile)}/balance`, {
    method: "POST",
    body: "{}",
  });
  if (resultBox) {
    resultBox.textContent = JSON.stringify(result.summary || result, null, 2);
  }
  text("infinite-balance-message", result.message || (result.ok ? "조회 성공" : "조회 실패"));
}

async function lookupVrFillHistory(periodKind) {
  const profile = state.selectedVr;
  if (!profile) return;
  text("vr-fill-message", `${periodKind === "previous" ? "지난차수" : "현재차수"} 체결내역 조회 중...`);
  const result = await api(`/api/kiwoom/vr/${encodeURIComponent(profile)}/fill-history/${periodKind}`, {
    method: "POST",
    body: "{}",
  });
  renderVrFillHistory(result.fills || []);
  text("vr-fill-message", result.message || (result.ok ? "조회 성공" : "조회 실패"));
}

async function lookupVrPeriodPreview() {
  const profile = state.selectedVr;
  if (!profile) return;
  text("vr-api-period-message", "VR 결과구간 조회 중...");
  const result = await api(`/api/kiwoom/vr/${encodeURIComponent(profile)}/period-preview`, {
    method: "POST",
    body: "{}",
  });
  if (result.preview) {
    renderVrPeriodPreview(result.preview);
  }
  text("vr-api-period-message", result.message || (result.ok ? "조회 성공" : "조회 실패"));
}

function orderResultText(result) {
  const lines = [result.message || (result.ok ? "주문실행 완료" : "주문실행 실패")];
  if (result.successes && result.successes.length) {
    lines.push(...result.successes);
  }
  if (result.order_executions && result.order_executions.length) {
    lines.push("최근 주문 이력:");
    result.order_executions.forEach((row, index) => {
      const price = row.price == null ? "시장가" : number(row.price);
      const orderNo = row.order_no || "-";
      const status = row.status === "failed" ? "실패" : "전송";
      const parts = [
        `${index + 1}. [${status}]`,
        row.side_label || "",
        `${row.quantity || 0}주`,
        price,
        row.order_type || "",
        row.status === "failed" ? row.message || "" : `주문번호 ${orderNo}`,
      ];
      lines.push(parts.filter(Boolean).join(" ").trim());
    });
  }
  return lines.join("\n");
}

function orderResultStatusText(result) {
  if (!result) return "";
  return result.message || (result.ok ? "주문실행 완료" : "주문실행 실패");
}

function activateOrderPanel(kind, panelName) {
  const group = document.querySelector(`[data-order-tabs="${kind}"]`);
  if (!group) return;
  group.querySelectorAll(".order-panel-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.orderPanel === panelName);
  });
  const host = group.closest(".panel");
  if (!host) return;
  host.querySelectorAll(".order-panel-page").forEach((panel) => {
    panel.classList.toggle("active", panel.id === panelName);
  });
}

function orderResultRows(result) {
  const executions = result?.order_executions || [];
  if (executions.length) return executions;
  return (result?.successes || []).map((message, index) => ({
    status: result?.ok ? "sent" : "failed",
    side_label: "",
    order_type: "",
    price: "",
    quantity: "",
    order_no: "",
    message: message || `${index + 1}. 주문 처리`,
  }));
}

function statusLabel(status) {
  if (status === "sent") return "전송";
  if (status === "failed") return "실패";
  return status || "-";
}

function renderOrderResult(kind, result) {
  const summary = document.getElementById(`${kind}-order-result-summary`);
  const tbody = document.getElementById(`${kind}-order-result-rows`);
  if (!summary || !tbody) return;
  const executionRows = orderResultRows(result);
  const sentCount = executionRows.filter((row) => row.status !== "failed").length;
  const failedCount = executionRows.filter((row) => row.status === "failed").length;
  const summaryItems = [
    ["주문건수", result ? `${sentCount}건` : "-"],
    ["실패", result ? `${failedCount}건` : "-"],
  ];
  summary.innerHTML = "";
  summaryItems.forEach(([label, value]) => {
    const item = document.createElement("div");
    const labelNode = document.createElement("span");
    const valueNode = document.createElement("strong");
    labelNode.textContent = label;
    valueNode.textContent = value;
    item.append(labelNode, valueNode);
    summary.appendChild(item);
  });
  if (!result) {
    renderEmpty(tbody, 7);
    return;
  }
  if (!executionRows.length) {
    rows(`${kind}-order-result-rows`, [{
      status: result.ok ? "sent" : "failed",
      side_label: "",
      order_type: "",
      price: "",
      quantity: "",
      order_no: "",
      message: orderResultStatusText(result),
    }], 7, (row) => [
      statusLabel(row.status),
      row.side_label,
      row.order_type,
      row.price == null || row.price === "" ? "-" : number(row.price),
      row.quantity || "-",
      row.order_no || "-",
      row.message || "-",
    ]);
    return;
  }
  rows(`${kind}-order-result-rows`, executionRows, 7, (row) => [
    statusLabel(row.status),
    row.side_label,
    row.order_type,
    row.price == null || row.price === "" ? "시장가" : number(row.price),
    row.quantity || "-",
    row.order_no || "-",
    row.message || "-",
  ]);
}

function setOrderResult(kind, result, activate = true) {
  if (kind === "vr") {
    state.vrOrderResult = result;
  } else {
    state.infiniteOrderResult = result;
  }
  renderOrderResult(kind, result);
  text(`${kind}-order-message`, orderResultStatusText(result));
  if (activate) activateOrderPanel(kind, `${kind}-order-result-panel`);
}

async function refreshDetailAfterOrder(kind, profile, messageId, result) {
  setOrderResult(kind, result);
  try {
    if (kind === "vr") {
      await loadVrDetail(profile);
    } else {
      await loadInfiniteDetail(profile);
    }
    setOrderResult(kind, result);
  } catch (error) {
    setOrderResult(kind, {
      ...result,
      message: `${orderResultStatusText(result)} / 상세 새로고침 실패: ${error.message}`,
    });
  }
}

function infiniteExecutionFormValues() {
  const form = document.getElementById("infinite-execution-form");
  return form ? formValues(form) : {};
}

function infiniteAfterInputReady() {
  if (!state.selectedInfinite || !state.infiniteDetail) return false;
  if (state.infiniteDetail.order_executable) return false;
  if (!state.infiniteDetail.execution_input?.allowed) return false;
  if (!state.infiniteExecutionPreview?.ok || !state.infiniteExecutionPreview?.preview) return false;
  const preview = state.infiniteExecutionPreview.preview;
  const current = infiniteExecutionFormValues();
  return Boolean(preview.trade_date && preview.trade_date !== "-" && preview.trade_date === current.trade_date);
}

function updateInfiniteOrderButtons() {
  const executeButton = document.getElementById("infinite-execute-orders");
  if (executeButton) executeButton.disabled = !state.infiniteDetail?.order_executable;
  const reorderButton = document.getElementById("infinite-reorder-orders");
  if (reorderButton) reorderButton.disabled = !state.infiniteDetail?.order_reorderable;
  const afterInputButton = document.getElementById("infinite-execute-after-input");
  if (afterInputButton) afterInputButton.disabled = !infiniteAfterInputReady();
}

function vrOrderOptions() {
  const mode = document.getElementById("vr-sell-order-mode")?.value || "match_buy";
  const count = Number(document.getElementById("vr-sell-order-count")?.value || 0);
  return {
    sell_mode: mode,
    sell_row_count: mode === "manual" ? Math.max(0, Math.floor(count || 0)) : null,
  };
}

function updateVrSellOrderMode() {
  const mode = document.getElementById("vr-sell-order-mode")?.value || "match_buy";
  const countInput = document.getElementById("vr-sell-order-count");
  if (countInput) countInput.disabled = mode !== "manual";
  state.vrOrderPreview = null;
}

function vrOrderSummaryText(result) {
  const summary = result?.summary?.execution || {};
  return [
    `대상일: ${result?.order_date || "-"}`,
    `옵션: ${result?.option?.label || "-"}`,
    `매수: ${summary.buy_count || 0}행 / ${summary.buy_qty || 0}주`,
    `매도: ${summary.sell_count || 0}행 / ${summary.sell_qty || 0}주`,
  ].join("\n");
}

function confirmReorder(kind, detail) {
  const orderDate = detail?.order_date || "-";
  const count = (detail?.order_executions || []).filter((row) => row.status !== "failed").length;
  const label = kind === "vr" ? "VR" : "무한매수법";
  const typed = window.prompt([
    `${label} ${orderDate} 주문실행 이력 ${count}건이 있습니다.`,
    "재주문은 키움 REST API로 실제 주문 요청을 다시 전송합니다.",
    "",
    "재주문하려면 '재주문'을 입력하세요.",
  ].join("\n"));
  return typed === "재주문";
}

async function executeVrOrders(forceReorder = false) {
  const profile = state.selectedVr;
  if (!profile) return;
  if (forceReorder) {
    if (!state.vrDetail?.order_reorderable || !confirmReorder("vr", state.vrDetail)) return;
  } else if (!state.vrDetail?.order_executable) {
    return;
  }
  const options = { ...vrOrderOptions(), force_reorder: Boolean(forceReorder) };
  try {
    text("vr-order-message", "VR 주문표 미리보기 조회 중...");
    const preview = await api(`/api/kiwoom/vr/${encodeURIComponent(profile)}/order-preview`, {
      method: "POST",
      body: JSON.stringify(vrOrderOptions()),
    });
    state.vrOrderPreview = preview;
    renderVrOrderLevels(preview.order_rows || []);
    text("vr-order-message", preview.message || (preview.ok ? "VR 주문표 미리보기 완료" : "VR 주문표 미리보기 실패"));
    if (!preview.ok || !(preview.order_rows || []).length) return;
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
    if (!window.confirm([
      "아래 VR 주문표 그대로 주문하시겠습니까?",
      "",
      vrOrderSummaryText(preview),
      "",
      "확인을 누르면 키움 REST API로 실제 주문 요청을 전송합니다.",
      "현재차수 체결내역에서 같은 가격 체결 수량은 제외됩니다.",
    ].join("\n"))) return;
    text("vr-order-message", forceReorder ? "VR 재주문 중..." : "VR 주문실행 중...");
    const result = await api(`/api/kiwoom/vr/${encodeURIComponent(profile)}/execute-orders`, {
      method: "POST",
      body: JSON.stringify(options),
    });
    await refreshDetailAfterOrder("vr", profile, "vr-order-message", result);
  } catch (error) {
    setOrderResult("vr", { ok: false, message: `VR 주문실행 실패: ${error.message}` });
  }
}

async function executeInfiniteOrders(forceReorder = false) {
  const profile = state.selectedInfinite;
  if (!profile) return;
  if (forceReorder) {
    if (!state.infiniteDetail?.order_reorderable || !confirmReorder("infinite", state.infiniteDetail)) return;
  } else if (!state.infiniteDetail?.order_executable) {
    return;
  }
  const message = [
    forceReorder ? "무한매수법 재주문을 진행할까요?" : "무한매수법 주문실행을 진행할까요?",
    "",
    "확인을 누르면 키움 REST API로 실제 주문 요청이 전송됩니다.",
    "해당 주문 실행일의 주문표만 실행됩니다.",
  ].join("\n");
  if (!window.confirm(message)) return;
  try {
    text("infinite-order-message", forceReorder ? "무한매수법 재주문 중..." : "무한매수법 주문실행 중...");
    const result = await api(`/api/kiwoom/infinite/${encodeURIComponent(profile)}/execute-orders`, {
      method: "POST",
      body: JSON.stringify({ force_reorder: Boolean(forceReorder) }),
    });
    await refreshDetailAfterOrder("infinite", profile, "infinite-order-message", result);
  } catch (error) {
    setOrderResult("infinite", { ok: false, message: `무한매수법 주문실행 실패: ${error.message}` });
  }
}

async function executeInfiniteAfterInput() {
  const profile = state.selectedInfinite;
  const result = state.infiniteExecutionPreview;
  if (!profile || !result?.preview) return;
  const preview = result.preview;
  const current = infiniteExecutionFormValues();
  if (state.infiniteDetail?.order_executable) {
    text("infinite-order-message", "이미 해당 주문표가 있습니다. 주문실행 버튼을 사용하세요.");
    updateInfiniteOrderButtons();
    return;
  }
  if (!state.infiniteDetail?.execution_input?.allowed) {
    text("infinite-order-message", "체결입력 저장 가능한 상태가 아닙니다.");
    updateInfiniteOrderButtons();
    return;
  }
  if (!preview.trade_date || preview.trade_date === "-") {
    text("infinite-order-message", "조회 결과에 체결 입력일이 없습니다.");
    return;
  }
  if (preview.trade_date !== current.trade_date) {
    text("infinite-order-message", `조회 입력일(${preview.trade_date})과 현재 입력일(${current.trade_date})이 다릅니다.`);
    updateInfiniteOrderButtons();
    return;
  }
  if (Number(preview.avg_price || 0) <= 0) {
    text("infinite-order-message", "조회 결과에 평균단가가 없습니다.");
    return;
  }
  const message = [
    "체결입력 후 주문실행을 진행할까요?",
    "",
    `입력일: ${preview.trade_date}`,
    `평균단가: ${preview.avg_price}`,
    `매수/매도: ${preview.buy_qty || 0} / ${preview.sell_qty || 0}`,
    "",
    "확인을 누르면 체결입력을 저장한 뒤 키움 REST API로 실제 주문 요청이 전송됩니다.",
  ].join("\n");
  if (!window.confirm(message)) return;
  let orderResult = null;
  try {
    text("infinite-order-message", "체결입력 저장 중...");
    await api(`/api/infinite/profiles/${encodeURIComponent(profile)}/execution`, {
      method: "POST",
      body: JSON.stringify({
        trade_date: preview.trade_date,
        avg_price: Number(preview.avg_price),
        buy_qty: Number(preview.buy_qty || 0),
        sell_qty: Number(preview.sell_qty || 0),
        cash_flow_amount: Number(current.cash_flow_amount || 0),
      }),
    });
    text("infinite-order-message", "주문표 생성 후 주문실행 중...");
    orderResult = await api(`/api/kiwoom/infinite/${encodeURIComponent(profile)}/execute-orders`, {
      method: "POST",
      body: "{}",
    });
    state.infiniteExecutionPreview = null;
    setOrderResult("infinite", orderResult);
    try {
      await loadDashboard();
      await loadInfiniteDetail(profile);
    } catch (error) {
      setOrderResult("infinite", {
        ...orderResult,
        message: `${orderResultStatusText(orderResult)} / 상세 새로고침 실패: ${error.message}`,
      });
      return;
    }
    setOrderResult("infinite", orderResult);
  } catch (error) {
    setOrderResult("infinite", {
      ...(orderResult || {}),
      ok: false,
      message: `${orderResult ? `${orderResultStatusText(orderResult)} / ` : ""}체결입력 후 주문실행 실패: ${error.message}`,
    });
  }
}

function vrCycleRecalculateData(row) {
  const snapshots = state.vrDetail?.snapshots || [];
  const nextSnapshot = snapshots.find((item) => Number(item.cycle_no) === Number(row.cycle_no) + 1);
  const defaults = state.vrDetail?.cycle_input || {};
  return {
    cycle_no: row.cycle_no,
    week_no: row.week_no,
    result_period: `${row.start_date || ""} ~ ${row.end_date || ""}`,
    next_period: nextSnapshot ? `${nextSnapshot.start_date || ""} ~ ${nextSnapshot.end_date || ""}` : defaults.next_period,
    close_price: row.close_price,
    trade_amount: row.trade_amount,
    shares: row.shares,
    dividend: row.dividend || 0,
    contribution_amount: row.contribution || 0,
    g_config: row.g_config || defaults.g_config || "",
    g_start_cycle_no: row.g_start_cycle_no || defaults.g_start_cycle_no || 0,
    buy_limit_config: row.buy_limit_config || defaults.buy_limit_config || "",
    buy_limit_start_week_no: row.buy_limit_start_week_no || defaults.buy_limit_start_week_no || 2,
    allowed: true,
    mode: "recalculate",
  };
}

function selectVrSnapshotForRecalculate(row) {
  activateInnerPanel("vr-cycle-panel");
  renderVrCycleInputForm(vrCycleRecalculateData(row), saveVrCycleInput);
  text("vr-cycle-message", `${row.cycle_no}차수 수정값 재계산 가능`);
  markTableRow("vr-snapshots", (state.vrDetail?.snapshots || []).indexOf(row));
  focusFormField("#vr-latest-input form", "dividend");
}

function visibleVrSnapshots(detail) {
  const cycleNo = Number(detail?.cycle_input?.cycle_no);
  return (detail?.snapshots || []).filter((row) => {
    if (String(row.status || "").toLowerCase() !== "pending") return true;
    return !(Number.isFinite(cycleNo) && Number(row.cycle_no) === cycleNo);
  });
}

function visibleInfiniteRows(detail) {
  const today = state.dashboard?.today;
  const inputDate = detail?.execution_input?.trade_date;
  return (detail?.rows || []).filter((row) => {
    const tradeDate = String(row.trade_date || "");
    if (today && tradeDate === today) return false;
    if (inputDate && tradeDate === inputDate && detail?.execution_input?.allowed) return false;
    return true;
  });
}

async function loadVrDetail(profileName) {
  const profileChanged = state.selectedVr && state.selectedVr !== profileName;
  state.selectedVr = profileName;
  state.vrDetail = null;
  state.vrOrderPreview = null;
  if (profileChanged) state.vrOrderResult = null;
  document.getElementById("vr-profile-select").value = profileName;
  const detail = await api(`/api/vr/profiles/${encodeURIComponent(profileName)}`);
  state.vrDetail = detail;
  const profile = detail.profile || {};
  updateProfileActionButtons("vr");
  text("vr-cycle-status", [profile.symbol, profile.account_number].filter(Boolean).join(" / "));
  renderSettingsForm("vr-settings", profile, [
    { name: "start_date", label: "시작일" },
    { name: "start_week_no", label: "시작주차", kind: "int" },
    { name: "symbol", label: "종목" },
    { name: "account_number", label: "계좌번호" },
    { name: "min_ratio", label: "최소 비율", kind: "float" },
    { name: "max_ratio", label: "최대 비율", kind: "float" },
    { name: "initial_v", label: "초기 V", kind: "float" },
    { name: "initial_pool", label: "초기 Pool", kind: "float" },
    { name: "initial_principal", label: "초기 투자원금", kind: "float" },
    { name: "initial_shares", label: "초기 개수", kind: "int" },
  ], saveVrSettings);
  renderVrCycleInputForm(detail.cycle_input || {}, saveVrCycleInput);
  renderFields("vr-order-options", profile, [
    ["수량간격", "quantity_step", number],
    ["매수한도", "buy_limit_ratio", pct],
    ["매수한도 시작주차", "buy_limit_start_week_no", number],
  ]);
  renderVrPeriodPreview({});
  text("vr-api-period-message", "");
  renderFields("vr-summary", detail.snapshots?.[0] || {}, [
    ["차수", "cycle_no"],
    ["G", "g", number],
    ["최소값", "min_value", number],
    ["최대값", "max_value", number],
    ["수익", "profit", number],
    ["평단", "avg_cost", number],
  ]);
  const snapshots = visibleVrSnapshots(detail);
  text("vr-snapshot-count", `${snapshots.length}개`);
  rows("vr-snapshots", snapshots, 11, (row) => [
    row.cycle_no,
    row.start_date,
    row.end_date,
    row.status,
    number(row.close_price),
    number(row.v),
    number(row.trade_amount),
    number(row.pool),
    number(row.account_total),
    number(row.shares, 0),
    pct(row.return_rate),
  ], {
    rowClass: "action-row",
    title: () => "더블클릭하면 이 차수를 재계산 입력 폼으로 불러옵니다.",
    onDblClick: selectVrSnapshotForRecalculate,
  });
  renderVrOrderLevels(detail.order_levels || []);
  updateVrSellOrderMode();
  const vrOrderButton = document.getElementById("vr-execute-orders");
  if (vrOrderButton) vrOrderButton.disabled = !detail.order_executable;
  const vrReorderButton = document.getElementById("vr-reorder-orders");
  if (vrReorderButton) vrReorderButton.disabled = !detail.order_reorderable;
  if (state.vrOrderResult) {
    renderOrderResult("vr", state.vrOrderResult);
  } else {
    renderOrderResult("vr", (detail.order_executions || []).length ? {
      ok: true,
      history_only: true,
      message: detail.order_message || "최근 주문 이력",
      order_executions: detail.order_executions,
    } : null);
    activateOrderPanel("vr", "vr-order-plan-panel");
    text("vr-order-message", detail.order_message || "");
  }
  renderEmpty(document.getElementById("vr-fill-history"), 5);
  text("vr-fill-message", "");
}

async function loadInfiniteDetail(profileName) {
  const profileChanged = state.selectedInfinite && state.selectedInfinite !== profileName;
  state.selectedInfinite = profileName;
  state.infiniteDetail = null;
  state.infiniteExecutionPreview = null;
  if (profileChanged) state.infiniteOrderResult = null;
  document.getElementById("infinite-profile-select").value = profileName;
  const detail = await api(`/api/infinite/profiles/${encodeURIComponent(profileName)}`);
  state.infiniteDetail = detail;
  const profile = detail.profile || {};
  updateProfileActionButtons("infinite");
  renderSettingsForm("infinite-settings", profile, [
    { name: "account_number", label: "계좌번호" },
    { name: "symbol", label: "종목", options: ["TQQQ", "SOXL"] },
    { name: "start_date", label: "차수 시작일" },
    { name: "initial_principal", label: "차수 시작원금", kind: "float" },
    { name: "initial_cumulative_amount", label: "초기 누적매수액", kind: "float" },
    { name: "initial_cumulative_qty", label: "초기 누적개수", kind: "int" },
    { name: "target_rate", label: "수익기준율", kind: "percent", formatter: percentInput },
    { name: "split_count", label: "분할 수", kind: "int" },
    { name: "fee_rate", label: "수수료", kind: "percent", formatter: percentInput },
    { name: "mode", label: "방식", options: ["기본", "반복리"] },
  ], saveInfiniteSettings);
  renderInfiniteExecutionForm(detail.execution_input || {}, saveInfiniteExecution);
  renderFields("infinite-api-preview", {}, [
    ["입력일", "trade_date"],
    ["평균단가", "avg_price"],
    ["매수개수", "buy_qty"],
    ["매도개수", "sell_qty"],
  ]);
  text("infinite-api-preview-message", "");
  const balanceBox = document.getElementById("infinite-balance-result");
  if (balanceBox) balanceBox.textContent = "";
  text("infinite-balance-message", "");
  const dataRows = visibleInfiniteRows(detail);
  text("infinite-row-count", `${dataRows.length}개`);
  rows("infinite-rows", dataRows, 11, (row) => [
    row.trade_date,
    number(row.close_price),
    number(row.avg_price),
    number(row.buy_qty, 0),
    number(row.sell_qty, 0),
    number(row.cumulative_qty, 0),
    number(row.t_value, 2),
    number(row.star_price),
    pct(row.return_rate),
    number(row.trade_amount),
    number(row.cumulative_amount),
  ]);
  renderInfiniteOrderPlan(detail.order_plan);
  updateInfiniteOrderButtons();
  if (state.infiniteOrderResult) {
    renderOrderResult("infinite", state.infiniteOrderResult);
  } else {
    renderOrderResult("infinite", (detail.order_executions || []).length ? {
      ok: true,
      history_only: true,
      message: detail.order_message || "최근 주문 이력",
      order_executions: detail.order_executions,
    } : null);
    activateOrderPanel("infinite", "infinite-order-plan-panel");
    text("infinite-order-message", detail.order_message || "");
  }
}

async function loadKiwoomForm(kind) {
  const profile = currentProfile(kind);
  const form = formForKind(kind);
  if (!profile || !form) return;
  const data = await api(`/api/kiwoom/${kind}/${encodeURIComponent(profile)}`);
  setFormValues(form, data);
  const hint = data.has_app_secret ? `저장된 Secret: ${data.app_secret_masked}` : "저장된 Secret 없음";
  text(messageIdForKind(kind), hint);
}

async function saveKiwoomForm(kind, event) {
  event.preventDefault();
  const profile = currentProfile(kind);
  if (!profile) return;
  const payload = formValues(formForKind(kind));
  const data = await api(`/api/kiwoom/${kind}/${encodeURIComponent(profile)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  text(messageIdForKind(kind), data.has_app_secret ? "API 키 저장 완료" : "API 키 저장 완료 / Secret 없음");
}

async function testKiwoomToken(kind) {
  const profile = currentProfile(kind);
  if (!profile) return;
  text(messageIdForKind(kind), "토큰 발급 요청 중...");
  const result = await api(`/api/kiwoom/${kind}/${encodeURIComponent(profile)}/token-test`, {
    method: "POST",
    body: "{}",
  });
  text(messageIdForKind(kind), result.message || (result.ok ? "토큰 발급 성공" : "토큰 발급 실패"));
}

async function loadTelegramForm() {
  const data = await api("/api/telegram");
  setFormValues(document.getElementById("telegram-form"), data);
  text(
    "telegram-message",
    data.has_bot_token ? `저장된 Bot Token: ${data.bot_token_masked}` : "저장된 Bot Token 없음",
  );
}

async function saveTelegramForm(event) {
  event.preventDefault();
  const payload = formValues(document.getElementById("telegram-form"));
  const data = await api("/api/telegram", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  text("telegram-message", data.has_bot_token ? "텔레그램 저장 완료" : "텔레그램 저장 완료 / 토큰 없음");
}

async function testTelegram() {
  text("telegram-message", "테스트 메시지 전송 중...");
  const result = await api("/api/telegram/test", { method: "POST", body: "{}" });
  text("telegram-message", result.message || (result.ok ? "테스트 메시지 전송 완료" : "테스트 메시지 실패"));
}

async function sendTelegramSelected() {
  text("telegram-message", "선택 항목 전송 중...");
  const result = await api("/api/telegram/send-selected", { method: "POST", body: "{}" });
  text("telegram-message", result.message || (result.ok ? "선택 항목 전송 완료" : "선택 항목 전송 실패"));
}

async function loadDashboard() {
  arrangeDashboardLayout();
  const data = await api("/api/dashboard");
  renderDashboard(data);
  setVisible("app");
  refreshDashboardCharts();
  await Promise.all([loadVrProfiles(), loadInfiniteProfiles()]);
  await loadTelegramForm();
}

document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab-button").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-page").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    document.getElementById(button.dataset.tab).classList.add("active");
    if (button.dataset.tab === "dashboard-tab") {
      refreshDashboardCharts();
    }
  });
});

document.querySelectorAll(".inner-tabs").forEach((group) => {
  group.querySelectorAll(".inner-tab").forEach((button) => {
    button.addEventListener("click", () => {
      group.querySelectorAll(".inner-tab").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      const parent = group.parentElement;
      parent.querySelectorAll(".inner-panel").forEach((panel) => panel.classList.remove("active"));
      document.getElementById(button.dataset.panel).classList.add("active");
    });
  });
});

document.querySelectorAll(".order-panel-tabs").forEach((group) => {
  const kind = group.dataset.orderTabs;
  group.querySelectorAll(".order-panel-tab").forEach((button) => {
    button.addEventListener("click", () => {
      activateOrderPanel(kind, button.dataset.orderPanel);
    });
  });
});

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginMessage.textContent = "";
  const formData = new FormData(loginForm);
  try {
    await api("/api/login", {
      method: "POST",
      body: JSON.stringify({
        username: String(formData.get("username") || ""),
        password: String(formData.get("password") || ""),
      }),
    });
    loginForm.reset();
    await loadDashboard();
  } catch (error) {
    loginMessage.textContent = error.message;
  }
});

logoutButton.addEventListener("click", async () => {
  await api("/api/logout", { method: "POST", body: "{}" });
  setVisible("login");
});

document.getElementById("vr-profile-select").addEventListener("change", async (event) => {
  await loadVrDetail(event.target.value);
  await loadKiwoomForm("vr");
});
document.getElementById("infinite-profile-select").addEventListener("change", async (event) => {
  await loadInfiniteDetail(event.target.value);
  await loadKiwoomForm("infinite");
});
document.getElementById("refresh-vr").addEventListener("click", loadVrProfiles);
document.getElementById("refresh-infinite").addEventListener("click", loadInfiniteProfiles);
document.getElementById("new-vr").addEventListener("click", createVrProfile);
document.getElementById("new-infinite").addEventListener("click", createInfiniteProfile);
document.getElementById("rename-vr").addEventListener("click", () => renameProfile("vr"));
document.getElementById("rename-infinite").addEventListener("click", () => renameProfile("infinite"));
document.getElementById("delete-vr").addEventListener("click", () => deleteSelectedProfile("vr"));
document.getElementById("delete-infinite").addEventListener("click", () => deleteSelectedProfile("infinite"));
document.getElementById("current-vr").addEventListener("click", () => gotoCurrentProfileRow("vr"));
document.getElementById("current-infinite").addEventListener("click", () => gotoCurrentProfileRow("infinite"));
document.getElementById("pause-vr").addEventListener("click", () => toggleProfilePause("vr"));
document.getElementById("pause-infinite").addEventListener("click", () => toggleProfilePause("infinite"));
document.getElementById("vr-reload-api").addEventListener("click", () => loadKiwoomForm("vr"));
document.getElementById("infinite-reload-api").addEventListener("click", () => loadKiwoomForm("infinite"));
document.getElementById("vr-test-api-token").addEventListener("click", () => testKiwoomToken("vr"));
document.getElementById("infinite-test-api-token").addEventListener("click", () => testKiwoomToken("infinite"));
document.getElementById("vr-api-period-call").addEventListener("click", lookupVrPeriodPreview);
document.getElementById("infinite-api-preview-call").addEventListener("click", lookupInfiniteExecutionPreview);
document.getElementById("infinite-balance-call").addEventListener("click", lookupInfiniteBalance);
document.getElementById("vr-fill-previous").addEventListener("click", () => lookupVrFillHistory("previous"));
document.getElementById("vr-fill-current").addEventListener("click", () => lookupVrFillHistory("current"));
document.getElementById("vr-execute-orders").addEventListener("click", () => executeVrOrders(false));
document.getElementById("vr-reorder-orders").addEventListener("click", () => executeVrOrders(true));
document.getElementById("vr-sell-order-mode").addEventListener("change", updateVrSellOrderMode);
document.getElementById("vr-sell-order-count").addEventListener("input", () => {
  state.vrOrderPreview = null;
});
document.getElementById("infinite-execute-orders").addEventListener("click", () => executeInfiniteOrders(false));
document.getElementById("infinite-reorder-orders").addEventListener("click", () => executeInfiniteOrders(true));
document.getElementById("infinite-execute-after-input").addEventListener("click", executeInfiniteAfterInput);
document.getElementById("vr-api-form").addEventListener("submit", (event) => saveKiwoomForm("vr", event));
document.getElementById("infinite-api-form").addEventListener("submit", (event) => saveKiwoomForm("infinite", event));
document.getElementById("reload-telegram").addEventListener("click", loadTelegramForm);
document.getElementById("test-telegram").addEventListener("click", testTelegram);
document.getElementById("send-telegram-selected").addEventListener("click", sendTelegramSelected);
document.getElementById("telegram-form").addEventListener("submit", saveTelegramForm);
document.getElementById("profile-create-form").addEventListener("submit", submitProfileCreate);
document.getElementById("profile-create-cancel").addEventListener("click", closeProfileCreateModal);
document.getElementById("profile-create-close").addEventListener("click", closeProfileCreateModal);
document.getElementById("profile-create-modal").addEventListener("click", (event) => {
  if (event.target.id === "profile-create-modal") closeProfileCreateModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !document.getElementById("profile-create-modal").hidden) {
    closeProfileCreateModal();
  }
});

window.addEventListener("resize", () => {
  Object.values(state.dashboardCharts.instances).forEach((chart) => chart.resize());
});

loadDashboard().catch(() => setVisible("login"));
