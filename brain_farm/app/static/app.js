// Frontend control system for WorldQuant BRAIN Alpha Farm
document.addEventListener("DOMContentLoaded", () => {
  // Session details stored in memory
  let currentUser = {
    authenticated: false,
    username: "",
    is_mock: true,
    user_id: null
  };

  let activeProjectId = null;
  let pollIntervalId = null;
  let logPollIntervalId = null;
  let analyticsPollingId = null;
  let lastRunningCount = 0;

  // Chart instances
  let scatterChart = null;
  let fitnessChart = null;
  let sharpeDensityChart = null;

  // Initialisation
  initNav();
  checkAuthStatus();
  initEventHandlers();

  // Lucide icons render
  lucide.createIcons();

  // Navigation Logic
  function initNav() {
    const navButtons = document.querySelectorAll(".nav-btn");
    navButtons.forEach(btn => {
      btn.addEventListener("click", () => {
        const viewId = btn.getAttribute("data-view");
        switchView(viewId);
      });
    });
  }

  function switchView(viewId) {
    // Nav class toggle
    document.querySelectorAll(".nav-btn").forEach(btn => {
      if (btn.getAttribute("data-view") === viewId) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });

    // Panel class toggle
    document.querySelectorAll(".view-panel").forEach(panel => {
      if (panel.id === `view-${viewId}`) {
        panel.classList.add("active");
      } else {
        panel.classList.remove("active");
      }
    });

    // View specific activation
    if (viewId === "projects-config") {
      loadProjectsList();
      loadFieldsCatalog();
    } else if (viewId === "farming-run") {
      updateFarmingViewWarnings();
    } else if (viewId === "live-queue") {
      startQueuePolling();
      stopAnalyticsPolling();
    } else if (viewId === "analytics") {
      stopQueuePolling();
      startAnalyticsPolling();
    } else {
      stopQueuePolling();
      stopAnalyticsPolling();
    }

    if (viewId === "passed-results") {
      loadPassedResults();
    }
  }

  // Base Headers mapping
  function getHeaders() {
    const hd = {
      "Content-Type": "application/json"
    };
    if (currentUser.user_id) {
      hd["X-User-ID"] = String(currentUser.user_id);
    }
    return hd;
  }

  // Auth Functions
  async function checkAuthStatus() {
    try {
      const response = await fetch("/api/auth/status", { headers: getHeaders() });
      const data = await response.json();

      currentUser.authenticated = data.authenticated;
      currentUser.username = data.username;
      currentUser.is_mock = data.is_mock;
      currentUser.user_id = data.user_id || currentUser.user_id;

      updateAuthUI();
      if (currentUser.authenticated) {
        logAuthActivity("System", "Active session restored successfully.", "SUCCESS");
        await loadProjectsList();
      }
    } catch (err) {
      console.error("Auth status checking failed:", err);
    }
  }

  function updateAuthUI() {
    const avatar = document.getElementById("avatarIcon");
    const nameLabel = document.getElementById("userDisplayName");
    const emailLabel = document.getElementById("userEmailAddress");
    const modeBadge = document.getElementById("modeBadge");
    const sessionInfo = document.getElementById("sessionInfoDetails");
    const logoutBtn = document.getElementById("logoutButton");

    // Auth Warnings
    const projWarning = document.getElementById("projectsAuthWarning");
    const projForm = document.getElementById("projectsFormWrapper");

    if (currentUser.authenticated) {
      // User Profile Sidebar
      const initials = currentUser.username.split("@")[0].slice(0, 2).toUpperCase();
      avatar.innerText = initials;
      nameLabel.innerText = currentUser.username.split("@")[0];
      emailLabel.innerText = currentUser.username;
      modeBadge.innerText = currentUser.is_mock ? "SIMULATED / SANDBOX" : "LIVE MODE";
      modeBadge.style.color = currentUser.is_mock ? "var(--warning)" : "var(--primary-accent)";
      sessionInfo.innerText = "Connected";
      logoutBtn.style.display = "flex";

      // Projects Config Warnings Hidden
      if (projWarning) projWarning.style.display = "none";
      if (projForm) projForm.style.display = "grid";

      document.getElementById("authCredentialsFormPanel").style.display = "none";
      document.getElementById("authOtpFormPanel").style.display = "none";
    } else {
      avatar.innerText = "?";
      nameLabel.innerText = "Guest";
      emailLabel.innerText = "Not signed in";
      modeBadge.innerText = "OFFLINE";
      modeBadge.style.color = "var(--text-secondary)";
      sessionInfo.innerText = "";
      logoutBtn.style.display = "none";

      if (projWarning) projWarning.style.display = "flex";
      if (projForm) projForm.style.display = "none";

      document.getElementById("authCredentialsFormPanel").style.display = "block";
      document.getElementById("authOtpFormPanel").style.display = "none";
    }

    updateFarmingViewWarnings();
    updateQueueViewWarnings();
    updateAnalyticsViewWarnings();
    updatePassedViewWarnings();
  }

  function logAuthActivity(type, msg, level = "INFO") {
    const feed = document.getElementById("authActivityLogsFeed");
    const placeholder = feed.querySelector(".placeholder-text");
    if (placeholder) placeholder.remove();

    const timeStr = new Date().toTimeString().split(" ")[0];
    const logLine = document.createElement("div");
    logLine.className = `log-line ${level}`;
    logLine.innerHTML = `<span>[${timeStr}] [${type}]</span> ${msg}`;
    feed.prepend(logLine);
  }

  // Event Handlers
  function initEventHandlers() {
    // Login Submission
    document.getElementById("btnSignInSubmit").addEventListener("click", handleSignIn);

    // OTP verify Submission
    document.getElementById("btnVerifyOtpSubmit").addEventListener("click", handleVerifyOtp);
    document.getElementById("btnCancelOtp").addEventListener("click", () => {
      document.getElementById("authCredentialsFormPanel").style.display = "block";
      document.getElementById("authOtpFormPanel").style.display = "none";
    });

    // Check Session Button
    document.getElementById("btnCheckSessionSubmit").addEventListener("click", () => {
      checkAuthStatus();
      logAuthActivity("Ping", "Triggered manual session ping verification.", "INFO");
    });

    // Logout
    document.getElementById("logoutButton").addEventListener("click", handleLogout);

    // Project creation
    document.getElementById("btnSubmitProject").addEventListener("click", handleCreateProject);

    // Active project dropdown handler
    document.getElementById("activeProjectSelect").addEventListener("change", (e) => {
      activeProjectId = e.target.value ? parseInt(e.target.value) : null;
      updateProjectSummaries();
    });

    // Fields Catalog filtering
    document.getElementById("fieldsCatalogSearch").addEventListener("input", filterFieldsTable);
    document.getElementById("fieldsFavoritesOnly").addEventListener("change", filterFieldsTable);

    // Sync Fields catalog
    document.getElementById("btnSyncFieldsCatalog").addEventListener("click", handleFieldsSync);

    // Engine Selection Change wrapper
    document.getElementById("farmEngineSelect").addEventListener("change", (e) => {
      const depthWrapper = document.getElementById("astDepthWrapper");
      const familyWrapper = document.getElementById("familySelectWrapper");
      if (e.target.value === "Recursive AST Generator") {
        depthWrapper.style.display = "block";
      } else {
        depthWrapper.style.display = "none";
      }
      if (e.target.value === "Research Family Generator") {
        familyWrapper.style.display = "block";
      } else {
        familyWrapper.style.display = "none";
      }
    });

    // Launch farming job
    document.getElementById("btnLaunchFarmingJob").addEventListener("click", handleLaunchFarm);

    // Manual Alpha Submit
    document.getElementById("btnSubmitManualExpression").addEventListener("click", handleManualSubmit);

    // Refresh Logs manually inside Queue page
    document.getElementById("btnRefreshLogsQueue").addEventListener("click", () => {
      loadQueueLogs();
    });

    // Export Result Files
    document.getElementById("btnExportCSV").addEventListener("click", () => downloadPassedFile("csv"));
    document.getElementById("btnExportJSON").addEventListener("click", () => downloadPassedFile("json"));

    // Submit Alpha to Registry
    document.getElementById("btnSubmitToRegistry").addEventListener("click", handleRegistrySubmission);
    document.getElementById("btnSubmitAllToRegistry").addEventListener("click", handleRegistrySubmissionAll);
  }

  async function handleSignIn() {
    const email = document.getElementById("authEmailInput").value;
    const password = document.getElementById("authPasswordInput").value;
    const useMock = document.getElementById("authModeCheckbox").checked;

    if (!email || !password) {
      alert("Please fill in both Email and Password fields.");
      return;
    }

    logAuthActivity("Auth", `Sending login challenge email=${email} mode=${useMock ? 'sandbox' : 'live'}`);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, use_mock: useMock })
      });
      const data = await res.json();

      if (!res.ok) {
        logAuthActivity("Auth-Error", data.detail || data.message || "Failed authentication step 1", "ERROR");
        return;
      }

      if (data.otp_pending) {
        logAuthActivity("Auth", "Step 1 completed. Awaiting OTP submittal details.", "WARNING");
        document.getElementById("authCredentialsFormPanel").style.display = "none";
        document.getElementById("authOtpFormPanel").style.display = "block";
      } else {
        currentUser.authenticated = true;
        currentUser.username = data.username;
        currentUser.is_mock = data.is_mock;
        currentUser.user_id = data.user_id;

        updateAuthUI();
        logAuthActivity("Auth", data.message, "SUCCESS");
        await loadProjectsList();
      }
    } catch (err) {
      logAuthActivity("Network", `Exception while signing in: ${err.message}`, "ERROR");
    }
  }

  async function handleVerifyOtp() {
    const email = document.getElementById("authEmailInput").value;
    const otpCode = document.getElementById("authOtpInput").value;

    if (!otpCode) {
      alert("Please enter the verification code sent to your email.");
      return;
    }

    logAuthActivity("Auth", "Submitting OTP token checking sequence.");
    try {
      const res = await fetch("/api/auth/verify-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, otp_code: otpCode })
      });
      const data = await res.json();

      if (!res.ok) {
        logAuthActivity("Auth-Error", data.detail || data.message || "Verification Failed", "ERROR");
        return;
      }

      currentUser.authenticated = true;
      currentUser.username = data.username;
      currentUser.is_mock = data.is_mock;
      currentUser.user_id = data.user_id;

      updateAuthUI();
      logAuthActivity("Auth", data.message, "SUCCESS");
      await loadProjectsList();
    } catch (err) {
      logAuthActivity("Network", `OTP exception: ${err.message}`, "ERROR");
    }
  }

  async function handleLogout() {
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        headers: getHeaders()
      });
      currentUser = { authenticated: false, username: "", is_mock: true, user_id: null };
      activeProjectId = null;
      document.getElementById("activeProjectSelect").innerHTML = "";
      updateAuthUI();
      logAuthActivity("Session", "Destroyed active token profiles manually.", "WARNING");
      switchView("auth-setup");
    } catch (err) {
      console.error(err);
    }
  }

  // Create Project Context
  async function handleCreateProject() {
    const name = document.getElementById("projNameInput").value;
    const description = document.getElementById("projDescInput").value;
    const region = document.getElementById("projRegionSelect").value;
    const universe = document.getElementById("projUniverseSelect").value;
    const neutralization = document.getElementById("projNeutralizationSelect").value;
    const delay = parseInt(document.getElementById("projDelayInput").value);
    const decay = parseInt(document.getElementById("projDecayInput").value);
    const min_sharpe = parseFloat(document.getElementById("projMinSharpe").value);
    const min_fitness = parseFloat(document.getElementById("projMinFitness").value);
    const max_turnover = parseFloat(document.getElementById("projMaxTurnover").value);
    const min_margin = parseFloat(document.getElementById("projMinMargin").value);
    const min_sub_universe_sharpe = parseFloat(document.getElementById("projMinSubSharpe").value);

    if (!name) {
      alert("Project designation name required!");
      return;
    }

    try {
      const res = await fetch("/api/projects", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({
          name, description, region, universe, neutralization, delay, decay,
          min_sharpe, min_fitness, max_turnover, min_margin, min_sub_universe_sharpe
        })
      });
      const data = await res.json();
      if (res.ok) {
        alert("Created project definition context!");
        await loadProjectsList();

        // Select the newly created project
        if (data.project_id) {
          activeProjectId = data.project_id;
          document.getElementById("activeProjectSelect").value = String(activeProjectId);
          updateProjectSummaries();
        }
      } else {
        alert("Creation failed: " + data.detail);
      }
    } catch (err) {
      console.error(err);
    }
  }

  // Load projects list
  async function loadProjectsList() {
    if (!currentUser.authenticated) return;
    try {
      const res = await fetch("/api/projects", { headers: getHeaders() });
      const projects = await res.json();

      const select = document.getElementById("activeProjectSelect");
      select.innerHTML = "";

      if (projects.length === 0) {
        const option = document.createElement("option");
        option.value = "";
        option.text = "-- No Projects Created --";
        select.appendChild(option);
        activeProjectId = null;
      } else {
        projects.forEach(p => {
          const option = document.createElement("option");
          option.value = String(p.id);
          option.text = `${p.name} (${p.region} - ${p.universe})`;
          select.appendChild(option);
        });

        // Auto-select first project if none is active
        if (!activeProjectId || !projects.find(p => p.id === activeProjectId)) {
          activeProjectId = projects[0].id;
        }
        select.value = String(activeProjectId);
      }

      window.cachedProjects = projects;
      updateProjectSummaries();
    } catch (err) {
      console.error("List load failed:", err);
    }
  }

  function updateProjectSummaries() {
    const list = window.cachedProjects || [];
    const summaryBox = document.getElementById("projectSummaryInfo");

    updateFarmingViewWarnings();
    updateQueueViewWarnings();
    updateAnalyticsViewWarnings();
    updatePassedViewWarnings();

    if (!activeProjectId) {
      summaryBox.innerHTML = '<p class="placeholder-text">Please choose or create a project context.</p>';
      return;
    }

    const project = list.find(p => p.id === activeProjectId);
    if (!project) return;

    summaryBox.innerHTML = `
      <div style="font-weight:600; margin-bottom:4px; font-size:12px; color:var(--primary-accent)">${project.name}</div>
      <div style="margin-bottom:6px">${project.description || 'No description provided.'}</div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px; font-size:10px;">
        <div>🌍 Reg: <strong>${project.region}</strong></div>
        <div>🛰️ Uni: <strong>${project.universe}</strong></div>
        <div>⏳ Delay: <strong>${project.delay}d</strong></div>
        <div>📉 Decay: <strong>${project.decay}d</strong></div>
      </div>
      <div style="margin-top:6px; border-top:1px solid var(--border-color); padding-top:4px; font-size:10px">
        🎯 Sharpe Threshold: <strong>${project.min_sharpe}</strong>
      </div>
    `;
  }

  // Warnings update
  function updateFarmingViewWarnings() {
    const warning = document.getElementById("farmingProjectWarning");
    const container = document.getElementById("farmingRunFormWrapper");
    if (!currentUser.authenticated || !activeProjectId) {
      if (warning) warning.style.display = "flex";
      if (container) container.style.display = "none";
    } else {
      if (warning) warning.style.display = "none";
      if (container) container.style.display = "grid";
    }
  }

  function updateQueueViewWarnings() {
    const warning = document.getElementById("queueProjectWarning");
    const container = document.getElementById("queueStatsContent");
    if (!currentUser.authenticated || !activeProjectId) {
      if (warning) warning.style.display = "flex";
      if (container) container.style.display = "none";
    } else {
      if (warning) warning.style.display = "none";
      if (container) container.style.display = "block";
    }
  }

  function updateAnalyticsViewWarnings() {
    const warning = document.getElementById("analyticsProjectWarning");
    const container = document.getElementById("analyticsContentWrapper");
    if (!currentUser.authenticated || !activeProjectId) {
      if (warning) warning.style.display = "flex";
      if (container) container.style.display = "none";
    } else {
      if (warning) warning.style.display = "none";
      if (container) container.style.display = "block";
    }
  }

  function updatePassedViewWarnings() {
    const warning = document.getElementById("passedProjectWarning");
    const container = document.getElementById("passedContentWrapper");
    if (!currentUser.authenticated || !activeProjectId) {
      if (warning) warning.style.display = "flex";
      if (container) container.style.display = "none";
    } else {
      if (warning) warning.style.display = "none";
      if (container) container.style.display = "block";
    }
  }

  // Fields Catalog implementation
  async function loadFieldsCatalog() {
    try {
      const res = await fetch("/api/fields");
      const fields = await res.json();
      window.cachedFields = fields;
      renderFieldsTable(fields);
    } catch (err) {
      console.error(err);
    }
  }

  function renderFieldsTable(fields) {
    const tableBody = document.querySelector("#fieldsCatalogTable tbody");
    tableBody.innerHTML = "";

    if (fields.length === 0) {
      tableBody.innerHTML = '<tr><td colspan="4" class="text-center">No fields available in catalog. Click Sync.</td></tr>';
      return;
    }

    fields.forEach(f => {
      const tr = document.createElement("tr");

      const starTd = document.createElement("td");
      starTd.className = "text-center";
      starTd.innerHTML = `<i data-lucide="star" class="fav-star ${f.is_favorite ? 'active' : ''}"></i>`;
      starTd.querySelector("i").addEventListener("click", () => handleFieldFavoriteToggle(f.id));

      const codeTd = document.createElement("td");
      codeTd.innerHTML = `<code>${f.id}</code>`;

      const nameTd = document.createElement("td");
      nameTd.innerText = f.name;

      const catTd = document.createElement("td");
      catTd.innerHTML = `<span class="badge" style="background:var(--bg-hover); border:1px solid var(--border-color); color:var(--text-secondary)">${f.category}</span>`;

      tr.appendChild(starTd);
      tr.appendChild(codeTd);
      tr.appendChild(nameTd);
      tr.appendChild(catTd);
      tableBody.appendChild(tr);
    });

    lucide.createIcons();
  }

  function filterFieldsTable() {
    const query = document.getElementById("fieldsCatalogSearch").value.toLowerCase();
    const favOnly = document.getElementById("fieldsFavoritesOnly").checked;

    const list = window.cachedFields || [];
    const filtered = list.filter(f => {
      const matchesQuery = f.id.toLowerCase().includes(query) || f.name.toLowerCase().includes(query) || f.category.toLowerCase().includes(query);
      const matchesFav = !favOnly || f.is_favorite;
      return matchesQuery && matchesFav;
    });
    renderFieldsTable(filtered);
  }

  async function handleFieldFavoriteToggle(fieldId) {
    try {
      const res = await fetch("/api/fields/toggle-favorite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field_id: fieldId })
      });
      if (res.ok) {
        const data = await res.json();
        // Update local cached cache
        const index = window.cachedFields.findIndex(f => f.id === fieldId);
        if (index > -1) {
          window.cachedFields[index].is_favorite = data.is_favorite;
          filterFieldsTable();
        }
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function handleFieldsSync() {
    const list = window.cachedProjects || [];
    const project = list.find(p => p.id === activeProjectId);
    const region = project ? project.region : "USA";
    const universe = project ? project.universe : "TOP3000";

    const syncBtn = document.getElementById("btnSyncFieldsCatalog");
    syncBtn.disabled = true;
    syncBtn.innerHTML = '<i data-lucide="loader-2" class="spin"></i> Syncing...';
    lucide.createIcons();

    try {
      const res = await fetch("/api/fields/sync", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ region, universe })
      });
      const data = await res.json();
      if (res.ok) {
        alert(`Successfully synced ${data.count} cache fields from API!`);
        await loadFieldsCatalog();
      } else {
        alert("Syncing failed: " + data.detail);
      }
    } catch (err) {
      console.error(err);
    } finally {
      syncBtn.disabled = false;
      syncBtn.innerHTML = '<i data-lucide="refresh-cw"></i> Sync Catalog';
      lucide.createIcons();
    }
  }

  // Launch Farming Batches
  async function handleLaunchFarm() {
    if (!activeProjectId) return;
    const engine = document.getElementById("farmEngineSelect").value;
    const count = parseInt(document.getElementById("farmCountRange").value);
    const depth = parseInt(document.getElementById("astDepthRange").value);
    const researchFamily = document.getElementById("farmEngineSelect").value === "Research Family Generator" ? document.getElementById("farmFamilySelect").value : null;

    const launchBtn = document.getElementById("btnLaunchFarmingJob");
    launchBtn.disabled = true;
    launchBtn.innerHTML = '<i data-lucide="loader-2" class="spin"></i> Launching...';
    lucide.createIcons();

    try {
      const res = await fetch("/api/farm/launch", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({
          project_id: activeProjectId,
          engine,
          count,
          ast_depth: depth,
          research_family: researchFamily
        })
      });
      const data = await res.json();
      if (res.ok) {
        alert(`Successfully launched farm batch! Enqueued ${data.queued_count} candidates.`);
        switchView("live-queue");
      } else {
        alert("Launch failed: " + data.detail);
      }
    } catch (err) {
      console.error(err);
    } finally {
      launchBtn.disabled = false;
      launchBtn.innerHTML = "Launch & Queue Farm Job";
    }
  }

  async function handleManualSubmit() {
    const expr = document.getElementById("manualExpressionInput").value;
    const feedback = document.getElementById("manualSubmissionResultFeedback");

    if (!expr) {
      alert("Specify formula to validate.");
      return;
    }

    feedback.innerHTML = '<div class="alert alert-info"><i data-lucide="loader-2" class="spin"></i> Validating expression syntax...</div>';
    lucide.createIcons();

    try {
      const res = await fetch("/api/farm/submit-single", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({
          project_id: activeProjectId,
          expression: expr
        })
      });
      const data = await res.json();

      if (res.ok) {
        feedback.innerHTML = `<div class="alert alert-info" style="border-color:var(--primary-accent); color:var(--primary-accent); background:var(--accent-faded)">✔ Successful Submission: ${data.message}</div>`;
      } else {
        feedback.innerHTML = `<div class="alert alert-error">✖ Validation Error: ${data.message || data.detail}</div>`;
      }
    } catch (err) {
      feedback.innerHTML = `<div class="alert alert-error">Network connection error: ${err.message}</div>`;
    }
  }

  // Queue Polling
  function startQueuePolling() {
    stopQueuePolling();
    loadQueueData();
    loadQueueLogs();

    pollIntervalId = setInterval(loadQueueData, 2000);
    logPollIntervalId = setInterval(loadQueueLogs, 4000);
  }

  function stopQueuePolling() {
    if (pollIntervalId) {
      clearInterval(pollIntervalId);
      pollIntervalId = null;
    }
    if (logPollIntervalId) {
      clearInterval(logPollIntervalId);
      logPollIntervalId = null;
    }
  }

  // Analytics Polling
  function startAnalyticsPolling() {
    stopAnalyticsPolling();
    loadAnalyticsData();
    analyticsPollingId = setInterval(loadAnalyticsData, 5000);
  }

  function stopAnalyticsPolling() {
    if (analyticsPollingId) {
      clearInterval(analyticsPollingId);
      analyticsPollingId = null;
    }
  }

  async function loadQueueData() {
    if (!activeProjectId) return;
    try {
      const res = await fetch(`/api/queue?project_id=${activeProjectId}`);
      const data = await res.json();

      document.getElementById("statQueuePending").innerText = data.pending_count;
      document.getElementById("statQueueRunning").innerText = data.running_count;

      // When running count drops to 0 (simulations just finished), refresh analytics
      if (lastRunningCount > 0 && data.running_count === 0) {
        loadAnalyticsData();
      }
      lastRunningCount = data.running_count;

      const tbody = document.querySelector("#queueSimulationsTable tbody");
      tbody.innerHTML = "";

      const list = data.simulations || [];
      if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center">No simulation tasks in queue history...</td></tr>';
        return;
      }

      list.forEach(s => {
        const tr = document.createElement("tr");

        const idTd = document.createElement("td");
        idTd.innerHTML = `<code>${s.sim_id}</code>`;

        const exprTd = document.createElement("td");
        exprTd.style.fontFamily = "monospace";
        exprTd.innerText = s.expression;

        const statusTd = document.createElement("td");
        const statusLower = s.status.toLowerCase();
        statusTd.innerHTML = `<span class="status-pill ${statusLower}">${s.status}</span>`;

        const checkTd = document.createElement("td");
        checkTd.innerText = s.last_checked;

        const detailTd = document.createElement("td");
        detailTd.style.color = statusLower === "error" ? "var(--error)" : "var(--text-secondary)";
        if (s.status === "ERROR" && s.category && s.category !== "NORMAL") {
          detailTd.innerHTML = `<code style="color: #ff5252; font-size: 0.85em; background: rgba(255, 82, 82, 0.1); padding: 2px 6px; border-radius: 4px; margin-right: 6px; border: 1px solid rgba(255, 82, 82, 0.2);">${s.category}</code> ${s.message}`;
        } else {
          detailTd.innerText = s.message;
        }

        tr.appendChild(idTd);
        tr.appendChild(exprTd);
        tr.appendChild(statusTd);
        tr.appendChild(checkTd);
        tr.appendChild(detailTd);
        tbody.appendChild(tr);
      });
    } catch (err) {
      console.error("Queue load failed:", err);
    }
  }

  async function loadQueueLogs() {
    if (!activeProjectId) return;
    try {
      const res = await fetch(`/api/logs?project_id=${activeProjectId}`);
      const logs = await res.json();

      const list = document.getElementById("miningFarmLogsList");
      list.innerHTML = "";

      if (logs.length === 0) {
        list.innerHTML = '<p class="placeholder-text">No message logs captured yet for this project...</p>';
        return;
      }

      logs.forEach(log => {
        const div = document.createElement("div");
        div.className = `log-line ${log.level}`;
        div.innerHTML = `<span>[${log.timestamp.split(" ")[1]}]</span> ${log.message}`;
        list.appendChild(div);
      });
    } catch (err) {
      console.error(err);
    }
  }

  // Analytics tab
  async function loadAnalyticsData() {
    if (!activeProjectId) return;
    try {
      const res = await fetch(`/api/analytics?project_id=${activeProjectId}`);
      const data = await res.json();

      const emptyAlert = document.getElementById("analyticsEmptyAlert");
      const chartsGrid = document.getElementById("analyticsChartsGrid");

      if (data.length === 0) {
        emptyAlert.style.display = "block";
        chartsGrid.style.display = "none";
        return;
      }
      emptyAlert.style.display = "none";
      chartsGrid.style.display = "grid";

      // Render Charts & Statistics values
      renderScatterChart(data);
      renderFitnessBoxesChart(data);
      renderSharpeRangesChart(data);
      renderAnalyticsAveragesTable(data);

      // Calculate mutual correlations if we have passed alphas
      loadAnalyticsMutualCorrelations();
    } catch (err) {
      console.error(err);
    }
  }

  function renderScatterChart(items) {
    const seriesData = items.map(item => ({
      x: parseFloat(item.turnover.toFixed(2)),
      y: parseFloat(item.sharpe.toFixed(2)),
      name: item.generator
    }));

    // Group series by generator type
    const grouped = {};
    seriesData.forEach(pt => {
      const grp = pt.name;
      if (!grouped[grp]) grouped[grp] = [];
      grouped[grp].push([pt.x, pt.y]);
    });

    const series = Object.keys(grouped).map(key => ({
      name: key,
      data: grouped[key]
    }));

    const options = {
      chart: {
        type: 'scatter',
        height: '100%',
        background: 'transparent',
        foreColor: 'var(--text-secondary)',
        toolbar: { show: false }
      },
      colors: ['#00e676', '#40c4ff', '#ffd740', '#ff5252', '#a855f7'],
      series: series,
      xaxis: {
        title: { text: 'Turnover Rate (%)' },
        labels: { formatter: val => `${val}%` }
      },
      yaxis: {
        title: { text: 'Sharpe Ratio' }
      },
      legend: { position: 'top', horizontalAlign: 'right' },
      theme: { mode: 'dark' },
      grid: { borderColor: 'var(--border-color)' }
    };

    if (scatterChart) scatterChart.destroy();
    scatterChart = new ApexCharts(document.getElementById("scatterChartWrapper"), options);
    scatterChart.render();
  }

  function renderFitnessBoxesChart(items) {
    // Collect Fitness by generator type
    const grouped = {};
    items.forEach(pt => {
      const key = pt.generator;
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(pt.fitness);
    });

    const series = Object.keys(grouped).map(key => {
      const vals = grouped[key].sort((a, b) => a - b);
      // Min, Q1, Median, Q3, Max box values
      const min = vals[0];
      const max = vals[vals.length - 1];
      const midIdx = Math.floor(vals.length / 2);
      const median = vals.length % 2 !== 0 ? vals[midIdx] : (vals[midIdx - 1] + vals[midIdx]) / 2;

      const q1Idx = Math.floor(vals.length / 4);
      const q1 = vals[q1Idx];
      const q3Idx = Math.floor(vals.length * 3 / 4);
      const q3 = vals[q3Idx];

      return {
        x: key,
        y: [
          parseFloat(min.toFixed(3)),
          parseFloat(q1.toFixed(3)),
          parseFloat(median.toFixed(3)),
          parseFloat(q3.toFixed(3)),
          parseFloat(max.toFixed(3))
        ]
      };
    });

    const options = {
      chart: {
        type: 'boxPlot',
        height: '100%',
        background: 'transparent',
        foreColor: 'var(--text-secondary)',
        toolbar: { show: false }
      },
      colors: ['#00e676', '#40c4ff'],
      series: [{ data: series }],
      yaxis: { title: { text: 'Fitness Score' } },
      grid: { borderColor: 'var(--border-color)' },
      theme: { mode: 'dark' }
    };

    if (fitnessChart) fitnessChart.destroy();
    fitnessChart = new ApexCharts(document.getElementById("fitnessChartWrapper"), options);
    fitnessChart.render();
  }

  function renderSharpeRangesChart(items) {
    const bins = {
      "< 0.5": 0, "0.5 - 1.0": 0, "1.0 - 1.5": 0, "1.5 - 2.0": 0, "2.0+": 0
    };

    items.forEach(pt => {
      const sh = pt.sharpe;
      if (sh < 0.5) bins["< 0.5"]++;
      else if (sh < 1.0) bins["0.5 - 1.0"]++;
      else if (sh < 1.5) bins["1.0 - 1.5"]++;
      else if (sh < 2.0) bins["1.5 - 2.0"]++;
      else bins["2.0+"]++;
    });

    const options = {
      chart: {
        type: 'bar',
        height: '100%',
        background: 'transparent',
        foreColor: 'var(--text-secondary)',
        toolbar: { show: false }
      },
      colors: ['#00e676'],
      plotOptions: {
        bar: { borderRadius: 4, horizontal: true }
      },
      series: [{
        name: 'Alpha Count',
        data: Object.values(bins)
      }],
      xaxis: {
        categories: Object.keys(bins),
        title: { text: 'Count of Candidates' }
      },
      grid: { borderColor: 'var(--border-color)' },
      theme: { mode: 'dark' }
    };

    if (sharpeDensityChart) sharpeDensityChart.destroy();
    sharpeDensityChart = new ApexCharts(document.getElementById("sharpeRangesChartWrapper"), options);
    sharpeDensityChart.render();
  }

  function renderAnalyticsAveragesTable(items) {
    const stats = {};
    items.forEach(item => {
      const key = item.generator;
      if (!stats[key]) {
        stats[key] = { count: 0, sharpe: 0, fitness: 0, turnover: 0, margin: 0 };
      }
      stats[key].count++;
      stats[key].sharpe += item.sharpe;
      stats[key].fitness += item.fitness;
      stats[key].turnover += item.turnover;
      stats[key].margin += item.margin;
    });

    const tbody = document.querySelector("#analyticsAveragesTable tbody");
    tbody.innerHTML = "";

    Object.keys(stats).forEach(engine => {
      const summary = stats[engine];
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-weight:600">${engine}</td>
        <td>${(summary.sharpe / summary.count).toFixed(3)}</td>
        <td>${(summary.fitness / summary.count).toFixed(3)}</td>
        <td>${(summary.turnover / summary.count).toFixed(2)}%</td>
        <td>${(summary.margin / summary.count).toFixed(3)}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  async function loadAnalyticsMutualCorrelations() {
    if (!activeProjectId) return;
    try {
      const res = await fetch(`/api/passed?project_id=${activeProjectId}`);
      const passed = await res.json();

      const matrixWrapper = document.getElementById("correlationMatrixWrapper");
      if (passed.length < 2) {
        matrixWrapper.style.display = "none";
        return;
      }

      matrixWrapper.style.display = "block";
      const tableHead = document.querySelector("#analyticsCorrelationMatrixTable scarcity thead");
      const tableBody = document.querySelector("#analyticsCorrelationMatrixTable tbody");

      // Clear
      document.querySelector("#analyticsCorrelationMatrixTable").innerHTML = `
        <thead><tr id="corrHeadRow"><th>Formula</th></tr></thead>
        <tbody></tbody>
      `;

      const headRow = document.getElementById("corrHeadRow");
      const tbody = document.querySelector("#analyticsCorrelationMatrixTable tbody");

      // Calculate a pseudo Jaccard-like or mock sub-universe similarity
      passed.forEach((p, idx) => {
        const th = document.createElement("th");
        th.style.fontSize = "10px";
        th.style.maxWidth = "120px";
        th.style.overflow = "hidden";
        th.style.textOverflow = "ellipsis";
        th.innerText = p.alpha_id === "Pending Registry" ? `P${idx + 1}` : p.alpha_id;
        th.title = p.expression;
        headRow.appendChild(th);
      });

      passed.forEach((p1, idx1) => {
        const tr = document.createElement("tr");
        const cellLabel = document.createElement("td");
        cellLabel.style.fontWeight = "600";
        cellLabel.innerText = p1.alpha_id === "Pending Registry" ? `P${idx1 + 1}` : p1.alpha_id;
        cellLabel.title = p1.expression;
        tr.appendChild(cellLabel);

        passed.forEach((p2, idx2) => {
          const td = document.createElement("td");
          td.style.textAlign = "center";
          // Similarity calculation heuristic based on overlapping characters of formulas
          let corr = 0.0;
          if (idx1 === idx2) {
            corr = 1.0;
          } else {
            // Overlapping word length comparison
            const w1 = new Set(p1.expression.toLowerCase().replace(/[^a-z0-9_]/g, " ").split(" "));
            const w2 = new Set(p2.expression.toLowerCase().replace(/[^a-z0-9_]/g, " ").split(" "));
            w1.delete(""); w2.delete("");
            const intersect = new Set([...w1].filter(x => w2.has(x)));
            const union = new Set([...w1, ...w2]);
            corr = union.size > 0 ? (intersect.size / union.size) : 0.0;
          }

          td.innerText = corr.toFixed(2);

          // Color highlighting based on density
          const alphaColor = Math.abs(corr);
          if (corr === 1.0) {
            td.style.color = "var(--primary-accent)";
            td.style.fontWeight = "bold";
          } else if (corr > 0.6) {
            td.style.backgroundColor = `rgba(255, 82, 82, ${alphaColor * 0.25})`;
            td.style.color = "var(--error)";
          } else {
            td.style.backgroundColor = `rgba(0, 230, 118, ${alphaColor * 0.15})`;
          }

          tr.appendChild(td);
        });

        tbody.appendChild(tr);
      });

    } catch (err) {
      console.error(err);
    }
  }

  function selectPassedAlpha(alpha) {
    // Highlight table row
    const rows = document.querySelectorAll("#passedAlphasTable tbody tr");
    rows.forEach(r => {
      const dbIdVal = r.getAttribute("data-db-id");
      if (dbIdVal === String(alpha.db_id)) {
        r.classList.add("active-row");
        r.style.backgroundColor = "var(--bg-hover)";
        r.style.borderLeft = "4px solid var(--primary-accent)";
      } else {
        r.classList.remove("active-row");
        r.style.backgroundColor = "";
        r.style.borderLeft = "";
      }
    });

    document.getElementById("inspectorDetailsPlaceholder").style.display = "none";
    const content = document.getElementById("inspectorDetailsContent");
    content.style.display = "block";

    // Set values
    document.getElementById("inspectAlphaId").innerText = alpha.alpha_id;
    document.getElementById("inspectGenerator").innerText = alpha.generator;
    document.getElementById("inspectExpression").innerText = alpha.expression;
    document.getElementById("inspectFamily").innerText = alpha.research_family || "N/A";
    document.getElementById("inspectComplexity").innerText = alpha.complexity_score || "N/A";

    const compScore = alpha.composite_research_score !== undefined ? alpha.composite_research_score : 0.0;
    document.getElementById("inspectCompositeScore").innerText = compScore.toFixed(3);

    // Components calculation from metrics
    const research = (alpha.sharpe / 6.0) + (alpha.fitness / 6.0);
    const simplicity = 1.0 - ((alpha.complexity_score || 1.0) - 1.0) / 19.0;
    const diversity = alpha.correlation_score !== undefined ? alpha.correlation_score : 1.0;

    const penalty = (alpha.parameter_sensitivity && alpha.parameter_sensitivity.penalty !== undefined)
      ? alpha.parameter_sensitivity.penalty
      : 1.0;
    const rawRobustness = ((alpha.walk_forward_score || 0.0) + (alpha.regime_score || 0.0)) / 2.0;
    const robustness = rawRobustness * penalty;

    document.getElementById("inspectSubResearch").innerText = Math.max(0.0, Math.min(1.0, research)).toFixed(2);
    document.getElementById("inspectSubRobustness").innerText = Math.max(0.0, Math.min(1.0, robustness)).toFixed(2);
    document.getElementById("inspectSubDiversity").innerText = Math.max(0.0, Math.min(1.0, diversity)).toFixed(2);
    document.getElementById("inspectSubSimplicity").innerText = Math.max(0.0, Math.min(1.0, simplicity)).toFixed(2);

    // IC stats
    document.getElementById("inspectRankIc").innerText = alpha.rank_ic !== undefined ? alpha.rank_ic.toFixed(4) : "N/A";
    document.getElementById("inspectIcIr").innerText = alpha.ic_ir !== undefined ? alpha.ic_ir.toFixed(4) : "N/A";
    const posRatio = alpha.positive_ic_ratio !== undefined ? (alpha.positive_ic_ratio * 100).toFixed(1) + "%" : "N/A";
    document.getElementById("inspectPosRatio").innerText = posRatio;
    document.getElementById("inspectWalkForward").innerText = alpha.walk_forward_score !== undefined ? alpha.walk_forward_score.toFixed(3) : "N/A";

    // Regimes
    document.getElementById("inspectRegimeScore").innerText = alpha.regime_score !== undefined ? alpha.regime_score.toFixed(3) : "N/A";
    const regPerf = alpha.regime_performance || {};
    document.getElementById("inspectLowVolSharpe").innerText = regPerf.sharpe_run_low !== undefined ? regPerf.sharpe_run_low.toFixed(3) : "N/A";
    document.getElementById("inspectHighVolSharpe").innerText = regPerf.sharpe_run_high !== undefined ? regPerf.sharpe_run_high.toFixed(3) : "N/A";

    // Sensitivity
    document.getElementById("inspectSensitivityPenalty").innerText = penalty.toFixed(2);
    const sensList = document.getElementById("inspectSensitivityList");
    sensList.innerHTML = "";

    const sensData = alpha.parameter_sensitivity || {};
    const corrs = sensData.correlations || [];
    if (corrs.length === 0) {
      sensList.innerHTML = '<div style="color: var(--text-secondary); font-style: italic;">No lookback parameters perturbed or identified.</div>';
    } else {
      corrs.forEach(item => {
        const itemDiv = document.createElement("div");
        itemDiv.style.display = "flex";
        itemDiv.style.justify = "space-between";
        itemDiv.style.padding = "2px 0";
        itemDiv.style.borderBottom = "1px solid rgba(255,255,255,0.03)";

        const codeSpan = document.createElement("span");
        codeSpan.style.fontFamily = "monospace";
        codeSpan.style.overflow = "hidden";
        codeSpan.style.textOverflow = "ellipsis";
        codeSpan.style.whiteSpace = "nowrap";
        codeSpan.style.maxWidth = "70%";
        codeSpan.innerText = item.expression;
        codeSpan.title = item.expression;

        const corrVal = document.createElement("strong");
        corrVal.innerText = item.correlation.toFixed(3);
        if (item.correlation > 0.85) {
          corrVal.style.color = "var(--primary-accent)";
        } else {
          corrVal.style.color = "var(--warning)";
        }

        itemDiv.appendChild(codeSpan);
        itemDiv.appendChild(corrVal);
        sensList.appendChild(itemDiv);
      });
    }
  }

  // Passed candidates results view
  async function loadPassedResults() {
    if (!activeProjectId) return;
    try {
      const res = await fetch(`/api/passed?project_id=${activeProjectId}`);
      const passed = await res.json();
      window.cachedPassed = passed;

      const tbody = document.querySelector("#passedAlphasTable tbody");
      tbody.innerHTML = "";

      const select = document.getElementById("passedRegistryAlphaSelector");
      select.innerHTML = "";

      if (passed.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">No qualified passed alphas recorded in this project context yet.</td></tr>';

        const opt = document.createElement("option");
        opt.value = "";
        opt.innerText = "No alphas available to register";
        select.appendChild(opt);

        document.getElementById("inspectorDetailsPlaceholder").style.display = "block";
        document.getElementById("inspectorDetailsContent").style.display = "none";
        return;
      }

      passed.forEach(p => {
        const tr = document.createElement("tr");
        tr.setAttribute("data-db-id", String(p.db_id));
        tr.addEventListener("click", () => selectPassedAlpha(p));

        const idTd = document.createElement("td");
        idTd.innerHTML = `<code>${p.alpha_id}</code>`;

        const exprTd = document.createElement("td");
        exprTd.style.fontFamily = "monospace";
        exprTd.innerText = p.expression;

        const sharpeTd = document.createElement("td");
        sharpeTd.innerText = p.sharpe;

        const fitnessTd = document.createElement("td");
        fitnessTd.innerText = p.fitness;

        const turnTd = document.createElement("td");
        turnTd.innerText = `${p.turnover}%`;

        const marginTd = document.createElement("td");
        marginTd.innerText = p.margin;

        const genTd = document.createElement("td");
        genTd.innerHTML = `<span class="badge" style="background:var(--bg-hover); border:1px solid var(--border-color); color:var(--primary-accent)">${p.generator}</span>`;

        tr.appendChild(idTd);
        tr.appendChild(exprTd);
        tr.appendChild(sharpeTd);
        tr.appendChild(fitnessTd);
        tr.appendChild(turnTd);
        tr.appendChild(marginTd);
        tr.appendChild(genTd);
        tbody.appendChild(tr);

        // Add to selector drop down if registered ID exists
        if (p.alpha_id && p.alpha_id !== "Pending Registry") {
          const opt = document.createElement("option");
          opt.value = p.alpha_id;
          opt.innerText = `${p.alpha_id} (${p.expression.substring(0, 30)}...)`;
          select.appendChild(opt);
        }
      });

      if (select.children.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.innerText = "No registered Alpha IDs found (Wait for worker polling)";
        select.appendChild(opt);
      }

      // Auto-select first row
      if (passed.length > 0) {
        selectPassedAlpha(passed[0]);
      } else {
        document.getElementById("inspectorDetailsPlaceholder").style.display = "block";
        document.getElementById("inspectorDetailsContent").style.display = "none";
      }
    } catch (err) {
      console.error(err);
    }
  }

  function downloadPassedFile(format) {
    const list = window.cachedPassed || [];
    if (list.length === 0) {
      alert("No passed alphas found to export!");
      return;
    }

    let fileContent = "";
    let mimeType = "";
    let filename = `passed_alphas_${activeProjectId}_${new Date().toISOString().slice(0, 10).replace(/-/g, "")}`;

    if (format === "csv") {
      mimeType = "text/csv;charset=utf-8;";
      filename += ".csv";

      const headers = ["Alpha ID", "Expression Formula", "Sharpe", "Fitness", "Turnover (%)", "Margin (bps)", "Generator"];
      fileContent = headers.join(",") + "\r\n";

      list.forEach(p => {
        const row = [
          `"${p.alpha_id}"`,
          `"${p.expression.replace(/"/g, '""')}"`,
          p.sharpe,
          p.fitness,
          p.turnover,
          p.margin,
          `"${p.generator}"`
        ];
        fileContent += row.join(",") + "\r\n";
      });
    } else {
      mimeType = "application/json;charset=utf-8;";
      filename += ".json";
      fileContent = JSON.stringify(list, null, 2);
    }

    const blob = new Blob([fileContent], { type: mimeType });
    const link = document.createElement("a");
    if (link.download !== undefined) {
      const url = URL.createObjectURL(blob);
      link.setAttribute("href", url);
      link.setAttribute("download", filename);
      link.style.visibility = 'hidden';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  }

  async function handleRegistrySubmission() {
    const alphaId = document.getElementById("passedRegistryAlphaSelector").value;
    const feedback = document.getElementById("registryFeedbackMessage");

    if (!alphaId) {
      alert("Select a valid Alpha ID to register.");
      return;
    }

    feedback.innerText = "Submitting alpha registry request...";
    feedback.className = "alert alert-info";

    try {
      const res = await fetch("/api/passed/submit-registry", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ alpha_id: alphaId })
      });
      const data = await res.json();

      if (res.ok) {
        feedback.innerText = `Registry Submission Completed: ${data.message}`;
        feedback.className = "alert alert-info";
        feedback.style.color = "var(--primary-accent)";
      } else {
        feedback.innerText = `Failed: ${data.message || data.detail}`;
        feedback.className = "alert alert-error";
      }
    } catch (err) {
      feedback.innerText = `Network error: ${err.message}`;
      feedback.className = "alert alert-error";
    }
  }

  async function handleRegistrySubmissionAll() {
    if (!activeProjectId) {
      alert("Select a valid farming project context first.");
      return;
    }
    const feedback = document.getElementById("registryFeedbackMessage");
    feedback.innerText = "Submitting all qualified alphas...";
    feedback.className = "alert alert-info";

    try {
      const res = await fetch("/api/passed/submit-all-registry", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({ project_id: activeProjectId })
      });
      const data = await res.json();
      if (res.ok) {
        feedback.innerText = `Bulk Registry Completed: ${data.message}`;
        feedback.className = "alert alert-info";
      } else {
        feedback.innerText = `Failed: ${data.message || data.detail}`;
        feedback.className = "alert alert-error";
      }
    } catch (err) {
      feedback.innerText = `Network error: ${err.message}`;
      feedback.className = "alert alert-error";
    }
  }
});
