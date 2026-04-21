(function () {
  const display = document.getElementById("sironaCalcDisplay");
  const historyEl = document.getElementById("sironaCalcHistory");
  const root = document.getElementById("sironaCalc");
  if (!display || !root) return;

  const STORAGE_KEY = "sirona_calc_value";
  let mem = null;

  function normalizeExpr(s) {
    return String(s || "")
      .replace(/×/g, "*")
      .replace(/÷/g, "/")
      .replace(/−/g, "-")
      .replace(/,/g, ".")
      .replace(/[^\d\.\+\-\*\/\(\)\s]/g, "");
  }

  function safeEval(expr) {
    // Expr normalizada: solo números, ., + - * / ( ) y espacios.
    // eslint-disable-next-line no-new-func
    return Function('"use strict";return (' + expr + ")")();
  }

  function setValue(v) {
    display.value = String(v ?? "");
  }

  function setHistory(v) {
    if (!historyEl) return;
    historyEl.textContent = String(v ?? "");
  }

  function append(t) {
    const start = display.selectionStart ?? display.value.length;
    const end = display.selectionEnd ?? display.value.length;
    const before = display.value.slice(0, start);
    const after = display.value.slice(end);
    const next = before + t + after;
    setValue(next);
    window.setTimeout(function () {
      try {
        display.focus();
        const pos = start + t.length;
        display.setSelectionRange(pos, pos);
      } catch (e) {}
    }, 0);
  }

  function backspace() {
    const start = display.selectionStart ?? display.value.length;
    const end = display.selectionEnd ?? display.value.length;
    if (start !== end) {
      const before = display.value.slice(0, start);
      const after = display.value.slice(end);
      setValue(before + after);
      return;
    }
    if (start <= 0) return;
    const before = display.value.slice(0, start - 1);
    const after = display.value.slice(end);
    setValue(before + after);
  }

  function persistToStorage() {
    try {
      window.localStorage.setItem(STORAGE_KEY, display.value);
    } catch (e) {}
  }

  function loadFromStorage() {
    try {
      const v = window.localStorage.getItem(STORAGE_KEY);
      if (v !== null) setValue(v);
    } catch (e) {}
  }

  function clear() {
    setValue("");
    setHistory("");
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
  }

  function getCurrentNumberValue() {
    const s = String(display.value || "").trim();
    if (!s) return null;
    const norm = normalizeExpr(s);
    try {
      if (norm.trim()) {
        const out = safeEval(norm);
        if (typeof out === "number" && Number.isFinite(out)) return out;
      }
    } catch (e) {}
    const mNum = s.match(/(-?\d+(?:[.,]\d+)?)\s*$/);
    if (!mNum) return null;
    return parseFloat(mNum[1].replace(",", "."));
  }

  function replaceLastUnary(mapper) {
    const s = String(display.value || "");
    const mNum = s.match(/(-?\d+(?:[.,]\d+)?)\s*$/);
    if (!mNum) return;
    const raw = mNum[1];
    const n = parseFloat(raw.replace(",", "."));
    if (!Number.isFinite(n)) return;
    const out = mapper(n);
    if (!Number.isFinite(out)) return;
    const rounded = Math.round(out * 1e12) / 1e12;
    const useComma = raw.indexOf(",") >= 0;
    let outStr = String(rounded);
    if (useComma) outStr = outStr.replace(".", ",");
    const before = s.slice(0, mNum.index || 0);
    const after = s.slice((mNum.index || 0) + raw.length);
    setValue(before + outStr + after);
  }

  function clearEntry() {
    const s = String(display.value || "");
    const mNum = s.match(/(-?\d+(?:[.,]\d+)?)\s*$/);
    if (!mNum) return clear();
    const beforeNum = s.slice(0, mNum.index || 0);
    setValue(beforeNum.trimEnd());
  }

  function toggleSign() {
    const s = String(display.value || "");
    const mNum = s.match(/(-?\d+(?:[.,]\d+)?)\s*$/);
    if (!mNum) return;
    const num = mNum[1];
    const before = s.slice(0, mNum.index || 0);
    const after = s.slice((mNum.index || 0) + num.length);
    if (num.startsWith("-")) {
      setValue(before + num.slice(1) + after);
    } else {
      setValue(before + "-" + num + after);
    }
  }

  function applyPercent() {
    // Estilo Windows:
    // - A + B%  => A + (A*B/100)
    // - A − B%  => A − (A*B/100)
    // - A × B%  => A × (B/100)
    // - A ÷ B%  => A ÷ (B/100)
    // Si no hay operador previo, aplica n -> n/100 al último número.
    const s = String(display.value || "");
    const mNum = s.match(/(-?\d+(?:[.,]\d+)?)\s*$/);
    if (!mNum) return;
    const rightRaw = mNum[1].replace(",", ".");
    const right = parseFloat(rightRaw);
    if (!Number.isFinite(right)) return;

    const beforeNum = s.slice(0, mNum.index || 0);
    let opIdx = -1;
    let op = "";
    for (let i = beforeNum.length - 1; i >= 0; i--) {
      const ch = beforeNum[i];
      if (
        ch === "+" ||
        ch === "-" ||
        ch === "−" ||
        ch === "*" ||
        ch === "×" ||
        ch === "/" ||
        ch === "÷"
      ) {
        opIdx = i;
        op = ch;
        break;
      }
    }

    if (opIdx < 0) {
      setValue(beforeNum + String(right / 100));
      return;
    }

    const leftExpr = beforeNum.slice(0, opIdx);
    const leftNorm = normalizeExpr(leftExpr);
    let leftVal = NaN;
    try {
      leftVal = leftNorm.trim() ? safeEval(leftNorm) : NaN;
    } catch (e) {
      leftVal = NaN;
    }

    const opNorm = op === "-" ? "−" : op === "*" ? "×" : op === "/" ? "÷" : op;

    let replacement = right / 100;
    if ((opNorm === "+" || opNorm === "−") && Number.isFinite(leftVal)) {
      replacement = (leftVal * right) / 100;
    }
    const fullBefore = s.slice(0, mNum.index || 0);
    setValue(fullBefore + String(replacement));
  }

  function compute() {
    const expr = normalizeExpr(display.value);
    if (!expr.trim()) return;
    try {
      const out = safeEval(expr);
      if (typeof out === "number" && Number.isFinite(out)) {
        const rounded = Math.round(out * 1e12) / 1e12;
        setHistory(String(display.value || "") + " =");
        setValue(String(rounded));
      }
    } catch (e) {}
  }

  root.addEventListener("click", function (ev) {
    const btn = ev.target.closest("[data-calc]");
    if (!btn) return;
    if (btn.disabled) return;
    const v = btn.getAttribute("data-calc");
    if (v === "C") return clear();
    if (v === "CE") return clearEntry();
    if (v === "%") return applyPercent();
    if (v === "BS") return backspace();
    if (v === "PM") return toggleSign();
    if (v === "=") return compute();
    if (v === "NOP") return;
    if (v === "MC") {
      mem = null;
      return;
    }
    if (v === "MR") {
      if (mem == null) return;
      setValue(String(mem));
      return;
    }
    if (v === "MS") {
      const n = getCurrentNumberValue();
      if (n == null) return;
      mem = n;
      return;
    }
    if (v === "M+") {
      const n = getCurrentNumberValue();
      if (n == null) return;
      mem = (mem ?? 0) + n;
      return;
    }
    if (v === "M-") {
      const n = getCurrentNumberValue();
      if (n == null) return;
      mem = (mem ?? 0) - n;
      return;
    }
    if (v === "INV") {
      return replaceLastUnary(function (n) {
        return n === 0 ? NaN : 1 / n;
      });
    }
    if (v === "SQ") {
      return replaceLastUnary(function (n) {
        return n * n;
      });
    }
    if (v === "SQRT") {
      return replaceLastUnary(function (n) {
        return n < 0 ? NaN : Math.sqrt(n);
      });
    }
    if (v === "÷") return append("÷");
    if (v === "×") return append("×");
    if (v === ",") return append(",");
    if (v === ".") return append(".");
    if (v === "+") return append("+");
    if (v === "-") return append("−");
    return append(v);
  });

  display.addEventListener("keydown", function (ev) {
    // Teclas tipo Windows: mapear operadores a los símbolos usados en UI.
    if (ev.key === "+" || ev.key === "-" || ev.key === "*" || ev.key === "/") {
      ev.preventDefault();
      if (ev.key === "+") append("+");
      else if (ev.key === "-") append("−");
      else if (ev.key === "*") append("×");
      else if (ev.key === "/") append("÷");
      return;
    }
    if (ev.key === ",") {
      ev.preventDefault();
      append(",");
      return;
    }
    if (ev.key === ".") {
      ev.preventDefault();
      append(",");
      return;
    }
    if (ev.key === "Enter") {
      ev.preventDefault();
      compute();
      return;
    }
    if (ev.key === "Escape") {
      ev.preventDefault();
      clear();
      return;
    }
    if (ev.key === "Delete") {
      ev.preventDefault();
      clear();
      return;
    }
    if (ev.key === "Backspace" && ev.ctrlKey) {
      ev.preventDefault();
      clearEntry();
      return;
    }
    if (ev.key === "%") {
      ev.preventDefault();
      applyPercent();
    }
  });

  root.addEventListener("shown.bs.offcanvas", function () {
    loadFromStorage();
    try {
      display.focus();
      display.setSelectionRange(display.value.length, display.value.length);
    } catch (e) {}
  });

  // Al ocultar el panel: guardar el número (localStorage). No borrar memoria en RAM.
  root.addEventListener("hidden.bs.offcanvas", function () {
    persistToStorage();
  });

  // Cerrar sesión (enlace Salir): borrar valor guardado para que vuelva a cero al próximo login.
  document.addEventListener(
    "click",
    function (ev) {
      const a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
      if (!a) return;
      const href = String(a.getAttribute("href") || "");
      if (!href) return;
      if (href.indexOf("/logout") === -1) return;
      try {
        window.localStorage.removeItem(STORAGE_KEY);
      } catch (e) {}
      mem = null;
      setValue("");
      setHistory("");
    },
    true
  );

  loadFromStorage();
  setHistory("");
})();

