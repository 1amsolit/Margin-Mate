"use strict";

const App = (() => {

  // ── State ──────────────────────────────────────────────────────
  let _orders     = [];
  let _inventory  = [];
  let _config     = {};
  let _statusPoll = null;
  let _expanded   = null;        // currently expanded order id
  let _filterStatus   = "all";
  let _filterMerchant = "all";
  let _invSubtab  = "inventory";

  // ── API ────────────────────────────────────────────────────────
  const api = {
    async get(url) {
      const r = await fetch(url);
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },
    async post(url, data) {
      const r = await fetch(url, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(data) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      return j;
    },
    async put(url, data) {
      const r = await fetch(url, { method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(data) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      return j;
    },
    async del(url) {
      const r = await fetch(url, { method:"DELETE" });
      if (!r.ok) throw new Error(r.statusText);
      return r.json();
    },
  };

  // ── Helpers ────────────────────────────────────────────────────
  const fmtAUD = v => v == null ? "—" :
    new Intl.NumberFormat("en-AU", { style:"currency", currency:"AUD" }).format(v);

  const fmtDate = s => {
    if (!s) return "—";
    const d = new Date(s);
    return isNaN(d) ? s.slice(0,10) : d.toLocaleDateString("en-AU", { day:"2-digit", month:"short", year:"numeric" });
  };

  const esc = s => String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");

  const MERCHANT_EMOJI = { Amazon:"📦", Target:"🛒", Kmart:"🛍️", Shopify:"🏪", BigW:"🏬" };

  function badge(status) {
    const labels = { confirmed:"Confirmed", shipped:"Shipped", delivered:"Delivered", cancelled:"Cancelled", refunded:"Refunded" };
    return `<span class="badge badge-${status}"><span class="badge-dot"></span>${labels[status]||status}</span>`;
  }

  function trackCell(o) {
    if (!o.tracking_number) return `<span style="color:var(--t5)">—</span>`;
    if (o.tracking_url)
      return `<a class="track-link" href="${esc(o.tracking_url)}" target="_blank" rel="noopener">📮 ${esc(o.tracking_number)}</a>`;
    return `<span style="font-family:'DM Mono',monospace;font-size:12px;color:var(--t2)">${esc(o.tracking_number)}</span>`;
  }

  // ── Debounce ───────────────────────────────────────────────────
  const _timers = new Map();
  function debounce(fn, ms=300) {
    return (...args) => {
      if (_timers.has(fn)) clearTimeout(_timers.get(fn));
      _timers.set(fn, setTimeout(() => { fn(...args); _timers.delete(fn); }, ms));
    };
  }

  // ── Toast ──────────────────────────────────────────────────────
  function toast(msg, type="info") {
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.getElementById("toast-container").appendChild(el);
    setTimeout(() => { el.classList.add("fade"); setTimeout(() => el.remove(), 350); }, 3200);
  }

  // ── Modal ──────────────────────────────────────────────────────
  function showModal(title, html) {
    document.getElementById("modal-title").textContent = title;
    document.getElementById("modal-body").innerHTML = html;
    document.getElementById("modal-overlay").classList.remove("hidden");
  }
  function closeModal(e) {
    if (e && e.target !== document.getElementById("modal-overlay")) return;
    document.getElementById("modal-overlay").classList.add("hidden");
  }
  function _hideModal() {
    document.getElementById("modal-overlay").classList.add("hidden");
  }

  // ── Tab switching ──────────────────────────────────────────────
  function switchTab(name) {
    document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
    document.querySelectorAll(".tab-pill").forEach(b => b.classList.remove("active"));
    document.getElementById(`tab-${name}`).classList.add("active");
    document.querySelector(`[data-tab="${name}"]`).classList.add("active");
    if (name === "orders")    { loadStats(); loadOrders(); }
    if (name === "inventory") { loadStats(); loadInventory(); loadSalesData(); }
    if (name === "sales")     { loadStats(); loadSalesTab(); }
    if (name === "settings")  { loadConfig(); pollEmailStatus(); }
  }

  // ── Stats ──────────────────────────────────────────────────────
  async function loadStats() {
    try {
      const s = await api.get("/api/stats");
      // Order stats sidebar counts
      document.getElementById("sc-all").textContent       = s.orders_total;
      document.getElementById("sc-confirmed").textContent = s.orders_confirmed;
      document.getElementById("sc-shipped").textContent   = s.orders_shipped;
      document.getElementById("sc-delivered").textContent = s.orders_delivered;
      document.getElementById("sc-cancelled").textContent = s.orders_cancelled;

      // Order stats cards
      document.getElementById("order-stats").innerHTML = [
        { label:"Total Orders",   value:s.orders_total,     icon:"📋", cls:"" },
        { label:"Confirmed",      value:s.orders_confirmed, icon:"⏳", cls:"indigo" },
        { label:"Shipped",        value:s.orders_shipped,   icon:"🚚", cls:"" },
        { label:"Delivered",      value:s.orders_delivered, icon:"✅", cls:"green" },
        { label:"Cancelled",      value:s.orders_cancelled, icon:"✕",  cls:"red" },
      ].map((c,i) => statCard(c, i)).join("");

      // Inventory stats
      document.getElementById("inv-stats").innerHTML = [
        { label:"Inventory Items",  value:s.inventory_items,           icon:"📦",  cls:"" },
        { label:"Inventory Value",  value:fmtAUD(s.inventory_value),   icon:"💸",  cls:"yellow" },
        { label:"Total Revenue",    value:fmtAUD(s.revenue),           icon:"💰",  cls:"green" },
        { label:"Total Profit",     value:fmtAUD(s.profit),            icon: s.profit>=0?"📈":"📉", cls: s.profit>=0?"green":"red" },
        { label:"Margin",           value:s.margin_pct.toFixed(1)+"%", icon:"🎯",  cls: s.margin_pct>=0?"green":"red" },
      ].map((c,i) => statCard(c, i)).join("");

      // Sales stats
      document.getElementById("sales-stats").innerHTML = [
        { label:"Revenue",  value:fmtAUD(s.revenue), icon:"💰", cls:"green" },
        { label:"Cost",     value:fmtAUD(s.cost),    icon:"💸", cls:"yellow" },
        { label:"Profit",   value:fmtAUD(s.profit),  icon: s.profit>=0?"📈":"📉", cls: s.profit>=0?"green":"red" },
        { label:"Margin",   value:s.margin_pct.toFixed(1)+"%", icon:"🎯", cls: s.margin_pct>=0?"green":"red" },
      ].map((c,i) => statCard(c, i)).join("");

    } catch(e) { console.error(e); }
  }

  function statCard({label, value, icon, cls}, i) {
    return `<div class="stat-card" style="animation-delay:${i*0.07}s">
      <div class="stat-card-top">
        <p class="stat-label">${label}</p>
        <span class="stat-icon">${icon}</span>
      </div>
      <p class="stat-value ${cls}">${value}</p>
    </div>`;
  }

  // ── Sidebar filters ────────────────────────────────────────────
  function setSidebarFilter(val, btn) {
    _filterStatus = val;
    document.querySelectorAll(".sidebar-btn[data-filter]").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    loadOrders();
  }

  function setSidebarMerchant(val, btn) {
    _filterMerchant = val;
    document.querySelectorAll(".sidebar-btn[data-merchant]").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    loadOrders();
  }

  // ── Orders ─────────────────────────────────────────────────────
  async function loadOrders() {
    const search = document.getElementById("f-search")?.value || "";
    const params = new URLSearchParams();
    if (_filterStatus   !== "all") params.set("status",   _filterStatus);
    if (_filterMerchant !== "all") params.set("merchant", _filterMerchant);
    if (search) params.set("search", search);

    const el = document.getElementById("orders-list");
    el.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⏳</div><p>Loading…</p></div>`;

    try {
      _orders = await api.get("/api/orders?" + params);
      renderOrders();
    } catch(e) { toast("Failed to load orders", "error"); }
  }

  function renderOrders() {
    const el = document.getElementById("orders-list");
    if (!el) return;
    if (!_orders.length) {
      el.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📭</div><p>No orders found.</p></div>`;
      return;
    }
    el.innerHTML = `<div class="orders-list">${_orders.map((o,i) => renderOrder(o,i)).join("")}</div>`;
  }

  function renderOrderExpanded(o) {
    return `<div class="order-expanded">
      ${[
        { label:"Order #",    value: o.order_number || "—", mono:true },
        { label:"Order Date", value: fmtDate(o.order_date), mono:true },
        { label:"Merchant",   value: o.merchant || "—" },
        { label:"Amount",     value: fmtAUD(o.amount) },
        { label:"Tracking",   value: "__tracking__" },
        { label:"Carrier",    value: o.carrier || "—" },
        { label:"Notes",      value: o.notes || "—" },
      ].map(d => `<div>
        <p class="detail-label">${d.label}</p>
        <p class="detail-value${d.mono?" mono":""}">${d.value === "__tracking__" ? trackCell(o) : esc(d.value)}</p>
      </div>`).join("")}
    </div>`;
  }

  function renderOrder(o, i) {
    const emoji = MERCHANT_EMOJI[o.merchant] || "🛍️";
    const title = o.item_description || o.email_subject || "Order";
    return `<div class="order-card" data-order-id="${o.id}" style="animation-delay:${i*0.04}s" onclick="App.toggleOrder(${o.id})">
      <div class="order-card-main">
        <div class="order-icon">${emoji}</div>
        <div class="order-info">
          <div class="order-title" title="${esc(title)}">${esc(title)}</div>
          <div class="order-meta">
            <span class="order-store">${esc(o.merchant)}</span>
            ${o.order_number ? `<span class="order-meta-sep">·</span><span class="order-num">${esc(o.order_number)}</span>` : ""}
            ${o.order_date   ? `<span class="order-meta-sep">·</span><span class="order-date-m">${fmtDate(o.order_date)}</span>` : ""}
          </div>
        </div>
        <div class="order-right">
          ${o.amount ? `<span class="order-amount">${fmtAUD(o.amount)}</span>` : ""}
          ${badge(o.status)}
          <div class="order-actions" onclick="event.stopPropagation()">
            <button class="btn-icon" title="Edit"   onclick="App.openOrderModal(${o.id})">✏</button>
            <button class="btn-icon" title="Delete" onclick="App.deleteOrder(${o.id})">🗑</button>
          </div>
        </div>
      </div>
    </div>`;
  }

  function toggleOrder(id) {
    const card = document.querySelector(`[data-order-id="${id}"]`);
    if (!card) return;

    const isOpen = _expanded === id;

    // Collapse any open card
    if (_expanded !== null) {
      const prev = document.querySelector(`[data-order-id="${_expanded}"]`);
      if (prev) {
        prev.classList.remove("expanded");
        const exp = prev.querySelector(".order-expanded");
        if (exp) exp.remove();
      }
    }

    if (isOpen) {
      _expanded = null;
    } else {
      _expanded = id;
      const order = _orders.find(o => o.id === id);
      if (order) {
        card.classList.add("expanded");
        card.insertAdjacentHTML("beforeend", renderOrderExpanded(order));
      }
    }
  }

  function openOrderModal(id = null) {
    const isEdit = id !== null;
    const go = async () => {
      let o = {};
      if (isEdit) {
        const all = await api.get("/api/orders");
        o = all.find(x => x.id === id) || {};
      }
      const merchants = ["Amazon","Target","Kmart","Shopify","BigW"];
      const statuses  = ["confirmed","shipped","delivered","cancelled","refunded"];

      const html = `<form id="order-form">
        <div class="form-row">
          <div class="form-group">
            <label class="label">Merchant</label>
            <select id="o-merchant" class="select input-full" required>
              <option value="">Select…</option>
              ${merchants.map(m => `<option ${o.merchant===m?"selected":""} value="${m}">${m}</option>`).join("")}
            </select>
          </div>
          <div class="form-group">
            <label class="label">Status</label>
            <select id="o-status" class="select input-full" onchange="App._trackingToggle()" required>
              ${statuses.map(s => `<option ${o.status===s?"selected":""} value="${s}">${s[0].toUpperCase()+s.slice(1)}</option>`).join("")}
            </select>
          </div>
        </div>
        <div class="form-group">
          <label class="label">Order Number</label>
          <input id="o-num" class="input input-full" placeholder="e.g. 123-4567890-1234567" value="${esc(o.order_number)}" />
        </div>
        <div class="form-group">
          <label class="label">Item Description</label>
          <input id="o-desc" class="input input-full" placeholder="What was ordered?" value="${esc(o.item_description)}" />
        </div>
        <div class="form-row">
          <div class="form-group">
            <label class="label">Amount (AUD)</label>
            <input id="o-amount" class="input input-full" type="number" step="0.01" value="${o.amount??""}" placeholder="0.00" />
          </div>
          <div class="form-group">
            <label class="label">Order Date</label>
            <input id="o-date" class="input input-full" type="date" value="${(o.order_date||"").slice(0,10)}" />
          </div>
        </div>
        <div id="tracking-fields" style="display:none">
          <div class="form-group">
            <label class="label">Tracking Number</label>
            <input id="o-tracking" class="input input-full" value="${esc(o.tracking_number)}" placeholder="e.g. JD000000000000000000" />
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="label">Carrier</label>
              <select id="o-carrier" class="select input-full">
                <option value="">Auto-detect</option>
                ${["Australia Post","StarTrack","Couriers Please","DHL","FedEx","UPS","Amazon Logistics","Sendle","Aramex/Fastway","TNT","Toll"]
                  .map(c => `<option ${o.carrier===c?"selected":""} value="${c}">${c}</option>`).join("")}
              </select>
            </div>
            <div class="form-group">
              <label class="label">Tracking URL</label>
              <input id="o-trackurl" class="input input-full" value="${esc(o.tracking_url)}" placeholder="https://…" />
            </div>
          </div>
        </div>
        <div class="form-group">
          <label class="label">Notes</label>
          <textarea id="o-notes" class="input input-full">${esc(o.notes)}</textarea>
        </div>
        <div class="form-actions">
          <button type="button" class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
          <button type="submit" class="btn btn-primary">${isEdit?"Save Changes":"Add Order"}</button>
        </div>
      </form>`;

      showModal(isEdit ? "Edit Order" : "Add Order", html);
      _trackingToggle();

      document.getElementById("order-form").onsubmit = async e => {
        e.preventDefault();
        const status = document.getElementById("o-status").value;
        const data = {
          merchant:         document.getElementById("o-merchant").value,
          order_number:     document.getElementById("o-num").value,
          status,
          item_description: document.getElementById("o-desc").value,
          amount:           parseFloat(document.getElementById("o-amount").value) || null,
          order_date:       document.getElementById("o-date").value,
          tracking_number:  document.getElementById("o-tracking").value || null,
          carrier:          document.getElementById("o-carrier").value  || null,
          tracking_url:     document.getElementById("o-trackurl").value || null,
          notes:            document.getElementById("o-notes").value,
        };
        try {
          if (isEdit) await api.put(`/api/orders/${id}`, data);
          else        await api.post("/api/orders", data);
          toast(isEdit ? "Order updated" : "Order added", "success");
          _hideModal();
          loadOrders(); loadStats();
        } catch(err) { toast(err.message, "error"); }
      };
    };
    go();
  }

  function _trackingToggle() {
    const s = document.getElementById("o-status")?.value;
    const tf = document.getElementById("tracking-fields");
    if (tf) tf.style.display = s === "shipped" ? "block" : "none";
  }

  async function deleteOrder(id) {
    if (!confirm("Delete this order?")) return;
    try {
      await api.del(`/api/orders/${id}`);
      toast("Deleted", "info");
      loadOrders(); loadStats();
    } catch(e) { toast(e.message, "error"); }
  }

  // ── Inventory ──────────────────────────────────────────────────
  function switchInvSubtab(tab) {
    _invSubtab = tab;
    document.getElementById("inv-subtab-inventory").classList.toggle("active", tab === "inventory");
    document.getElementById("inv-subtab-sales").classList.toggle("active",     tab === "sales");
    document.getElementById("inventory-list").style.display = tab === "inventory" ? "" : "none";
    document.getElementById("inv-sales-wrap").style.display = tab === "sales"     ? "" : "none";

    const btn = document.getElementById("inv-action-btn");
    btn.innerHTML = tab === "inventory"
      ? `<button class="btn btn-primary" onclick="App.openInventoryModal()">+ Add Item</button>`
      : `<button class="btn btn-success" onclick="App.openSaleModal()">+ Record Sale</button>`;
  }

  async function loadInventory() {
    _inventory = await api.get("/api/inventory").catch(() => []);
    const el = document.getElementById("inventory-list");
    if (!_inventory.length) {
      el.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📦</div><p>No inventory items yet.</p></div>`;
      return;
    }
    el.innerHTML = `<div style="display:flex;flex-direction:column;gap:8px">
      ${_inventory.map((item, i) => renderInventoryCard(item, i)).join("")}
    </div>`;

    // update subtab button
    switchInvSubtab(_invSubtab);
  }

  function renderInventoryCard(item, i) {
    const qty = item.quantity || 0;
    const qtyColor = qty === 0 ? "var(--red)" : qty < 5 ? "var(--yellow)" : "var(--green)";
    const margin = item.sale_price > 0
      ? ((item.sale_price - item.cost_price) / item.sale_price * 100).toFixed(1) + "%"
      : "—";
    return `<div class="item-card" style="animation-delay:${i*0.04}s">
      <div class="item-card-main">
        <div class="item-icon">📦</div>
        <div class="item-info">
          <div class="item-name">${esc(item.product_name)}</div>
          <div class="item-sub">
            ${item.sku ? esc(item.sku) + " · " : ""}
            ${item.category ? esc(item.category) + " · " : ""}
            Margin: ${margin}
          </div>
        </div>
        <div class="item-right">
          <div class="item-price-block">
            <div class="item-price">${fmtAUD(item.cost_price)} <span style="color:var(--t3);font-weight:400;font-size:12px">cost</span></div>
            <div class="item-price-sub">${fmtAUD(item.sale_price)} sale · <span style="color:${qtyColor};font-weight:600">${qty} in stock</span></div>
          </div>
          <div class="item-actions">
            ${qty > 0 ? `<button class="btn-sell" onclick="App.openSaleModal(${item.id})">💵 Sell</button>` : ""}
            <button class="btn-icon" title="Edit"   onclick="App.openInventoryModal(${item.id})">✏</button>
            <button class="btn-icon" title="Delete" onclick="App.deleteInventoryItem(${item.id})">🗑</button>
          </div>
        </div>
      </div>
    </div>`;
  }

  function openInventoryModal(id = null) {
    const isEdit = id !== null;
    const go = async () => {
      let item = {};
      if (isEdit) {
        const all = await api.get("/api/inventory");
        item = all.find(x => x.id === id) || {};
      }

      // Fetch suggestions from tracked order items (only for new items)
      let suggestions = [];
      if (!isEdit) {
        suggestions = await api.get("/api/inventory/suggestions").catch(() => []);
      }

      const suggestionsHtml = suggestions.length ? `
        <div class="form-group">
          <label class="label">From tracked orders <span style="color:var(--t4);font-weight:400">(click to pre-fill)</span></label>
          <div id="inv-suggestions" style="display:flex;flex-wrap:wrap;gap:6px;max-height:140px;overflow-y:auto;padding:4px 0">
            ${suggestions.map(s => `
              <button type="button" class="suggestion-chip" onclick="App._pickSuggestion(${JSON.stringify(esc(s.item_description))})">
                ${esc(s.item_description)}
              </button>`).join("")}
          </div>
        </div>` : "";

      const html = `<form id="inv-form">
        ${suggestionsHtml}
        <div class="form-group">
          <label class="label">Product Name *</label>
          <input id="i-name" class="input input-full" required placeholder="e.g. Nike Air Max 90" value="${esc(item.product_name)}" />
        </div>
        <div class="form-row">
          <div class="form-group">
            <label class="label">SKU</label>
            <input id="i-sku" class="input input-full" placeholder="e.g. NK-AM-42" value="${esc(item.sku)}" />
          </div>
          <div class="form-group">
            <label class="label">Category</label>
            <input id="i-cat" class="input input-full" placeholder="e.g. Footwear" value="${esc(item.category)}" />
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label class="label">Quantity</label>
            <input id="i-qty" class="input input-full" type="number" min="0" value="${item.quantity??0}" required />
          </div>
          <div class="form-group">
            <label class="label">Cost Price (AUD)</label>
            <input id="i-cost" class="input input-full" type="number" step="0.01" value="${item.cost_price??""}" placeholder="0.00" oninput="App._invMargin()" />
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label class="label">Sale Price (AUD)</label>
            <input id="i-sale" class="input input-full" type="number" step="0.01" value="${item.sale_price??""}" placeholder="0.00" oninput="App._invMargin()" />
          </div>
          <div class="form-group" style="display:flex;align-items:flex-end;padding-bottom:2px">
            <p id="i-margin-preview" class="hint" style="color:var(--green)"></p>
          </div>
        </div>
        <div class="form-group">
          <label class="label">Notes</label>
          <textarea id="i-notes" class="input input-full">${esc(item.notes)}</textarea>
        </div>
        <div class="form-actions">
          <button type="button" class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
          <button type="submit" class="btn btn-primary">${isEdit?"Save Changes":"Add Item"}</button>
        </div>
      </form>`;

      showModal(isEdit ? "Edit Item" : "Add Inventory Item", html);
      if (isEdit) _invMargin();

      document.getElementById("inv-form").onsubmit = async e => {
        e.preventDefault();
        const data = {
          product_name: document.getElementById("i-name").value,
          sku:          document.getElementById("i-sku").value  || null,
          category:     document.getElementById("i-cat").value  || null,
          quantity:     parseInt(document.getElementById("i-qty").value)  || 0,
          cost_price:   parseFloat(document.getElementById("i-cost").value) || 0,
          sale_price:   parseFloat(document.getElementById("i-sale").value) || 0,
          notes:        document.getElementById("i-notes").value || null,
        };
        try {
          if (isEdit) await api.put(`/api/inventory/${id}`, data);
          else        await api.post("/api/inventory", data);
          toast(isEdit ? "Item updated" : "Item added", "success");
          _hideModal();
          loadInventory(); loadStats();
        } catch(err) { toast(err.message, "error"); }
      };
    };
    go();
  }

  function _pickSuggestion(name) {
    const el = document.getElementById("i-name");
    if (el) {
      el.value = name;
      el.focus();
      // Highlight active chip
      document.querySelectorAll(".suggestion-chip").forEach(c => {
        c.classList.toggle("active", c.textContent.trim() === name);
      });
    }
  }

  function _invMargin() {
    const cost = parseFloat(document.getElementById("i-cost")?.value) || 0;
    const sale = parseFloat(document.getElementById("i-sale")?.value) || 0;
    const el   = document.getElementById("i-margin-preview");
    if (!el) return;
    if (sale > 0) {
      const m = ((sale-cost)/sale*100).toFixed(1);
      const p = (sale-cost).toFixed(2);
      el.textContent = `Margin: ${m}%  ·  Profit: $${p}`;
      el.style.color = (sale-cost) >= 0 ? "var(--green)" : "var(--red)";
    } else { el.textContent = ""; }
  }

  async function deleteInventoryItem(id) {
    if (!confirm("Delete this item?")) return;
    try {
      await api.del(`/api/inventory/${id}`);
      toast("Deleted", "info");
      loadInventory(); loadStats();
    } catch(e) { toast(e.message, "error"); }
  }

  // ── Sales ──────────────────────────────────────────────────────
  async function loadSalesData() {
    const sales = await api.get("/api/sales").catch(() => []);
    renderSalesList("sales-list", sales);
  }

  async function loadSalesTab() {
    const sales = await api.get("/api/sales").catch(() => []);
    renderSalesList("sales-list2", sales);
  }

  function renderSalesList(elId, sales) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (!sales.length) {
      el.innerHTML = `<div class="empty-state"><div class="empty-state-icon">💵</div><p>No sales recorded yet.</p></div>`;
      return;
    }
    el.innerHTML = sales.map((s, i) => {
      const profit = (s.sale_price - s.cost_price) * s.quantity_sold;
      return `<div class="sale-row" style="animation-delay:${i*0.03}s">
        <div style="min-width:0">
          <div class="sale-name">${esc(s.product_name || "—")}</div>
          ${s.quantity_sold > 1 ? `<div style="color:var(--t4);font-size:11px">×${s.quantity_sold} units</div>` : ""}
        </div>
        <span class="sale-platform">${esc(s.order_ref||"—")}</span>
        <span class="sale-num" style="color:var(--text)">${fmtAUD(s.sale_price)}</span>
        <span class="sale-profit ${profit>=0?"profit-pos":"profit-neg"}">${profit>=0?"+":""}${fmtAUD(profit)}</span>
        <span class="sale-num" style="color:var(--t3)">${fmtAUD(s.cost_price)}</span>
        <span style="color:var(--t4);font-size:11px">${fmtDate(s.sale_date)}</span>
        <div class="item-actions">
          <button class="btn-icon" title="Delete" onclick="App.deleteSale(${s.id})">🗑</button>
        </div>
      </div>`;
    }).join("");
  }

  function openSaleModal(preselectedId = null) {
    const go = async () => {
      if (!_inventory.length) _inventory = await api.get("/api/inventory").catch(() => []);
      if (!_inventory.length) { toast("Add inventory items first", "error"); return; }

      const today = new Date().toISOString().slice(0,10);
      const opts  = _inventory.map(i =>
        `<option value="${i.id}" data-sale="${i.sale_price}" data-cost="${i.cost_price}" ${i.id===preselectedId?"selected":""}>
          ${esc(i.product_name)} (${i.quantity} in stock)
        </option>`
      ).join("");

      const html = `<form id="sale-form">
        <div class="form-group">
          <label class="label">Product *</label>
          <select id="s-item" class="select input-full" required onchange="App._saleItemChange()">${opts}</select>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label class="label">Quantity *</label>
            <input id="s-qty" class="input input-full" type="number" min="1" value="1" required oninput="App._saleProfit()" />
          </div>
          <div class="form-group">
            <label class="label">Sale Price (AUD) *</label>
            <input id="s-price" class="input input-full" type="number" step="0.01" required oninput="App._saleProfit()" />
          </div>
        </div>
        <div id="profit-preview"></div>
        <div class="form-row">
          <div class="form-group">
            <label class="label">Sale Date</label>
            <input id="s-date" class="input input-full" type="date" value="${today}" style="color-scheme:dark" />
          </div>
          <div class="form-group">
            <label class="label">Order Reference</label>
            <input id="s-ref" class="input input-full" placeholder="Optional" />
          </div>
        </div>
        <div class="form-group">
          <label class="label">Notes</label>
          <textarea id="s-notes" class="input input-full" placeholder="Optional"></textarea>
        </div>
        <div class="form-actions">
          <button type="button" class="btn btn-ghost" onclick="App.closeModal()">Cancel</button>
          <button type="submit" class="btn btn-success">Record Sale</button>
        </div>
      </form>`;

      showModal("Record Sale", html);
      _saleItemChange();

      document.getElementById("sale-form").onsubmit = async e => {
        e.preventDefault();
        const data = {
          inventory_id:  parseInt(document.getElementById("s-item").value),
          quantity_sold: parseInt(document.getElementById("s-qty").value),
          sale_price:    parseFloat(document.getElementById("s-price").value),
          sale_date:     document.getElementById("s-date").value,
          order_ref:     document.getElementById("s-ref").value   || null,
          notes:         document.getElementById("s-notes").value || null,
        };
        try {
          await api.post("/api/sales", data);
          toast("Sale recorded", "success");
          _hideModal();
          loadInventory(); loadSalesData(); loadSalesTab(); loadStats();
        } catch(err) { toast(err.message, "error"); }
      };
    };
    go();
  }

  function _saleItemChange() {
    const sel = document.getElementById("s-item");
    if (!sel) return;
    const opt = sel.options[sel.selectedIndex];
    const priceEl = document.getElementById("s-price");
    if (priceEl && opt.dataset.sale) priceEl.value = parseFloat(opt.dataset.sale).toFixed(2);
    _saleProfit();
  }

  function _saleProfit() {
    const sel = document.getElementById("s-item");
    if (!sel) return;
    const opt    = sel.options[sel.selectedIndex];
    const cost   = parseFloat(opt?.dataset.cost) || 0;
    const price  = parseFloat(document.getElementById("s-price")?.value) || 0;
    const qty    = parseInt(document.getElementById("s-qty")?.value) || 1;
    const profit = (price - cost) * qty;
    const el     = document.getElementById("profit-preview");
    if (!el) return;
    if (!price) { el.innerHTML = ""; return; }
    const pos = profit >= 0;
    el.innerHTML = `<div class="profit-preview ${pos?"pos":"neg"}">
      <span style="color:var(--t3);font-size:12px">Estimated profit</span>
      <span style="color:${pos?"var(--green)":"var(--red)"};font-size:16px;font-weight:700">${pos?"+":""}${fmtAUD(profit)}</span>
    </div>`;
  }

  async function deleteSale(id) {
    if (!confirm("Delete this sale? Stock will be restored.")) return;
    try {
      await api.del(`/api/sales/${id}`);
      toast("Deleted", "info");
      loadInventory(); loadSalesData(); loadSalesTab(); loadStats();
    } catch(e) { toast(e.message, "error"); }
  }

  // ── Email check ────────────────────────────────────────────────
  async function checkEmails() {
    const icon = document.getElementById("sync-icon");
    if (icon) icon.classList.add("spin");
    try {
      await api.post("/api/email/check", {});
      toast("Email check started…", "info");
      pollEmailStatus();
    } catch(e) { toast(e.message, "error"); }
  }

  function pollEmailStatus() {
    if (_statusPoll) clearInterval(_statusPoll);
    const update = async () => {
      try {
        const s = await api.get("/api/email/status");
        const chip = document.getElementById("email-chip");
        if (chip) {
          chip.className = `email-chip ${s.status}`;
          chip.textContent = s.status === "running" ? "Checking…" : (s.message || s.status);
        }
        const icon = document.getElementById("sync-icon");
        if (icon) icon.classList.toggle("spin", s.status === "running");
        renderCheckInfo(s);
        if (s.status !== "running" && _statusPoll) {
          clearInterval(_statusPoll); _statusPoll = null;
          if (s.status === "idle" && document.getElementById("tab-orders").classList.contains("active")) {
            loadOrders(); loadStats();
          }
        }
      } catch(e) {}
    };
    update();
    _statusPoll = setInterval(update, 2000);
  }

  function renderCheckInfo(s) {
    const el = document.getElementById("email-check-info");
    if (!el) return;
    const last = s.last_check
      ? fmtDate(s.last_check) + " " + new Date(s.last_check).toLocaleTimeString("en-AU")
      : "Never";
    el.innerHTML = `
      <div class="check-row"><span class="check-key">Status</span><span class="check-val">${esc(s.status)}</span></div>
      <div class="check-row"><span class="check-key">Last check</span><span class="check-val">${last}</span></div>
      <div class="check-row"><span class="check-key">Message</span><span class="check-val">${esc(s.message)}</span></div>`;
  }

  // ── Settings / Config ──────────────────────────────────────────
  async function loadConfig() {
    try {
      _config = await api.get("/api/config");
      const imap = _config.imap || {};
      document.getElementById("cfg-host").value        = imap.host     || "";
      document.getElementById("cfg-port").value        = imap.port     || 993;
      document.getElementById("cfg-user").value        = imap.username || "";
      document.getElementById("cfg-pass").value        = imap.password || "";
      document.getElementById("cfg-interval").value    = imap.check_interval_seconds || 300;
      document.getElementById("cfg-days").value        = imap.scan_days_back || 30;
      document.getElementById("cfg-auspost-key").value = (_config.auspost || {}).api_key || "";

      const container = document.getElementById("merchant-toggles");
      container.innerHTML = Object.entries(_config.merchants || {}).map(([name, cfg]) => `
        <div class="merchant-row">
          <div>
            <div class="merchant-name">${MERCHANT_EMOJI[name]||"🛍"} ${name}</div>
            <div class="merchant-patterns">${(cfg.sender_patterns||[]).join(", ")}</div>
          </div>
          <label class="toggle">
            <input type="checkbox" id="toggle-${name}" ${cfg.enabled?"checked":""} />
            <span class="toggle-track"></span>
          </label>
        </div>`).join("");

      pollEmailStatus();
    } catch(e) { toast("Failed to load config", "error"); }
  }

  async function saveConfig(e) {
    e.preventDefault();
    const data = { imap: {
      host:                   document.getElementById("cfg-host").value,
      port:                   parseInt(document.getElementById("cfg-port").value),
      username:               document.getElementById("cfg-user").value,
      password:               document.getElementById("cfg-pass").value,
      check_interval_seconds: parseInt(document.getElementById("cfg-interval").value),
      scan_days_back:         parseInt(document.getElementById("cfg-days").value),
    }};
    try { await api.put("/api/config", data); toast("Saved", "success"); }
    catch(e) { toast(e.message, "error"); }
  }

  async function saveMerchants() {
    const merchants = {};
    Object.entries(_config.merchants || {}).forEach(([name, cfg]) => {
      merchants[name] = { ...cfg, enabled: !!document.getElementById(`toggle-${name}`)?.checked };
    });
    try { await api.put("/api/config", { merchants }); toast("Merchant settings saved", "success"); }
    catch(e) { toast(e.message, "error"); }
  }

  async function saveAuspostKey() {
    const key = document.getElementById("cfg-auspost-key")?.value || "";
    try {
      await api.put("/api/config", { auspost: { api_key: key } });
      toast("AusPost API key saved", "success");
    } catch(e) { toast(e.message, "error"); }
  }

  async function checkDeliveries() {
    try {
      await api.post("/api/tracking/check", {});
      toast("Delivery check started…", "info");
      setTimeout(() => { loadOrders(); loadStats(); }, 3000);
    } catch(e) { toast(e.message, "error"); }
  }

  // ── Init ───────────────────────────────────────────────────────
  function init() {
    loadStats();
    loadOrders();
    pollEmailStatus();
    // Set up inventory subtab button on first render
    const btn = document.getElementById("inv-action-btn");
    if (btn) btn.innerHTML = `<button class="btn btn-primary" onclick="App.openInventoryModal()">+ Add Item</button>`;
  }

  document.addEventListener("DOMContentLoaded", init);

  // ── Public ─────────────────────────────────────────────────────
  return {
    switchTab, setSidebarFilter, setSidebarMerchant,
    loadOrders, loadInventory, loadSalesData, loadSalesTab,
    toggleOrder, openOrderModal, deleteOrder,
    openInventoryModal, deleteInventoryItem, switchInvSubtab, _pickSuggestion,
    openSaleModal, deleteSale,
    checkEmails, saveConfig, saveMerchants, saveAuspostKey, checkDeliveries,
    closeModal, debounce,
    _trackingToggle, _invMargin, _saleItemChange, _saleProfit,
  };
})();
