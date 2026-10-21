(() => {
  const { h, extLink, pending, store, plainRow, KIND } = Suppliers;
  const STATUSES = { new: "новый", call: "позвонить", rfq_sent: "запросил КП", rejected: "отказ", working: "работаем" };
  const listBox = document.getElementById("shortlist");
  const compareBox = document.getElementById("compare");
  const compareBtn = document.getElementById("compare-btn");
  const csvBtn = document.getElementById("csv-btn");
  const selected = new Set();

  const update = (domain, patch) => {
    const items = store.load();
    Object.assign(items[domain], patch);
    store.save(items);
  };

  const refreshCompare = () => {
    compareBtn.disabled = selected.size < 2;
    compareBtn.textContent = selected.size ? `Сравнить (${selected.size})` : "Сравнить";
  };

  const card = (item) => {
    const s = item.supplier;
    const plain = plainRow(s);
    const box = h("input", {
      type: "checkbox",
      checked: selected.has(s.domain),
      "aria-label": "Выбрать для сравнения",
      onchange: (e) => {
        if (e.target.checked && selected.size >= 3) {
          e.target.checked = false;
          return;
        }
        e.target.checked ? selected.add(s.domain) : selected.delete(s.domain);
        refreshCompare();
      },
    });
    const status = h(
      "select",
      { onchange: (e) => update(s.domain, { status: e.target.value }) },
      Object.entries(STATUSES).map(([value, label]) => h("option", { value, selected: item.status === value }, label)),
    );
    const note = h("textarea", { rows: 2, placeholder: "Заметка: с кем говорил, что обещали…", oninput: (e) => update(s.domain, { note: e.target.value }) }, item.note || "");
    const remove = h(
      "button",
      {
        class: "btn btn-small btn-ghost",
        type: "button",
        onclick: () => {
          const items = store.load();
          delete items[s.domain];
          selected.delete(s.domain);
          store.save(items);
          render();
        },
      },
      "Убрать",
    );
    return h(
      "article",
      { class: `sl-card status-${item.status}` },
      h(
        "div",
        { class: "sl-head" },
        h("label", { class: "sl-pick" }, box),
        h("div", {}, h("div", { class: "sl-name" }, s.name || s.domain), h("div", { class: "sup-meta" }, extLink(s.url, s.domain), ` · ${KIND[s.kind] || KIND.unknown} · ${item.category}, ${item.city}`)),
        remove,
      ),
      h(
        "dl",
        { class: "sl-facts" },
        h("dt", {}, "Телефон"),
        h("dd", {}, plain.phones || pending()),
        h("dt", {}, "Доставка"),
        h("dd", {}, plain.delivery || pending()),
        h("dt", {}, "Мин. заказ"),
        h("dd", {}, plain.min_order || pending()),
        h("dt", {}, "Цена"),
        h("dd", {}, plain.price || pending("по запросу")),
      ),
      h("div", { class: "sl-edit" }, h("label", { class: "field" }, h("span", {}, "Статус"), status), h("label", { class: "field" }, h("span", {}, "Заметка"), note)),
    );
  };

  const COMPARE_ROWS = [
    ["Тип", (item) => KIND[item.supplier.kind] || KIND.unknown],
    ["Доставка в город", (item) => plainRow(item.supplier).delivery],
    ["Телефоны", (item) => plainRow(item.supplier).phones],
    ["E-mail", (item) => plainRow(item.supplier).emails],
    ["Мин. заказ", (item) => plainRow(item.supplier).min_order],
    ["Цена", (item) => plainRow(item.supplier).price],
    ["Документы", (item) => plainRow(item.supplier).documents],
    ["Оплата", (item) => plainRow(item.supplier).payment],
    ["Юрлицо", (item) => plainRow(item.supplier).legal],
    ["Подтверждено", (item) => `${item.supplier.confirmed} из ${(item.supplier.checklist || []).length || 6}`],
    ["Статус", (item) => STATUSES[item.status]],
    ["Заметка", (item) => item.note],
  ];

  const renderCompare = () => {
    const items = store.load();
    const picked = [...selected].map((domain) => items[domain]).filter(Boolean);
    compareBox.replaceChildren(
      h(
        "div",
        { class: "compare" },
        h("div", { class: "section-head" }, h("h3", {}, "Сравнение"), h("button", { class: "btn btn-small btn-ghost", type: "button", onclick: () => compareBox.replaceChildren() }, "Закрыть")),
        h(
          "div",
          { class: "table-wrap" },
          h(
            "table",
            { class: "compare-table" },
            h("thead", {}, h("tr", {}, h("th", {}, ""), picked.map((item) => h("th", {}, item.supplier.name || item.supplier.domain)))),
            h(
              "tbody",
              {},
              COMPARE_ROWS.map(([label, get]) => h("tr", {}, h("th", {}, label), picked.map((item) => h("td", {}, get(item) || pending())))),
            ),
          ),
        ),
      ),
    );
    compareBox.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const csvCell = (value) => {
    let text = String(value ?? "");
    if (/^[=+\-@\t\r]/.test(text) && !/^\+?[\d\s()-]+$/.test(text)) text = `'${text}`;
    return /[";\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };

  const downloadCsv = () => {
    const header = ["Поставщик", "Домен", "Сайт", "Тип", "Категория", "Город", "Телефоны", "E-mail", "Адрес", "ИНН", "Доставка", "Мин. заказ", "Цена", "Документы", "Оплата", "Юрлицо", "Подтверждено", "Статус", "Заметка", "Добавлен"];
    const lines = Object.values(store.load()).map((item) => {
      const s = item.supplier;
      const plain = plainRow(s);
      return [
        s.name, s.domain, s.url, KIND[s.kind] || KIND.unknown, item.category, item.city, plain.phones, plain.emails, s.address, s.inn,
        plain.delivery, plain.min_order, plain.price, plain.documents, plain.payment, plain.legal, s.confirmed, STATUSES[item.status], item.note, item.added.slice(0, 10),
      ];
    });
    const csv = "﻿" + [header, ...lines].map((row) => row.map(csvCell).join(";")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = h("a", { download: `shortlist-${new Date().toISOString().slice(0, 10)}.csv` });
    link.href = url;
    link.click();
    URL.revokeObjectURL(url);
  };

  const render = () => {
    const items = Object.values(store.load()).sort((a, b) => b.added.localeCompare(a.added));
    csvBtn.disabled = !items.length;
    refreshCompare();
    listBox.replaceChildren(
      items.length
        ? h("div", { class: "sl-list" }, items.map(card))
        : h("div", { class: "notice" }, h("p", {}, "Пока пусто. Отмечайте поставщиков звёздочкой ☆ в результатах поиска."), h("p", {}, h("a", { href: "/" }, "К поиску и готовым примерам"))),
    );
  };

  compareBtn.addEventListener("click", renderCompare);
  csvBtn.addEventListener("click", downloadCsv);
  render();
})();
