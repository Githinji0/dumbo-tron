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
  let fitnessTurnoverChart = null;
  let sharpeFitnessChart = null;

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
      stopLogsTabPolling();
    } else if (viewId === "analytics") {
      stopQueuePolling();
      startAnalyticsPolling();
      stopLogsTabPolling();
    } else if (viewId === "project-logs-tab") {
      stopQueuePolling();
      stopAnalyticsPolling();
      updateLogsViewWarnings();
      startLogsTabPolling();
    } else if (viewId === "ai-assistant") {
      stopQueuePolling();
      stopAnalyticsPolling();
      stopLogsTabPolling();
      loadAiConfig();
    } else {
      stopQueuePolling();
      stopAnalyticsPolling();
      stopLogsTabPolling();
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

    // Cancel simulations
    document.getElementById("btnCancelAllSimulations").addEventListener("click", handleCancelAllSimulations);

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

    // Diagnostics tab action events
    document.getElementById("btnRefreshDiagnostics").addEventListener("click", () => {
      loadDiagnosticsLogs();
    });
    document.getElementById("filterLogLevelSelect").addEventListener("change", () => {
      loadDiagnosticsLogs();
    });
    document.getElementById("inputLogSearch").addEventListener("input", () => {
      loadDiagnosticsLogs();
    });
    document.getElementById("selectLogLimit").addEventListener("change", () => {
      loadDiagnosticsLogs();
    });

    // Report modal triggers
    document.getElementById("btnGenerateReport").addEventListener("click", handleGenerateDiagnosticReport);

    // Close report modal
    const closeModal = () => {
      document.getElementById("logsReportModal").style.display = "none";
    };
    document.getElementById("closeReportModal").addEventListener("click", closeModal);
    document.getElementById("btnCloseReportBtn").addEventListener("click", closeModal);
    document.getElementById("logsReportModal").addEventListener("click", (e) => {
      if (e.target === document.getElementById("logsReportModal")) {
        closeModal();
      }
    });

    // Close log detail modal
    const closeLogDetailModal = () => {
      document.getElementById("logDetailModal").style.display = "none";
    };
    document.getElementById("closeLogDetailModal").addEventListener("click", closeLogDetailModal);
    document.getElementById("btnCloseLogDetailBtn").addEventListener("click", closeLogDetailModal);
    document.getElementById("logDetailModal").addEventListener("click", (e) => {
      if (e.target === document.getElementById("logDetailModal")) {
        closeLogDetailModal();
      }
    });

    // Copy Formula inside detail modal
    document.getElementById("btnCopyDetailFormula").addEventListener("click", (e) => {
      const textToCopy = e.currentTarget._formulaText;
      if (textToCopy) {
        navigator.clipboard.writeText(textToCopy)
          .then(() => {
            const orgText = e.currentTarget.innerHTML;
            e.currentTarget.innerHTML = '<i data-lucide="check"></i> Copied!';
            lucide.createIcons();
            setTimeout(() => {
              e.currentTarget.innerHTML = orgText;
              lucide.createIcons();
            }, 2000);
          })
          .catch(err => {
            console.error("Clipboard copy failed:", err);
          });
      }
    });

    // Export log buttons
    document.getElementById("btnExportLogsCSV").addEventListener("click", () => handleExportLogs("csv"));
    document.getElementById("btnExportLogsTXT").addEventListener("click", () => handleExportLogs("txt"));
    document.getElementById("btnExportLogsMD").addEventListener("click", () => handleExportLogs("md"));
    document.getElementById("btnDownloadReportMD").addEventListener("click", handleDownloadReportFile);

    // Export Result Files
    document.getElementById("btnExportCSV").addEventListener("click", () => downloadPassedFile("csv"));
    document.getElementById("btnExportJSON").addEventListener("click", () => downloadPassedFile("json"));

    // Filter controls for Passed Alphas
    document.getElementById("filterParetoOnly").addEventListener("change", loadPassedResults);
    document.getElementById("filterTierSelect").addEventListener("change", loadPassedResults);

    // Submit Alpha to Registry
    document.getElementById("btnSubmitToRegistry").addEventListener("click", handleRegistrySubmission);
    document.getElementById("btnSubmitAllToRegistry").addEventListener("click", handleRegistrySubmissionAll);

    // AI Assistant Handlers
    document.getElementById("btnSaveAiKey").addEventListener("click", handleSaveAiConfig);
    document.getElementById("btnClearAiChat").addEventListener("click", handleClearAiChat);
    document.getElementById("btnSendAiMessage").addEventListener("click", handleSendAiMessage);
    document.getElementById("aiProviderSelect").addEventListener("change", handleAiProviderChange);
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
    updateLogsViewWarnings();

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

  function updateLogsViewWarnings() {
    const warning = document.getElementById("logsProjectWarning");
    const container = document.getElementById("logsContentWrapper");
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
      starTd.style.cursor = "pointer";
      starTd.innerHTML = `<i data-lucide="star" class="fav-star ${f.is_favorite ? 'active' : ''}"></i>`;
      starTd.addEventListener("click", () => handleFieldFavoriteToggle(f.id));

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
      const matchesQuery =
        (f.id || "").toLowerCase().includes(query) ||
        (f.name || "").toLowerCase().includes(query) ||
        (f.category || "").toLowerCase().includes(query);
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
    pollIntervalId = setInterval(loadQueueData, 2000);
  }

  function stopQueuePolling() {
    if (pollIntervalId) {
      clearInterval(pollIntervalId);
      pollIntervalId = null;
    }
  }

  let logsTabPollingId = null;

  function startLogsTabPolling() {
    stopLogsTabPolling();
    loadDiagnosticsLogs();
    logsTabPollingId = setInterval(loadDiagnosticsLogs, 5000);
  }

  function stopLogsTabPolling() {
    if (logsTabPollingId) {
      clearInterval(logsTabPollingId);
      logsTabPollingId = null;
    }
  }

  async function handleCancelAllSimulations() {
    if (!activeProjectId) return;
    if (!confirm("Are you sure you want to stop all active simulations for this project?")) {
      return;
    }
    try {
      const res = await fetch(`/api/queue/stop?project_id=${activeProjectId}`, {
        method: "POST",
        headers: getHeaders()
      });
      if (res.ok) {
        const data = await res.json();
        alert(`Stopped ${data.stopped_count} active simulations.`);
        loadQueueData();
      } else {
        const data = await res.json();
        alert("Failed to stop simulations: " + (data.detail || "Unknown error"));
      }
    } catch (err) {
      console.error(err);
      alert("Error: " + err.message);
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

  // --- Virtual scroll state ---
  let _vsLogs = [];        // full data array
  const ROW_HEIGHT = 72;   // estimated px per log row
  const VS_BUFFER = 5;    // extra rows to render above/below viewport
  let _vsRafPending = false;

  function vsSetup() {
    const viewport = document.getElementById("logsFeedViewport");
    if (!viewport) return;

    // Max height: fill remaining page up to 80vh
    viewport.style.maxHeight = "80vh";
    viewport.style.minHeight = "120px";

    viewport.addEventListener("scroll", vsOnScroll, { passive: true });

    // Keep layout correct when window resizes
    if (window._vsResizeObs) window._vsResizeObs.disconnect();
    window._vsResizeObs = new ResizeObserver(() => vsRender());
    window._vsResizeObs.observe(viewport);
  }

  function vsOnScroll() {
    if (_vsRafPending) return;
    _vsRafPending = true;
    requestAnimationFrame(() => {
      _vsRafPending = false;
      vsRender();
    });
  }

  function vsRender() {
    const viewport = document.getElementById("logsFeedViewport");
    const list = document.getElementById("logsFeedList");
    const spacer = document.getElementById("logsFeedSpacer");
    if (!viewport || !list || !spacer) return;

    const totalRows = _vsLogs.length;
    const totalHeight = totalRows * ROW_HEIGHT;

    // Spacer controls scrollbar range
    spacer.style.height = totalHeight + "px";

    const scrollTop = viewport.scrollTop;
    const vpHeight = viewport.clientHeight;
    const startIdx = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - VS_BUFFER);
    const endIdx = Math.min(totalRows, Math.ceil((scrollTop + vpHeight) / ROW_HEIGHT) + VS_BUFFER);

    list.innerHTML = "";
    list.style.transform = `translateY(${startIdx * ROW_HEIGHT}px)`;

    for (let i = startIdx; i < endIdx; i++) {
      const log = _vsLogs[i];
      const div = document.createElement("div");
      div.className = `log-line ${log.level}`;
      div.style.height = ROW_HEIGHT + "px";
      const formattedMsg = log.message.replace(/\n/g, "<br>").replace(/  /g, "&nbsp;&nbsp;");
      div.innerHTML = `<span>[${log.timestamp}]</span> ${formattedMsg}`;
      div.addEventListener("click", () => showLogDetail(log));
      list.appendChild(div);
    }
  }

  async function loadDiagnosticsLogs() {
    if (!activeProjectId) return;
    try {
      const level = document.getElementById("filterLogLevelSelect").value;
      const search = document.getElementById("inputLogSearch").value;
      const limit = document.getElementById("selectLogLimit").value;

      let url = `/api/logs?project_id=${activeProjectId}&limit=${limit}`;
      if (level && level !== "ALL") url += `&level=${encodeURIComponent(level)}`;
      if (search && search.trim() !== "") url += `&search=${encodeURIComponent(search.trim())}`;

      const res = await fetch(url);
      const logs = await res.json();

      const viewport = document.getElementById("logsFeedViewport");
      const list = document.getElementById("logsFeedList");
      if (!viewport || !list) return;

      if (logs.length === 0) {
        _vsLogs = [];
        list.innerHTML = '<p class="placeholder-text">No message logs captured matching criteria...</p>';
        document.getElementById("logsFeedSpacer").style.height = "0px";
        return;
      }

      _vsLogs = logs;
      vsSetup();
      viewport.scrollTop = 0;
      vsRender();
    } catch (err) {
      console.error(err);
    }
  }

  function parseLogMessage(msg) {
    const result = {
      title: "Log Detail",
      formula: "",
      metrics: [],
      advice: "",
      rawHtml: ""
    };

    if (msg.includes("Alpha Mined Passed") || msg.includes("Mined Passed")) {
      result.title = "Alpha Mined Passed Result";
    } else if (msg.includes("Alpha Rejected") || msg.includes("Rejected")) {
      result.title = "Alpha Mined Rejected Result";
    } else if (msg.includes("Simulation ERROR")) {
      result.title = "Simulation Error Diagnostic";
    } else if (msg.includes("Pre-Screen Filter")) {
      result.title = "Pre-Screen Logic Filtered";
    } else if (msg.includes("Duplicate Checker")) {
      result.title = "Duplicate Expression Filtered";
    } else if (msg.includes("Correlation Filter")) {
      result.title = "Correlation Filtered";
    }

    // Try parsing formula
    const formulaMatch = msg.match(/Formula:\s*['"](.+?)['"]/s) || msg.match(/Formula:\s*(.+?)(\n|$)/s);
    if (formulaMatch) {
      result.formula = formulaMatch[1].trim();
    }

    // Try parsing metrics comparison
    const metricLines = [...msg.matchAll(/-\s*([^:]+):\s*([^(]+?)\s*\(([^)]+?)\)\s*->\s*(PASS|FAIL)/g)];
    if (metricLines.length > 0) {
      metricLines.forEach(m => {
        result.metrics.push({
          name: m[1].trim(),
          value: m[2].trim(),
          expected: m[3].trim(),
          status: m[4].trim()
        });
      });
    } else {
      const subUnivMatch = msg.match(/-\s*Sub-Universe Sharpe:\s*([^\s]+?)\s*\(Expected\s*([^)]+?)\)/);
      if (subUnivMatch) {
        const isPass = subUnivMatch[1].toUpperCase() === "PASS" || subUnivMatch[1].toUpperCase().includes("PASS");
        result.metrics.push({
          name: "Sub-Universe Sharpe",
          value: subUnivMatch[1],
          expected: subUnivMatch[2],
          status: isPass ? "PASS" : "FAIL"
        });
      }
    }

    // Try parsing Advice
    const adviceIndex = msg.indexOf("Advice:");
    if (adviceIndex !== -1) {
      result.advice = msg.substring(adviceIndex + 7).trim();
    }

    result.rawHtml = msg.replace(/\n/g, "<br>").replace(/  /g, "&nbsp;&nbsp;");
    return result;
  }

  function showLogDetail(log) {
    try {
      console.log("showLogDetail called for log:", log);
      const parsed = parseLogMessage(log.message);

      const tsElem = document.getElementById("logDetailTimestamp");
      if (tsElem) tsElem.innerText = log.timestamp;

      const levelBadge = document.getElementById("logDetailLevel");
      if (levelBadge) {
        levelBadge.innerText = log.level;
        levelBadge.className = `status-pill ${log.level.toLowerCase()}`;
      }

      const titleElem = document.getElementById("logDetailTitle");
      if (titleElem) {
        titleElem.innerHTML = `<i data-lucide="info"></i> ${parsed.title}`;
      }

      const body = document.getElementById("logDetailBody");
      if (body) {
        body.innerHTML = "";

        if (parsed.formula) {
          const formCard = document.createElement("div");
          formCard.innerHTML = `
            <label><strong>Alpha Expression Formula:</strong></label>
            <div style="background: var(--bg-primary); font-family: monospace; padding: 12px; border-radius: 6px; border: 1px solid var(--border-color); color: var(--primary-accent); word-break: break-all; margin-top: 5px;">
              ${parsed.formula}
            </div>
          `;
          body.appendChild(formCard);

          const copyBtn = document.getElementById("btnCopyDetailFormula");
          if (copyBtn) {
            copyBtn.style.display = "inline-flex";
            copyBtn._formulaText = parsed.formula;
          }
        } else {
          const copyBtn = document.getElementById("btnCopyDetailFormula");
          if (copyBtn) copyBtn.style.display = "none";
        }

        if (parsed.metrics.length > 0) {
          const tableCard = document.createElement("div");
          tableCard.innerHTML = `
            <label style="display:block; margin-bottom:6px;"><strong>Metrics Validation Check:</strong></label>
            <table class="grid-table" style="min-width: 100%; border: 1px solid var(--border-color); border-radius: 6px;">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Observed</th>
                  <th>Target Threshold</th>
                  <th style="text-align: center;">Status</th>
                </tr>
              </thead>
              <tbody id="modalChecklistBody"></tbody>
            </table>
          `;
          body.appendChild(tableCard);

          const tbody = tableCard.querySelector("#modalChecklistBody");
          parsed.metrics.forEach(m => {
            const tr = document.createElement("tr");
            const statusClass = m.status === "PASS" ? "complete" : "error";
            tr.innerHTML = `
              <td><strong>${m.name}</strong></td>
              <td>${m.value}</td>
              <td>${m.expected}</td>
              <td style="text-align: center;"><span class="status-pill ${statusClass}">${m.status}</span></td>
            `;
            tbody.appendChild(tr);
          });
        }

        if (parsed.advice) {
          const advCard = document.createElement("div");
          const adviceUnits = parsed.advice.split("|").map(x => x.trim()).filter(Boolean);
          let listItems = "";
          adviceUnits.forEach(u => {
            listItems += `<li style="margin-bottom: 8px;">${u}</li>`;
          });

          advCard.innerHTML = `
            <div class="alert alert-warning" style="margin: 0; padding: 15px; border-left: 4px solid var(--warning); background-color: rgba(255, 215, 64, 0.05); border-color: rgba(255, 215, 64, 0.2);">
              <div style="font-weight: 600; display:flex; align-items:center; gap:6px; margin-bottom:8px; color: var(--warning);">
                <i data-lucide="lightbulb" style="width:16px; height:16px;"></i> Optimization Recommendations
              </div>
              <ul class="bullet-list-small" style="margin:0; padding-left: 20px;">
                ${listItems}
              </ul>
            </div>
          `;
          body.appendChild(advCard);
        }

        if (!parsed.formula && parsed.metrics.length === 0 && !parsed.advice) {
          const fallbackCard = document.createElement("div");
          fallbackCard.innerHTML = `
            <label><strong>Log Message Details:</strong></label>
            <div style="background: var(--bg-primary); border: 1px solid var(--border-color); padding: 15px; border-radius: 6px; font-family: monospace; white-space: pre-wrap; margin-top: 5px; line-height: 1.5;">
              ${parsed.rawHtml}
            </div>
          `;
          body.appendChild(fallbackCard);
        }
      }

      const modal = document.getElementById("logDetailModal");
      if (modal) {
        modal.style.display = "flex";
      }
      if (window.lucide) {
        lucide.createIcons();
      }
    } catch (e) {
      console.error("Error displaying log detail:", e);
      alert("Error displaying log detail: " + e.message);
    }
  }

  let currentReportMarkdown = "";

  async function handleGenerateDiagnosticReport() {
    if (!activeProjectId) return;
    const modal = document.getElementById("logsReportModal");
    const body = document.getElementById("reportModalBody");

    body.innerText = "Generating diagnostic report from latest logs...";
    modal.style.display = "flex";

    try {
      const res = await fetch(`/api/logs/report?project_id=${activeProjectId}`);
      const data = await res.json();
      if (res.ok) {
        currentReportMarkdown = data.report;
        body.innerText = data.report;
      } else {
        body.innerText = "Error generating report: " + (data.detail || "Unknown error");
      }
    } catch (err) {
      body.innerText = "Network error: " + err.message;
    }
  }

  async function handleExportLogs(format) {
    if (!activeProjectId) return;
    const level = document.getElementById("filterLogLevelSelect").value;
    const search = document.getElementById("inputLogSearch").value;

    let url = `/api/logs/export?project_id=${activeProjectId}&format=${format}`;
    if (level && level !== "ALL") {
      url += `&level=${encodeURIComponent(level)}`;
    }
    if (search && search.trim() !== "") {
      url += `&search=${encodeURIComponent(search.trim())}`;
    }

    window.open(url, "_blank");
  }

  function handleDownloadReportFile() {
    if (!currentReportMarkdown) {
      alert("Please generate a report first.");
      return;
    }
    const blob = new Blob([currentReportMarkdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `project_${activeProjectId}_diagnostic_report.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // Analytics tab
  async function loadAnalyticsData() {
    if (!activeProjectId) return;
    try {
      const res = await fetch(`/api/analytics?project_id=${activeProjectId}`);
      const data = await res.json();

      const emptyAlert = document.getElementById("analyticsEmptyAlert");
      const chartsGrid = document.getElementById("analyticsChartsGrid");
      const kpiRow = document.getElementById("analyticsKpiRow");
      const statsSection = document.getElementById("analyticsStatsSection");

      if (data.length === 0) {
        emptyAlert.style.display = "block";
        chartsGrid.style.display = "none";
        if (kpiRow) kpiRow.style.display = "none";
        if (statsSection) statsSection.style.display = "none";
        return;
      }

      emptyAlert.style.display = "none";
      chartsGrid.style.display = "grid";

      // === KPI Row ===
      if (kpiRow) {
        const passed = data.filter(d => d.pareto_optimal || d.tier === 0);
        const passRate = data.length > 0 ? ((passed.length / data.length) * 100).toFixed(1) : 0;
        const bestSharpe = Math.max(...data.map(d => d.sharpe)).toFixed(3);
        const avgSharpe = (data.reduce((s, d) => s + d.sharpe, 0) / data.length).toFixed(3);
        const avgFitness = (data.reduce((s, d) => s + d.fitness, 0) / data.length).toFixed(3);
        const avgTO = (data.reduce((s, d) => s + d.turnover, 0) / data.length).toFixed(1);

        document.getElementById("kpiTotalSimulations").innerText = data.length;
        document.getElementById("kpiPassRate").innerText = passRate + "%";
        document.getElementById("kpiBestSharpe").innerText = bestSharpe;
        document.getElementById("kpiAvgSharpe").innerText = avgSharpe;
        document.getElementById("kpiAvgFitness").innerText = avgFitness;
        document.getElementById("kpiAvgTurnover").innerText = avgTO + "%";
        kpiRow.style.display = "grid";
        if (window.lucide) lucide.createIcons();
      }

      // Render Charts & Statistics values
      renderScatterChart(data);
      renderFitnessTurnoverChart(data);
      renderSharpeFitnessChart(data);
      renderAnalyticsAveragesTable(data);
      if (statsSection) statsSection.style.display = "block";

      // Calculate mutual correlations if we have passed alphas
      loadAnalyticsMutualCorrelations();
    } catch (err) {
      console.error(err);
    }
  }

  function renderScatterChart(items) {
    // 1. Turnover vs Sharpe (x = turnover, y = sharpe)
    const grouped = { "Pareto Frontier": [] };

    items.forEach(item => {
      const x = parseFloat(item.turnover.toFixed(2));
      const y = parseFloat(item.sharpe.toFixed(3));
      if (item.pareto_optimal) {
        grouped["Pareto Frontier"].push([x, y]);
      } else {
        const grp = item.generator || "Standard Generator";
        if (!grouped[grp]) grouped[grp] = [];
        grouped[grp].push([x, y]);
      }
    });

    const series = Object.keys(grouped)
      .filter(k => grouped[k].length > 0)
      .map(key => ({
        name: key,
        data: grouped[key]
      }));

    const options = {
      chart: {
        type: 'scatter',
        height: '100%',
        background: 'transparent',
        foreColor: 'var(--text-secondary)',
        toolbar: { show: true }
      },
      colors: ['#ff007f', '#00e676', '#40c4ff', '#ffd740', '#ff5252', '#a855f7'],
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

  function renderFitnessTurnoverChart(items) {
    // 2. Fitness vs Turnover (x = turnover, y = fitness)
    const grouped = { "Pareto Frontier": [] };

    items.forEach(item => {
      const x = parseFloat(item.turnover.toFixed(2));
      const y = parseFloat(item.fitness.toFixed(3));
      if (item.pareto_optimal) {
        grouped["Pareto Frontier"].push([x, y]);
      } else {
        const grp = item.generator || "Standard Generator";
        if (!grouped[grp]) grouped[grp] = [];
        grouped[grp].push([x, y]);
      }
    });

    const series = Object.keys(grouped)
      .filter(k => grouped[k].length > 0)
      .map(key => ({
        name: key,
        data: grouped[key]
      }));

    const options = {
      chart: {
        type: 'scatter',
        height: '100%',
        background: 'transparent',
        foreColor: 'var(--text-secondary)',
        toolbar: { show: true }
      },
      colors: ['#ff007f', '#00e676', '#40c4ff', '#ffd740', '#ff5252', '#a855f7'],
      series: series,
      xaxis: {
        title: { text: 'Turnover Rate (%)' },
        labels: { formatter: val => `${val}%` }
      },
      yaxis: {
        title: { text: 'Fitness Score' }
      },
      legend: { position: 'top', horizontalAlign: 'right' },
      theme: { mode: 'dark' },
      grid: { borderColor: 'var(--border-color)' }
    };

    if (fitnessTurnoverChart) fitnessTurnoverChart.destroy();
    fitnessTurnoverChart = new ApexCharts(document.getElementById("fitnessTurnoverChartWrapper"), options);
    fitnessTurnoverChart.render();
  }

  function renderSharpeFitnessChart(items) {
    // 3. Sharpe vs Fitness (x = fitness, y = sharpe)
    const grouped = { "Pareto Frontier": [] };

    items.forEach(item => {
      const x = parseFloat(item.fitness.toFixed(3));
      const y = parseFloat(item.sharpe.toFixed(3));
      if (item.pareto_optimal) {
        grouped["Pareto Frontier"].push([x, y]);
      } else {
        const grp = item.generator || "Standard Generator";
        if (!grouped[grp]) grouped[grp] = [];
        grouped[grp].push([x, y]);
      }
    });

    const series = Object.keys(grouped)
      .filter(k => grouped[k].length > 0)
      .map(key => ({
        name: key,
        data: grouped[key]
      }));

    const options = {
      chart: {
        type: 'scatter',
        height: '100%',
        background: 'transparent',
        foreColor: 'var(--text-secondary)',
        toolbar: { show: true }
      },
      colors: ['#ff007f', '#00e676', '#40c4ff', '#ffd740', '#ff5252', '#a855f7'],
      series: series,
      xaxis: {
        title: { text: 'Fitness Score' }
      },
      yaxis: {
        title: { text: 'Sharpe Ratio' }
      },
      legend: { position: 'top', horizontalAlign: 'right' },
      theme: { mode: 'dark' },
      grid: { borderColor: 'var(--border-color)' }
    };

    if (sharpeFitnessChart) sharpeFitnessChart.destroy();
    sharpeFitnessChart = new ApexCharts(document.getElementById("sharpeFitnessChartWrapper"), options);
    sharpeFitnessChart.render();
  }

  function renderAnalyticsAveragesTable(items) {
    const stats = {};
    items.forEach(item => {
      const key = item.generator || "Standard";
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
      const s = stats[engine];
      const n = s.count;
      const avgSharpe = (s.sharpe / n).toFixed(3);
      const avgFitness = (s.fitness / n).toFixed(3);
      const avgTO = (s.turnover / n).toFixed(2);
      const avgMargin = (s.margin / n).toFixed(3);
      // colour-code sharpe value
      const sharpeVal = parseFloat(avgSharpe);
      const sharpeColor = sharpeVal >= 1.5 ? "var(--primary-accent)" : sharpeVal >= 1.0 ? "var(--warning)" : "var(--error)";

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-weight:600">${engine}</td>
        <td>${n}</td>
        <td style="color:${sharpeColor}; font-weight:600">${avgSharpe}</td>
        <td>${avgFitness}</td>
        <td>${avgTO}%</td>
        <td>${avgMargin}</td>
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

    const isParetoText = alpha.pareto_optimal ? "Yes" : "No";
    document.getElementById("inspectTierPareto").innerText = `Tier ${alpha.candidate_tier} / Pareto: ${isParetoText}`;

    // Populate Hypothesis and Lineage details
    document.getElementById("inspectHypothesis").innerText = alpha.hypothesis || "N/A";
    document.getElementById("inspectLineageId").innerText = alpha.lineage_id !== undefined && alpha.lineage_id !== null ? alpha.lineage_id : "N/A";
    document.getElementById("inspectParentId").innerText = alpha.parent_id !== undefined && alpha.parent_id !== null ? alpha.parent_id : "N/A";
    document.getElementById("inspectGeneration").innerText = alpha.generation_number !== undefined && alpha.generation_number !== null ? alpha.generation_number : "0";

    // Build optimization trace flowchart
    let trace = [];
    let curr = alpha;
    const allAlphas = window.cachedPassed || [];
    while (curr) {
      trace.unshift(curr);
      const parentId = curr.parent_id !== undefined ? curr.parent_id : curr.transformation_parent;
      if (parentId !== undefined && parentId !== null) {
        const found = allAlphas.find(x => x.db_id === parentId);
        if (found && found !== curr) {
          curr = found;
        } else {
          break;
        }
      } else {
        break;
      }
    }
    let traceText = "";
    trace.forEach((node, idx) => {
      if (idx > 0) {
        const type = node.transformation_type || node.mutation_type || "MUTATION";
        traceText += `\n       ↓ [${type}]\n\n`;
      }
      traceText += `${node.generator || "Base"} (ID: ${node.db_id})
  Expr: ${node.expression}
  Sharpe: ${node.sharpe.toFixed(3)} | Fitness: ${node.fitness.toFixed(3)} | Turnover: ${node.turnover.toFixed(2)}%`;
    });
    document.getElementById("inspectEvolutionTrace").innerText = traceText || "No evolutionary lineage path identified.";

    const compScore = alpha.alpha_research_score !== undefined ? alpha.alpha_research_score : 0.0;
    document.getElementById("inspectCompositeScore").innerText = compScore.toFixed(3);

    // Dynamic multi-factor scoring details retrieved from backend
    const research = alpha.composite_research_score !== undefined ? alpha.composite_research_score : 0.0;
    const robustness = alpha.robustness_score !== undefined ? alpha.robustness_score : 0.0;
    const diversity = alpha.diversity_score !== undefined ? alpha.diversity_score : 1.0;
    const simplicity = alpha.simplicity_score !== undefined ? alpha.simplicity_score : 1.0;

    document.getElementById("inspectSubResearch").innerText = research.toFixed(2);
    document.getElementById("inspectSubRobustness").innerText = robustness.toFixed(2);
    document.getElementById("inspectSubDiversity").innerText = diversity.toFixed(2);
    document.getElementById("inspectSubSimplicity").innerText = simplicity.toFixed(2);

    // IC stats
    document.getElementById("inspectRankIc").innerText = alpha.rank_ic !== undefined ? alpha.rank_ic.toFixed(4) : "N/A";
    document.getElementById("inspectIcIr").innerText = alpha.ic_ir !== undefined ? alpha.ic_ir.toFixed(4) : "N/A";
    const posRatio = alpha.positive_ic_ratio !== undefined ? (alpha.positive_ic_ratio * 100).toFixed(1) + "%" : "N/A";
    document.getElementById("inspectPosRatio").innerText = posRatio;

    // Detailed Walk-forward output
    const wfMin = alpha.walk_forward_min_sharpe !== undefined ? alpha.walk_forward_min_sharpe.toFixed(2) : "N/A";
    const wfMed = alpha.walk_forward_median_sharpe !== undefined ? alpha.walk_forward_median_sharpe.toFixed(2) : "N/A";
    document.getElementById("inspectWalkForward").innerText = `Score: ${alpha.walk_forward_score.toFixed(2)} (Med: ${wfMed}, Min: ${wfMin})`;

    // Regimes
    document.getElementById("inspectRegimeScore").innerText = alpha.regime_score !== undefined ? alpha.regime_score.toFixed(3) : "N/A";
    const regPerf = alpha.regime_performance || {};
    document.getElementById("inspectLowVolSharpe").innerText = regPerf.sharpe_run_low !== undefined ? regPerf.sharpe_run_low.toFixed(3) : "N/A";
    document.getElementById("inspectHighVolSharpe").innerText = regPerf.sharpe_run_high !== undefined ? regPerf.sharpe_run_high.toFixed(3) : "N/A";

    // Sensitivity
    const penalty = alpha.parameter_stability_score !== undefined ? alpha.parameter_stability_score : 1.0;
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

      // Extract client-side checkbox and dropdown filters
      const paretoOnly = document.getElementById("filterParetoOnly").checked;
      const tierFilter = document.getElementById("filterTierSelect").value;

      let filtered = passed;
      if (paretoOnly) {
        filtered = filtered.filter(p => p.pareto_optimal);
      }
      if (tierFilter !== "ALL") {
        const targetTier = parseInt(tierFilter);
        filtered = filtered.filter(p => p.candidate_tier === targetTier);
      }

      const tbody = document.querySelector("#passedAlphasTable tbody");
      tbody.innerHTML = "";

      const select = document.getElementById("passedRegistryAlphaSelector");
      select.innerHTML = "";

      if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">No alphas match the filter criteria.</td></tr>';

        const opt = document.createElement("option");
        opt.value = "";
        opt.innerText = "No alphas available to register";
        select.appendChild(opt);

        document.getElementById("inspectorDetailsPlaceholder").style.display = "block";
        document.getElementById("inspectorDetailsContent").style.display = "none";
        return;
      }

      filtered.forEach(p => {
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

        const tierTd = document.createElement("td");
        tierTd.innerHTML = `<span class="badge" style="background:var(--bg-hover); color:#40c4ff;">Tier ${p.candidate_tier}</span>`;

        const paretoTd = document.createElement("td");
        if (p.pareto_optimal) {
          paretoTd.innerHTML = `<span class="badge" style="background:#ff5252; color:#fff;">Pareto</span>`;
        } else {
          paretoTd.innerHTML = `<span style="color:var(--text-secondary);">-</span>`;
        }

        tr.appendChild(idTd);
        tr.appendChild(exprTd);
        tr.appendChild(sharpeTd);
        tr.appendChild(fitnessTd);
        tr.appendChild(turnTd);
        tr.appendChild(tierTd);
        tr.appendChild(paretoTd);
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
      if (filtered.length > 0) {
        selectPassedAlpha(filtered[0]);
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

  // === AI Assistant Implementation ===
  let aiChatHistory = [];

  function loadAiConfig() {
    const provider = localStorage.getItem("dumbo_ai_provider") || "gemini";
    const apiKey = localStorage.getItem("dumbo_ai_apikey") || "";
    const model = localStorage.getItem("dumbo_ai_model") || (provider === "gemini" ? "gemini-1.5-flash" : "gpt-4o-mini");

    document.getElementById("aiProviderSelect").value = provider;
    document.getElementById("aiApiKeyInput").value = apiKey;
    document.getElementById("aiModelInput").value = model;

    // Load Chat History
    const historyJson = localStorage.getItem("dumbo_ai_chat_history");
    if (historyJson) {
      try {
        aiChatHistory = JSON.parse(historyJson);
        renderAiChat();
      } catch (err) {
        aiChatHistory = [];
      }
    } else {
      aiChatHistory = [];
      renderAiChat();
    }
  }

  function handleAiProviderChange(e) {
    const provider = e.target.value;
    const modelInput = document.getElementById("aiModelInput");
    if (provider === "gemini") {
      modelInput.placeholder = "e.g. gemini-1.5-flash";
      if (!modelInput.value || modelInput.value.startsWith("gpt")) {
        modelInput.value = "gemini-1.5-flash";
      }
    } else {
      modelInput.placeholder = "e.g. gpt-4o-mini";
      if (!modelInput.value || modelInput.value.startsWith("gemini")) {
        modelInput.value = "gpt-4o-mini";
      }
    }
  }

  function handleSaveAiConfig() {
    const provider = document.getElementById("aiProviderSelect").value;
    const apiKey = document.getElementById("aiApiKeyInput").value.trim();
    const model = document.getElementById("aiModelInput").value.trim();

    localStorage.setItem("dumbo_ai_provider", provider);
    localStorage.setItem("dumbo_ai_apikey", apiKey);
    localStorage.setItem("dumbo_ai_model", model);

    const badge = document.getElementById("aiSavedBadge");
    badge.style.display = "block";
    if (window.lucide) lucide.createIcons();
    setTimeout(() => {
      badge.style.display = "none";
    }, 3000);
  }

  function handleClearAiChat() {
    aiChatHistory = [];
    localStorage.removeItem("dumbo_ai_chat_history");
    renderAiChat();
  }

  function renderAiChat() {
    const container = document.getElementById("aiChatWindow");
    const placeholder = document.getElementById("aiChatPlaceholder");

    // Clear messages
    const msgDivs = container.querySelectorAll(".ai-msg-block");
    msgDivs.forEach(div => div.remove());

    if (aiChatHistory.length === 0) {
      placeholder.style.display = "block";
      return;
    }

    placeholder.style.display = "none";

    aiChatHistory.forEach(msg => {
      const msgBlock = document.createElement("div");
      msgBlock.className = "ai-msg-block";
      msgBlock.style.display = "flex";
      msgBlock.style.flexDirection = "column";
      msgBlock.style.gap = "4px";
      msgBlock.style.alignSelf = msg.role === "user" ? "flex-end" : "flex-start";
      msgBlock.style.maxWidth = "80%";

      const header = document.createElement("span");
      header.style.fontSize = "10px";
      header.style.textTransform = "uppercase";
      header.style.color = "var(--text-secondary)";
      header.style.alignSelf = msg.role === "user" ? "flex-end" : "flex-start";
      header.innerText = msg.role === "user" ? "You" : "Assistant";

      const bubble = document.createElement("div");
      bubble.style.padding = "10px 14px";
      bubble.style.borderRadius = "8px";
      bubble.style.whiteSpace = "pre-wrap";
      bubble.style.wordBreak = "break-word";
      bubble.style.lineHeight = "1.5";

      if (msg.role === "user") {
        bubble.style.background = "var(--primary-accent)";
        bubble.style.color = "var(--bg-primary)";
        bubble.style.fontWeight = "500";
      } else {
        bubble.style.background = "var(--bg-secondary)";
        bubble.style.color = "var(--text-primary)";
        bubble.style.border = "1px solid var(--border-color)";
      }

      bubble.innerText = msg.content;
      msgBlock.appendChild(header);
      msgBlock.appendChild(bubble);
      container.appendChild(msgBlock);
    });

    container.scrollTop = container.scrollHeight;
  }

  async function handleSendAiMessage() {
    const prompt = document.getElementById("aiMessageInput").value.trim();
    if (!prompt) return;

    const apiKey = localStorage.getItem("dumbo_ai_apikey");
    if (!apiKey) {
      showAiError("Missing API Key. Please save a valid API key configuration first.");
      return;
    }

    const provider = localStorage.getItem("dumbo_ai_provider") || "gemini";
    const model = localStorage.getItem("dumbo_ai_model") || (provider === "gemini" ? "gemini-1.5-flash" : "gpt-4o-mini");

    hideAiError();

    // 1. Add User Message
    aiChatHistory.push({ role: "user", content: prompt });
    document.getElementById("aiMessageInput").value = "";
    renderAiChat();

    // 2. Add Typing Indicator
    const container = document.getElementById("aiChatWindow");
    const indicatorBlock = document.createElement("div");
    indicatorBlock.className = "ai-msg-block typing-indicator";
    indicatorBlock.style.alignSelf = "flex-start";
    indicatorBlock.innerHTML = `
      <span style="font-size: 10px; text-transform: uppercase; color: var(--text-secondary);">Assistant</span>
      <div style="background: var(--bg-secondary); border: 1px solid var(--border-color); padding: 10px 14px; border-radius: 8px; color: var(--text-secondary); width: fit-content;">
        Thinking...
      </div>
    `;
    container.appendChild(indicatorBlock);
    container.scrollTop = container.scrollHeight;

    try {
      let botResponseText = "";

      if (provider === "gemini") {
        const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }]
          })
        });
        const data = await response.json();
        if (response.ok) {
          botResponseText = data?.candidates?.[0]?.content?.parts?.[0]?.text || "No text return from Gemini API.";
        } else {
          throw new Error(data?.error?.message || "Google API Error");
        }
      } else {
        const url = `https://api.openai.com/v1/chat/completions`;
        const response = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${apiKey}`
          },
          body: JSON.stringify({
            model: model,
            messages: [{ role: "user", content: prompt }]
          })
        });
        const data = await response.json();
        if (response.ok) {
          botResponseText = data?.choices?.[0]?.message?.content || "No message return from OpenAI API.";
        } else {
          throw new Error(data?.error?.message || "OpenAI API Error");
        }
      }

      indicatorBlock.remove();
      aiChatHistory.push({ role: "assistant", content: botResponseText });
      localStorage.setItem("dumbo_ai_chat_history", JSON.stringify(aiChatHistory));
      renderAiChat();
    } catch (err) {
      indicatorBlock.remove();
      showAiError(`API Error: ${err.message}`);
    }
  }

  function showAiError(msg) {
    const errBanner = document.getElementById("aiErrorBanner");
    errBanner.innerText = msg;
    errBanner.style.display = "block";
  }

  function hideAiError() {
    const errBanner = document.getElementById("aiErrorBanner");
    errBanner.style.display = "none";
  }
});
