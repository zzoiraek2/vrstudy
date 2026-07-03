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
      // Keep the default message for non-JSON failures.
    }
    throw new Error(message);
  }
  return response.json();
}

function setVisible(view) {
  loginView.hidden = view !== "login";
  appView.hidden = view !== "app";
}

function text(id, value) {
  document.getElementById(id).textContent = value;
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
    cell.textContent = value || "-";
    row.appendChild(cell);
  });
}

function renderDashboard(data) {
  text("session-user", data.username);
  text("count-vr", data.counts.vr_snapshots);
  text("count-infinite-profiles", data.counts.infinite_profiles);
  text("count-infinite-rows", data.counts.infinite_rows);
  text("count-order-levels", data.counts.order_levels);

  const vrBody = document.getElementById("vr-profiles");
  const vrProfiles = data.vr_profiles || [];
  text("vr-profile-count", `${vrProfiles.length}개`);
  if (!vrProfiles.length) {
    renderEmpty(vrBody, 3);
  } else {
    vrBody.innerHTML = "";
    vrProfiles.forEach((profile) => {
      const row = document.createElement("tr");
      appendCells(row, [profile.name, profile.symbol, profile.account_number]);
      vrBody.appendChild(row);
    });
  }

  const infiniteBody = document.getElementById("infinite-profiles");
  const infiniteProfiles = data.infinite_profiles || [];
  text("infinite-profile-count", `${infiniteProfiles.length}개`);
  if (!infiniteProfiles.length) {
    renderEmpty(infiniteBody, 6);
  } else {
    infiniteBody.innerHTML = "";
    infiniteProfiles.forEach((profile) => {
      const row = document.createElement("tr");
      appendCells(row, [
        profile.profile_no,
        profile.name,
        profile.symbol,
        profile.start_date,
        profile.account_number,
        profile.calculation_paused ? "일시정지" : profile.mode,
      ]);
      infiniteBody.appendChild(row);
    });
  }
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  renderDashboard(data);
  setVisible("app");
}

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

loadDashboard().catch(() => setVisible("login"));

