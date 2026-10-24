(() => {
  "use strict";

  // Payloads mirror samples/requests.json so the buttons stay aligned with the fixtures.
  const SAMPLES = [
    {
      id: "cn_ok_mock",
      label: "中国 · 南山可送达",
      tone: "ok",
      body: {
        address: {
          country: "CN",
          province: "广东省",
          city: "深圳市",
          county: "南山区",
          road: "科技园南路",
          raw: "广东省深圳市南山区科技园南路",
        },
        carrier: "sf_express",
      },
    },
    {
      id: "id_incomplete",
      label: "印尼 · 仅路名",
      tone: "bad",
      body: {
        address: { country: "ID", raw: "JL. GANDARIA I" },
        carrier: "generic",
      },
    },
    {
      id: "co_bad_geocode",
      label: "哥伦比亚 · 坐标争议",
      tone: "bad",
      body: {
        address: {
          country: "CO",
          raw: "Transversal 32 No. 134A-49",
          sample_tag: "co_bad_geocode",
        },
        carrier: "generic",
      },
    },
    {
      id: "za_dirty",
      label: "南非 · 脏文本",
      tone: "warn",
      body: {
        address: {
          country: "ZA",
          raw: "Gauteng; NDC BoksburgCnr of Dam and Main RoadAnderboltBoksburg North1459;null;",
        },
        carrier: "generic",
      },
    },
    {
      id: "br_abbrev_sp",
      label: "巴西 · 简写邮编",
      tone: "warn",
      body: {
        address: {
          country: "BR",
          raw: "Rua,,,,ALAMEDA EUROPA,945,TAMBORE,SANTANA DE PARNAIBA,SP,06.543-325",
        },
        carrier: "generic",
      },
    },
  ];

  const STRUCT_FIELDS = [
    ["province", "省 / 直辖市"],
    ["city", "城市"],
    ["county", "区县"],
    ["district", "片区"],
    ["road", "道路"],
    ["house_number", "门牌"],
    ["postal_code", "邮编"],
    ["admin1", "一级行政区"],
    ["admin2", "二级行政区"],
    ["locality", "地方"],
    ["suburb", "街区 / 郊区"],
    ["sample_tag", "样例标签"],
  ];

  const FIELD_LABELS = {
    country: "国家",
    province: "省 / 直辖市",
    admin1: "一级行政区",
    city: "城市",
    locality: "地方",
    admin2: "二级行政区",
    suburb: "街区 / 郊区",
    road: "道路",
    house_number: "门牌",
    postal_code: "邮编",
    county: "区县",
    district: "片区",
    cleaned_raw: "清洗后原文",
    raw: "原始地址",
    parse_confidence: "解析置信度",
    completeness: "完整度",
  };

  const PARSED_GROUPS = [
    {
      title: "行政区划",
      keys: ["country", "province", "admin1", "city", "locality", "admin2", "county", "district", "suburb"],
    },
    {
      title: "道路与邮编",
      keys: ["road", "house_number", "postal_code"],
    },
    {
      title: "解析质量",
      keys: ["cleaned_raw", "parse_confidence", "completeness"],
    },
  ];

  const STAGE_ORDER = ["clean", "parse", "validate", "verify", "geocode", "carrier_filter", "aggregate"];

  const STAGE_ZH = {
    clean: "清洗",
    parse: "解析",
    validate: "校验",
    geocode: "地理编码",
    verify: "验真",
    carrier_filter: "承运商筛单",
    carrier: "承运商筛单",
    aggregate: "汇总",
  };

  const STATUS_ZH = {
    reachable: "可送达",
    unreachable: "不可达",
    needs_review: "需人工复核",
  };

  const SEVERITY_ZH = { info: "提示", warn: "警告", block: "阻断" };
  const SEVERITY_RANK = { info: 1, warn: 2, block: 3 };

  const CODE_ZH = {
    ADDR_DIRTY_NULL_TOKEN: "原文含空占位",
    ADDR_DIRTY_GLUED_TOKENS: "词语粘连",
    ADDR_DIRTY_SEPARATOR: "连续空分隔符",
    ADDR_ADMIN1_ABBREV: "行政区简写已展开",
    ADDR_INCOMPLETE: "地址不完整",
    ADDR_COUNTRY_MISSING: "缺少国家",
    ADDR_PROVINCE_MISSING: "缺少省份",
    ADDR_POSTCODE_INVALID: "邮编无效",
    GEO_LOW_CONF: "地理编码置信度不足",
    GEO_PROVIDER_DISPUTE: "多源坐标不一致",
    GEO_BAD_CANDIDATE: "候选坐标偏移",
    CARRIER_ADDR_UNCONFIRMED: "地址无法确认",
    CARRIER_OUT_OF_SERVICE: "不可收派",
    CARRIER_MANUAL_CONFIRM: "需人工确认",
    VERIFY_FAIL: "地址验真未通过",
    FENGTU_HTTP_ERROR: "丰图接口错误",
  };

  const COMPLETENESS_ZH = {
    sufficient: "充分",
    insufficient: "不足",
    unknown: "未知",
  };

  const FILTER_RESULT = {
    1: { label: "人工确认", hint: "先人工筛单，不自动放行", tone: "review" },
    2: { label: "可收派", hint: "在收派范围内", tone: "ok" },
    3: { label: "不可收派", hint: "超出收派范围", tone: "bad" },
    4: { label: "地址无法确认", hint: "地址不足以判断能否收派", tone: "bad" },
  };

  const OOS_REMARK = { 1: "收方超范围", 2: "派方超范围", 3: "其它原因" };

  const REMARK_ZH = {
    incomplete: "地址不完整",
    "address unconfirmed (mock)": "地址无法确认（模拟）",
  };

  const ADAPTER_ZH = {
    fengtu: "丰图",
    sf_filter: "顺丰筛单",
    intl_geocoder: "国际地理编码",
  };

  let requestSeq = 0;

  const $ = (id) => document.getElementById(id);
  const form = $("query-form");
  const resultEl = $("result");
  const errorEl = $("form-error");
  const submitBtn = $("submit");

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      Object.entries(attrs).forEach(([key, value]) => {
        if (value == null || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key.startsWith("on") && typeof value === "function") {
          node.addEventListener(key.slice(2), value);
        } else node.setAttribute(key, value);
      });
    }
    (children || []).forEach((child) => {
      if (child == null) return;
      node.append(child);
    });
    return node;
  }

  function toneOfStatus(status) {
    if (status === "reachable") return "ok";
    if (status === "needs_review") return "review";
    return "bad";
  }

  function stageLabel(stage) {
    if (!stage) return "未标注阶段";
    return STAGE_ZH[stage] || stage;
  }

  function codeLabel(reason) {
    const gloss = CODE_ZH[reason.code];
    return gloss ? `${gloss}（${reason.code}）` : reason.code || "未命名原因";
  }

  function percent(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    if (n >= 0 && n <= 1) return `${Math.round(n * 1000) / 10}%`;
    return String(n);
  }

  function formatValue(key, value) {
    if (value == null || value === "") return null;
    if (key === "parse_confidence") return percent(value);
    if (key === "completeness") return `${COMPLETENESS_ZH[value] || value}（${value}）`;
    return String(value);
  }

  function worstSeverity(reasons) {
    return (reasons || []).reduce((worst, reason) => {
      const rank = SEVERITY_RANK[reason.severity] || 0;
      return rank > (SEVERITY_RANK[worst] || 0) ? reason.severity : worst;
    }, "");
  }

  function stageIndex(stage) {
    const idx = STAGE_ORDER.indexOf(stage);
    return idx === -1 ? 99 : idx;
  }

  function ordered(reasons) {
    return [...(reasons || [])].sort((a, b) => {
      const byStage = stageIndex(a.stage) - stageIndex(b.stage);
      if (byStage !== 0) return byStage;
      return (SEVERITY_RANK[b.severity] || 0) - (SEVERITY_RANK[a.severity] || 0);
    });
  }

  function fieldKeyFromPath(path) {
    if (!path || !path.startsWith("address.")) return null;
    return path.slice("address.".length);
  }

  function reasonsForField(key, reasons) {
    return (reasons || []).filter((reason) => {
      const field = fieldKeyFromPath(reason.path);
      if (field === key) return true;
      return key === "cleaned_raw" && reason.path === "address.raw";
    });
  }

  function reasonsForStage(stage, reasons) {
    const aliases = stage === "geocode" ? ["geocode", "verify"] : [stage];
    return (reasons || []).filter(
      (reason) => aliases.includes(reason.stage) || aliases.some((name) => reason.path === `stage.${name}`)
    );
  }

  function locate(selector) {
    const node = document.querySelector(selector);
    if (!node) return;
    node.scrollIntoView({ behavior: "smooth", block: "center" });
    node.classList.remove("located");
    void node.offsetWidth;
    node.classList.add("located");
  }

  function targetSelector(path) {
    if (!path) return null;
    if (path.startsWith("address.")) return `[data-path="${cssEscape(path)}"]`;
    if (path === "stage.verify" || path === "stage.geocode") return '[data-anchor="stage.geocode"]';
    if (path.startsWith("stage.")) return `[data-anchor="${cssEscape(path)}"]`;
    return null;
  }

  function cssEscape(value) {
    return window.CSS && CSS.escape ? CSS.escape(value) : value.replace(/"/g, '\\"');
  }

  function pathPhrase(path, parsed) {
    if (!path) return "未提供 path";
    const field = fieldKeyFromPath(path);
    if (field) {
      const label = FIELD_LABELS[field] || field;
      if (field === "raw") return `原文（${path}）`;
      const value = parsed ? parsed[field] : undefined;
      if (value == null || value === "") return `字段「${label}」为空（${path}）`;
      return `字段「${label}」= ${value}（${path}）`;
    }
    if (path.startsWith("stage.")) {
      return `阶段「${stageLabel(path.slice("stage.".length))}」（${path}）`;
    }
    return path;
  }

  function diagnosis(resp) {
    const reasons = resp.reasons || [];
    const blocks = reasons.filter((reason) => reason.severity === "block");
    const warns = reasons.filter((reason) => reason.severity === "warn");
    const infos = reasons.filter((reason) => reason.severity === "info");
    if (resp.status === "reachable" && reasons.length === 0) {
      return "清洗、解析、校验、地理编码和筛单都通过，可以自动判定为可送达。";
    }
    if (resp.status === "reachable") {
      const bits = [];
      if (warns.length) bits.push(`${warns.length} 条警告`);
      if (infos.length) bits.push(`${infos.length} 条提示`);
      const extra = bits.length ? `另有 ${bits.join("、")}，` : "";
      return `可送达。${extra}没有阻断项。`;
    }
    const primary = ordered(blocks.length ? blocks : reasons)[0];
    if (!primary) {
      return resp.status === "needs_review"
        ? "评分或规则要求人工复核，这次响应没有单独的原因条目。"
        : "判定为不可达，但这条响应没有原因条目。";
    }
    const where = pathPhrase(primary.path, resp.parsed);
    const lead = resp.status === "needs_review" ? "需人工复核" : "不可达";
    return `${lead}。最先出问题的是「${stageLabel(primary.stage)}」：${where}。${codeLabel(primary)}。`;
  }

  function buildStructFields() {
    const grid = $("struct-grid");
    STRUCT_FIELDS.forEach(([key, label]) => {
      const input = el("input", { id: `f-${key}`, placeholder: "可选" });
      grid.append(el("div", null, [el("label", { class: "field-label", for: `f-${key}`, text: label }), input]));
    });
  }

  function buildSamples() {
    const host = $("samples");
    SAMPLES.forEach((sample) => {
      const button = el(
        "button",
        {
          type: "button",
          class: "sample",
          onclick: () => applySample(sample),
        },
        [el("span", { class: `dot ${sample.tone}`, "aria-hidden": "true" }), document.createTextNode(sample.label)]
      );
      host.append(button);
    });
  }

  function clearStruct() {
    STRUCT_FIELDS.forEach(([key]) => {
      const input = $(`f-${key}`);
      if (input) input.value = "";
    });
    $("f-lat").value = "";
    $("f-lng").value = "";
  }

  function applySample(sample) {
    clearStruct();
    const address = sample.body.address || {};
    $("raw").value = address.raw || "";
    $("country").value = address.country || "";
    $("carrier").value = sample.body.carrier || "sf_express";
    $("product").value = sample.body.product_code || "";
    STRUCT_FIELDS.forEach(([key]) => {
      const input = $(`f-${key}`);
      if (input) input.value = address[key] == null ? "" : String(address[key]);
    });
    $("f-lat").value = address.lat == null ? "" : String(address.lat);
    $("f-lng").value = address.lng == null ? "" : String(address.lng);
    const advanced = document.querySelector(".advanced");
    const hasStruct = STRUCT_FIELDS.some(([key]) => address[key] != null && address[key] !== "");
    if (advanced && hasStruct) advanced.open = true;
    submitQuery();
  }

  function readNumber(id, label) {
    const raw = $(id).value.trim();
    if (!raw) return { ok: true, value: null };
    const value = Number(raw);
    if (!Number.isFinite(value)) return { ok: false, message: `${label}需要是数字` };
    return { ok: true, value };
  }

  function buildPayload() {
    const address = {};
    const raw = $("raw").value.trim();
    const country = $("country").value.trim().toUpperCase();
    if (raw) address.raw = raw;
    if (country) address.country = country;
    STRUCT_FIELDS.forEach(([key]) => {
      const value = $(`f-${key}`).value.trim();
      if (value) address[key] = value;
    });
    const lat = readNumber("f-lat", "纬度");
    const lng = readNumber("f-lng", "经度");
    if (!lat.ok) return { error: lat.message };
    if (!lng.ok) return { error: lng.message };
    if (lat.value != null) address.lat = lat.value;
    if (lng.value != null) address.lng = lng.value;
    if (Object.keys(address).length === 0) return { error: "请填写原始地址，或至少一项结构化字段。" };
    const body = { address };
    const carrier = $("carrier").value.trim();
    const product = $("product").value.trim();
    if (carrier) body.carrier = carrier;
    if (product) body.product_code = product;
    return { body };
  }

  function showFormError(message) {
    if (!message) {
      errorEl.hidden = true;
      errorEl.textContent = "";
      return;
    }
    errorEl.hidden = false;
    errorEl.textContent = message;
  }

  async function submitQuery(event) {
    if (event) event.preventDefault();
    const built = buildPayload();
    if (built.error) {
      showFormError(built.error);
      return;
    }
    showFormError("");
    const seq = ++requestSeq;
    submitBtn.disabled = true;
    submitBtn.textContent = "分析中…";
    renderLoading();
    try {
      const response = await fetch("/v1/address/reachability", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(built.body),
      });
      const text = await response.text();
      if (seq !== requestSeq) return;
      let data = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = null;
      }
      if (!response.ok) {
        renderHttpError(response.status, data || text);
        return;
      }
      renderResult(data, built.body);
    } catch (err) {
      if (seq !== requestSeq) return;
      renderHttpError(0, err && err.message ? err.message : "网络请求失败");
    } finally {
      if (seq === requestSeq) {
        submitBtn.disabled = false;
        submitBtn.textContent = "分析可达性";
      }
    }
  }

  function renderLoading() {
    resultEl.replaceChildren(
      el("div", { class: "empty" }, [
        el("p", { class: "empty-kicker", text: "正在分析" }),
        el("h2", { text: "流水线运行中" }),
        el("p", { text: "清洗、解析、校验、地理编码、筛单完成后会显示在这里。" }),
      ])
    );
  }

  function renderHttpError(status, payload) {
    const detail = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
    const title = status === 422 ? "请求未通过校验" : status ? `查询失败（HTTP ${status}）` : "无法连接服务";
    resultEl.replaceChildren(
      el("div", { class: "banner-error" }, [
        el("h2", { text: title }),
        el("p", { text: status === 422 ? "请检查国家代码、经纬度和地址字段。" : "确认本页与接口在同一服务上，然后重试。" }),
        el("pre", { text: detail || "无响应正文" }),
      ])
    );
  }

  function renderResult(resp, requestBody) {
    const tone = toneOfStatus(resp.status);
    const reasons = resp.reasons || [];
    const score = Number(resp.deliverability_score);
    const scoreText = Number.isFinite(score) ? String(score) : "—";
    const blocks = ordered(reasons.filter((reason) => reason.severity === "block" || reason.severity === "warn"));

    const hero = el("div", { class: `hero tone-${tone}` }, [
      el("div", { class: `score tone-${tone}`, style: `--p:${clampScore(score)}` }, [
        el("div", { class: "score-inner" }, [
          el("span", { class: "score-num", text: scoreText }),
          el("span", { class: "score-cap", text: "可送达评分" }),
        ]),
      ]),
      el("div", null, [
        el("div", { class: "status-row" }, [
          el("span", { class: `pill ${tone}`, text: STATUS_ZH[resp.status] || resp.status || "未知状态" }),
          el("span", {
            class: `pill ${resp.reachable ? "ok" : "bad"}`,
            text: resp.reachable ? "reachable = 是" : "reachable = 否",
          }),
          el("span", { class: "pill neutral", text: resp.status || "—" }),
        ]),
        el("p", { class: "diagnosis", text: diagnosis(resp) }),
        blocks.length
          ? el(
              "div",
              { class: "chain" },
              blocks.map((reason) =>
                el(
                  "button",
                  {
                    type: "button",
                    class: reason.severity === "block" ? "bad" : "review",
                    onclick: () => locate(targetSelector(reason.path)),
                  },
                  [
                    document.createTextNode(
                      `${stageLabel(reason.stage)} · ${reason.path || "无 path"}`
                    ),
                  ]
                )
              )
            )
          : null,
        el("p", { class: "meta" }, [
          document.createTextNode("规则版本 "),
          el("code", { text: resp.rules_version || "—" }),
          document.createTextNode(" · 请求号 "),
          el("code", { text: resp.request_id || "—" }),
          document.createTextNode(" · 本次原文："),
          document.createTextNode(requestBody.address.raw || "（仅结构化字段）"),
        ]),
      ]),
    ]);

    const pipeline = renderPipeline(resp);
    const lower = el("div", { class: "grid-2" }, [renderReasons(resp), renderParsed(resp)]);
    const evidence = el("div", { class: "grid-2" }, [renderGeocode(resp), renderCarrier(resp)]);
    const raw = el("div", null, [
      el("h3", { class: "section-title", text: "原始响应" }),
      el("pre", { class: "json", text: JSON.stringify(resp, null, 2) }),
    ]);

    resultEl.replaceChildren(hero, pipeline, lower, evidence, raw);
    const primary = ordered(reasons.filter((reason) => reason.severity === "block"))[0] || ordered(reasons)[0];
    if (primary) {
      const node = document.querySelector(targetSelector(primary.path));
      if (node) node.classList.add("located");
    }
    markRawHit(reasons);
  }

  function clampScore(score) {
    if (!Number.isFinite(score)) return 0;
    return Math.max(0, Math.min(100, score));
  }

  function markRawHit(reasons) {
    const hit = reasons.some((reason) => reason.path === "address.raw");
    $("raw").classList.toggle("hit", hit);
  }

  function renderPipeline(resp) {
    const traces = Array.isArray(resp.pipeline) ? resp.pipeline.slice() : [];
    const hasAggregate = traces.some((trace) => trace.stage === "aggregate");
    if (!hasAggregate) {
      traces.push({
        stage: "aggregate",
        ok: resp.status === "reachable",
        duration_ms: null,
        notes: ["由本次响应的 status、reachable、deliverability_score 汇总。服务端流水线没有单独记录这一步的耗时。"],
        synthetic: true,
        status: resp.status,
      });
    }
    const wrap = el("div", null, [el("h3", { class: "section-title", text: "流水线" })]);
    wrap.append(
      el(
        "div",
        { class: "pipeline" },
        traces.map((trace) => renderStage(trace, resp.reasons || [], resp.status))
      )
    );
    return wrap;
  }

  function renderStage(trace, reasons, status) {
    const related = trace.stage === "aggregate" ? [] : reasonsForStage(trace.stage, reasons);
    const severity = worstSeverity(related);
    let tone = !trace.ok ? (severity === "warn" ? "review" : "bad") : severity === "warn" ? "review" : "ok";
    if (trace.stage === "aggregate") tone = toneOfStatus(trace.status || status);
    let state = trace.ok ? "通过" : "未通过";
    if (trace.stage === "aggregate" && (trace.status || status) === "needs_review") state = "需复核";
    else if (trace.ok && severity === "warn") state = "通过 · 有警告";
    else if (trace.ok && severity === "info") state = "通过 · 有提示";
    const bits = [];
    if (trace.duration_ms == null) bits.push("耗时 —");
    else bits.push(`${trace.duration_ms} ms`);
    const summary = stageSummary(trace);
    if (summary) bits.push(summary);
    const noteText = (trace.notes || []).filter(Boolean).join("；");
    const codes = related.map((reason) => reason.code).filter(Boolean);
    return el(
      "article",
      {
        class: `stage ${tone}${trace.synthetic ? " synthetic" : ""}`,
        "data-anchor": `stage.${trace.stage === "verify" ? "verify" : trace.stage}`,
        id: `stage-${trace.stage}`,
      },
      [
        el("div", { class: "stage-name" }, [
          document.createTextNode(stageLabel(trace.stage)),
          el("span", { class: "stage-en", text: trace.stage }),
        ]),
        el("div", { class: "stage-state", text: state }),
        el("p", { text: bits.join(" · ") }),
        noteText ? el("p", { text: noteText }) : null,
        codes.length ? el("p", { text: codes.join("、") }) : null,
      ]
    );
  }

  function stageSummary(trace) {
    const data = trace.data || {};
    if (trace.stage === "clean" && data.cleaned_raw) return "已输出清洗文本";
    if (trace.stage === "validate" && data.postal_code_invalid) return "邮编无效";
    if (trace.stage === "geocode") {
      const confidence = data.geocode && data.geocode.confidence;
      const conf = confidence == null ? "" : `置信度 ${percent(confidence)}`;
      const verify = verifyRan(data) ? (data.verify_ok ? "验真通过" : "验真未通过") : "";
      return [conf, verify].filter(Boolean).join("，");
    }
    if (trace.stage === "carrier_filter" && data.carrier_filter) {
      const result = data.carrier_filter.filter_result;
      const known = FILTER_RESULT[result];
      return known ? `筛单 ${result} ${known.label}` : `筛单 ${result}`;
    }
    if (trace.stage === "aggregate") return "见上方状态与评分";
    return "";
  }

  function renderReasons(resp) {
    const reasons = ordered(resp.reasons || []);
    const card = el("section", { class: "card" }, [el("h3", { text: `原因（${reasons.length}）` })]);
    if (!reasons.length) {
      card.append(el("p", { class: "hint", text: "没有原因码。这次判定没有需要解释的规则命中。" }));
      return card;
    }
    reasons.forEach((reason, index) => {
      const severity = reason.severity || "info";
      const item = el("article", { class: `reason ${severity}`, id: `reason-${index}` }, [
        el("div", { class: "reason-top" }, [
          el("h4", { text: reason.message || codeLabel(reason) }),
          el("span", { class: `pill ${severity === "block" ? "bad" : severity === "warn" ? "review" : "neutral"}`, text: SEVERITY_ZH[severity] || severity }),
        ]),
        el("p", { class: "sub", text: `${codeLabel(reason)} · ${pathPhrase(reason.path, resp.parsed)}` }),
        el("div", { class: "kv" }, [
          reason.path
            ? el("span", { class: `path${severity === "block" ? " hot" : ""}`, text: reason.path })
            : null,
          reason.rule_id ? el("span", { text: `规则 ${reason.rule_id}` }) : null,
          reason.stage ? el("span", { text: `阶段 ${stageLabel(reason.stage)}` }) : null,
          el(
            "button",
            {
              type: "button",
              class: "btn tiny",
              onclick: () => locate(targetSelector(reason.path)),
              text: "定位",
            }
          ),
        ]),
      ]);
      if (reason.details && Object.keys(reason.details).length) {
        item.append(el("p", { class: "sub", text: `明细 ${JSON.stringify(reason.details)}` }));
      }
      card.append(item);
    });
    return card;
  }

  function renderParsed(resp) {
    const parsed = resp.parsed || {};
    const reasons = resp.reasons || [];
    const cardTone = worstSeverity(reasons.filter((reason) => fieldKeyFromPath(reason.path)));
    const card = el("section", { class: `card ${cardTone === "block" ? "bad" : cardTone === "warn" ? "review" : ""}` }, [
      el("h3", { text: "解析字段" }),
    ]);
    if (!resp.parsed) {
      card.append(el("p", { class: "hint", text: "这次没有返回 parsed。" }));
      return card;
    }
    card.append(
      el("div", { class: "quality" }, [
        el("span", { class: "pill neutral", text: `置信度 ${percent(parsed.parse_confidence)}` }),
        el("span", {
          class: `pill ${parsed.completeness === "sufficient" ? "ok" : parsed.completeness === "insufficient" ? "bad" : "neutral"}`,
          text: `完整度 ${COMPLETENESS_ZH[parsed.completeness] || parsed.completeness || "未知"}`,
        }),
      ])
    );
    PARSED_GROUPS.forEach((group) => {
      card.append(el("h3", { class: "section-title", text: group.title }));
      const list = el("div", { class: "fields" });
      group.keys.forEach((key) => {
        const hits = reasonsForField(key, reasons);
        const severity = worstSeverity(hits);
        const shown = formatValue(key, parsed[key]);
        const anchorPath = key === "cleaned_raw" && hits.some((reason) => reason.path === "address.raw")
          ? "address.raw"
          : `address.${key}`;
        list.append(
          el("div", { class: `field${severity ? ` ${severity}` : ""}`, "data-path": anchorPath, id: `field-${key}` }, [
            el("div", { class: "k", text: FIELD_LABELS[key] || key }),
            el("div", { class: `v${shown ? "" : " empty"}`, text: shown || (severity === "block" ? "空 · 这里失败" : "—") }),
          ])
        );
      });
      card.append(list);
    });
    return card;
  }

  function renderGeocode(resp) {
    const geo = resp.geocode;
    const reasons = reasonsForStage("geocode", resp.reasons || []);
    const severity = worstSeverity(reasons);
    const card = el("section", {
      class: `card ${severity === "block" ? "bad" : severity === "warn" ? "review" : ""}`,
      "data-anchor": "stage.geocode",
      id: "panel-geocode",
    }, [el("h3", { text: "地理编码" })]);
    if (!geo) {
      card.append(el("p", { class: "hint", text: "这次没有返回 geocode。" }));
      return card;
    }
    const hasPoint = geo.lat != null && geo.lng != null;
    card.append(
      el("p", { class: `geo-coords${hasPoint ? "" : " missing"}`, text: hasPoint ? `${geo.lat}, ${geo.lng}` : "没有可用坐标" })
    );
    const ratio = Number(geo.confidence);
    const barClass = !Number.isFinite(ratio) ? "" : ratio < 0.55 ? "low" : ratio < 0.75 ? "mid" : "";
    card.append(
      el("div", { class: `bar ${barClass}` }, [
        el("span", { style: `width:${Math.max(0, Math.min(100, (Number.isFinite(ratio) ? ratio : 0) * 100))}%` }),
      ])
    );
    const rows = [
      ["置信度", percent(geo.confidence)],
      ["提供方", geo.provider || "—"],
      ["坐标系", geo.coordinate_system || "—"],
      ["多源距离", geo.dispute_km == null ? "—" : `${geo.dispute_km} km`],
    ];
    rows.forEach(([key, value]) => {
      card.append(
        el("div", { class: "field" }, [el("div", { class: "k", text: key }), el("div", { class: "v", text: value })])
      );
    });
    const verify = verifyFlag(resp);
    if (verify != null) {
      card.append(
        el("div", { class: "field" }, [
          el("div", { class: "k", text: "验真" }),
          el("div", { class: "v", text: verify ? "通过" : "未通过" }),
        ])
      );
    }
    if (Array.isArray(geo.candidates) && geo.candidates.length) {
      const list = el("ul", { class: "candidates" });
      geo.candidates.forEach((candidate) => list.append(el("li", { text: formatCandidate(candidate) })));
      card.append(el("p", { class: "hint", text: "候选点" }), list);
    }
    return card;
  }

  function verifyRan(data) {
    if (!data || !Object.prototype.hasOwnProperty.call(data, "verify_ok")) return false;
    if (data.verify_ok === false) return true;
    const provider = data.geocode && data.geocode.provider;
    return typeof provider === "string" && provider.startsWith("fengtu");
  }

  function verifyFlag(resp) {
    const trace = (resp.pipeline || []).find((item) => item.stage === "geocode");
    if (!trace || !verifyRan(trace.data)) return null;
    return Boolean(trace.data.verify_ok);
  }

  function formatCandidate(candidate) {
    if (candidate == null) return "—";
    if (typeof candidate !== "object") return String(candidate);
    const parts = [];
    if (candidate.label) parts.push(String(candidate.label));
    if (candidate.lat != null && candidate.lng != null) parts.push(`${candidate.lat}, ${candidate.lng}`);
    if (candidate.confidence != null) parts.push(`置信度 ${percent(candidate.confidence)}`);
    if (candidate.note) parts.push(String(candidate.note));
    return parts.join(" · ") || JSON.stringify(candidate);
  }

  function renderCarrier(resp) {
    const carrier = resp.carrier_filter;
    const reasons = reasonsForStage("carrier_filter", resp.reasons || []);
    const severity = worstSeverity(reasons);
    const card = el("section", {
      class: `card ${severity === "block" ? "bad" : severity === "warn" ? "review" : ""}`,
      "data-anchor": "stage.carrier_filter",
      id: "panel-carrier",
    }, [el("h3", { text: "承运商筛单" })]);
    if (!carrier) {
      card.append(el("p", { class: "hint", text: "这次没有返回 carrier_filter。" }));
      return card;
    }
    const known = FILTER_RESULT[carrier.filter_result] || {
      label: "未知结果",
      hint: "不在 1–4 的筛单语义里",
      tone: "bad",
    };
    card.append(
      el("div", { class: "filter-result" }, [
        el("div", { class: `filter-num ${known.tone === "ok" ? "" : known.tone}`, text: String(carrier.filter_result) }),
        el("div", null, [
          el("strong", { text: known.label }),
          el("p", { class: "hint", text: known.hint }),
        ]),
      ])
    );
    const remark = carrier.remark == null || carrier.remark === "" ? "—" : String(carrier.remark);
    let remarkText = remark;
    if (carrier.filter_result === 3 && OOS_REMARK[remark]) remarkText = `${remark} · ${OOS_REMARK[remark]}`;
    else if (REMARK_ZH[remark]) remarkText = `${remark} · ${REMARK_ZH[remark]}`;
    [
      ["说明", remarkText],
      ["始发代码", carrier.origin_code || "—"],
      ["目的代码", carrier.dest_code || "—"],
      ["适配器", carrier.carrier || "—"],
    ].forEach(([key, value]) => {
      card.append(
        el("div", { class: "field" }, [el("div", { class: "k", text: key }), el("div", { class: "v", text: value })])
      );
    });
    const legend = el("ol", { class: "legend" });
    Object.entries(FILTER_RESULT).forEach(([num, item]) => {
      const current = String(carrier.filter_result) === num;
      legend.append(el("li", { class: current ? "on" : "", text: `${num} ${item.label}` }));
    });
    card.append(legend);
    return card;
  }

  async function loadHealth() {
    const node = $("health");
    try {
      const response = await fetch("/health");
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      const adapters = data.adapters || {};
      const parts = Object.entries(adapters).map(([key, value]) => {
        const name = ADAPTER_ZH[key] || key;
        const mode = value === "mock" ? "模拟" : value === "live" ? "线上" : value;
        return `${name} ${mode}`;
      });
      node.classList.remove("bad");
      node.replaceChildren(
        document.createTextNode("服务正常 · 规则 "),
        el("strong", { text: data.rules_version || "—" }),
        document.createTextNode(parts.length ? ` · ${parts.join(" · ")}` : "")
      );
      if (adapters.fengtu === "mock") {
        node.append(document.createTextNode("。丰图密钥未配置，中国地址走本地模拟。"));
      }
    } catch {
      node.classList.add("bad");
      node.textContent = "健康检查失败。页面仍可尝试查询。";
    }
  }

  function resetForm() {
    form.reset();
    clearStruct();
    $("raw").classList.remove("hit");
    showFormError("");
    resultEl.replaceChildren(
      el("div", { class: "empty" }, [
        el("p", { class: "empty-kicker", text: "等待查询" }),
        el("h2", { text: "粘贴地址，或选择左侧样例" }),
        el("p", { text: "结果会标出整体状态、可送达评分、解析字段、原因 path，以及清洗到汇总的各段是否通过。" }),
      ])
    );
  }

  buildStructFields();
  buildSamples();
  form.addEventListener("submit", submitQuery);
  $("clear").addEventListener("click", resetForm);
  loadHealth();
})();
