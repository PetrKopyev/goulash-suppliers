const Suppliers = (() => {
  const KIND = { producer: "производитель", distributor: "дистрибьютор", retail: "розничный магазин", aggregator: "агрегатор", unknown: "тип не ясен" };
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
  const COLUMNS = ["Поставщик", "Доставка", "Контакты", "Мин. заказ", "Цена", "Документы", "Юрлицо", "Подтверждено", ""];
  const STORE_KEY = "suppliers.shortlist.v1";
  const SNIPPET_LENGTH = 160;
  const COLUMN_WIDTHS = [17, 12, 14, 10, 9, 10, 9, 14, 5];
  const SVG_NS = "http://www.w3.org/2000/svg";

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

  const displayUrl = (supplier) => {
    try {
      const path = decodeURI(new URL(supplier.url).pathname).replace(/\/$/, "");
      return supplier.domain + path;
    } catch {
      return supplier.domain;
    }
  };

  const shortSnippet = (text) => {
    const first = (text || "").split(" … ")[0].replace(/^[.…\s]+|[.…\s]+$/g, "");
    if (first.length <= SNIPPET_LENGTH) return first;
    const cut = first.slice(0, SNIPPET_LENGTH);
    return `${cut.slice(0, cut.lastIndexOf(" ")).replace(/[,;:\s–—-]+$/, "")}…`;
  };

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

  const glue = (text) => text && text.replace(/(\d) (?=\S)/g, "$1\u00a0");

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

  const deliveryMark = (supplier) => check(supplier, "delivers_to_city")?.mark || "unknown";

  const deliveryLabel = (supplier) => supplier.delivery_label || "уточнить";

  const deliveryBadge = (supplier) => h("span", { class: `route route-${deliveryMark(supplier)}` }, deliveryLabel(supplier));

  const plainRow = (supplier) => ({
    delivery: deliveryLabel(supplier),
    delivery_terms: supplier.facts?.delivery?.value || null,
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

  const svg = (cls, viewBox, d) => {
    const el = document.createElementNS(SVG_NS, "svg");
    const path = document.createElementNS(SVG_NS, "path");
    if (cls) el.setAttribute("class", cls);
    el.setAttribute("viewBox", viewBox);
    el.setAttribute("aria-hidden", "true");
    path.setAttribute("d", d);
    el.append(path);
    return el;
  };

  const starButton = (supplier, context) => {
    const caption = h("span", { class: "star-label" });
    const button = h("button", { class: "star", type: "button" }, svg(null, "0 0 24 24", "M12 2.8l2.8 5.8 6.3.9-4.6 4.4 1.1 6.3L12 17.2l-5.6 3 1.1-6.3-4.6-4.4 6.3-.9z"), caption);
    const paint = (on) => {
      caption.textContent = on ? "В шорт-листе" : "В шорт-лист";
      button.classList.toggle("on", on);
      button.title = on ? "Убрать из шорт-листа" : "В шорт-лист";
      button.setAttribute("aria-label", button.title);
      button.setAttribute("aria-pressed", String(on));
    };
    paint(store.has(supplier.domain));
    button.addEventListener("click", () => paint(store.toggle(supplier, context)));
    return button;
  };

  const supplierCell = (supplier) => {
    const kind = KIND[supplier.kind] || KIND.unknown;
    return h(
      "div",
      { class: "sup" },
      h("button", { class: "expand", type: "button", "aria-expanded": "false" }, supplier.name || supplier.domain),
      h("div", { class: "sup-meta" }, extLink(supplier.url, supplier.domain), supplier.doubt === kind ? null : [" · ", kind]),
      supplier.doubt ? h("div", { class: "doubt" }, supplier.doubt) : null,
      supplier.site_opened ? null : h("div", { class: "note" }, "сайт не открылся, данные из поиска"),
    );
  };

  const contactsCell = (supplier) => {
    const phones = (supplier.phones || []).slice(0, 2).map((phone) => h("a", { href: `tel:${phone.replace(/[^\d+]/g, "")}`, class: "nowrap" }, phone));
    const emails = (supplier.emails || []).slice(0, 1).map((email) => h("a", { href: `mailto:${email}`, class: "clip", title: email }, email));
    const items = [...phones, ...emails];
    return items.length ? h("div", { class: "stack" }, items) : pending();
  };

  const tick = () => svg("tick", "0 0 12 12", "M2 6.5l2.6 2.6L10 3.4");

  const tip = (() => {
    let el, owner = null, pinned = false;
    const close = () => {
      if (!owner) return;
      owner.setAttribute("aria-expanded", "false");
      el.hidden = true;
      owner = null;
      pinned = false;
    };
    const place = (button) => {
      const box = button.getBoundingClientRect();
      const { width, height } = el.getBoundingClientRect();
      const below = box.bottom + 8;
      const top = below + height > innerHeight - 8 && box.top - 8 - height >= 8 ? box.top - 8 - height : below;
      const left = Math.min(Math.max(box.left + box.width / 2 - width / 2, 8), innerWidth - 8 - width);
      el.style.top = `${top}px`;
      el.style.left = `${left}px`;
    };
    const open = (button, content) => {
      el ||= document.getElementById("tip");
      if (owner === button) return;
      close();
      owner = button;
      el.replaceChildren(...content());
      el.hidden = false;
      button.setAttribute("aria-expanded", "true");
      place(button);
    };
    const button = (label, content) => {
      const info = h("button", { class: "info", type: "button", "aria-label": label, "aria-expanded": "false", "aria-controls": "tip" });
      info.addEventListener("mouseenter", () => pinned || open(info, content));
      info.addEventListener("focus", () => pinned || open(info, content));
      info.addEventListener("mouseleave", () => pinned || close());
      info.addEventListener("blur", () => pinned || close());
      info.addEventListener("click", (e) => {
        e.stopPropagation();
        if (owner === info && pinned) return close();
        open(info, content);
        pinned = true;
      });
      return info;
    };
    document.addEventListener("click", (e) => owner && !el.contains(e.target) && close());
    document.addEventListener("keydown", (e) => e.key === "Escape" && close());
    addEventListener("scroll", close, true);
    addEventListener("resize", close);
    return { button };
  })();

  const confirmedTip = () => [
    h("p", { class: "tip-title" }, "Подтверждено: сколько пунктов проверки пройдено."),
    h("p", {}, "Всего 6 пунктов: возит в город; работает с юрлицами и оптом; есть документы; известен минимальный заказ; известна цена; юрлицу не меньше года."),
    h("p", {}, "Пункт засчитывается, только если подтверждён цитатой с сайта поставщика или записью в реестре. Всё остальное считается «уточнить» и в счёт не идёт."),
  ];

  const scoreTip = (supplier, total) => () => {
    const items = supplier.checklist || [];
    const done = items.filter((item) => item.mark === "yes");
    const rest = items.filter((item) => item.mark !== "yes");
    if (!done.length) return [h("p", {}, "Пока ни один пункт не подтверждён цитатой или реестром — все шесть нужно уточнить.")];
    if (!rest.length) return [h("p", { class: "tip-title" }, `Все ${total} пунктов подтверждены.`)];
    return [
      h("p", { class: "tip-title" }, `Засчитано ${done.length} из ${total}`),
      h("ul", { class: "tip-list" }, done.map((item) => h("li", {}, tick(), item.label))),
      h("p", { class: "tip-title" }, "Уточнить при звонке"),
      h("ul", { class: "tip-list tip-rest" }, rest.map((item) => h("li", {}, item.label))),
    ];
  };

  const confirmedCell = (supplier) => {
    const total = (supplier.checklist || []).length || 6;
    return h(
      "div",
      { class: "score" },
      h(
        "div",
        { class: "score-line" },
        h("span", { class: "score-num" }, supplier.confirmed ? tick() : null, `${supplier.confirmed} из ${total}`),
        tip.button(`Что значит «${supplier.confirmed} из ${total}»`, scoreTip(supplier, total)),
      ),
      h("span", { class: "meter" }, h("span", { style: `width:${Math.round((supplier.confirmed / total) * 100)}%` })),
    );
  };

  const factLabel = (key) => (key === "sells_category" ? "Товар в продаже" : FACT_LABELS[key] || key);

  const QUOTE_LENGTH = 180;

  const quote = (text) => {
    if (text.length <= QUOTE_LENGTH) return h("blockquote", {}, `«${text}»`);
    const space = text.lastIndexOf(" ", QUOTE_LENGTH);
    const cut = text.slice(0, space > 0 ? space : QUOTE_LENGTH).replace(/[\s,;:.–—-]+$/, "");
    const body = h("span", {}, `«${cut}…»`);
    const more = h("button", { class: "linkish", type: "button" }, "целиком");
    more.addEventListener("click", () => {
      body.textContent = `«${text}»`;
      more.remove();
    });
    return h("blockquote", {}, body, " ", more);
  };

  const factValue = (key, fact) => (key === "sells_category" ? MARK[fact.value] || fact.value : glue(fact.value));

  const factItem = (key, fact) =>
    h(
      "div",
      { class: "fact" },
      h("dt", {}, factLabel(key)),
      h("dd", {}, h("div", { class: "fact-value" }, factValue(key, fact)), quote(fact.quote), h("div", { class: "fact-source" }, extLink(fact.url, "источник"))),
    );

  const pairs = (rows) => h("dl", { class: "pairs" }, rows.filter(([, value]) => value != null && value !== "").map(([label, value]) => h("div", {}, h("dt", {}, label), h("dd", {}, value))));

  const block = (title, ...children) => h("section", { class: "block" }, typeof title === "string" ? h("h4", {}, title) : title, ...children);

  const MARK_ICON = { yes: "✓", no: "✕", unknown: "?" };

  const details = (supplier) => {
    const facts = Object.entries(supplier.facts || {}).sort(([a], [b]) => (b === "sells_category") - (a === "sells_category"));
    const legal = supplier.legal;
    const registered = legal?.registered ? parseDate(legal.registered)?.toLocaleDateString("ru-RU") || legal.registered : null;
    return h(
      "div",
      { class: "details" },
      block(
        "Условия с сайта",
        facts.length ? h("dl", { class: "facts" }, facts.map(([key, fact]) => factItem(key, fact))) : h("p", { class: "muted" }, "Подтверждённых цитатами условий не нашли — спросите при звонке."),
        supplier.snippet ? h("p", { class: "snippet" }, h("span", { class: "snippet-label" }, "Описание в поиске"), shortSnippet(supplier.snippet)) : null,
      ),
      block(
        "Контакты",
        pairs([
          ["Телефон", supplier.phones?.length ? h("div", { class: "stack" }, supplier.phones.map((phone) => h("a", { href: `tel:${phone.replace(/[^\d+]/g, "")}` }, phone))) : null],
          ["Почта", supplier.emails?.length ? h("div", { class: "stack" }, supplier.emails.map((email) => h("a", { href: `mailto:${email}` }, email))) : null],
          ["Адрес", supplier.address],
          ["Сайт", extLink(supplier.url, displayUrl(supplier))],
        ]),
        h("h4", { class: "sub" }, "Юрлицо"),
        legal
          ? [
              pairs([
                ["Название", legal.name],
                ["ИНН", legal.inn],
                ["Статус", legal.status ? [legalStatus(legal), registered ? `, с ${registered}` : ""] : null],
                ["ОКВЭД", legal.okved ? [legal.okved, legal.okved_name ? ` — ${legal.okved_name}` : ""] : null],
                ["Адрес", legal.address],
              ]),
              h("p", { class: "block-link" }, extLink(legal.check_url, "Проверить на Rusprofile")),
            ]
          : h("p", {}, supplier.inn ? `ИНН ${supplier.inn}` : pending("ИНН на сайте не найден")),
      ),
      block(
        "Проверка",
        h(
          "ul",
          { class: "checklist" },
          (supplier.checklist || []).map((item) =>
            h(
              "li",
              { class: `mark-${item.mark}` },
              h("span", { class: "mark", role: "img", title: MARK[item.mark], "aria-label": MARK[item.mark] }, MARK_ICON[item.mark]),
              h("span", {}, h("span", { class: "check-label" }, item.label), item.note ? h("span", { class: "check-note" }, item.note) : null),
            ),
          ),
        ),
      ),
      block(
        h("div", { class: "section-head" }, h("h4", {}, "Вопросы на звонок"), copyButton(() => supplier.questions.map((q) => `— ${q}`).join("\n"))),
        h("ol", { class: "questions" }, supplier.questions.map((q) => h("li", {}, q))),
      ),
      block(h("div", { class: "section-head" }, h("h4", {}, "Черновик запроса КП"), copyButton(() => supplier.rfq)), h("textarea", { class: "rfq", readonly: true, rows: 12 }, supplier.rfq)),
    );
  };

  const rows = (supplier, context) => {
    const plain = plainRow(supplier);
    const cells = [
      supplierCell(supplier),
      deliveryBadge(supplier),
      contactsCell(supplier),
      glue(plain.min_order) || pending(),
      glue(plain.price) || pending("по запросу"),
      glue(plain.documents) || pending(),
      glue(plain.legal) || pending(),
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
    const head = (title) => (title === "Подтверждено" ? h("span", { class: "th-in" }, title, tip.button("Что значит «Подтверждено»", confirmedTip)) : title);
    const el = h(
      "table",
      { class: "suppliers" },
      h("colgroup", {}, COLUMN_WIDTHS.map((width) => h("col", { style: `width:${width}%` }))),
      h("thead", {}, h("tr", {}, COLUMNS.map((title) => h("th", {}, head(title))))),
      tbody,
    );
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

  const groupTable = (suppliers, context) => {
    const list = table();
    suppliers.forEach((supplier) => list.add(supplier, context));
    return h("div", { class: "table-wrap" }, list.el);
  };

  const matchBlock = (match, doubtful, result, context) => {
    if (match.length) return [h("h2", { class: "group-title" }, `Подходят — ${match.length}`), groupTable(match, context)];
    if (!doubtful.length) return h("p", { class: "notice" }, "Поставщиков с подтверждёнными данными не нашли. Попробуйте сформулировать категорию шире.");
    return h(
      "p",
      { class: "notice" },
      `Подходящих не нашлось: никто не подтвердил на сайте и товар, и доставку в ${result.city}. Ниже — найденные поставщики под вопросом, у каждого указана причина.`,
    );
  };

  const doubtfulBlock = (match, doubtful, context) =>
    doubtful.length
      ? h(
          "details",
          { class: "fold", open: !match.length },
          h("summary", {}, `Под вопросом — ${doubtful.length}`, h("span", { class: "muted small" }, "другой регион, розница или не подтверждён товар")),
          groupTable(doubtful, context),
        )
      : null;

  const renderResult = (container, result) => {
    const context = { category: result.category, city: result.city };
    const match = result.suppliers.filter((supplier) => supplier.group === "match");
    const doubtful = result.suppliers.filter((supplier) => supplier.group !== "match");
    const top = match.slice(0, 3).filter((supplier) => supplier.why);
    const parts = [
      top.length
        ? h("div", { class: "why-top" }, h("h3", {}, "Почему первыми"), h("ol", {}, top.map((supplier) => h("li", {}, h("b", {}, supplier.name), " — ", supplier.why))))
        : null,
      matchBlock(match, doubtful, result, context),
      doubtfulBlock(match, doubtful, context),
      result.aggregators.length
        ? h(
            "details",
            { class: "fold" },
            h("summary", {}, `Отсеяли агрегаторы и маркетплейсы — ${result.aggregators.length}`),
            h("div", { class: "fold-body" }, h("ul", {}, result.aggregators.map((source) => h("li", {}, extLink(source.url, source.title || source.domain), h("span", { class: "muted" }, ` · ${source.domain}`))))),
          )
        : null,
      h(
        "p",
        { class: "stats" },
        statsLine(result),
        result.stats.rejected_quotes ? h("span", { class: "muted" }, ` · отброшено неподтверждённых цитат: ${result.stats.rejected_quotes}`) : null,
      ),
    ];
    container.replaceChildren(...parts.flat().filter(Boolean));
  };

  document.addEventListener("DOMContentLoaded", updateBadge);

  return { h, extLink, pending, glue, plural, ddmm, plainRow, store, copyText, table, renderResult, KIND };
})();
