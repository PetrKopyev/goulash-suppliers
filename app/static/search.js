(() => {
  const { h } = Suppliers;
  const root = document.getElementById("search");
  const stages = document.getElementById("stages");
  const resultBox = document.getElementById("result");
  const status = document.getElementById("search-status");
  const { category, city } = root.dataset;
  const context = { category, city };
  const started = Date.now();
  const live = Suppliers.table();
  let finished = false;

  const tick = setInterval(() => {
    if (!finished) status.textContent = `Ищем… ${Math.round((Date.now() - started) / 1000)} с`;
  }, 1000);

  const addStage = (event, cls = "") => {
    stages.querySelector("li.current")?.classList.remove("current");
    stages.append(h("li", { class: `current ${cls}` }, event.message || event.stage || ""));
  };

  const showError = (message) =>
    resultBox.append(
      h("div", { class: "notice notice-error" }, h("p", {}, message), h("p", {}, h("a", { href: "/" }, "К готовым примерам и новому поиску"))),
    );

  const handle = (event) => {
    if (event.type === "stage") addStage(event);
    if (event.type === "supplier") {
      if (!live.el.isConnected) resultBox.append(h("div", { class: "table-wrap" }, live.el));
      live.add(event.supplier, context);
    }
    if (event.type === "error") {
      addStage(event, "stage-error");
      if (event.stage === "limit" || event.stage === "internal") showError(event.message);
    }
    if (event.type === "done") {
      finished = true;
      stages.querySelector("li.current")?.classList.remove("current");
      status.textContent = `Готово за ${Math.round(event.result.stats.seconds)} с.`;
      Suppliers.renderResult(resultBox, event.result);
    }
  };

  const run = async () => {
    const params = new URLSearchParams({ category, city });
    const response = await fetch(`/api/search/stream?${params}`);
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      const lines = buffer.split("\n");
      buffer = lines.pop();
      lines.filter((line) => line.trim()).forEach((line) => handle(JSON.parse(line)));
    }
    if (buffer.trim()) handle(JSON.parse(buffer));
  };

  run()
    .catch(() => showError("Связь с сервером прервалась. Обновите страницу или откройте готовый пример."))
    .finally(() => {
      clearInterval(tick);
      if (!finished) status.textContent = "Поиск остановлен.";
    });
})();
