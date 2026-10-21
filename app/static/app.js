const Suppliers = (() => {
  const KIND = { producer: "производитель", distributor: "дистрибьютор", aggregator: "агрегатор", unknown: "тип не ясен" };
  const MARK = { yes: "да", no: "нет", unknown: "уточнить" };
  const LEGAL_STATUS = {
    ACTIVE: "действует",
    LIQUIDATING: "ликвидируется",
    LIQUIDATED: "ликвидировано",
    BANKRUPT: "банкротство",
    REORGANIZING: "реорганизация",
  };
  const FACT_LABELS = {
    delivery: "Доставка",
    min_order: "Мин. заказ",
    price: "Цена",
    documents: "Документы",
    payment: "Оплата",
    region: "Регион работы",
  };
  const COLUMNS = ["Поставщик", "Доставка в город", "Контакты", "Мин. заказ", "Цена", "Документы", "Юрлицо", "Подтверждено", ""];
  const STORE_KEY = "suppliers.shortlist.v1";

  const safeUrl = (url) => (/^https?:\/\//i.test(url || "") ? url : null);

  const h = (tag, attrs = {}, ...children) => {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null || value === false) continue;
      if (key === "class") el.className = value;
      else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
      else if (key === "href") {
        const url = value.startsWith("tel:") || value.startsWith("mailto:") ? value : safeUrl(value);
        if (url) el.setAttribute("href", url);
      } else el.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat(Infinity)) {
      if (child == null || child === false) continue;
      el.append(child instanceof Node ? child : String(child));
    }
    return el;
  };

  const extLink = (url, text) => h("a", { href: url, target: "_blank", rel: "noopener noreferrer nofollow" }, text);

  const plural = (n, one, few, many) => {
    const m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  };

  const parseDate = (value) => {
    if (!value) return null;
    const date = /^\d+$/.test(value) ? new Date(Number(value)) : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  };

  const yearsSince = (value) => {
    const date = parseDate(value);
    return date ? Math.floor((Date.now() - date.getTime()) / (365.25 * 24 * 3600 * 1000)) : null;
  };

  const ddmm = (value) => {
    const date = parseDate(value);
    return date ? date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) : "";
  };

  const pending = (text = "уточнить") => h("span", { class: "pending" }, text);

  const check = (supplier, key) => (supplier.checklist || []).find((item) => item.key === key);

  const legalStatus = (legal) => LEGAL_STATUS[legal.status] || (legal.status ? legal.status.toLowerCase() : null);

  const legalSummary = (supplier) => {
    const legal = supplier.legal;
    if (!legal || !legal.status) return supplier.inn ? `ИНН ${supplier.inn}` : null;
    const years = yearsSince(legal.registered);
    const age = years == null ? "" : years < 1 ? " · меньше года" : ` · ${years} ${plural(years, "год", "года", "лет")}`;
    return legalStatus(legal) + age;
  };

  const deliverySummary = (supplier) => {
    const mark = check(supplier, "delivers_to_city")?.mark || "unknown";
    const fact = supplier.facts?.delivery?.value;
    if (mark === "unknown" && !fact) return null;
    return [mark === "unknown" ? null : MARK[mark], fact].filter(Boolean).join(" — ");
  };

  const plainRow = (supplier) => ({
    delivery: deliverySummary(supplier),
    phones: (supplier.phones || []).join(", "),
    emails: (supplier.emails || []).join(", "),
    min_order: supplier.facts?.min_order?.value || null,
    price: supplier.facts?.price?.value || null,
    documents: supplier.facts?.documents?.value || null,
    payment: supplier.facts?.payment?.value || null,
    legal: legalSummary(supplier),
  });

  const store = {
    load: () => {
      try {
        return JSON.parse(localStorage.getItem(STORE_KEY)) || {};
      } catch {
        return {};
      }
    },
    save: (items) => {
      localStorage.setItem(STORE_KEY, JSON.stringify(items));
      updateBadge();
    },
    has: (domain) => domain in store.load(),
    toggle: (supplier, context) => {
      const items = store.load();
      if (items[supplier.domain]) delete items[supplier.domain];
      else items[supplier.domain] = { supplier, ...context, status: "new", note: "", added: new Date().toISOString() };
      store.save(items);
      return Boolean(items[supplier.domain]);
    },
  };

  const updateBadge = () => {
    const count = Object.keys(store.load()).length;
    document.querySelectorAll("[data-shortlist-count]").forEach((el) => (el.textContent = count ? String(count) : ""));
  };

  const copyText = async (text, button) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = h("textarea", { class: "offscreen" }, text);
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    const label = button.textContent;
    button.textContent = "Скопировано";
    setTimeout(() => (button.textContent = label), 1500);
  };

  const copyButton = (getText) => h("button", { class: "btn btn-small", type: "button", onclick: (e) => copyText(getText(), e.currentTarget) }, "Копировать");

  const starButton = (supplier, context) => {
    const button = h("button", { class: "star", type: "button" });
    const paint = (on) => {
      button.textContent = on ? "★" : "☆";
      button.classList.toggle("on", on);
      button.title = on ? "Убрать из шорт-листа" : "В шорт-лист";
      button.setAttribute("aria-label", button.title);
      button.setAttribute("aria-pressed", String(on));
    };
    paint(store.has(supplier.domain));
    button.addEventListener("click", () => paint(store.toggle(supplier, context)));
    return button;
  };

  const supplierCell = (supplier) =>
    h(
      "div",
      { class: "sup" },
      h("button", { class: "expand", type: "button", "aria-expanded": "false" }, supplier.name || supplier.domain),
      h("div", { class: "sup-meta" }, extLink(supplier.url, supplier.domain), " · ", KIND[supplier.kind] || KIND.unknown),
      supplier.site_opened ? null : h("div", { class: "tag tag-warn" }, "сайт не открылся — по сниппету"),
    );

  const contactsCell = (supplier) => {
    const phones = (supplier.phones || []).slice(0, 2).map((phone) => h("a", { href: `tel:${phone.replace(/[^\d+]/g, "")}`, class: "nowrap" }, phone));
    const emails = (supplier.emails || []).slice(0, 1).map((email) => h("a", { href: `mailto:${email}` }, email));
    const items = [...phones, ...emails];
    return items.length ? h("div", { class: "stack" }, items) : pending();
  };

  const confirmedCell = (supplier) => {
    const total = (supplier.checklist || []).length || 6;
    return h(
      "div",
      { class: "score", title: `Подтверждено ${supplier.confirmed} из ${total}` },
      h("span", { class: "score-num" }, `✓ ${supplier.confirmed} из ${total}`),
      h("span", { class: "meter" }, h("span", { style: `width:${Math.round((supplier.confirmed / total) * 100)}%` })),
    );
  };

  const factItem = (key, fact) =>
    h(
      "li",
      { class: "fact" },
      h("div", { class: "fact-head" }, h("b", {}, FACT_LABELS[key] || key), ": ", fact.value),
      h("blockquote", {}, "«", fact.quote, "»"),
      extLink(fact.url, "источник"),
    );

  const details = (supplier) => {
    const facts = Object.entries(supplier.facts || {});
    const legal = supplier.legal;
    return h(
      "div",
      { class: "details" },
      h(
        "section",
        {},
        h("h4", {}, "Факты с сайта"),
        facts.length ? h("ul", { class: "facts" }, facts.map(([key, fact]) => factItem(key, fact))) : h("p", { class: "muted" }, "Подтверждённых цитатами фактов не нашли."),
        supplier.snippet ? h("p", { class: "snippet" }, h("span", { class: "muted" }, "Из выдачи поиска: "), supplier.snippet) : null,
      ),
      h(
        "section",
        {},
        h("h4", {}, "Контакты"),
        h(
          "ul",
          { class: "plain" },
          (supplier.phones || []).map((phone) => h("li", {}, h("a", { href: `tel:${phone.replace(/[^\d+]/g, "")}` }, phone))),
          (supplier.emails || []).map((email) => h("li", {}, h("a", { href: `mailto:${email}` }, email))),
          supplier.address ? h("li", {}, supplier.address) : null,
          h("li", {}, extLink(supplier.url, supplier.url)),
        ),
        h("h4", {}, "Юрлицо"),
        legal
          ? h(
              "ul",
              { class: "plain" },
              legal.name ? h("li", {}, legal.name) : null,
              h("li", {}, `ИНН ${legal.inn}`),
              legal.status ? h("li", {}, legalStatus(legal), legal.registered ? `, с ${parseDate(legal.registered)?.toLocaleDateString("ru-RU") || legal.registered}` : "") : null,
              legal.okved ? h("li", {}, `ОКВЭД ${legal.okved}`, legal.okved_name ? ` — ${legal.okved_name}` : "") : null,
              legal.address ? h("li", {}, legal.address) : null,
              h("li", {}, extLink(legal.check_url, "Проверить в ЕГРЮЛ")),
            )
          : h("p", {}, supplier.inn ? `ИНН ${supplier.inn}` : pending("ИНН на сайте не найден")),
      ),
      h(
        "section",
        {},
        h("h4", {}, "Чек-лист"),
        h(
          "ul",
          { class: "checklist" },
          (supplier.checklist || []).map((item) =>
            h("li", { class: `mark-${item.mark}` }, h("span", { class: "mark" }, MARK[item.mark]), h("span", {}, item.label, item.note ? h("span", { class: "muted" }, ` — ${item.note}`) : null)),
          ),
        ),
      ),
      h(
        "section",
        {},
        h("div", { class: "section-head" }, h("h4", {}, "Что спросить по телефону"), supplier.questions?.length ? copyButton(() => supplier.questions.map((q) => `— ${q}`).join("\n")) : null),
        supplier.questions?.length ? h("ol", { class: "questions" }, supplier.questions.map((q) => h("li", {}, q))) : h("p", { class: "muted" }, "Вопросов нет."),
        supplier.rfq
          ? [h("div", { class: "section-head" }, h("h4", {}, "Черновик запроса КП"), copyButton(() => supplier.rfq)), h("textarea", { class: "rfq", readonly: true, rows: 8 }, supplier.rfq)]
          : null,
      ),
    );
  };

  const rows = (supplier, context) => {
    const plain = plainRow(supplier);
    const cells = [
      supplierCell(supplier),
      plain.delivery || pending(),
      contactsCell(supplier),
      plain.min_order || pending(),
      plain.price || pending("по запросу"),
      plain.documents || pending(),
      plain.legal || pending(),
      confirmedCell(supplier),
      starButton(supplier, context),
    ];
    const row = h("tr", { class: "row" }, cells.map((cell, i) => h("td", { "data-label": COLUMNS[i] }, cell)));
    const more = h("tr", { class: "more", hidden: true }, h("td", { colspan: COLUMNS.length }, details(supplier)));
    const expand = row.querySelector(".expand");
    const toggle = () => {
      more.hidden = !more.hidden;
      row.classList.toggle("open", !more.hidden);
      expand.setAttribute("aria-expanded", String(!more.hidden));
    };
    row.addEventListener("click", (e) => {
      if (e.target.closest("a, button:not(.expand)")) return;
      toggle();
    });
    return [row, more];
  };

  const table = () => {
    const tbody = h("tbody");
    const el = h("table", { class: "suppliers" }, h("thead", {}, h("tr", {}, COLUMNS.map((title) => h("th", {}, title)))), tbody);
    return { el, add: (supplier, context) => tbody.append(...rows(supplier, context)) };
  };

  const statsLine = (result) => {
    const s = result.stats;
    const n = (value, one, few, many) => `${value} ${plural(value, one, few, many)}`;
    return [
      `${Math.round(s.seconds)} с`,
      `${s.cost_rub.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} ₽`,
      `${n(s.candidates, "кандидат", "кандидата", "кандидатов")} → ${n(s.suppliers, "поставщик", "поставщика", "поставщиков")}`,
      `${s.with_phone} с телефоном`,
      `данные с сайтов на ${ddmm(result.created_at)}`,
    ].join(" · ");
  };

  const renderResult = (container, result) => {
    const context = { category: result.category, city: result.city };
    const top = result.suppliers.slice(0, 3).filter((supplier) => supplier.why);
    const list = table();
    result.suppliers.forEach((supplier) => list.add(supplier, context));
    container.replaceChildren(
      top.length
        ? h("div", { class: "why-top" }, h("h3", {}, "Почему первыми"), h("ol", {}, top.map((supplier) => h("li", {}, h("b", {}, supplier.name), " — ", supplier.why))))
        : null,
      result.suppliers.length ? h("div", { class: "table-wrap" }, list.el) : h("p", { class: "notice" }, "Поставщиков с подтверждёнными данными не нашли. Попробуйте сформулировать категорию шире."),
      result.aggregators.length
        ? h(
            "details",
            { class: "aggregators" },
            h("summary", {}, `Отсеяли агрегаторы и маркетплейсы: ${result.aggregators.length}`),
            h("ul", {}, result.aggregators.map((source) => h("li", {}, extLink(source.url, source.title || source.domain), h("span", { class: "muted" }, ` · ${source.domain}`)))),
          )
        : null,
      h(
        "p",
        { class: "stats" },
        statsLine(result),
        result.stats.rejected_quotes ? h("span", { class: "muted" }, ` · отброшено неподтверждённых цитат: ${result.stats.rejected_quotes}`) : null,
      ),
    );
  };

  document.addEventListener("DOMContentLoaded", updateBadge);

  return { h, extLink, pending, plural, ddmm, plainRow, store, copyText, table, renderResult, KIND };
})();
