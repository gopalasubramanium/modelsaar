/* modelsaar.com — optional enhancements only. Every page works without this file. */
(function () {
  "use strict";

  // Copy buttons for command blocks (accessible feedback through a live region)
  var live = document.createElement("div");
  live.setAttribute("aria-live", "polite");
  live.className = "sr-only";
  document.body.appendChild(live);
  document.querySelectorAll(".cmd").forEach(function (box) {
    var pre = box.querySelector("pre");
    var bar = box.querySelector(".cmd-bar");
    if (!pre || !bar || !navigator.clipboard) return;
    var code = pre.querySelector("code") || pre;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy";
    btn.textContent = "Copy";
    btn.setAttribute("aria-label", "Copy command to clipboard");
    btn.addEventListener("click", function () {
      // The exact canonical text: visual wrapping never adds newlines, prompts or labels to the value.
      navigator.clipboard.writeText(code.textContent.replace(/\n$/, "")).then(function () {
        btn.textContent = "Copied";
        live.textContent = "Command copied to clipboard";
        setTimeout(function () { btn.textContent = "Copy"; live.textContent = ""; }, 1800);
      }, function () {
        btn.textContent = "Select and copy";
        live.textContent = "Clipboard unavailable; select the text to copy it";
      });
    });
    bar.appendChild(btn);
  });

  // Routing walkthrough: turn the <details> scenarios into tabs (content stays in the page without JS)
  var walk = document.querySelector(".walkthrough");
  if (walk) {
    var items = Array.prototype.slice.call(walk.querySelectorAll("details.scenario"));
    if (items.length > 1) {
      var tabs = document.createElement("ul");
      tabs.className = "scenario-tabs";
      tabs.setAttribute("role", "tablist");
      items.forEach(function (d, i) {
        var li = document.createElement("li");
        li.setAttribute("role", "presentation");
        var b = document.createElement("button");
        b.type = "button";
        b.setAttribute("role", "tab");
        b.id = "tab-" + i;
        b.textContent = d.querySelector("summary").firstChild.textContent.trim();
        b.setAttribute("aria-selected", i === 0 ? "true" : "false");
        b.setAttribute("aria-controls", d.id || ("scenario-" + i));
        b.tabIndex = i === 0 ? 0 : -1;
        b.addEventListener("click", function () { select(i); });
        b.addEventListener("keydown", function (e) {
          var n = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
          if (n === null) return;
          n = (n + items.length) % items.length;
          select(n);
          tabs.querySelectorAll("button")[n].focus();
        });
        li.appendChild(b);
        tabs.appendChild(li);
        if (!d.id) d.id = "scenario-" + i;
        d.setAttribute("role", "tabpanel");
        d.setAttribute("aria-labelledby", b.id);
      });
      function select(n) {
        items.forEach(function (d, i) {
          d.open = i === n;
          var b = tabs.querySelectorAll("button")[i];
          b.setAttribute("aria-selected", i === n ? "true" : "false");
          b.tabIndex = i === n ? 0 : -1;
        });
      }
      walk.insertBefore(tabs, items[0]);
      walk.classList.add("js-tabs");
      select(0);
    }
  }
})();
