/*
 * wontfit diagnostics.
 *
 * Runs in the harness window and reaches into each same-origin iframe's
 * document. Everything here is best-effort: any frame that navigated to
 * another origin, or has not finished loading, throws on access and the
 * caller treats that as "no data". Nothing here mutates the page's own DOM
 * except for overlay boxes tagged `data-wontfit`, which are removed
 * before every re-run.
 *
 * Exposed as `window.WontfitDiagnostics` with:
 *   canAccess(frame)                     -> boolean
 *   analyze(doc)                         -> report (see below)
 *   renderTapOverlay(doc, targets)       -> draws boxes around small tap targets
 *   clearOverlays(doc, kind?)            -> removes overlays ("tap", "inspect", or all)
 *   pathFor(el)                          -> a CSS path usable across frames
 *   highlight(doc, selector, label)      -> draws the inspect box; returns true if found
 *   attachInspect(doc, onHover, onLeave) -> returns a detach function
 */
(function (global) {
  "use strict";

  var TAP_MIN = 44;          // WCAG 2.5.5 / Apple HIG minimum, CSS px
  var TEXT_MIN = 12;         // below this most mobile browsers auto-zoom forms or it is simply unreadable
  var MAX_CULPRITS = 8;
  var INTERACTIVE = "a[href],button,input,select,textarea,summary,label[for],[role=button],[role=link],[role=tab],[onclick]";
  var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, HEAD: 1, META: 1, LINK: 1, TITLE: 1 };

  function canAccess(frame) {
    try {
      var doc = frame.contentDocument;
      return !!(doc && doc.documentElement && doc.location && doc.body);
    } catch (e) {
      return false;
    }
  }

  function isOurs(el) {
    return !!(el.closest && el.closest("[data-wontfit]"));
  }

  function classLabel(el) {
    var cls = typeof el.className === "string" ? el.className : "";
    var parts = cls.trim().split(/\s+/).filter(Boolean).slice(0, 2);
    return parts.length ? "." + parts.join(".") : "";
  }

  function label(el) {
    var tag = el.tagName.toLowerCase();
    if (el.id) return tag + "#" + el.id;
    return tag + classLabel(el);
  }

  function visible(el, rect) {
    if (!rect.width || !rect.height) return false;
    var cs = el.ownerDocument.defaultView.getComputedStyle(el);
    return cs.visibility !== "hidden" && cs.display !== "none" && cs.opacity !== "0";
  }

  /* ---- horizontal overflow ------------------------------------------------ */

  function findOverflow(doc) {
    var root = doc.documentElement;
    var vw = root.clientWidth;
    var sw = Math.max(root.scrollWidth, doc.body ? doc.body.scrollWidth : 0);
    if (sw <= vw + 1) return null;
    // Only the inline-end side scrolls. Content past the start edge is clipped, never
    // scrollable, which is where skip links and visually-hidden text are parked.
    var rtl = doc.defaultView.getComputedStyle(doc.body || root).direction === "rtl";
    var culprits = [];
    var found = [];  // outermost offenders only: a wide <td> inside a wide <table> is noise
    var all = doc.body.querySelectorAll("*");
    for (var i = 0; i < all.length && culprits.length < MAX_CULPRITS; i++) {
      var el = all[i];
      if (SKIP_TAGS[el.tagName] || isOurs(el)) continue;
      var inside = false;
      for (var j = 0; j < found.length; j++) {
        if (found[j].contains(el)) { inside = true; break; }
      }
      if (inside) continue;
      var r = el.getBoundingClientRect();
      if (!r.width) continue;
      if (rtl ? r.left < -1 : r.right > vw + 1) {
        found.push(el);
        culprits.push({ label: label(el), left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width) });
      }
    }
    return { viewport: vw, scrollWidth: sw, amount: sw - vw, culprits: culprits };
  }

  /* ---- tap targets ---------------------------------------------------------- */

  function findSmallTapTargets(doc) {
    var out = [];
    var nodes = doc.body.querySelectorAll(INTERACTIVE);
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (isOurs(el)) continue;
      if (el.tagName === "INPUT" && el.type === "hidden") continue;
      var r = el.getBoundingClientRect();
      if (!visible(el, r)) continue;
      if (r.width < TAP_MIN || r.height < TAP_MIN) {
        out.push({ el: el, label: label(el), width: Math.round(r.width), height: Math.round(r.height) });
      }
    }
    return out;
  }

  /* ---- small text ------------------------------------------------------------ */

  function hasOwnText(el) {
    for (var n = el.firstChild; n; n = n.nextSibling) {
      if (n.nodeType === 3 && /\S/.test(n.nodeValue)) return true;
    }
    return false;
  }

  function countSmallText(doc) {
    var count = 0;
    var view = doc.defaultView;
    var all = doc.body.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (SKIP_TAGS[el.tagName] || isOurs(el) || !hasOwnText(el)) continue;
      var r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      var size = parseFloat(view.getComputedStyle(el).fontSize);
      if (size && size < TEXT_MIN) count++;
    }
    return count;
  }

  function analyze(doc) {
    return {
      overflow: findOverflow(doc),
      tapTargets: findSmallTapTargets(doc),
      smallText: countSmallText(doc)
    };
  }

  /* ---- overlays -------------------------------------------------------------- */

  function overlayLayer(doc, kind) {
    var id = "__wontfit-" + kind;
    var layer = doc.getElementById(id);
    if (layer) return layer;
    layer = doc.createElement("div");
    layer.id = id;
    layer.setAttribute("data-wontfit", kind);
    layer.style.cssText = "position:absolute;top:0;left:0;width:0;height:0;overflow:visible;pointer-events:none;z-index:2147483647;";
    doc.documentElement.appendChild(layer);
    return layer;
  }

  function clearOverlays(doc, kind) {
    var sel = kind ? "[data-wontfit='" + kind + "']" : "[data-wontfit]";
    var nodes = doc.querySelectorAll(sel);
    for (var i = 0; i < nodes.length; i++) nodes[i].parentNode.removeChild(nodes[i]);
  }

  function box(doc, rect, style) {
    var view = doc.defaultView;
    var b = doc.createElement("div");
    b.style.cssText =
      "position:absolute;box-sizing:border-box;pointer-events:none;" +
      "left:" + (rect.left + view.scrollX) + "px;top:" + (rect.top + view.scrollY) + "px;" +
      "width:" + rect.width + "px;height:" + rect.height + "px;" + style;
    return b;
  }

  function renderTapOverlay(doc, targets) {
    clearOverlays(doc, "tap");
    if (!targets.length) return;
    var layer = overlayLayer(doc, "tap");
    for (var i = 0; i < targets.length; i++) {
      var r = targets[i].el.getBoundingClientRect();
      layer.appendChild(box(doc, r, "outline:2px dashed #f5b74f;outline-offset:1px;background:rgba(245,183,79,.12);"));
    }
  }

  /* ---- inspect --------------------------------------------------------------- */

  function cssEscape(doc, s) {
    var view = doc.defaultView;
    return view.CSS && view.CSS.escape ? view.CSS.escape(s) : s.replace(/([^\w-])/g, "\\$1");
  }

  function pathFor(el) {
    var doc = el.ownerDocument;
    var parts = [];
    while (el && el.nodeType === 1 && el.tagName !== "HTML" && el.tagName !== "BODY") {
      var tag = el.tagName.toLowerCase();
      if (el.id) {
        parts.unshift(tag + "#" + cssEscape(doc, el.id));
        break;
      }
      var cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 2) : [];
      var index = 1;
      for (var sib = el.previousElementSibling; sib; sib = sib.previousElementSibling) {
        if (sib.tagName === el.tagName) index++;
      }
      var piece = tag;
      for (var i = 0; i < cls.length; i++) piece += "." + cssEscape(doc, cls[i]);
      parts.unshift(piece + ":nth-of-type(" + index + ")");
      el = el.parentElement;
    }
    return parts.join(" > ");
  }

  function highlight(doc, selector, text) {
    clearOverlays(doc, "inspect");
    var el;
    try {
      el = selector ? doc.querySelector(selector) : null;
    } catch (e) {
      el = null;
    }
    if (!el) return false;
    var layer = overlayLayer(doc, "inspect");
    var r = el.getBoundingClientRect();
    var b = box(doc, r, "outline:2px solid #7cc4ff;background:rgba(124,196,255,.15);");
    if (text) {
      var tag = doc.createElement("div");
      tag.textContent = text + " " + Math.round(r.width) + "x" + Math.round(r.height);
      tag.style.cssText =
        "position:absolute;left:0;top:-18px;padding:1px 5px;font:11px/16px ui-monospace,Menlo,monospace;" +
        "color:#0b1220;background:#7cc4ff;border-radius:3px;white-space:nowrap;";
      if (r.top < 20) tag.style.top = "100%";
      b.appendChild(tag);
    }
    layer.appendChild(b);
    return true;
  }

  function attachInspect(doc, onHover, onLeave) {
    var pending = null;
    var last = null;
    function move(ev) {
      if (pending) return;
      pending = doc.defaultView.requestAnimationFrame(function () {
        pending = null;
        var el = doc.elementFromPoint(ev.clientX, ev.clientY);
        if (!el || isOurs(el) || el === last) return;
        last = el;
        onHover(pathFor(el), label(el));
      });
    }
    function leave() {
      last = null;
      onLeave();
    }
    doc.addEventListener("mousemove", move, true);
    doc.documentElement.addEventListener("mouseleave", leave, true);
    return function detach() {
      doc.removeEventListener("mousemove", move, true);
      doc.documentElement.removeEventListener("mouseleave", leave, true);
    };
  }

  global.WontfitDiagnostics = {
    TAP_MIN: TAP_MIN,
    TEXT_MIN: TEXT_MIN,
    canAccess: canAccess,
    analyze: analyze,
    renderTapOverlay: renderTapOverlay,
    clearOverlays: clearOverlays,
    pathFor: pathFor,
    highlight: highlight,
    attachInspect: attachInspect
  };
})(window);
