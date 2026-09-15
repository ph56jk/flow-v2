const app = document.querySelector("#app");
const modal = document.querySelector("#modal");
const toast = document.querySelector("#toast");

const state = {
  data: null, detail: null, selected: "", screen: "programs", tab: "overview",
  preview: new URLSearchParams(location.search).has("preview"),
  // Màn hình Agent điều phối giữ state riêng: overview (luồng + yêu cầu +
  // phạm vi), luồng đang mở, bản nháp đang gõ, và các diff đang bung ra.
  agent: null, thread: null, draft: "", openDiffs: new Set(), diffCache: new Map(), agentTimer: 0, agentError: "",
  // Gửi xong mới biết server có coi luồng là "đang bận" không — nghĩa là giữa
  // lúc bấm gửi và lúc refreshAgent() trả về, chưa có gì khoá khung nhập.  Lag
  // mạng trong khoảng đó khiến một cú bấm Enter hoặc bấm gửi thứ hai chạy lại
  // sendAgentMessage() trong khi threadId vẫn còn rỗng, tạo ra một luồng mới
  // trùng lặp thay vì nối vào cùng một luồng. Cờ này khoá ngay khi bấm.
  agentSending: false,
  // railOpen: ngăn cuộc trò chuyện trên điện thoại.  stickBottom: đang dính
  // đáy đoạn chat hay không — vòng làm mới 4.5s sẽ kéo người đọc về cuối nếu
  // không nhớ lại họ đã cuộn lên đọc lại cái gì.
  railOpen: false, stickBottom: true, streamScroll: 0,
};

const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const short = (value = "") => String(value).split("@")[0].split(/[._-]/).map((part) => part[0]?.toUpperCase() || "").join("").slice(0, 2) || "HG";
const localTime = (value) => value ? new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" }).format(new Date(value)) : "Chưa có";
const statusText = (status) => ({ active: "Đang hoạt động", running: "Đang tạo ảnh", queued: "Đang chờ runner", cancel_requested: "Đang dừng", cancelled: "Đã huỷ", completed: "Hoàn tất", paused: "Sẵn sàng", draft: "Chờ thiết lập", needs_runner: "Cần runner", online: "Runner trực tuyến", offline: "Runner chưa kết nối", pending: "Chờ duyệt", approved: "Đã duyệt", rejected: "Đã từ chối", error: "Có lỗi", planning: "Agent đang soạn", awaiting_approval: "Chờ duyệt", applying: "Đang áp thay đổi", applied: "Đã áp", answered: "Đã trả lời", bot_done: "Đã chuyển lệnh cho bot", failed: "Không thực hiện được" })[status] || status;
const can = (capability) => state.detail?.permissions?.includes(capability) || state.data?.capabilities?.includes(capability) || false;
// Màn hình Agent có bộ quyền riêng do /agent trả về; đừng đọc nhầm sang
// permissions của dashboard detail, hai lần tải đó không đồng bộ với nhau.
const canAgent = (capability) => state.agent?.permissions?.includes(capability) || false;
function safeExternalUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" ? url.href : "";
  } catch { return ""; }
}

function icon(name) {
  const paths = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.2" cy="9" r="1.6"/><path d="m4 17 4.8-4.8 3.2 3.2 2.2-2.2L20 19"/>',
    arrows: '<path d="M7 7h12l-3-3"/><path d="m19 7-3 3"/><path d="M17 17H5l3 3"/><path d="m5 17 3-3"/>',
    check: '<circle cx="12" cy="12" r="8.5"/><path d="m8.3 12.1 2.5 2.6 5-5"/>',
    branch: '<circle cx="6" cy="5" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M8 5h3a3 3 0 0 1 3 3v7a3 3 0 0 0 3 3h-1"/><path d="M14 8a3 3 0 0 0 3-2"/>',
    home: '<path d="m3 11 9-8 9 8"/><path d="M5.5 10v10h13V10"/>',
    bot: '<rect x="4" y="7" width="16" height="12" rx="3"/><path d="M12 3v4M8 12h.01M16 12h.01M8 16h8"/>',
    project: '<path d="M3 7h6l2 2h10v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v2"/>',
    review: '<path d="m4 4 16 16"/><path d="M20 10v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h9"/><path d="m8 13 2.3 2.3L19 6.6"/>',
    users: '<circle cx="9" cy="8" r="3"/><path d="M3 20c.5-3.5 2.5-5 6-5s5.5 1.5 6 5"/><path d="M17 11.5a3 3 0 1 0-1.2-5.8"/><path d="M17 15c2.3.1 3.7 1.5 4 4"/>',
    audit: '<path d="M12 8v5l3 2"/><circle cx="12" cy="12" r="9"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.1 2.1-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-3v-.2a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1-2.1-2.1.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H5v-3h.2a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1 2.1-2.1.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6V3h3v.2a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1 2.1 2.1-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v3h-.2a1.7 1.7 0 0 0-1.6 1Z"/>',
    play: '<path d="m9 7 8 5-8 5Z"/>',
    pause: '<path d="M9 6v12M15 6v12"/>',
    back: '<path d="m14 5-7 7 7 7"/><path d="M7 12h12"/>',
    send: '<path d="M4.5 12 20 4.5 14.5 20l-3-6.5Z"/><path d="m11.5 13.5 8.5-9"/>',
    chat: '<path d="M20 15a2 2 0 0 1-2 2H8l-4 3V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2Z"/>',
    trash: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>',
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.grid}</svg>`;
}

function sampleData() {
  const dashboards = [
    { id: "content-image-agent", slug: "agent-tao-anh-content", name: "Agent tạo ảnh Content", description: "Tạo ảnh theo idea, chờ duyệt từng ảnh và gửi kết quả đã duyệt về đúng nguồn.", icon: "image", color: "teal", status: "active", role: "owner", counts: { bots: 1, running: 0, approvals: 2, projects: 0 }, last_activity_at: "2026-08-12T04:00:00.000Z" },
  ];
  return { session: { email: "phong.hothanh@havigroup.llc", display_name: "Hồ Thanh Phong", global_role: "owner", is_owner: true }, capabilities: ["view", "run", "review", "configure", "manage_members", "create_dashboard"], dashboards, role_definitions: [], agent_chat: { locked: "", runner_online: true, slug: "agent-tao-anh-content", dashboards: 1, awaiting: 1, active: 0 } };
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "content-type": "application/json", ...(options.headers || {}) } });
  const contentType = (response.headers.get("content-type") || "").toLowerCase();
  const crossOriginRedirect = response.redirected
    && new URL(response.url, location.href).origin !== location.origin;
  if (crossOriginRedirect || contentType.includes("text/html")) {
    throw new Error("Phiên đăng nhập đã hết hạn. Hãy tải lại trang để đăng nhập lại.");
  }
  const emptyBody = response.status === 204 || response.status === 205 || response.headers.get("content-length") === "0";
  let payload = {};
  if (!emptyBody) {
    if (!contentType.includes("application/json") && !contentType.includes("+json")) {
      throw new Error("Máy chủ trả dữ liệu không hợp lệ.");
    }
    try {
      payload = await response.json();
    } catch {
      throw new Error("Máy chủ trả dữ liệu không hợp lệ.");
    }
  }
  if (!response.ok) throw new Error(payload.error || "Không thể kết nối Automation Center.");
  return payload;
}

function showToast(message, isError = false) {
  toast.textContent = message;
  toast.className = `toast${isError ? " error" : ""}`;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 4600);
}

async function load() {
  if (state.preview) {
    state.data = sampleData();
    state.selected ||= state.data.dashboards[0].slug;
    state.detail = sampleDetail(state.selected);
    render();
    return;
  }
  try {
    state.data = await api("/api/bootstrap");
    state.selected ||= state.data.dashboards[0]?.slug || "";
    if (state.selected) state.detail = await api(`/api/dashboards/${encodeURIComponent(state.selected)}`);
    render();
  } catch (caught) {
    app.innerHTML = loginState(caught.message);
  }
}

function sampleDetail(slug) {
  const dashboard = sampleData().dashboards.find((item) => item.slug === slug) || sampleData().dashboards[0];
  return {
    dashboard,
    permissions: ["view", "run", "review", "configure", "manage_members"],
    projects: [],
    bots: dashboard.slug === "agent-tao-anh-content" ? [
      { id: "content-image-agent-runner", name: "Agent tạo ảnh Content", purpose: "Tạo ảnh theo idea; mỗi ảnh sẽ chờ duyệt trên dashboard.", runner_key: "content-image-runner", status: "paused", runner_status: "online", runner_online: true, runner_last_seen_at: new Date().toISOString(), last_run_status: "ready", active_run: null },
    ] : [],
    approvals: dashboard.slug === "agent-tao-anh-content" ? [
      { id: "sample-a", title: "Ảnh concept mùa lễ", detail: "Chờ người duyệt quyết định trước khi đẩy về nguồn idea.", artifact_url: "", status: "pending", requested_by: "Flow Image Agent", created_at: "2026-08-12T03:50:00.000Z" },
      { id: "sample-b", title: "Ảnh chỉnh sửa thủ công", detail: "Ảnh bổ sung vào bộ idea, cần duyệt riêng.", status: "pending", requested_by: "Hồ Thanh Phong", created_at: "2026-08-12T03:56:00.000Z" },
    ] : [],
    runs: [],
    logs: [{ id: "1", actor_email: "phong.hothanh@havigroup.llc", action: "dashboard.opened", target_type: "dashboard", target_id: dashboard.id, created_at: "2026-08-12T04:00:00.000Z" }],
    members: [{ email: "phong.hothanh@havigroup.llc", display_name: "Hồ Thanh Phong", role: "admin", granted_by: "system", created_at: "2026-08-12T03:00:00.000Z" }],
  };
}

function loginState(message) {
  return `<main class="login-state"><div class="brand-mark">H</div><h1>Automation HaviGroup</h1><p>${esc(message)}</p><p>Trang này chỉ nhận tài khoản công ty qua Cloudflare Access. Sau khi Access được cấu hình, hãy đăng nhập bằng email <strong>@havigroup.llc</strong>.</p></main>`;
}

function sidebar() {
  const session = state.data.session;
  const nav = [
    ["programs", "grid", "Chương trình"], ["agent", "branch", "Agent điều phối"], ["bots", "bot", "Bot"], ["approvals", "review", "Yêu cầu duyệt"], ["projects", "project", "Dự án"], ["audit", "audit", "Lịch sử hoạt động"],
  ];
  return `<aside class="sidebar"><div class="brand"><div class="brand-mark">H</div><div class="brand-copy"><strong>Automation HaviGroup</strong><small>automation.havigroup.llc</small></div></div><nav class="nav-list" aria-label="Điều hướng">${nav.map(([screen, iconName, label]) => `<button class="nav-button ${state.screen === screen ? "active" : ""}" data-screen="${screen}"><span class="nav-icon">${icon(iconName)}</span><span>${label}</span></button>`).join("")}</nav><div class="nav-divider"></div><div class="nav-list"><button class="nav-button" data-action="open-members"><span class="nav-icon">${icon("users")}</span><span>Quyền truy cập</span></button><button class="nav-button" data-action="open-create-dashboard"><span class="nav-icon">${icon("settings")}</span><span>Cài đặt hệ thống</span></button></div><div class="sidebar-spacer"></div><div class="account-chip"><span class="avatar">${esc(short(session.email))}</span><div class="account-copy"><strong>${esc(session.display_name || session.email)}</strong><small>${esc(session.global_role === "owner" ? "Owner" : session.global_role)}</small></div></div></aside>`;
}

function metric(label, value, hint) {
  return `<article class="metric"><span class="metric-label">${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(hint)}</small></article>`;
}

// Khung chat được đưa lên đầu màn hình chính.  Chỗ này trước đây là bốn ô số
// riêng biệt, mỗi ô cao 102-119px: trên điện thoại chúng chiếm trọn màn hình
// đầu tiên để nói bốn con số mà phần lớn là 0, còn thứ người dùng thật sự vào
// đây để làm — nhắn cho agent — bị đẩy xuống dưới nếp gấp.  Bốn con số gộp lại
// thành một dải một dòng, chỗ trống trả cho khung chat.
function agentHeroCard() {
  const chat = state.data.agent_chat || {};
  const target = (state.data.dashboards || []).find((item) => item.slug === chat.slug);
  const runnerState = chat.runner_online ? "online" : "offline";
  const chips = [
    `<span class="status ${runnerState}">${esc(chat.runner_online ? "Máy trung tâm sẵn sàng" : "Máy trung tâm chưa kết nối")}</span>`,
    chat.awaiting ? `<span class="status awaiting_approval">${esc(chat.awaiting)} yêu cầu chờ duyệt</span>` : "",
    chat.active ? `<span class="status planning">${esc(chat.active)} yêu cầu đang chạy</span>` : "",
  ].join("");
  // Ba lý do không nhắn được, xếp theo thứ tự người dùng phải xử lý: bị khoá
  // thì xin mở khoá, chưa có chương trình thì xin quyền, máy trung tâm chết
  // thì gọi người bật.  Hiện thẳng lý do chứ không ẩn nút đi — nút biến mất
  // không nói cho ai biết phải làm gì tiếp.
  let action;
  if (chat.locked) action = `<div class="permission-note">${esc(chat.locked)}</div>`;
  else if (!chat.slug) action = `<div class="permission-note">Bạn chưa được cấp quyền nhắn trong chương trình nào. Owner vào "Quyền truy cập" mở quyền cho email của bạn trước.</div>`;
  else action = `<div class="agent-hero-actions"><button class="primary-button" data-action="open-agent-in" data-slug="${esc(chat.slug)}">Mở khung chat</button>${chat.dashboards > 1 ? `<small>Vào ${esc(target?.name || chat.slug)}; đổi chương trình ngay trong khung chat.</small>` : ""}</div>`;
  return `<section class="agent-hero"><div class="agent-hero-copy"><div class="agent-hero-title"><div class="program-icon teal">${icon("branch")}</div><h2>Nhắn cho Agent điều phối</h2></div><p>Tiếng Việt thường: sửa tool, đổi luồng cột, chạy hoặc dừng bot. Agent soạn xong vẫn phải chờ người duyệt.</p><div class="agent-hero-chips">${chips}</div></div>${action}</section>`;
}

function programsView() {
  const dashboards = state.data.dashboards;
  const totalBots = dashboards.reduce((sum, item) => sum + item.counts.bots, 0);
  const running = dashboards.reduce((sum, item) => sum + item.counts.running, 0);
  const approvals = dashboards.reduce((sum, item) => sum + item.counts.approvals, 0);
  const projects = dashboards.reduce((sum, item) => sum + item.counts.projects, 0);
  const selected = dashboards.find((item) => item.slug === state.selected) || dashboards[0];
  const strip = [
    ["Dashboard", dashboards.length, "được cấp"],
    ["Bot", totalBots, `${running} đang chạy`],
    ["Chờ duyệt", approvals, ""],
    ["Dự án", projects, ""],
  ].map(([label, value, hint]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong>${hint ? `<em>${esc(hint)}</em>` : ""}</div>`).join("");
  return `<div class="topbar"><div><h1 class="page-title">Chương trình tự động hóa</h1><p class="page-subtitle">Mỗi chương trình là một dashboard độc lập: bot, project, dữ liệu, quyền và lịch sử hoạt động không dùng chung nếu chưa được cấp.</p></div><div class="top-actions">${state.data.session.is_owner ? `<button class="primary-button" data-action="open-create-dashboard"><span class="button-icon">${icon("plus")}</span>Tạo chương trình</button>` : ""}</div></div>${agentHeroCard()}<section class="stat-strip">${strip}</section><section class="program-layout"><div class="program-list">${dashboards.length ? dashboards.map(programCard).join("") : `<div class="empty-state"><div><h2>Chưa có dashboard được cấp</h2><p>Owner có thể tạo chương trình hoặc Admin thêm bạn vào dashboard phù hợp.</p></div></div>`}</div>${selected ? dashboardSummaryPanel(selected) : ""}</section>`;
}

function programCard(dashboard) {
  const selected = dashboard.slug === state.selected;
  return `<article class="program-card ${selected ? "selected" : ""}"><div class="program-icon ${esc(dashboard.color)}">${icon(dashboard.icon)}</div><div class="program-copy"><h2>${esc(dashboard.name)}</h2><p>${esc(dashboard.description)}</p></div><div class="program-stats"><div class="program-stat"><span>Bot</span><strong>${dashboard.counts.bots}</strong></div><div class="program-stat"><span>Dự án</span><strong>${dashboard.counts.projects}</strong></div><div class="program-stat"><span>Duyệt chờ</span><strong>${dashboard.counts.approvals}</strong></div><div class="program-stat"><span>Quyền của bạn</span><strong>${esc(dashboard.role)}</strong></div></div><div class="program-actions"><span class="status ${esc(dashboard.status)}">${esc(statusText(dashboard.status))}</span><button class="secondary-button" data-action="open-dashboard" data-slug="${esc(dashboard.slug)}">Mở dashboard</button></div></article>`;
}

function dashboardSummaryPanel(dashboard) {
  const detail = state.detail?.dashboard?.slug === dashboard.slug ? state.detail : null;
  const bots = detail?.bots || [];
  const projects = detail?.projects || [];
  return `<aside class="detail-panel"><div class="detail-title-row"><div class="program-icon ${esc(dashboard.color)}">${icon(dashboard.icon)}</div><div><h2>${esc(dashboard.name)}</h2><p>${esc(dashboard.description)}</p></div></div><div class="tabs"><button class="tab active">Tổng quan</button><button class="tab" data-action="open-dashboard" data-slug="${esc(dashboard.slug)}">Bot & duyệt</button><button class="tab" data-action="open-members">Quyền truy cập</button></div><section class="detail-section"><h3>Bot trong chương trình</h3><div class="mini-list">${bots.length ? bots.slice(0, 4).map((bot) => `<div class="mini-row"><div><strong>${esc(bot.name)}</strong><small>${esc(bot.purpose || "Chưa có mô tả")}</small></div><span class="status ${esc(bot.status)}">${esc(statusText(bot.status))}</span></div>`).join("") : `<div class="mini-row"><small>Chưa có bot. Tạo bot khi runner đã sẵn sàng.</small></div>`}</div></section><section class="detail-section"><h3>Project được gán</h3><div class="mini-list">${projects.length ? projects.map((project) => `<div class="mini-row"><div><strong>${esc(project.project_name || project.project_id)}</strong><small>${esc(project.project_id)}</small></div></div>`).join("") : `<div class="mini-row"><small>Chưa gán project nào.</small></div>`}</div></section><section class="detail-section"><h3>Ranh giới quyền</h3><div class="permission-note">Vai trò <strong>${esc(dashboard.role)}</strong> chỉ có hiệu lực trong dashboard này. Cấp quyền ở một chương trình không tự mở quyền ở chương trình khác.</div></section></aside>`;
}

function dashboardView() {
  const detail = state.detail;
  if (!detail) return `<div class="empty-state"><div><h2>Đang tải dashboard</h2></div></div>`;
  const { dashboard, bots = [], approvals = [], logs = [], projects = [], runs = [] } = detail;
  const activeCount = bots.filter((item) => item.active_run).length;
  return `<div class="topbar"><div><button class="quiet-button" data-action="back-programs"><span class="button-icon">${icon("back")}</span>Danh mục chương trình</button><h1 class="page-title" style="margin-top:17px">${esc(dashboard.name)}</h1><p class="page-subtitle">${esc(dashboard.description)}</p></div><div class="top-actions">${can("manage_members") ? `<button class="quiet-button" data-action="open-members">Quyền truy cập</button>` : ""}</div></div><section class="overview-grid">${metric("Bot", bots.length, `${activeCount} lệnh đang xử lý`)}${metric("Chờ duyệt", approvals.filter((item) => item.status === "pending").length, "Phải có quyết định từng ảnh")}${metric("Runner", bots.some((item) => item.runner_online) ? "Sẵn sàng" : "Chưa kết nối", bots.some((item) => item.runner_online) ? "Có thể tạo ảnh" : "Không tạo lệnh giả")}${metric("Quyền hiện tại", detail.dashboard.role, `${(detail.permissions || []).join(", ") || "view"}`)}</section><section class="dashboard-shell"><div class="panel"><div class="panel-header"><div><h2>Agent tạo ảnh</h2><p>Bấm tạo ảnh sẽ mở yêu cầu; huỷ/đóng không lưu gì. Sau khi gửi lệnh, nút Dừng luôn khả dụng.</p></div></div>${renderBotTable(bots, dashboard.slug)}</div><div class="panel"><div class="panel-header"><div><h2>Yêu cầu duyệt</h2><p>Ảnh đã tạo sẽ nằm tại đây để duyệt từng ảnh.</p></div></div>${approvals.length ? approvals.map((item) => approvalCard(item, dashboard.slug)).join("") : `<div class="empty-state" style="min-height:180px;margin:0"><div><h2>Chưa có ảnh chờ duyệt</h2><p>Kết quả từ runner sẽ xuất hiện tại đây.</p></div></div>`}</div><div class="panel"><div class="panel-header"><div><h2>Lần chạy gần đây</h2><p>Trạng thái thật từ runner và Google Flow.</p></div></div>${renderRuns(runs)}</div><div class="panel"><div class="panel-header"><div><h2>Hoạt động gần đây</h2><p>Audit theo người thao tác và dashboard.</p></div></div><div class="audit-list">${logs.length ? logs.slice(0, 8).map((log) => `<div class="audit-item"><span class="audit-dot"></span><div><strong>${esc(log.action.replaceAll(".", " · "))}</strong><span>${esc(log.actor_email)} · ${esc(log.target_type)}</span></div><time>${esc(localTime(log.created_at))}</time></div>`).join("") : `<p class="page-subtitle">Chưa có hoạt động được ghi nhận.</p>`}</div></div></section>`;
}

function renderBotTable(bots, slug) {
  if (!bots.length) return `<div class="empty-state" style="min-height:260px;margin:0"><div><h2>Chưa có bot</h2><p>Thêm bot sau khi đã có runner bảo mật hoặc connector phù hợp.</p></div></div>`;
  return `<div style="overflow-x:auto"><table class="bot-table"><thead><tr><th>Bot</th><th>Runner</th><th>Trạng thái</th><th>Lần gần nhất</th><th></th></tr></thead><tbody>${bots.map((bot) => {
    const execution = bot.active_run?.status || bot.status;
    const runnerState = bot.runner_online ? "online" : "offline";
    let control = "";
    if (can("run")) {
      if (["queued", "running"].includes(bot.active_run?.status)) control = `<button class="action-button danger-action" data-action="bot-action" data-bot-id="${esc(bot.id)}" data-bot-action="pause" data-slug="${esc(slug)}">Dừng</button>`;
      else if (bot.active_run?.status === "cancel_requested") control = `<button class="action-button" disabled>Đang dừng…</button>`;
      else if (bot.runner_online) control = `<button class="action-button" data-action="open-content-run" data-bot-id="${esc(bot.id)}" data-slug="${esc(slug)}">Tạo ảnh</button>`;
      else control = `<button class="action-button" data-action="open-runner-setup" data-bot-id="${esc(bot.id)}">Thiết lập runner</button>`;
    }
    return `<tr><td><div class="bot-name"><span class="bot-dot">${icon("bot")}</span><div><strong>${esc(bot.name)}</strong><small>${esc(bot.purpose || "Chưa có mô tả")}</small></div></div></td><td><strong>${esc(bot.runner_key || "Chưa gán")}</strong><small class="runner-state"><span class="status ${runnerState}">${esc(statusText(runnerState))}</span></small></td><td><span class="status ${esc(execution)}">${esc(statusText(execution))}</span></td><td>${esc(localTime(bot.active_run?.created_at || bot.last_run_at))}</td><td><div class="table-actions">${control}</div></td></tr>`;
  }).join("")}</tbody></table></div>`;
}

function renderRuns(runs) {
  if (!runs.length) return `<div class="mini-row"><small>Chưa có lần tạo ảnh nào.</small></div>`;
  return `<div class="mini-list">${runs.slice(0, 8).map((run) => `<div class="mini-row"><div><strong>${esc(run.title || "Ảnh Content")}</strong><small>${esc(run.error || `${run.image_count || 1} ảnh · ${run.aspect || "landscape"}`)}</small></div><span class="status ${esc(run.status)}">${esc(statusText(run.status))}</span></div>`).join("")}</div>`;
}

function approvalCard(item, slug) {
  const isPending = item.status === "pending";
  const artifactUrl = safeExternalUrl(item.artifact_url);
  const artifact = artifactUrl ? `<a class="artifact-link" href="${esc(artifactUrl)}" target="_blank" rel="noopener noreferrer">Mở ảnh kết quả</a>` : "";
  return `<article class="approval-card"><div style="display:flex;justify-content:space-between;gap:12px"><h3>${esc(item.title)}</h3><span class="status ${esc(item.status)}">${esc(statusText(item.status))}</span></div><p>${esc(item.detail)}</p>${artifact}<p>Yêu cầu bởi ${esc(item.requested_by || "Hệ thống")} · ${esc(localTime(item.created_at))}</p>${isPending && can("review") ? `<div class="approval-actions"><button class="secondary-button" data-action="review-approval" data-approval-id="${esc(item.id)}" data-status="approved" data-slug="${esc(slug)}">Duyệt</button><button class="quiet-button" data-action="review-approval" data-approval-id="${esc(item.id)}" data-status="rejected" data-slug="${esc(slug)}">Từ chối</button></div>` : ""}</article>`;
}

// ─── Agent điều phối ────────────────────────────────────────────────────────

// Danh sách do Worker trả trong agent overview.  Không chép cứng ở đây: Worker
// là nơi thực thi luật khoá luồng, app chỉ trình bày đúng luật đó.
function agentBusyStatuses() {
  const fromWorker = state.agent?.busy_statuses;
  if (Array.isArray(fromWorker) && fromWorker.length) return fromWorker;
  // Compatibility fallback cho một response Worker cũ/không đủ trường: thà
  // poll và khoá tạm nhiều hơn còn hơn để màn hình đứng im sau khi gửi tin.
  // agent_busy_parity.test.mjs bắt danh sách này trôi khỏi nguồn Worker.
  return ["queued", "planning", "awaiting_approval", "approved", "applying"];
}

function parseList(value) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch { return []; }
}

function diffHtml(text) {
  const lines = String(text || "").split("\n");
  const shown = lines.slice(0, 900);
  const body = shown.map((line) => {
    const marker = line.startsWith("+++") || line.startsWith("---") ? ""
      : line.startsWith("+") ? "add"
      : line.startsWith("-") ? "del"
      : line.startsWith("@@") ? "hunk" : "";
    return marker ? `<span class="${marker}">${esc(line)}</span>` : esc(line);
  }).join("\n");
  const cut = lines.length > shown.length ? `\n… còn ${lines.length - shown.length} dòng nữa.` : "";
  return `<pre class="diff-view">${body}${esc(cut)}</pre>`;
}

function requestCard(request) {
  const files = parseList(request.files_json);
  const mine = request.requested_by === state.data.session.email;
  const canDecide = canAgent("code_approve") && request.status === "awaiting_approval" && (!mine || state.data.session.is_owner);
  const canCancel = ["queued", "planning", "awaiting_approval"].includes(request.status) && (mine || canAgent("code_approve"));
  const diffOpen = state.openDiffs.has(request.id);
  const testLine = request.test_output
    ? `<p>${request.tests_passed ? "Test đã chạy và xanh." : "Test chưa xanh — cần người xem trước khi áp."}</p>`
    : "";
  const protectedNote = request.touches_protected
    ? `<p class="scope-chip danger">Chạm file được bảo vệ · chỉ Owner duyệt được</p>` : "";
  // Diff bị cắt lúc lưu thì bản commit vẫn đầy đủ.  Không nói ra thì người
  // duyệt tưởng mình đã đọc hết trong khi thực tế chưa.
  const truncatedNote = request.diff_truncated
    ? `<p class="scope-chip danger">Diff quá dài nên đã bị cắt khi lưu · bản commit vẫn đầy đủ, hãy xem nhánh ${esc(request.branch || "")} trên máy trung tâm trước khi duyệt</p>` : "";
  // Yêu cầu điều khiển bot không có diff để soi, nên từng lệnh phải hiện ra
  // nguyên văn — nếu không, dòng duy nhất người xem thấy là "Đã chuyển lệnh"
  // mà không biết đã chuyển cho bot nào.
  const botLine = parseList(request.bot_commands_json)
    .map((item) => `<span class="scope-chip ${item.ok ? "" : "danger"}">${esc(`${item.ok ? "✓" : "✗"} ${item.command || "?"} · ${item.bot_id || "?"} · ${item.message || ""}`)}</span>`)
    .join("");
  const failure = request.error ? `<p>${esc(request.error)}</p>` : "";
  return `<article class="approval-card">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
      <h3>${esc(request.instruction.slice(0, 120))}</h3>
      <span class="status ${esc(request.status)}">${esc(statusText(request.status))}</span>
    </div>
    <p>${esc(request.requested_by)} · ${esc(localTime(request.created_at))}${request.auto_applied ? " · áp thẳng theo phạm vi" : ""}</p>
    ${request.plan_summary ? `<p>${esc(request.plan_summary)}</p>` : ""}
    ${files.length ? `<div>${files.map((path) => `<span class="scope-chip">${esc(path)}</span>`).join("")}</div>` : ""}
    ${request.files_changed ? `<p>${request.files_changed} file · ${request.lines_changed} dòng${request.branch ? ` · nhánh ${esc(request.branch)}` : ""}</p>` : ""}
    ${botLine ? `<div>${botLine}</div>` : ""}
    ${testLine}${protectedNote}${truncatedNote}${failure}
    ${request.diff_length ? `<button class="quiet-button" data-action="toggle-diff" data-request-id="${esc(request.id)}">${diffOpen ? "Ẩn thay đổi" : "Xem thay đổi"}</button>` : ""}
    ${diffOpen ? (state.diffCache.has(request.id) ? diffHtml(state.diffCache.get(request.id)) : `<pre class="diff-view">Đang tải thay đổi…</pre>`) : ""}
    ${diffOpen && request.test_output ? `<pre class="diff-view">${esc(request.test_output)}</pre>` : ""}
    ${canDecide || canCancel ? `<div class="approval-actions">
      ${canDecide ? `<button class="secondary-button" data-action="decide-request" data-request-id="${esc(request.id)}" data-decision="approved">Duyệt và áp</button>
      <button class="quiet-button" data-action="decide-request" data-request-id="${esc(request.id)}" data-decision="rejected">Từ chối</button>` : ""}
      ${canCancel ? `<button class="quiet-button" data-action="decide-request" data-request-id="${esc(request.id)}" data-decision="cancelled">Rút lại</button>` : ""}
    </div>` : ""}
    ${mine && request.status === "awaiting_approval" && !state.data.session.is_owner ? `<p>Bạn không tự duyệt được thay đổi của chính mình; cần một Admin hoặc Owner khác.</p>` : ""}
  </article>`;
}

// Khung chat của Agent điều phối dựng theo dáng một ứng dụng nhắn tin thường:
// tin của mình nằm bên phải, tin của agent nằm bên trái kèm avatar, ô soạn
// dính đáy màn hình, Enter là gửi.  Bản trước là một cái panel tài liệu — mọi
// tin nhắn đều là thẻ chữ nhật xám giống hệt nhau xếp trong khung cao 54vh,
// còn ô soạn nằm lửng giữa trang.  Người ta đọc nó như đang điền form chứ
// không như đang nói chuyện với ai.
const DAY_MS = 86400000;
const clockTime = (value) => value ? new Intl.DateTimeFormat("vi-VN", { timeStyle: "short" }).format(new Date(value)) : "";

// "Hôm nay"/"Hôm qua" là cách người ta thật sự đọc mốc thời gian trong một
// đoạn chat; ngày đầy đủ chỉ cần cho những gì cũ hơn thế.
function dayLabel(value) {
  // new Date(null) ra đúng mốc 1/1/1970 chứ không phải Invalid Date, nên thiếu
  // dòng chặn này thì một tin không có created_at sẽ đẻ ra dải ngăn cách
  // "1 tháng 1, 1970" nằm giữa đoạn chat.
  if (!value) return "";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return "";
  const today = new Date().setHours(0, 0, 0, 0);
  const diff = today - new Date(at).setHours(0, 0, 0, 0);
  if (diff === 0) return "Hôm nay";
  if (diff === DAY_MS) return "Hôm qua";
  return new Intl.DateTimeFormat("vi-VN", { dateStyle: "long" }).format(at);
}

// Một yêu cầu chỉ đáng hiện thẻ khi có thứ để xem hoặc để quyết.  Agent trả
// lời một câu hỏi thì câu trả lời đã nằm ngay trên dưới dạng tin nhắn — kèm
// thêm một thẻ "Đã trả lời" rỗng chỉ làm đoạn chat dài gấp đôi mà không thêm
// thông tin nào.
function requestNeedsCard(request) {
  if (request.diff_length || request.files_changed || request.error) return true;
  if (parseList(request.bot_commands_json).length) return true;
  return ["awaiting_approval", "applying", "applied", "rejected", "cancelled", "failed"].includes(request.status);
}

function chatRow(message, previous, afterDivider) {
  // Tin hệ thống ("đã duyệt", "đã rút lại") không phải lời của ai cả, nên nó
  // là một dòng nhỏ nằm giữa chứ không phải một bong bóng có chủ.
  if (message.kind === "system") return `<div class="chat-note"><span>${esc(message.content)}</span></div>`;
  const mine = message.kind === "user" && message.author_email === state.data.session.email;
  // Nhiều tin liên tiếp của cùng một người thì chỉ tin đầu mang tên và avatar;
  // lặp avatar ở mọi dòng làm đoạn chat trông lại giống một cái bảng.
  const grouped = !afterDivider && previous && previous.kind === message.kind && previous.author_email === message.author_email;
  const who = message.kind === "agent" ? "Agent điều phối" : message.author_email;
  const avatar = message.kind === "agent"
    ? `<span class="chat-avatar bot">${icon("branch")}</span>`
    : `<span class="chat-avatar">${esc(short(message.author_email))}</span>`;
  return `<div class="chat-row ${mine ? "mine" : "theirs"}${grouped ? " grouped" : ""}">
    ${mine ? "" : (grouped ? `<span class="chat-avatar blank"></span>` : avatar)}
    <div class="chat-line">
      ${mine || grouped ? "" : `<span class="chat-who">${esc(who)}</span>`}
      <div class="chat-bubble ${esc(message.kind)}">${esc(message.content)}<time>${esc(clockTime(message.created_at))}</time></div>
    </div>
  </div>`;
}

function chatStream() {
  const messages = state.thread?.messages || [];
  const requests = state.thread?.requests || [];
  const busy = requests.some((request) => agentBusyStatuses().includes(request.status));
  if (!messages.length) {
    return `<div class="chat-stream" data-stream><div class="chat-empty"><span class="chat-avatar bot big">${icon("branch")}</span><h3>Agent điều phối</h3><p>Nhắn bằng tiếng Việt thường. Ví dụ: “đổi nhãn nút Tạo ảnh thành Tạo ảnh mới”, “bot content đang chạy gì”, “dừng bot tạo ảnh lại”.</p><p class="chat-empty-note">Agent đọc code trên máy trung tâm và soạn thay đổi; áp hay không vẫn do người duyệt.</p></div></div>`;
  }
  const byId = new Map(requests.map((request) => [request.id, request]));
  // Thẻ yêu cầu treo vào tin nhắn CUỐI cùng mang cùng request_id, để nó rơi
  // xuống ngay sau câu trả lời của agent chứ không chen vào giữa câu mình vừa
  // gõ và câu agent đáp lại.
  const lastOf = new Map();
  messages.forEach((message, index) => { if (message.request_id) lastOf.set(message.request_id, index); });

  let day = "";
  let previous = null;
  const rows = messages.map((message, index) => {
    const stamp = dayLabel(message.created_at);
    const divider = stamp && stamp !== day ? `<div class="chat-day"><span>${esc(stamp)}</span></div>` : "";
    if (stamp) day = stamp;
    const block = [divider, chatRow(message, previous, divider !== "")];
    previous = message.kind === "system" ? null : message;
    const request = lastOf.get(message.request_id) === index ? byId.get(message.request_id) : null;
    if (request && requestNeedsCard(request)) {
      block.push(`<div class="chat-attach">${requestCard(request)}</div>`);
      previous = null;
    }
    return block.join("");
  }).join("");
  // Ba chấm nhảy nói "agent đang làm" rõ hơn mọi câu chữ, và nó nằm đúng chỗ
  // câu trả lời sắp hiện ra nên mắt không phải đi tìm.
  const typing = busy
    ? `<div class="chat-row theirs"><span class="chat-avatar bot">${icon("branch")}</span><div class="chat-line"><div class="chat-bubble agent typing" aria-label="Agent đang soạn"><i></i><i></i><i></i></div></div></div>`
    : "";
  return `<div class="chat-stream" data-stream>${rows}${typing}</div>`;
}

function chatComposer() {
  const scope = state.agent.scope;
  const requests = state.thread?.requests || [];
  const busy = state.agentSending || requests.some((request) => agentBusyStatuses().includes(request.status));
  // Lý do khoá đứng trước mọi lý do khác: người bị danh sách trắng chặn mà đọc
  // được "chưa cấp phạm vi" sẽ đi xin phạm vi, và không ai cấp nổi — phạm vi
  // không phải thứ đang chặn họ.
  const blocked = state.agent.chat_locked ? state.agent.chat_locked
    : !canAgent("code_request") ? "Vai trò của bạn chỉ được xem. Hãy nhờ Owner hoặc Admin cấp quyền gửi yêu cầu sửa code."
    : !scope ? "Owner và Admin của chương trình này nhắn được ngay. Vai trò của bạn cần Owner cấp phạm vi trước — mở \"Phạm vi và giới hạn\" trong danh sách cuộc trò chuyện."
    : !state.agent.runner.online ? "Máy trung tâm chưa kết nối nên yêu cầu sẽ không có ai xử lý. Hãy bật orchestrator-runner trước."
    : "";
  if (blocked) return `<div class="chat-dock"><div class="chat-blocked">${esc(blocked)}</div></div>`;
  // Một dòng, không xuống dòng.  Bản dài ba dòng chiếm 133px đáy màn hình điện
  // thoại vĩnh viễn để nói một thứ người ta đọc đúng một lần; phần đầy đủ nằm
  // trong "Phạm vi và giới hạn" ở ngăn bên.
  const hint = `Tối đa ${scope.max_files} file · ${scope.max_lines} dòng · ${scope.auto_apply ? "áp thẳng khi test xanh" : "chờ người duyệt"} · Enter để gửi`;
  return `<div class="chat-dock">
    <div class="chat-input">
      <textarea data-draft rows="1" placeholder="${busy ? "Agent đang xử lý yêu cầu trước…" : "Nhắn cho agent…"}" maxlength="6000" ${busy ? "disabled" : ""}>${esc(state.draft)}</textarea>
      <button class="chat-send" data-action="send-agent" aria-label="Gửi" title="Gửi (Enter)" ${busy || !state.draft.trim() ? "disabled" : ""}>${icon("send")}</button>
    </div>
    <small class="chat-hint">${esc(hint)}</small>
  </div>`;
}

// Danh sách luồng đọc như danh sách cuộc trò chuyện.  Phạm vi và danh sách file
// cấm nằm trong một <details> ở đáy: chúng quan trọng nhưng chỉ được xem một
// lần rồi thôi, để mở sẵn thì mỗi lần vào chat lại phải cuộn qua chúng.
function chatRail() {
  const threads = state.agent.threads || [];
  const scope = state.agent.scope;
  const scopes = state.agent.scopes;
  const rows = threads.length
    ? threads.map((thread) => `<div class="chat-thread-row">
        <button class="chat-thread ${state.thread?.thread?.id === thread.id ? "selected" : ""}" data-action="open-thread" data-thread-id="${esc(thread.id)}"><strong>${esc(thread.title)}</strong><small>${esc(thread.created_by)} · ${esc(localTime(thread.updated_at))}</small></button>
        <button class="chat-thread-delete" data-action="delete-thread" data-thread-id="${esc(thread.id)}" data-thread-title="${esc(thread.title)}" title="Xoá cuộc trò chuyện" aria-label="Xoá cuộc trò chuyện">${icon("trash")}</button>
      </div>`).join("")
    : `<p class="chat-rail-empty">Chưa có cuộc trò chuyện nào. Nhắn một câu là luồng đầu tiên tự mở.</p>`;
  const mine = scope
    ? `<div>${scope.allow_globs.map((glob) => `<span class="scope-chip">${esc(glob)}</span>`).join("")}</div>
       <p>Tối đa ${scope.max_files} file và ${scope.max_lines} dòng mỗi lần. ${scope.auto_apply ? "Thay đổi hợp lệ, test xanh được áp thẳng." : "Mọi thay đổi đều chờ duyệt."}</p>`
    : `<p>${state.agent.chat_locked ? esc(state.agent.chat_locked) : "Bạn chưa được cấp phạm vi sửa code trong chương trình này."}</p>`;
  const granted = scopes
    ? `<h4>Phạm vi đã cấp</h4><div class="mini-list">${scopes.length ? scopes.map((row) => `<div class="mini-row"><div><strong>${esc(row.subject_type === "role" ? `Vai trò ${row.subject}` : row.subject)}</strong><small>${esc(String(row.allow_globs).split("\n").join(" · "))}</small></div><span class="status ${row.auto_apply ? "approved" : "pending"}">${row.auto_apply ? "Áp thẳng" : "Chờ duyệt"}</span></div>`).join("") : `<div class="mini-row"><small>Chưa cấp phạm vi cho ai.</small></div>`}</div><button class="quiet-button" data-action="open-code-scope">Cấp hoặc sửa phạm vi</button>`
    : "";
  return `<aside class="chat-rail${state.railOpen ? " open" : ""}">
    <div class="chat-rail-head"><strong>Cuộc trò chuyện</strong><button class="quiet-button" data-action="new-thread">Luồng mới</button></div>
    <div class="chat-rail-list">${rows}</div>
    <details class="chat-rail-info">
      <summary>Phạm vi và giới hạn</summary>
      <div class="chat-rail-info-body">
        ${mine}
        ${granted}
        <h4>Luôn ngoài tầm với</h4>
        <p>Bí mật, cấu hình triển khai, migration và chính phần phân quyền không bao giờ được sửa tự động.</p>
        <div>${state.agent.protected_globs.slice(0, 8).map((glob) => `<span class="scope-chip danger">${esc(glob)}</span>`).join("")}</div>
      </div>
    </details>
  </aside>`;
}

function chatHeader() {
  const runner = state.agent.runner;
  const waiting = (state.agent.requests || []).filter((request) => request.status === "awaiting_approval").length;
  const program = (state.data.dashboards || []).find((item) => item.slug === state.selected);
  const thread = state.thread?.thread || null;
  return `<header class="chat-topbar">
    <button class="icon-button" data-action="back-programs" title="Danh mục chương trình" aria-label="Danh mục chương trình">${icon("back")}</button>
    <button class="icon-button chat-rail-toggle" data-action="toggle-rail" title="Cuộc trò chuyện" aria-label="Cuộc trò chuyện">${icon("chat")}</button>
    <span class="chat-avatar bot ${runner.online ? "on" : "off"}" title="${esc(runner.online ? "Máy trung tâm sẵn sàng" : "Máy trung tâm chưa kết nối")}">${icon("branch")}</span>
    <div class="chat-peer">
      <strong>Agent điều phối</strong>
      <small>${esc(program?.name || state.selected)} · ${esc(thread ? thread.title : "luồng mới")}</small>
    </div>
    <div class="chat-topbar-actions">
      ${waiting ? `<span class="status awaiting_approval">${esc(waiting)} chờ duyệt</span>` : ""}
      <span class="status ${runner.online ? "online" : "offline"}">${esc(runner.online ? "Máy trung tâm sẵn sàng" : "Máy trung tâm chưa kết nối")}</span>
    </div>
  </header>`;
}

function agentView() {
  if (!state.selected) return agentPickerView();
  if (!state.agent) {
    return state.agentError
      ? `<div class="empty-state"><div><h2>Không tải được Agent điều phối</h2><p>${esc(state.agentError)}</p><div class="chat-form-actions"><button class="secondary-button" data-action="retry-agent">Thử lại</button><button class="quiet-button" data-action="back-programs">Danh mục chương trình</button></div></div></div>`
      : `<div class="empty-state"><div><h2>Đang tải Agent điều phối</h2></div></div>`;
  }
  return `<div class="chat-screen">
    ${chatHeader()}
    <div class="chat-body">
      ${chatRail()}
      ${state.railOpen ? `<div class="chat-scrim" data-action="toggle-rail"></div>` : ""}
      <section class="chat-main">${chatStream()}${chatComposer()}</section>
    </div>
  </div>`;
}

// Diff không đi kèm danh sách vì nó lớn và ít khi được mở.  Tải một lần rồi
// giữ lại: nội dung của một yêu cầu đã có diff thì không đổi nữa.
async function toggleDiff(requestId) {
  if (state.openDiffs.has(requestId)) {
    state.openDiffs.delete(requestId);
    render();
    return;
  }
  state.openDiffs.add(requestId);
  render();
  if (state.diffCache.has(requestId)) return;
  try {
    const payload = await api(`/api/dashboards/${encodeURIComponent(state.selected)}/agent/requests/${encodeURIComponent(requestId)}/diff`);
    state.diffCache.set(requestId, String(payload.diff_text || ""));
  } catch (caught) {
    // Mở ra rồi mà không tải được thì phải đóng lại: một khung trống trông
    // hệt như "thay đổi này không có gì", và đó là hiểu nhầm nguy hiểm nhất
    // ngay trước lúc bấm Duyệt.
    state.openDiffs.delete(requestId);
    showToast(caught.message, true);
  }
  render();
}

async function refreshAgent({ threadId = state.thread?.thread?.id || "", quiet = false } = {}) {
  clearTimeout(state.agentTimer);
  const base = `/api/dashboards/${encodeURIComponent(state.selected)}/agent`;
  try {
    state.agent = await api(base);
    state.thread = threadId ? await api(`${base}/threads/${encodeURIComponent(threadId)}`) : null;
    state.agentError = "";
    // Đang gõ dở thì đừng vẽ lại toàn trang: vẽ lại sẽ xoá và dựng lại ô soạn
    // đang có focus, cắt ngang bộ gõ tiếng Việt và hất con trỏ về cuối dòng —
    // cảm giác như bị văng khỏi ô nhắn giữa chừng. Dữ liệu mới vẫn lưu vào
    // state, sẽ hiện ra ngay khi rời ô nhắn (xem focusout) hoặc khi gửi xong.
    if (!(quiet && state.composerFocused)) render();
    scheduleAgentRefresh();
  } catch (caught) {
    if (!quiet) showToast(caught.message, true);
    // Một yêu cầu chạy vài phút, nên một lần rớt mạng không được phép dừng hẳn
    // vòng làm mới — nếu dừng, người dùng nhìn thấy trạng thái đứng im và tưởng
    // agent treo.  Thử lại chậm hơn nhịp thường.
    state.agentError = caught.message;
    render();
    if (state.screen === "agent") {
      state.agentTimer = setTimeout(() => { void refreshAgent({ threadId, quiet: true }); }, 12000);
    }
  }
}

function scheduleAgentRefresh() {
  clearTimeout(state.agentTimer);
  if (state.screen !== "agent") return;
  const pool = [...(state.thread?.requests || []), ...(state.agent?.requests || [])];
  if (!pool.some((request) => agentBusyStatuses().includes(request.status))) return;
  state.agentTimer = setTimeout(() => { void refreshAgent({ quiet: true }); }, 4500);
}

async function openAgent(threadId = "") {
  if (state.preview) return showToast("Preview: Agent điều phối cần dữ liệu thật từ máy trung tâm.", true);
  // Bấm "Agent điều phối" ở thanh bên khi chưa mở chương trình nào thì trước
  // đây chỉ hiện một toast rồi đứng im — với người không biết phải bấm vào một
  // chương trình trước, khung chat coi như không tồn tại.  Đúng một chương
  // trình thì vào thẳng; nhiều hơn thì hiện danh sách để bấm, vì phạm vi quyền
  // gắn với từng chương trình nên không có "khung chat chung" để rơi vào.
  if (!state.selected) {
    const list = state.data?.dashboards || [];
    if (list.length === 1) return openAgentIn(list[0].slug);
    clearTimeout(state.agentTimer);
    state.screen = "agent";
    state.agent = null;
    state.agentError = "";
    render();
    return;
  }
  state.screen = "agent";
  state.thread = null;
  state.stickBottom = true;
  render();
  await refreshAgent({ threadId });
}

async function openAgentIn(slug) {
  await selectDashboard(slug, "agent");
  if (state.selected === slug) await refreshAgent({});
}

async function sendAgentMessage() {
  if (state.agentSending) return;
  const message = state.draft.trim();
  if (message.length < 8) return showToast("Hãy mô tả yêu cầu rõ hơn (ít nhất 8 ký tự).", true);
  const base = `/api/dashboards/${encodeURIComponent(state.selected)}/agent`;
  const threadId = state.thread?.thread?.id || "";
  state.agentSending = true;
  render();
  try {
    let target = typeof threadId === "string" ? threadId.trim() : "";
    if (target) {
      await api(`${base}/threads/${encodeURIComponent(target)}/messages`, { method: "POST", body: JSON.stringify({ message }) });
    } else {
      const created = await api(`${base}/threads`, { method: "POST", body: JSON.stringify({ title: message.slice(0, 120), message }) });
      target = typeof created?.thread_id === "string" ? created.thread_id.trim() : "";
      if (!target) throw new Error("Không tạo được luồng mới. Bản nháp vẫn được giữ để gửi lại.");
    }
    state.draft = "";
    // Không toast "đã gửi" nữa: trong một đoạn chat, tin nhắn của mình hiện ra
    // ở cuối luồng đã là xác nhận rồi, thêm một hộp thoại góc màn hình chỉ che
    // mất chính câu vừa gửi.
    state.stickBottom = true;
    await refreshAgent({ threadId: target });
  } catch (caught) { showToast(caught.message, true); } finally { state.agentSending = false; render(); }
}

async function deleteThread(threadId, threadTitle) {
  const result = await showModal(
    "Xoá cuộc trò chuyện",
    `Xoá vĩnh viễn "${threadTitle}" cùng toàn bộ tin nhắn và lịch sử yêu cầu sửa code trong đó. Không thể hoàn tác.`,
    "",
    "Xoá",
  );
  if (!result.submitted) return;
  try {
    await api(`/api/dashboards/${encodeURIComponent(state.selected)}/agent/threads/${encodeURIComponent(threadId)}`, { method: "DELETE" });
    if (state.thread?.thread?.id === threadId) state.thread = null;
    showToast("Đã xoá cuộc trò chuyện.");
    await refreshAgent({});
  } catch (caught) { showToast(caught.message, true); }
}

async function decideCodeRequest(requestId, decision) {
  try {
    await api(`/api/dashboards/${encodeURIComponent(state.selected)}/agent/requests/${encodeURIComponent(requestId)}`, { method: "POST", body: JSON.stringify({ decision }) });
    showToast({ approved: "Đã duyệt. Máy trung tâm sẽ áp thay đổi.", rejected: "Đã từ chối. Không file nào bị đổi.", cancelled: "Đã rút lại yêu cầu." }[decision]);
    await refreshAgent({});
  } catch (caught) { showToast(caught.message, true); }
}

async function openCodeScope() {
  if (!state.agent?.scopes) return showToast("Bạn không có quyền cấp phạm vi.", true);
  const isOwner = state.data.session.is_owner;
  const result = await showModal(
    "Cấp phạm vi sửa code",
    "Phạm vi là ranh giới thật: agent chỉ ghi được vào những đường dẫn khớp danh sách này. Để trống danh sách nghĩa là gỡ quyền.",
    `<label>Áp cho<select name="subject_type"><option value="role">Một vai trò trong dashboard</option><option value="user">Một người cụ thể</option></select></label>
     <label>Vai trò hoặc email<input name="subject" required maxlength="254" placeholder="operator hoặc ten@havigroup.llc" /></label>
     <label>Đường dẫn được sửa <small>(mỗi dòng một mẫu, ví dụ flow_web/static/**)</small><textarea name="allow_globs" placeholder="flow_web/static/**&#10;automation_center/public/**"></textarea></label>
     <div class="form-row"><label>Tối đa số file<input name="max_files" type="number" min="1" max="60" value="3" /></label><label>Tối đa số dòng<input name="max_lines" type="number" min="1" max="6000" value="200" /></label></div>
     ${isOwner ? `<label><input type="checkbox" name="auto_apply" /> Áp thẳng khi hợp lệ và test xanh (không cần ai duyệt)</label>` : `<div class="setup-note">Chỉ Owner mới bật được chế độ áp thẳng.</div>`}
     <label>Ghi chú<input name="note" maxlength="240" placeholder="Vì sao nhóm này được sửa phần đó" /></label>`,
    "Lưu phạm vi",
  );
  if (!result.submitted) return;
  try {
    await api(`/api/dashboards/${encodeURIComponent(state.selected)}/agent/scopes`, { method: "POST", body: JSON.stringify({
      subject_type: result.data.subject_type, subject: result.data.subject, allow_globs: result.data.allow_globs,
      max_files: result.data.max_files, max_lines: result.data.max_lines, auto_apply: result.data.auto_apply === true, note: result.data.note,
    }) });
    showToast("Đã lưu phạm vi.");
    await refreshAgent({});
  } catch (caught) { showToast(caught.message, true); }
}

function filteredView() {
  if (state.screen === "agent") return agentView();
  if (state.screen === "programs") return programsView();
  if (state.screen === "bots") return dashboardView();
  if (state.screen === "approvals") return dashboardView();
  if (state.screen === "projects") return dashboardView();
  if (state.screen === "audit") return dashboardView();
  return programsView();
}

// Ô soạn cao theo nội dung như mọi app nhắn tin, nhưng có trần: một tin dài
// 40 dòng mà đẩy hết đoạn chat ra khỏi màn hình thì không còn là chat nữa.
function growComposer(element) {
  if (!element) return;
  element.style.height = "auto";
  element.style.height = `${Math.min(element.scrollHeight, 168)}px`;
}

function render() {
  // Màn hình chat chiếm trọn chiều cao và tự cuộn bên trong, nên trang không
  // được cuộn theo — hai thanh cuộn lồng nhau là cách chắc chắn nhất để mất ô
  // soạn khi đang gõ.
  const chatMode = state.screen === "agent" && Boolean(state.selected) && Boolean(state.agent);
  app.classList.toggle("chat-mode", chatMode);
  app.innerHTML = `${sidebar()}<main class="main">${filteredView()}</main>`;
  // Vòng làm mới chạy 4.5s một lần trong lúc agent xử lý.  Đang dính đáy thì
  // giữ ở đáy; đã cuộn lên đọc lại thì trả đúng chỗ cũ, không giật về cuối.
  const stream = app.querySelector("[data-stream]");
  if (stream) stream.scrollTop = state.stickBottom ? stream.scrollHeight : state.streamScroll;
  // Màn hình Agent tự làm mới trong lúc máy trung tâm chạy. Nếu người dùng
  // đang gõ thì trả con trỏ về ô soạn — không thì mỗi vòng làm mới lại cướp
  // mất chỗ đang gõ dở.
  const composer = app.querySelector("[data-draft]");
  growComposer(composer);
  if (state.composerFocused && composer) {
    composer.focus();
    composer.selectionStart = composer.selectionEnd = composer.value.length;
  }
}

async function selectDashboard(slug, screen = "programs") {
  // Đổi chương trình là đổi cả phạm vi quyền; giữ lại luồng chat cũ sẽ hiển
  // thị dữ liệu của dashboard trước dưới nhãn dashboard mới.
  clearTimeout(state.agentTimer);
  state.agent = null;
  state.thread = null;
  state.draft = "";
  state.agentError = "";
  state.selected = slug;
  state.screen = screen;
  state.tab = "overview";
  try {
    state.detail = state.preview ? sampleDetail(slug) : await api(`/api/dashboards/${encodeURIComponent(slug)}`);
    render();
  } catch (caught) { showToast(caught.message, true); }
}

modal.addEventListener("click", (event) => {
  if (event.target === modal) modal.close("cancel");
});

function showModal(title, intro, body, onSubmitLabel = "Lưu", { submit = true } = {}) {
  const actions = submit
    ? `<button type="button" class="quiet-button" data-modal-close>Huỷ</button><button type="submit" class="primary-button">${esc(onSubmitLabel)}</button>`
    : `<button type="button" class="primary-button" data-modal-close>Đóng</button>`;
  modal.innerHTML = `<form class="modal-body" novalidate><h2>${esc(title)}</h2><p>${esc(intro)}</p><div class="form-grid">${body}</div><div class="modal-actions">${actions}</div></form>`;
  const form = modal.querySelector("form");
  return new Promise((resolve) => {
    const finish = () => {
      const data = Object.fromEntries(new FormData(form).entries());
      for (const input of form.querySelectorAll('input[type="checkbox"]')) data[input.name] = input.checked;
      resolve({ submitted: modal.returnValue === "submit", data });
    };
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      modal.close("submit");
    });
    form.querySelector("[data-modal-close]")?.addEventListener("click", () => modal.close("cancel"));
    modal.addEventListener("close", finish, { once: true });
    modal.showModal();
  });
}

async function openCreateDashboard() {
  if (!state.data.session.is_owner) return showToast("Chỉ Owner có thể tạo chương trình.", true);
  const result = await showModal("Tạo chương trình", "Mỗi chương trình là một dashboard tách biệt về dữ liệu, bot và quyền. Bấm Huỷ, Escape hoặc ra ngoài hộp để bỏ qua hoàn toàn.", `<label>Tên chương trình<input name="name" required maxlength="120" placeholder="Ví dụ: Agent chăm sóc khách hàng" /></label><label>Mô tả<textarea name="description" maxlength="420" placeholder="Mục đích và ranh giới vận hành"></textarea></label><label>Slug (tùy chọn)<input name="slug" maxlength="64" placeholder="agent-cham-soc-khach-hang" /></label><label><input type="checkbox" name="runner_required" checked /> Cần runner để thực thi bot</label>`);
  if (!result.submitted) return;
  try {
    if (state.preview) { showToast("Preview: dashboard sẽ được tạo sau khi triển khai."); return; }
    const output = await api("/api/dashboards", { method: "POST", body: JSON.stringify({ name: result.data.name, description: result.data.description, slug: result.data.slug, runner_required: result.data.runner_required }) });
    showToast("Đã tạo chương trình ở trạng thái chờ thiết lập.");
    await load();
    await selectDashboard(output.dashboard.slug);
  } catch (caught) { showToast(caught.message, true); }
}

async function openCreateBot() {
  if (!state.detail || !can("configure")) return showToast("Bạn không có quyền cấu hình bot.", true);
  const result = await showModal("Tạo bot", "Bot mới sẽ chưa tự chạy nếu chưa được nối với runner bảo mật.", `<label>Tên bot<input name="name" required maxlength="120" placeholder="Ví dụ: Image Generation Runner" /></label><label>Mục đích<textarea name="purpose" maxlength="500" placeholder="Bot thực hiện việc gì, trong phạm vi nào?"></textarea></label><label>Runner key (tùy chọn)<input name="runner_key" maxlength="120" placeholder="Ví dụ: flow-runner-hcm" /></label>`);
  if (!result.submitted) return;
  try {
    if (state.preview) { showToast("Preview: bot sẽ được tạo sau khi triển khai."); return; }
    await api(`/api/dashboards/${encodeURIComponent(state.selected)}/bots`, { method: "POST", body: JSON.stringify({ name: result.data.name, purpose: result.data.purpose, runner_key: result.data.runner_key }) });
    showToast("Đã tạo bot. Hãy nối runner trước khi chạy.");
    await selectDashboard(state.selected, "bots");
  } catch (caught) { showToast(caught.message, true); }
}

async function openMembers() {
  if (!state.detail || !can("manage_members")) return showToast("Chọn một dashboard mà bạn có quyền quản lý thành viên.", true);
  const members = state.detail.members || [];
  const result = await showModal("Quyền truy cập dashboard", "Cấp quyền chỉ cho dashboard đang mở; không cấp quyền sang chương trình khác.", `<div class="mini-list">${members.length ? members.map((member) => `<div class="mini-row"><div><strong>${esc(member.display_name || member.email)}</strong><small>${esc(member.email)}</small></div><span class="status ${esc(member.role)}">${esc(member.role)}</span></div>`).join("") : `<div class="mini-row"><small>Chưa có thành viên được gán riêng.</small></div>`}</div><label>Email công ty<input name="email" type="email" required placeholder="ten@havigroup.llc" /></label><label>Vai trò<select name="role"><option value="viewer">Viewer — chỉ xem</option><option value="reviewer">Reviewer — xem và duyệt</option><option value="operator">Operator — xem và chạy bot</option><option value="admin">Admin — cấu hình và cấp quyền</option></select></label>`, "Cấp quyền");
  if (!result.submitted) return;
  try {
    if (state.preview) { showToast("Preview: quyền sẽ được lưu sau khi triển khai."); return; }
    await api(`/api/dashboards/${encodeURIComponent(state.selected)}/members`, { method: "POST", body: JSON.stringify({ email: result.data.email, role: result.data.role }) });
    showToast("Đã cấp quyền theo dashboard.");
    await selectDashboard(state.selected, state.screen);
  } catch (caught) { showToast(caught.message, true); }
}

async function openRunnerSetup(botId) {
  const bot = state.detail?.bots?.find((item) => item.id === botId);
  if (!bot) return;
  await showModal("Runner chưa kết nối", "Agent sẽ không nhận lệnh và không tự báo chạy khi runner chưa online.", `<div class="setup-note"><strong>Để bật Agent tạo ảnh Content:</strong><ol><li>Chạy Flow v2 trên Mac/VM công ty và đăng nhập Google Flow.</li><li>Tạo Cloudflare Access Service Token giới hạn riêng cho Automation.</li><li>Điền các giá trị vào file runner rồi chạy Content Image Runner.</li></ol><p>Không có thay đổi nào được lưu khi bạn đóng hộp này.</p></div>`, "Đóng", { submit: false });
}

async function openContentRun(slug, botId) {
  const bot = state.detail?.bots?.find((item) => item.id === botId);
  // Bot ERP cần biết ghi ảnh đã duyệt về Task nào.  Để trống thì Flow tự lấy
  // Task từ danh sách nguồn của PROJ-0049, nên ô này không bắt buộc.
  const erpField = bot?.runner_key === "listing2-erp-runner"
    ? `<label>Mã Task ERP nguồn <small>(để trống nếu muốn Flow tự chọn Task trong PROJ-0049)</small><input name="erp_task_id" maxlength="140" pattern="[Tt][Aa][Ss][Kk]-[A-Za-z0-9-]{1,120}" placeholder="TASK-0001" /></label>`
    : "";
  const result = await showModal("Tạo ảnh Content", "Nhập idea rõ ràng. Bấm Huỷ, Escape hoặc ra ngoài hộp sẽ không tạo lệnh nào.", `<label>Idea / prompt<input name="title" maxlength="120" placeholder="Ví dụ: Ảnh lifestyle bình giữ nhiệt cho mùa tựu trường" /></label><label>Mô tả chi tiết<textarea name="prompt" required minlength="5" maxlength="3000" placeholder="Sản phẩm, phong cách, màu sắc, đối tượng, chữ cần tránh…"></textarea></label>${erpField}<div class="form-row"><label>Số ảnh<select name="count"><option value="1">1 ảnh</option><option value="2">2 ảnh</option><option value="3">3 ảnh</option><option value="4">4 ảnh</option></select></label><label>Tỷ lệ<select name="aspect"><option value="landscape">Ngang</option><option value="portrait">Dọc</option><option value="square">Vuông</option></select></label></div>`, "Bắt đầu tạo ảnh");
  if (!result.submitted) return;
  await botAction(slug, botId, "run", result.data);
}

async function botAction(slug, botId, action, options = {}) {
  try {
    if (state.preview) {
      const bot = state.detail?.bots?.find((item) => item.id === botId);
      if (!bot) return;
      if (action === "run") {
        bot.status = "running";
        bot.last_run_at = new Date().toISOString();
        bot.active_run = { id: `preview-${Date.now()}`, title: options.title || "Ảnh Content", prompt: options.prompt, image_count: Number(options.count || 1), aspect: options.aspect || "landscape", status: "queued", created_at: bot.last_run_at };
        showToast("Preview: đã xếp lệnh; nút Dừng đang hoạt động.");
      } else {
        bot.status = "paused";
        bot.last_run_status = "cancelled_before_start";
        bot.active_run = null;
        showToast("Preview: đã huỷ lệnh trước khi runner nhận việc.");
      }
      render();
      return;
    }
    const output = await api(`/api/dashboards/${encodeURIComponent(slug)}/bots/${encodeURIComponent(botId)}/action`, { method: "POST", body: JSON.stringify({ action, ...options }) });
    showToast(output.message || "Đã ghi nhận lệnh bot.");
    await selectDashboard(slug, "bots");
  } catch (caught) { showToast(caught.message, true); }
}

async function reviewApproval(slug, approvalId, status) {
  try {
    if (state.preview) { showToast(`Preview: đã ${status === "approved" ? "duyệt" : "từ chối"} yêu cầu.`); return; }
    await api(`/api/dashboards/${encodeURIComponent(slug)}/approvals/${encodeURIComponent(approvalId)}`, { method: "POST", body: JSON.stringify({ status }) });
    showToast(status === "approved" ? "Đã duyệt yêu cầu." : "Đã từ chối yêu cầu.");
    await selectDashboard(slug, "approvals");
  } catch (caught) { showToast(caught.message, true); }
}

app.addEventListener("input", (event) => {
  if (!event.target.matches("[data-draft]")) return;
  state.draft = event.target.value;
  // Cập nhật tại chỗ chứ không render lại: render lại ở mỗi phím gõ sẽ cắt
  // ngang bộ gõ tiếng Việt đang dựng dở một chữ có dấu.
  growComposer(event.target);
  const send = app.querySelector(".chat-send");
  if (send) send.disabled = !state.draft.trim();
});
// Enter gửi, Shift+Enter xuống dòng — đúng thói quen của mọi app nhắn tin.
app.addEventListener("keydown", (event) => {
  if (!event.target.matches("[data-draft]")) return;
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  void sendAgentMessage();
});
// scroll không nổi bọt nên phải bắt ở pha capture.
app.addEventListener("scroll", (event) => {
  const stream = event.target;
  if (!stream.matches?.("[data-stream]")) return;
  state.streamScroll = stream.scrollTop;
  state.stickBottom = stream.scrollHeight - stream.scrollTop - stream.clientHeight < 64;
}, true);
app.addEventListener("focusin", (event) => {
  if (event.target.matches("[data-draft]")) state.composerFocused = true;
});
app.addEventListener("focusout", (event) => {
  if (!event.target.matches("[data-draft]")) return;
  state.composerFocused = false;
  // Vòng làm mới nền có thể đã âm thầm gom được dữ liệu mới trong lúc gõ mà
  // không vẽ lại (xem refreshAgent) — rời ô nhắn thì hiện luôn, khỏi chờ 4.5s.
  render();
});

app.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action], [data-screen]");
  if (!target) return;
  if (target.dataset.screen) {
    if (target.dataset.screen === "agent") { void openAgent(); return; }
    clearTimeout(state.agentTimer);
    state.screen = target.dataset.screen;
    render();
    return;
  }
  const action = target.dataset.action;
  if (action === "toggle-rail") { state.railOpen = !state.railOpen; render(); }
  if (action === "open-thread") { state.railOpen = false; state.stickBottom = true; void refreshAgent({ threadId: target.dataset.threadId }); }
  if (action === "delete-thread") void deleteThread(target.dataset.threadId, target.dataset.threadTitle);
  if (action === "retry-agent") void refreshAgent();
  if (action === "new-thread") { state.thread = null; state.draft = ""; state.railOpen = false; state.stickBottom = true; render(); }
  if (action === "send-agent") void sendAgentMessage();
  if (action === "decide-request") void decideCodeRequest(target.dataset.requestId, target.dataset.decision);
  if (action === "open-agent-in") void openAgentIn(target.dataset.slug);
  if (action === "open-code-scope") void openCodeScope();
  if (action === "toggle-diff") void toggleDiff(target.dataset.requestId);
  if (action === "open-dashboard") void selectDashboard(target.dataset.slug, "bots");
  if (action === "back-programs") { clearTimeout(state.agentTimer); state.agentError = ""; state.screen = "programs"; render(); }
  if (action === "open-create-dashboard") void openCreateDashboard();
  if (action === "open-create-bot") void openCreateBot();
  if (action === "open-members") void openMembers();
  if (action === "open-runner-setup") void openRunnerSetup(target.dataset.botId);
  if (action === "open-content-run") void openContentRun(target.dataset.slug, target.dataset.botId);
  if (action === "bot-action") void botAction(target.dataset.slug, target.dataset.botId, target.dataset.botAction);
  if (action === "review-approval") void reviewApproval(target.dataset.slug, target.dataset.approvalId, target.dataset.status);
});

load();
