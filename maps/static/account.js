"use strict";
// Account, sign-in and members (D52). Loaded after app.js.
// In single-user mode (CONTINUUM_AUTH=off) /api/me does not exist and this file
// changes nothing. When sign-in is on, the server decides who you are: the
// "You:" picker becomes your account, and every change is recorded as you.

var ME = null;   // {user:{email,name,role,actor,workspace}, workspaces:[…]} when signed in

// ---- every request: a lost session goes to sign-in; a conflict reloads ----
(function () {
  var orig = window.fetch.bind(window);
  window.fetch = function (input, init) {
    return orig(input, init).then(function (r) {
      if (r.status === 401 && ME) { location.href = "/auth/login?next=" + encodeURIComponent(location.pathname + location.search); }
      if (r.status === 409) { ccToast("Someone saved this first — you're now looking at the latest version. Re-apply your change if it still applies.", "warn"); if (typeof load === "function") load().then(function () { if (typeof renderCenter === "function") renderCenter(); }); }
      return r;
    });
  };
})();

function ccToast(text, kind) {
  var t = document.getElementById("cc-toast");
  if (!t) { t = document.createElement("div"); t.id = "cc-toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
  t.className = "cc-toast " + (kind || "ok");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(t._h);
  t._h = setTimeout(function () { t.hidden = true; }, 6000);
}

function isRole(min) {
  if (!ME) return true;  // single-user mode: everything is allowed, as before
  var rank = { viewer: 1, editor: 2, approver: 3, admin: 4 };
  return (rank[ME.user.role] || 0) >= rank[min];
}

fetch("/api/me").then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
  if (!d || !d.user) return;
  ME = d;
  document.body.classList.add("signed-in");
  document.body.setAttribute("data-cc-role", d.user.role);
  if (typeof setIdentity === "function") setIdentity(d.user.name || d.user.email, d.user.actor);
  var who = document.getElementById("who-btn");
  if (who) {
    who.textContent = (d.user.name || d.user.email) + " · " + d.user.role;
    who.title = "Signed in as " + d.user.email + " — " + d.user.role + " on " + d.user.workspace;
    var fresh = who.cloneNode(true);       // drop the role-picker handler
    who.parentNode.replaceChild(fresh, who);
    fresh.addEventListener("click", openAccount);
  }
}).catch(function () {});

function openAccount() {
  var modal = document.getElementById("who-modal"), body = document.getElementById("who-body");
  var u = ME.user;
  var h = modal.querySelector(".modal-head h2"); if (h) h.textContent = "Your account";
  body.innerHTML = '<div class="acct">'
    + '<div class="acct-row"><span class="lbl2">Signed in as</span><b>' + esc(u.name || u.email) + '</b> <span class="muted">' + esc(u.email) + "</span></div>"
    + '<div class="acct-row"><span class="lbl2">This model</span>' + esc(u.workspace) + ' · <span class="role-pill r-' + esc(u.role) + '">' + esc(u.role) + "</span></div>"
    + '<div class="acct-row"><span class="lbl2">Recorded as</span><code>' + esc(u.actor) + '</code><div class="hint">Changes you make are recorded under this role and your email (ISO 9001 §7.5). An administrator can link you to a different role.</div></div>'
    + '<div class="actions"><a class="add-btn ghost-btn" href="/auth/logout">Sign out</a>'
    + (u.role === "admin" ? ' <button class="add-btn" type="button" id="acct-members">Members &amp; access</button>' : "") + "</div>"
    + '<div id="members-panel"></div></div>';
  modal.hidden = false;
  var mb = document.getElementById("acct-members");
  if (mb) mb.addEventListener("click", loadMembers);
}

function loadMembers() {
  Promise.all([fetch("/api/members").then(function (r) { return r.json(); }),
               fetch("/api/roles").then(function (r) { return r.json(); })]).then(function (res) {
    var d = res[0], roles = (res[1].roles || []);
    var panel = document.getElementById("members-panel");
    if (!d.ok) { panel.innerHTML = '<div class="msg err">' + esc(d.error) + "</div>"; return; }
    var roleOpts = function (sel) { return d.roles.map(function (r) { return '<option' + (r === sel ? " selected" : "") + ">" + r + "</option>"; }).join(""); };
    var hrOpts = function (sel) { return '<option value="">— not linked —</option>' + roles.map(function (r) { return '<option value="' + esc(r.id) + '"' + (r.id === sel ? " selected" : "") + ">" + esc(r.name) + "</option>"; }).join(""); };
    panel.innerHTML = '<h3 class="sub-h">Members of ' + esc(d.workspace) + "</h3>"
      + '<table class="ea-table"><thead><tr><th>Person</th><th>Access</th><th>Acts as role</th><th></th></tr></thead><tbody>'
      + d.members.map(function (m) {
        return '<tr data-email="' + esc(m.email) + '"><td><b>' + esc(m.name || m.email) + '</b><div class="muted small">' + esc(m.email) + (m.org_wide ? " · org-wide" : "") + "</div></td>"
          + "<td>" + (m.org_wide ? '<span class="role-pill r-admin">admin</span>' : '<select class="m-role">' + roleOpts(m.role) + "</select>") + "</td>"
          + "<td>" + (m.org_wide ? "" : '<select class="m-hr">' + hrOpts(m.human_role) + "</select>") + "</td>"
          + "<td>" + (m.org_wide || m.email === ME.user.email ? "" : '<button class="add-btn ghost-btn m-save" type="button">Save</button> <button class="add-btn ghost-btn m-revoke" type="button">Remove</button>') + "</td></tr>";
      }).join("") + "</tbody></table>"
      + '<form id="m-add" class="m-add"><input id="m-email" type="email" required placeholder="name@company.com">'
      + '<select id="m-role">' + roleOpts("viewer") + '</select><select id="m-hr">' + hrOpts("") + '</select>'
      + '<button class="add-btn" type="submit">Give access</button></form><div id="m-msg" class="msg" hidden></div>'
      + '<div class="hint">viewer reads · editor changes the model · approver decides reviews and staged imports · admin manages members, policy and imports.</div>';
    function post(body) {
      return fetch("/api/members", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        .then(function (r) { return r.json(); }).then(function (res) {
          var msg = document.getElementById("m-msg");
          if (!res.ok) { msg.textContent = res.error; msg.className = "msg err"; msg.hidden = false; return; }
          loadMembers();
        });
    }
    panel.querySelectorAll(".m-save").forEach(function (b) {
      b.addEventListener("click", function () {
        var tr = b.closest("tr");
        post({ op: "grant", email: tr.getAttribute("data-email"), role: tr.querySelector(".m-role").value, human_role: tr.querySelector(".m-hr").value });
      });
    });
    panel.querySelectorAll(".m-revoke").forEach(function (b) {
      b.addEventListener("click", function () {
        var em = b.closest("tr").getAttribute("data-email");
        if (confirmInline(b, "Remove " + em + "?")) post({ op: "revoke", email: em });
      });
    });
    document.getElementById("m-add").addEventListener("submit", function (e) {
      e.preventDefault();
      post({ op: "grant", email: document.getElementById("m-email").value, role: document.getElementById("m-role").value, human_role: document.getElementById("m-hr").value });
    });
  });
}

// Two-click confirmation without a browser dialog: the first click arms the button.
function confirmInline(btn, label) {
  if (btn.getAttribute("data-armed") === "1") return true;
  btn.setAttribute("data-armed", "1");
  var old = btn.textContent;
  btn.textContent = "Confirm";
  btn.title = label;
  setTimeout(function () { btn.removeAttribute("data-armed"); btn.textContent = old; }, 4000);
  return false;
}
