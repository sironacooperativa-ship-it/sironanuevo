(function () {
  const display = document.getElementById("sironaCalcDisplay");
  const historyEl = document.getElementById("sironaCalcHistory");
  const root = document.getElementById("sironaCalc");
  if (!display || !root) return;

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
    try {
      window.localStorage.setItem("sirona_calc_value", display.value);
    } catch (e) {}
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

  function clear() {
    setValue("");
    setHistory("");
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
    if (v === "÷") return append("÷");
    if (v === "×") return append("×");
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
      append(".");
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
    try {
      display.focus();
      display.setSelectionRange(display.value.length, display.value.length);
    } catch (e) {}
  });

  try {
    const saved = window.localStorage.getItem("sirona_calc_value");
    if (saved) display.value = saved;
  } catch (e) {}
  setHistory("");
})();

