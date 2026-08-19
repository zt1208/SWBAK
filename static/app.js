/* ========== SWBAK Web 前端逻辑 ========== */
const API = (url, opt = {}) => fetch(url, {
  headers: { "Content-Type": "application/json" },
  ...opt,
}).then(r => {
  if (r.status === 401) { location.href = "/login"; throw new Error("请重新登录"); }
  return r.ok ? r.json().catch(() => ({})) : r.json().catch(() => ({})).then(e => Promise.reject(e));
});

let devices = [];
let meta = { vendor_labels: {}, vendors: [] };
let currentFile = { path: "", name: "" };
let compareFiles = [];
let sseSource = null;
// 文件路径注册表: 避免把含反斜杠的路径放进内联 onclick 的 JS 字符串字面量
// (反斜杠会被当转义符, 如 \b -> 退格), 改用索引引用
let fileRegistry = [];
function regFile(path, name) {
  fileRegistry.push({ path, name });
  return fileRegistry.length - 1;
}
// 跨 Tab 跳转查看文件时的暂存 (切换 Tab 会重渲染树并清空 fileRegistry)
let pendingView = null;

/* ---------- 工具函数 ---------- */
function toast(msg, type = "") {
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = msg;
  document.getElementById("toastRoot").appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function statusTag(status) {
  const map = {
    "成功": "tag-ok", "失败": "tag-fail",
    "备份中": "tag-running", "排队中": "tag-running", "未备份": "tag-pending",
    "无变化": "tag-unchanged",
  };
  return `<span class="tag ${map[status] || "tag-pending"}">${status || "未备份"}</span>`;
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.toggle("active", p.id === "tab-" + name));
  if (name === "history") loadBackupTree();
  if (name === "compare") loadCompareTree();
  if (name === "settings") loadSettings();
  if (name === "backup") renderBackupStatus();
}

document.querySelectorAll(".tab").forEach(t =>
  t.addEventListener("click", () => switchTab(t.dataset.tab)));

/* ---------- 模态框 ---------- */
const Modal = {
  open(html, { title = "", wide = false, foot = "" } = {}) {
    const root = document.getElementById("modalRoot");
    root.innerHTML = `
      <div class="modal-mask" onclick="if(event.target===this)Modal.close()">
        <div class="modal ${wide ? "wide" : ""}">
          <div class="modal-head"><span>${title}</span><button class="modal-close" onclick="Modal.close()">×</button></div>
          <div class="modal-body">${html}</div>
          ${foot ? `<div class="modal-foot">${foot}</div>` : ""}
        </div>
      </div>`;
  },
  close() { document.getElementById("modalRoot").innerHTML = ""; }
};

/* ---------- 设备管理 ---------- */
async function loadMeta() {
  try {
    meta = await API("/api/meta");
  } catch (e) { /* ignore */ }
}

async function loadDevices() {
  try {
    devices = await API("/api/devices");
    renderDevices();
    updateStats();
  } catch (e) {
    toast("加载设备失败", "fail");
  }
}

function renderDevices() {
  const kw = document.getElementById("deviceSearch").value.trim().toLowerCase();
  const tbody = document.getElementById("deviceBody");
  const empty = document.getElementById("deviceEmpty");
  let list = devices;
  if (kw) {
    list = devices.filter(d =>
      (d.host || "").toLowerCase().includes(kw) ||
      (d.name || "").toLowerCase().includes(kw) ||
      (d.group || "").toLowerCase().includes(kw) ||
      (d.real_hostname || "").toLowerCase().includes(kw));
  }
  // 排序: 成功 -> 失败 -> 其余, 各组内 IP 升序
  const ipKey = ip => { try { return ip.split(".").map(Number); } catch { return [255,255,255,255]; } };
  const ok = list.filter(d => d.status === "成功").sort((a,b) => ipKey(a.host) > ipKey(b.host) ? 1 : -1);
  const unchanged = list.filter(d => d.status === "无变化").sort((a,b) => ipKey(a.host) > ipKey(b.host) ? 1 : -1);
  const fail = list.filter(d => d.status === "失败").sort((a,b) => ipKey(a.host) > ipKey(b.host) ? 1 : -1);
  const rest = list.filter(d => !["成功","无变化","失败"].includes(d.status)).sort((a,b) => ipKey(a.host) > ipKey(b.host) ? 1 : -1);
  const sorted = [...ok, ...unchanged, ...fail, ...rest];

  if (!sorted.length) {
    tbody.innerHTML = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";
  tbody.innerHTML = sorted.map(d => {
    const cls = d.status === "成功" ? "status-ok" : d.status === "失败" ? "status-fail" :
                d.status === "无变化" ? "status-unchanged" :
                d.status === "备份中" ? "status-running" : "";
    const name = d.name || d.real_hostname || d.host;
    return `<tr class="${cls}" data-id="${d.id}">
      <td class="cb-col"><input type="checkbox" class="dev-chk" value="${d.id}"></td>
      <td>${escapeHtml(name)}</td>
      <td>${escapeHtml(d.host)}</td>
      <td><span class="tag tag-vendor">${escapeHtml(meta.vendor_labels[d.vendor] || d.vendor)}</span></td>
      <td>${d.protocol.toUpperCase()}</td>
      <td>${d.port}</td>
      <td><span class="tag tag-group">${escapeHtml(d.group)}</span></td>
      <td>${statusTag(d.status)}</td>
      <td>${escapeHtml(d.last_time || "-")}</td>
      <td class="msg-cell" title="${escapeHtml(d.message)}">${escapeHtml(d.message || "-")}</td>
      <td><button class="btn-mini" onclick="DeviceDialog.open(${d.id})">编辑</button>
          <button class="btn-mini" onclick="delDevice(${d.id})">删</button></td>
    </tr>`;
  }).join("");
}

function getSelectedIds() {
  return [...document.querySelectorAll(".dev-chk:checked")].map(c => parseInt(c.value));
}

function toggleAll(chk) {
  document.querySelectorAll(".dev-chk").forEach(c => c.checked = chk.checked);
}

function editSelected() {
  const ids = getSelectedIds();
  if (ids.length !== 1) { toast("请选择一台设备进行编辑", "warn"); return; }
  DeviceDialog.open(ids[0]);
}

async function delSelected() {
  const ids = getSelectedIds();
  if (!ids.length) { toast("请先选择设备", "warn"); return; }
  if (!confirm(`确认删除选中的 ${ids.length} 台设备?`)) return;
  for (const id of ids) {
    try { await API(`/api/devices/${id}`, { method: "DELETE" }); } catch (e) {}
  }
  toast("已删除", "ok");
  loadDevices();
}

async function delDevice(id) {
  if (!confirm("确认删除该设备?")) return;
  await API(`/api/devices/${id}`, { method: "DELETE" });
  toast("已删除", "ok");
  loadDevices();
}

async function clearAll() {
  if (!devices.length) return;
  if (!confirm(`确认清空全部 ${devices.length} 台设备?\n(已备份的配置文件不会被删除)`)) return;
  await API("/api/devices/clear", { method: "POST" });
  toast("已清空", "ok");
  loadDevices();
}

// FormData 上传 (含 401 登录态处理)
async function postForm(url, fd) {
  const r = await fetch(url, { method: "POST", body: fd });
  if (r.status === 401) { location.href = "/login"; return { ok: false, msg: "登录已过期, 正在跳转登录页" }; }
  return r.json();
}

async function importFile(event) {
  // 旧版直接上传已废弃, 现在由 FileImportDialog 处理
  // 保留此函数以防外部引用
  const file = event.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await postForm("/api/devices/import", fd);
    if (r.ok) {
      toast(`新增 ${r.added} 台, 跳过重复 ${r.skipped} 台`, "ok");
      loadDevices();
    } else {
      toast(r.msg || "导入失败", "fail");
    }
  } catch (e) {
    toast("导入失败: " + (e.msg || e), "fail");
  }
  event.target.value = "";
}

function downloadTemplate() {
  window.open("/api/devices/template?fmt=xlsx", "_blank");
}

/* ---------- 添加/编辑设备对话框 ---------- */
const DeviceDialog = {
  async open(id) {
    let d = { name:"",host:"",port:22,vendor:"auto",protocol:"ssh",
              username:"",password:"",enable_password:"",group:"默认",timeout:30 };
    let title = "添加设备";
    if (id) {
      d = devices.find(x => x.id === id) || d;
      title = "编辑设备";
    } else {
      // 加载上次凭据
      try {
        const last = await API("/api/last_credentials");
        d.username = last.username || "";
        d.password = last.password || "";
        d.enable_password = last.enable_password || "";
        d.vendor = last.vendor || "auto";
        d.protocol = last.protocol || "ssh";
        d.port = last.port || 22;
        d.group = last.group || "默认";
      } catch (e) {}
    }
    const opts = (arr, cur) => arr.map(v =>
      `<option value="${v}" ${v === cur ? "selected" : ""}>${meta.vendor_labels[v] || v}</option>`).join("");
    Modal.open(`
      <form class="modal-form" id="devForm">
        <div class="form-row"><label>设备名称</label><input class="input" name="name" value="${escapeHtml(d.name)}" placeholder="可空, 备份时用实际主机名"></div>
        <div class="form-row-2">
          <div class="form-row"><label>IP 地址 *</label><input class="input" name="host" value="${escapeHtml(d.host)}" required></div>
          <div class="form-row"><label>端口</label><input class="input" type="number" name="port" value="${d.port}"></div>
        </div>
        <div class="form-row-2">
          <div class="form-row"><label>厂商</label><select class="input" name="vendor">${opts(meta.vendors || ["auto","huawei","h3c","ruijie"], d.vendor)}</select></div>
          <div class="form-row"><label>协议</label><select class="input" name="protocol">
            <option value="ssh" ${d.protocol==="ssh"?"selected":""}>SSH</option>
            <option value="telnet" ${d.protocol==="telnet"?"selected":""}>Telnet</option></select></div>
        </div>
        <div class="form-row-2">
          <div class="form-row"><label>用户名 *</label><input class="input" name="username" value="${escapeHtml(d.username)}" required></div>
          <div class="form-row"><label>密码 *</label><input class="input" type="password" name="password" value="${escapeHtml(d.password)}" required></div>
        </div>
        <div class="form-row-2">
          <div class="form-row"><label>特权密码</label><input class="input" type="password" name="enable_password" value="${escapeHtml(d.enable_password)}"></div>
          <div class="form-row"><label>超时(秒)</label><input class="input" type="number" name="timeout" value="${d.timeout}"></div>
        </div>
        <div class="form-row"><label>分组</label><input class="input" name="group" value="${escapeHtml(d.group)}"></div>
      </form>
    `, {
      title,
      foot: `<button class="btn" onclick="Modal.close()">取消</button>
             ${!id ? `<button class="btn" onclick="Modal.close(); FileImportDialog.open()">📂 从文件导入</button>` : ""}
             <button class="btn primary" onclick="DeviceDialog.save(${id||'null'})">保存</button>
             ${!id ? `<button class="btn" onclick="DeviceDialog.save(${id||'null'}, true)">保存并测试</button>` : ""}`
    });
  },
  async save(id, test) {
    const form = document.getElementById("devForm");
    const data = Object.fromEntries(new FormData(form).entries());
    data.port = parseInt(data.port) || 22;
    data.timeout = parseInt(data.timeout) || 30;
    if (!data.host || !data.username || !data.password) {
      toast("IP/用户名/密码必填", "warn"); return;
    }
    try {
      if (id) {
        await API(`/api/devices/${id}`, { method: "PUT", body: JSON.stringify(data) });
        toast("已保存", "ok");
      } else {
        await API("/api/devices", { method: "POST", body: JSON.stringify(data) });
        toast("已添加", "ok");
      }
      Modal.close();
      loadDevices();
      if (test) {
        const r = await API("/api/test", { method: "POST", body: JSON.stringify(data) });
        toast(r.ok ? `测试成功: ${r.hostname} (${r.vendor})` : `测试失败: ${r.message}`,
              r.ok ? "ok" : "fail");
        loadDevices();
      }
    } catch (e) {
      toast(e.msg || "保存失败", "fail");
    }
  }
};

/* ---------- 批量录入对话框 ---------- */
const BatchDialog = {
  async open(mode) {
    const isUnified = mode === "unified";
    const opts = (arr, cur) => arr.map(v =>
      `<option value="${v}" ${v === cur ? "selected" : ""}>${meta.vendor_labels[v] || v}</option>`).join("");
    // 加载上次凭据, 自动填充默认账号密码
    let last = { username:"", password:"", enable_password:"", vendor:"auto", protocol:"ssh", port:22, group:"默认" };
    try { const r = await API("/api/last_credentials"); Object.assign(last, r); } catch (e) {}
    const body = isUnified ? `
      <form class="modal-form" id="batchForm">
        <div class="form-row"><label>IP 列表</label>
          <textarea class="input" name="text" placeholder="每行一个 IP 地址&#10;10.0.0.1&#10;10.0.0.2"></textarea></div>
        <div class="form-row-2">
          <div class="form-row"><label>用户名</label><input class="input" name="username" value="${escapeHtml(last.username)}"></div>
          <div class="form-row"><label>密码</label><input class="input" type="password" name="password" value="${escapeHtml(last.password)}"></div>
        </div>
        <div class="form-row-2">
          <div class="form-row"><label>特权密码</label><input class="input" type="password" name="enable_password" value="${escapeHtml(last.enable_password)}"></div>
          <div class="form-row"><label>分组</label><input class="input" name="group" value="${escapeHtml(last.group)}"></div>
        </div>
        <div class="form-row-2">
          <div class="form-row"><label>厂商</label><select class="input" name="vendor">${opts(meta.vendors||["auto","huawei","h3c","ruijie"],last.vendor)}</select></div>
          <div class="form-row"><label>协议</label><select class="input" name="protocol">
            <option value="ssh" ${last.protocol==="ssh"?"selected":""}>SSH</option>
            <option value="telnet" ${last.protocol==="telnet"?"selected":""}>Telnet</option></select></div>
        </div>
        <input type="hidden" name="mode" value="unified">
      </form>
    ` : `
      <form class="modal-form" id="batchForm">
        <div class="form-row"><label>设备列表</label>
          <textarea class="input" name="text" placeholder="每行格式: IP [用户名] [密码] [厂商] [协议]&#10;留空则使用下方默认账号密码&#10;10.0.0.1&#10;10.0.0.2 admin pass huawei ssh&#10;10.0.0.3</textarea></div>
        <p style="color:#94a3b8;font-size:12px;margin-left:90px;">留空则使用下方默认值, 厂商可选: auto/huawei/h3c/ruijie</p>
        <div class="form-row-2">
          <div class="form-row"><label>默认用户名</label><input class="input" name="username" value="${escapeHtml(last.username)}" placeholder="未写用户名时使用"></div>
          <div class="form-row"><label>默认密码</label><input class="input" type="password" name="password" value="${escapeHtml(last.password)}" placeholder="未写密码时使用"></div>
        </div>
        <div class="form-row-2">
          <div class="form-row"><label>默认特权密码</label><input class="input" type="password" name="enable_password" value="${escapeHtml(last.enable_password)}"></div>
          <div class="form-row"><label>默认分组</label><input class="input" name="group" value="${escapeHtml(last.group)}"></div>
        </div>
        <div class="form-row-2">
          <div class="form-row"><label>默认厂商</label><select class="input" name="vendor">${opts(meta.vendors||["auto","huawei","h3c","ruijie"],last.vendor)}</select></div>
          <div class="form-row"><label>默认协议</label><select class="input" name="protocol">
            <option value="ssh" ${last.protocol==="ssh"?"selected":""}>SSH</option>
            <option value="telnet" ${last.protocol==="telnet"?"selected":""}>Telnet</option></select></div>
        </div>
        <input type="hidden" name="mode" value="simple">
      </form>
    `;
    Modal.open(body, {
      title: isUnified ? "统一密码导入" : "批量录入",
      foot: `<button class="btn" onclick="Modal.close()">取消</button>
             <button class="btn primary" onclick="BatchDialog.submit()">导入</button>`
    });
  },
  async submit() {
    const form = document.getElementById("batchForm");
    const data = Object.fromEntries(new FormData(form).entries());
    if (isFinite(data.port)) data.port = parseInt(data.port);
    try {
      const r = await API("/api/devices/batch", { method: "POST", body: JSON.stringify(data) });
      if (r.ok) {
        toast(`新增 ${r.added} 台, 跳过重复 ${r.skipped} 台`, "ok");
        Modal.close();
        loadDevices();
      } else {
        toast(r.msg || "导入失败", "fail");
      }
    } catch (e) {
      toast(e.msg || "导入失败", "fail");
    }
  }
};

/* ---------- 文件导入对话框 (选文件 + 填默认凭据) ---------- */
const FileImportDialog = {
  _file: null,
  _onSuccess: null,  // 导入成功后回调, 用于从添加设备对话框调用时关闭它

  async open(onSuccess) {
    this._file = null;
    this._onSuccess = onSuccess || null;
    let last = { username:"", password:"", enable_password:"", vendor:"auto", protocol:"ssh", port:22, group:"默认" };
    try { const r = await API("/api/last_credentials"); Object.assign(last, r); } catch (e) {}
    const opts = (arr, cur) => arr.map(v =>
      `<option value="${v}" ${v === cur ? "selected" : ""}>${meta.vendor_labels[v] || v}</option>`).join("");
    Modal.open(`
      <form class="modal-form" id="fileImportForm">
        <div class="form-row">
          <label>选择文件</label>
          <div style="display:flex;align-items:center;gap:8px;flex:1">
            <input type="file" id="fileImportInput" accept=".xlsx,.xls,.csv,.txt" onchange="FileImportDialog.onFileChange(this)" style="flex:1">
            <span id="fileImportName" style="color:#94a3b8;font-size:12px;white-space:nowrap"></span>
          </div>
        </div>
        <p style="color:#94a3b8;font-size:12px;margin-left:90px;margin-bottom:12px;">支持 Excel/CSV/TXT, 文件中缺的字段用下方默认值补充</p>
        <div class="form-row-2">
          <div class="form-row"><label>默认用户名</label><input class="input" name="username" value="${escapeHtml(last.username)}" placeholder="文件中缺用户名时使用"></div>
          <div class="form-row"><label>默认密码</label><input class="input" type="password" name="password" value="${escapeHtml(last.password)}" placeholder="文件中缺密码时使用"></div>
        </div>
        <div class="form-row-2">
          <div class="form-row"><label>默认特权密码</label><input class="input" type="password" name="enable_password" value="${escapeHtml(last.enable_password)}"></div>
          <div class="form-row"><label>默认分组</label><input class="input" name="group" value="${escapeHtml(last.group)}"></div>
        </div>
        <div class="form-row-2">
          <div class="form-row"><label>默认厂商</label><select class="input" name="vendor">${opts(meta.vendors||["auto","huawei","h3c","ruijie"],last.vendor)}</select></div>
          <div class="form-row"><label>默认协议</label><select class="input" name="protocol">
            <option value="ssh" ${last.protocol==="ssh"?"selected":""}>SSH</option>
            <option value="telnet" ${last.protocol==="telnet"?"selected":""}>Telnet</option></select></div>
        </div>
      </form>
    `, {
      title: "文件导入",
      foot: `<button class="btn" onclick="Modal.close()">取消</button>
             <button class="btn primary" id="btnFileImportSubmit" onclick="FileImportDialog.submit()" disabled>导入</button>`
    });
  },

  onFileChange(input) {
    this._file = input.files[0];
    const btn = document.getElementById("btnFileImportSubmit");
    const nameEl = document.getElementById("fileImportName");
    if (this._file) {
      btn.disabled = false;
      nameEl.textContent = this._file.name;
    } else {
      btn.disabled = true;
      nameEl.textContent = "";
    }
  },

  async submit() {
    if (!this._file) { toast("请先选择文件", "warn"); return; }
    const form = document.getElementById("fileImportForm");
    const data = new FormData(form);
    data.append("file", this._file);
    try {
      const r = await postForm("/api/devices/import", data);
      if (r.ok) {
        toast(`新增 ${r.added} 台, 跳过重复 ${r.skipped} 台`, "ok");
        Modal.close();
        loadDevices();
        if (this._onSuccess) this._onSuccess();
      } else {
        toast(r.msg || "导入失败", "fail");
      }
    } catch (e) {
      toast("导入失败: " + (e.msg || e), "fail");
    }
  }
};

/* ---------- 备份监控 ---------- */
async function startBackup(all) {
  const ids = getSelectedIds();
  if (!all && !ids.length) { toast("请先在设备管理中选择设备", "warn"); return; }
  const body = all ? { all: true } : { ids };
  try {
    const r = await API("/api/backup", { method: "POST", body: JSON.stringify(body) });
    if (r.ok) {
      toast(`开始备份 ${r.total} 台设备`, "ok");
      switchTab("backup");
      connectSSE();
      setBackupRunning(true);
    } else {
      toast(r.msg || "启动失败", "fail");
    }
  } catch (e) {
    toast(e.msg || "启动失败", "fail");
  }
}

async function stopBackup() {
  await API("/api/backup/stop", { method: "POST" });
  toast("已请求停止", "warn");
}

function setBackupRunning(running) {
  document.getElementById("btnBackupAll").disabled = running;
  document.getElementById("btnBackupSel").disabled = running;
  document.getElementById("btnStop").disabled = !running;
}

function connectSSE() {
  if (sseSource) sseSource.close();
  const es = new EventSource("/api/backup/stream");
  sseSource = es;
  es.onmessage = (ev) => {
    let d;
    try { d = JSON.parse(ev.data); } catch { return; }
    handleSSEEvent(d);
  };
  es.onerror = () => {
    // SSE 断开: 若是登录态过期 (401) 则跳登录页, 否则由浏览器自动重连
    if (es._probing) return;
    es._probing = true;
    fetch("/api/meta").then(r => {
      if (r.status === 401) location.href = "/login";
    }).catch(() => {}).finally(() => {
      setTimeout(() => { es._probing = false; }, 5000);
    });
  };
}

let backupStatusMap = {};  // host -> {status, message}

function handleSSEEvent(d) {
  if (d.type === "snapshot") {
    if (d.is_running) {
      setBackupRunning(true);
      updateProgress(d.done, d.total, d.ok, d.fail);
    }
  } else if (d.type === "start") {
    backupStatusMap = {};
    document.getElementById("logBox").innerHTML = "";
    document.getElementById("progressTitle").textContent = "备份进行中...";
    updateProgress(0, d.total, 0, 0);
    addLog(`开始备份, 共 ${d.total} 台`);
  } else if (d.type === "log") {
    addLog(d.msg);
  } else if (d.type === "progress") {
    const dev = d.device;
    backupStatusMap[dev.host] = dev;
    updateProgress(d.done, d.total, d.ok, d.fail);
    renderBackupStatus();
    // 实时刷新设备表的状态
    const target = devices.find(x => x.id === dev.id);
    if (target) {
      target.status = dev.status;
      target.message = dev.message;
      target.last_time = dev.last_time;
      target.real_hostname = dev.real_hostname;
      target.vendor = dev.vendor;
      updateStats();
    }
  } else if (d.type === "done") {
    updateProgress(d.done, d.total, d.ok, d.fail);
    document.getElementById("progressTitle").textContent = "备份完成";
    addLog(`备份完成: 成功 ${d.ok}, 失败 ${d.fail}`);
    setBackupRunning(false);
    if (sseSource) { sseSource.close(); sseSource = null; }
    loadDevices();
    const unchanged = d.done - d.ok - d.fail;
    toast(`备份完成: 成功 ${d.ok} / 无变化 ${unchanged} / 失败 ${d.fail}`,
          d.fail ? "warn" : "ok");
  }
}

function updateProgress(done, total, ok, fail) {
  const pct = total ? (done / total * 100) : 0;
  document.getElementById("progressFill").style.width = pct + "%";
  document.getElementById("progressCount").textContent = `${done} / ${total}`;
  document.getElementById("progOk").textContent = ok;
  // 无变化已经计入 ok 总数, 所以 unchanged = done - ok - fail, ok 包含无变化
  document.getElementById("progUnchanged").textContent = (done - ok - fail);
  document.getElementById("progFail").textContent = fail;
  document.getElementById("progRunning").textContent = total - done;
  document.getElementById("progressFill").classList.toggle("running", done < total);
}

function renderBackupStatus() {
  const box = document.getElementById("backupStatusList");
  const items = Object.values(backupStatusMap);
  if (!items.length) {
    box.innerHTML = `<div class="empty-inline">点击「开始备份」后这里实时显示每台设备状态</div>`;
    return;
  }
  const order = { "备份中": 0, "失败": 1, "无变化": 2, "成功": 3 };
  items.sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9));
  box.innerHTML = items.map(d => {
    const cls = d.status === "成功" ? "ok" : d.status === "失败" ? "fail" :
                d.status === "无变化" ? "unchanged" : "running";
    const dot = d.status === "成功" ? "●" : d.status === "失败" ? "●" :
                d.status === "无变化" ? "○" : "◐";
    return `<div class="status-item ${cls}">
      <span class="status-dot">${dot}</span>
      <span class="si-host">${escapeHtml(d.name || d.host)}</span>
      <span class="si-msg">${escapeHtml(d.message || d.status)}</span>
    </div>`;
  }).join("");
}

function addLog(msg) {
  const box = document.getElementById("logBox");
  const cls = /失败|异常|超时|认证失败|错误/.test(msg) ? "err" :
              /成功|完成|无变化/.test(msg) ? "ok" : "";
  const line = document.createElement("div");
  line.className = "log-line " + cls;
  line.textContent = msg;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function clearLog() {
  document.getElementById("logBox").innerHTML = "";
}

/* ---------- 统计 ---------- */
function updateStats() {
  const total = devices.length;
  const ok = devices.filter(d => d.status === "成功").length;
  const fail = devices.filter(d => d.status === "失败").length;
  document.getElementById("statTotal").textContent = total;
  document.getElementById("statOk").textContent = ok;
  document.getElementById("statFail").textContent = fail;
}

async function refreshSchedInfo() {
  try {
    const s = await API("/api/stats");
    const el = document.getElementById("schedInfo");
    if (s.scheduler_running) {
      el.textContent = `⏰ 定时备份: 下次 ${s.scheduler_next}`;
    } else {
      el.textContent = "";
    }
  } catch (e) {}
}

/* ---------- 备份历史 ---------- */
let backupTreeData = [];

async function loadBackupTree() {
  try {
    backupTreeData = await API("/api/backups/tree");
    renderTree();
    // 消费跨 Tab 跳转的待查看文件
    if (pendingView) {
      const pv = pendingView;
      pendingView = null;
      viewFile(pv.path, pv.name);
    }
  } catch (e) {
    toast("加载备份目录失败", "fail");
  }
}

function renderTree() {
  const kw = (document.getElementById("treeSearch")?.value || "").trim().toLowerCase();
  const root = document.getElementById("backupTree");
  let groups = backupTreeData;
  if (kw) {
    groups = groups.map(g => ({
      ...g,
      devices: g.devices.filter(d => d.name.toLowerCase().includes(kw)),
    })).filter(g => g.devices.length);
  }
  if (!groups.length) {
    root.innerHTML = `<div class="empty-inline">暂无备份文件</div>`;
    return;
  }
  fileRegistry = [];
  root.innerHTML = groups.map(g => `
    <div class="tree-group">
      <div class="tree-group-head">📁 ${escapeHtml(g.name)} <span style="color:#94a3b8;font-weight:400">(${g.devices.length})</span></div>
      ${g.devices.map(d => `
        <div class="tree-device">
          <div class="tree-device-head">🖥 ${escapeHtml(d.name)}</div>
          <div class="tree-files">
            ${d.files.map(f => {
              const idx = regFile(f.path, f.name);
              const isDiff = f.name.endsWith(".diff");
              const icon = isDiff ? "⊕" : f.is_latest ? "🟢" : "📄";
              const cls = isDiff ? "diff-file" : "";
              return `<div class="tree-file ${cls}" onclick="viewFileByIdx(${idx},event)">
                <span>${icon} ${escapeHtml(f.name)}</span>
                <span style="color:#94a3b8;font-size:11px">${f.time}</span>
              </div>`;
            }).join("")}
          </div>
        </div>`).join("")}
    </div>`).join("");
}

async function viewFileByIdx(idx, ev) {
  const item = fileRegistry[idx];
  if (!item) return;
  await viewFile(item.path, item.name, ev);
}

function viewFileFromSearch(idx) {
  const item = fileRegistry[idx];
  if (!item) return;
  // 暂存路径, 切换到 history Tab 后由 loadBackupTree 消费
  pendingView = { path: item.path, name: item.name };
  switchTab("history");
}

async function viewFile(path, name, ev) {
  currentFile = { path, name };
  document.getElementById("fileName").textContent = name;
  document.getElementById("btnDownload").style.display = "inline-block";
  document.querySelectorAll(".tree-file").forEach(e => e.classList.remove("selected"));
  if (ev && ev.currentTarget) ev.currentTarget.classList.add("selected");
  try {
    const r = await API("/api/backups/file?path=" + encodeURIComponent(path));
    if (r.ok) {
      document.getElementById("fileContent").textContent = r.content || "(空文件)";
    } else {
      document.getElementById("fileContent").textContent = "加载失败: " + (r.msg || "");
    }
  } catch (e) {
    document.getElementById("fileContent").textContent = "加载失败";
  }
}

function downloadCurrent() {
  if (currentFile.path) {
    window.open("/api/backups/download?path=" + encodeURIComponent(currentFile.path), "_blank");
  }
}

/* ---------- 配置对比 ---------- */
async function loadCompareTree() {
  try {
    if (!backupTreeData.length) {
      backupTreeData = await API("/api/backups/tree");
    }
    const root = document.getElementById("compareTree");
    if (!backupTreeData.length) {
      root.innerHTML = `<div class="empty-inline">暂无备份文件</div>`;
      return;
    }
    root.innerHTML = backupTreeData.map(g => `
      <div class="tree-group">
        <div class="tree-group-head">📁 ${escapeHtml(g.name)}</div>
        ${g.devices.map(d => `
          <div class="tree-device">
            <div class="tree-device-head" onclick="loadCompareFiles('${escapeHtml(d.name)}')">
              🖥 ${escapeHtml(d.name)} <span style="color:#94a3b8;font-size:11px">(${d.files.length})</span>
            </div>
          </div>`).join("")}
      </div>`).join("");
  } catch (e) {
    toast("加载失败", "fail");
  }
}

async function loadCompareFiles(devName) {
  // 从已加载树中取出该设备的所有文件
  let files = [];
  for (const g of backupTreeData) {
    for (const d of g.devices) {
      if (d.name === devName) files = d.files;
    }
  }
  compareFiles = files;
  const oldSel = document.getElementById("cmpOld");
  const newSel = document.getElementById("cmpNew");
  const opts = `<option value="">--选择文件--</option>` + files.map(f =>
    `<option value="${escapeHtml(f.path)}">${escapeHtml(f.name)} (${f.time})</option>`).join("");
  oldSel.innerHTML = opts;
  newSel.innerHTML = opts;
  // 默认选倒数两个 (最新两个)
  if (files.length >= 2) {
    oldSel.value = files[1].path;
    newSel.value = files[0].path;
  } else if (files.length === 1) {
    newSel.value = files[0].path;
  }
}

async function runCompare() {
  const oldPath = document.getElementById("cmpOld").value;
  const newPath = document.getElementById("cmpNew").value;
  if (!oldPath || !newPath) { toast("请选择两个文件", "warn"); return; }
  try {
    const r = await API("/api/compare", {
      method: "POST", body: JSON.stringify({ old: oldPath, new: newPath })
    });
    if (r.ok) {
      const diffHtml = r.diff_text.split("\n").map(line => {
        let cls = "ctx";
        if (line.startsWith("+++") || line.startsWith("---")) cls = "hunk";
        else if (line.startsWith("@@")) cls = "hunk";
        else if (line.startsWith("+")) cls = "add";
        else if (line.startsWith("-")) cls = "del";
        return `<div class="diff-line ${cls}">${escapeHtml(line)}</div>`;
      }).join("");
      document.getElementById("compareResult").innerHTML = `
        <div class="diff-meta">
          新增 <b style="color:var(--ok)">+${r.added}</b> 行,
          删除 <b style="color:var(--fail)">-${r.removed}</b> 行,
          旧: ${escapeHtml(r.old_mtime)} → 新: ${escapeHtml(r.new_mtime)}
        </div>
        ${r.is_different ? diffHtml : '<div class="empty-inline">两个版本完全相同, 无差异</div>'}
      `;
    } else {
      toast(r.msg || "对比失败", "fail");
    }
  } catch (e) {
    toast(e.msg || "对比失败", "fail");
  }
}

/* ---------- 配置搜索 ---------- */
async function doSearch() {
  const kw = document.getElementById("searchKeyword").value.trim();
  if (!kw) { toast("请输入关键字", "warn"); return; }
  document.getElementById("searchStats").textContent = "搜索中...";
  document.getElementById("searchBody").innerHTML = "";
  try {
    const r = await API("/api/search", { method: "POST", body: JSON.stringify({ keyword: kw }) });
    if (r.ok) {
      document.getElementById("searchStats").textContent =
        `找到 ${r.total} 条结果${r.total > 500 ? " (仅显示前 500 条)" : ""}`;
      fileRegistry = [];
      document.getElementById("searchBody").innerHTML = r.results.map(it => {
        const idx = regFile(it[0], it[0].split(/[/\\]/).pop());
        return `<tr>
          <td title="${escapeHtml(it[0])}">${escapeHtml(it[0].replace(/\\/g,"/").split("/").slice(-2).join("/"))}
            <button class="btn-mini" onclick="viewFileFromSearch(${idx})">查看</button></td>
          <td>${it[1]}</td>
          <td style="font-family:Consolas,monospace">${escapeHtml(it[2])}</td>
        </tr>`;
      }).join("");
    } else {
      toast(r.msg || "搜索失败", "fail");
    }
  } catch (e) {
    toast(e.msg || "搜索失败", "fail");
  }
}

/* ---------- 设置 ---------- */
async function loadSettings() {
  try {
    const s = await API("/api/settings");
    document.getElementById("setBackupDir").value = s.backup_dir || "";
    document.getElementById("setWorkers").value = s.max_workers || 10;
    document.getElementById("setTimeout").value = s.default_timeout || 30;
    document.getElementById("setSchedEnable").checked = !!s.schedule_enabled;
    document.getElementById("setSchedMode").value = s.schedule_mode || "interval";
    document.getElementById("setSchedInterval").value = s.schedule_interval_hours || 24;
    document.getElementById("setSchedHour").value = s.schedule_daily_hour || 2;
    document.getElementById("setMailEnable").checked = !!s.mail_enabled;
    document.getElementById("setSmtpHost").value = s.smtp_host || "";
    document.getElementById("setSmtpPort").value = s.smtp_port || 465;
    document.getElementById("setSmtpSsl").value = String(s.smtp_ssl !== false);
    document.getElementById("setMailSender").value = s.mail_sender || "";
    document.getElementById("setMailRcpt").value = s.mail_recipients || "";
    document.getElementById("setMailPwd").value = s.mail_password ? "********" : "";
    toggleSchedRows();
  } catch (e) {
    toast("加载设置失败", "fail");
  }
}

function toggleSchedRows() {
  const mode = document.getElementById("setSchedMode").value;
  document.getElementById("schedIntervalRow").style.display = mode === "interval" ? "" : "none";
  document.getElementById("schedDailyRow").style.display = mode === "daily" ? "" : "none";
}
document.getElementById("setSchedMode")?.addEventListener("change", toggleSchedRows);

async function saveSettings() {
  const data = {
    backup_dir: document.getElementById("setBackupDir").value,
    max_workers: parseInt(document.getElementById("setWorkers").value) || 10,
    default_timeout: parseInt(document.getElementById("setTimeout").value) || 30,
    schedule_enabled: document.getElementById("setSchedEnable").checked,
    schedule_mode: document.getElementById("setSchedMode").value,
    schedule_interval_hours: parseInt(document.getElementById("setSchedInterval").value) || 24,
    schedule_daily_hour: parseInt(document.getElementById("setSchedHour").value) || 2,
    mail_enabled: document.getElementById("setMailEnable").checked,
    smtp_host: document.getElementById("setSmtpHost").value,
    smtp_port: parseInt(document.getElementById("setSmtpPort").value) || 465,
    smtp_ssl: document.getElementById("setSmtpSsl").value === "true",
    mail_sender: document.getElementById("setMailSender").value,
    mail_recipients: document.getElementById("setMailRcpt").value,
  };
  const pwd = document.getElementById("setMailPwd").value;
  if (pwd && pwd !== "********") data.mail_password = pwd;
  try {
    await API("/api/settings", { method: "POST", body: JSON.stringify(data) });
    toast("设置已保存", "ok");
    refreshSchedInfo();
  } catch (e) {
    toast(e.msg || "保存失败", "fail");
  }
}

/* ---------- 初始化 ---------- */
(async function init() {
  await loadMeta();
  await loadDevices();
  refreshSchedInfo();
  // 页面加载后连接 SSE, 接收备份状态快照与实时事件
  connectSSE();
})();

// 每分钟刷新一次定时器信息
setInterval(refreshSchedInfo, 60000);
