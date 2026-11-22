let runningJob = null;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function fold(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .replace(/[^a-z0-9/ ]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function gender(value) {
  const text = fold(value).replace(/[^a-z]/g, "");
  if (text === "nam" || text === "male") return "Nam";
  if (text === "nu" || text === "female") return "Nữ";
  return "";
}

function parseDate(value) {
  const match = String(value || "").replace(/[.\-]/g, "/").match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (!match) return "";
  const day = match[1].padStart(2, "0");
  const month = match[2].padStart(2, "0");
  const year = Number(match[3]);
  const date = new Date(year, Number(month) - 1, Number(day));
  if (date.getFullYear() !== year || date.getMonth() !== Number(month) - 1 || date.getDate() !== Number(day)) return "";
  return `${day}/${month}/${match[3]}`;
}

function searchRoot() {
  return document.querySelector("section.section-search") || document.querySelector("ord-search-box-page");
}

function searchField(selector) {
  const root = searchRoot();
  return root ? root.querySelector(selector) : null;
}

async function typeText(input, text) {
  input.scrollIntoView({ block: "center" });
  input.focus();
  input.click();
  document.execCommand("selectAll", false, null);
  document.execCommand("delete", false, null);
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  for (const char of text) {
    const before = input.value;
    const keyCode = char.charCodeAt(0);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: char, keyCode, which: keyCode, bubbles: true }));
    const typed = document.execCommand("insertText", false, char);
    if (!typed || input.value === before) {
      setter.call(input, before + char);
      input.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, data: char, inputType: "insertText" }));
      input.dispatchEvent(new InputEvent("input", { bubbles: true, data: char, inputType: "insertText" }));
    }
    input.dispatchEvent(new KeyboardEvent("keyup", { key: char, keyCode, which: keyCode, bubbles: true }));
    await sleep(15);
  }
  input.dispatchEvent(new Event("change", { bubbles: true }));
  input.blur();
}

function searchButton() {
  const root = searchRoot();
  if (!root) return null;
  return [...root.querySelectorAll(".main-search-box button")].find((node) => /^tìm\s*kiếm$/i.test((node.innerText || "").trim()));
}

function tableBox() {
  return document.querySelector("ord-datatable");
}

async function waitForRows(job) {
  for (let elapsed = 0; elapsed < 3000; elapsed += 200) {
    if (job.closed || job.stopped) return;
    showProgress(job);
    await sleep(200);
  }
}

function bestTable() {
  const root = tableBox();
  if (!root) return [];
  let header = [];
  let body = [];
  let bodyScore = 0;
  for (const table of root.querySelectorAll("table")) {
    const heads = [...table.querySelectorAll("thead th")].map((cell) => cell.innerText.replace(/\s+/g, " ").trim());
    if (heads.filter(Boolean).length > header.filter(Boolean).length) header = heads;
    const rows = [...table.querySelectorAll("tbody tr")].map((row) =>
      [...row.querySelectorAll("td")].map((cell) => cell.innerText.replace(/\s+/g, " ").trim())
    ).filter((row) => row.some(Boolean));
    const score = rows.reduce((sum, row) => sum + row.filter(Boolean).length, 0);
    if (score > bodyScore) {
      body = rows;
      bodyScore = score;
    }
  }
  return header.length ? [header, ...body] : body;
}

function headerMap(header) {
  const found = {};
  const folded = header.map(fold);
  const needles = {
    ho_ten: ["ho va ten", "ho ten", "ten benh nhan"],
    gioi_tinh: ["gioi tinh"],
    ngay_sinh: ["ngay sinh", "nam sinh"],
    cccd: ["cccd", "cmnd", "can cuoc", "giay to"],
  };
  for (const [key, words] of Object.entries(needles)) {
    const index = folded.findIndex((cell) => words.some((word) => cell.includes(word)));
    if (index >= 0) found[key] = index;
  }
  return found;
}

function compare(person, rows) {
  const page = (tableBox() && tableBox().innerText) || "";
  const empty = {
    id: person.id, anh: person.anh, stt: person.stt, ho_ten: person.ho_ten,
    ngay_sinh: person.ngay_sinh, gioi_tinh: person.gioi_tinh, cccd: person.cccd, dia_chi: person.dia_chi,
  };
  if (!rows.length) {
    const missing = /không có dữ liệu|không tìm thấy|no data/i.test(page) || !page.includes(person.cccd);
    return Object.assign(empty, missing
      ? { co_tren_he_thong: "Khong", khop_ho_ten: "Khong_co_du_lieu", khop_gioi_tinh: "Khong_co_du_lieu", khop_ngay_sinh: "Khong_co_du_lieu", ket_luan: "KHONG_CO_TREN_HE_THONG", ho_ten_web: "", gioi_tinh_web: "", ngay_sinh_web: "", ghi_chu: "Không có dòng khám sức khỏe khớp CCCD." }
      : { co_tren_he_thong: "Khong_ro", khop_ho_ten: "Khong_kiem_tra", khop_gioi_tinh: "Khong_kiem_tra", khop_ngay_sinh: "Khong_kiem_tra", ket_luan: "LOI_KIEM_TRA", ho_ten_web: "", gioi_tinh_web: "", ngay_sinh_web: "", ghi_chu: "Không đọc được bảng kết quả." });
  }
  const mapping = headerMap(rows[0]);
  const body = Object.keys(mapping).length ? rows.slice(1) : rows;
  const exact = body.filter((row) => row.join(" ").replace(/\s+/g, "").includes(person.cccd));
  if (!exact.length) {
    const filtered = body.length >= 15 && !page.includes(person.cccd);
    return Object.assign(empty, filtered
      ? { co_tren_he_thong: "Khong_ro", khop_ho_ten: "Khong_kiem_tra", khop_gioi_tinh: "Khong_kiem_tra", khop_ngay_sinh: "Khong_kiem_tra", ket_luan: "LOI_KIEM_TRA", ho_ten_web: "", gioi_tinh_web: "", ngay_sinh_web: "", ghi_chu: "Bộ lọc chưa áp dụng, bảng vẫn còn nhiều dòng khác." }
      : { co_tren_he_thong: "Khong", khop_ho_ten: "Khong_co_du_lieu", khop_gioi_tinh: "Khong_co_du_lieu", khop_ngay_sinh: "Khong_co_du_lieu", ket_luan: "KHONG_CO_TREN_HE_THONG", ho_ten_web: "", gioi_tinh_web: "", ngay_sinh_web: "", ghi_chu: "Không có dòng trùng CCCD." });
  }
  const sample = exact[0];
  const cell = (key) => {
    const index = mapping[key];
    return index >= 0 && index < sample.length ? sample[index] : "";
  };
  let webName = cell("ho_ten");
  let webGender = cell("gioi_tinh");
  let webDob = cell("ngay_sinh");
  for (const part of sample) {
    if (!webName && fold(part).split(" ").length >= 2 && !/\d{4}/.test(part)) webName = part;
    if (!webGender && gender(part)) webGender = part;
    if (!webDob && parseDate(part)) webDob = part;
  }
  const nameOk = webName && fold(webName) === fold(person.ho_ten);
  const genderOk = webGender && gender(webGender) === gender(person.gioi_tinh);
  const dobOk = webDob && parseDate(webDob) === parseDate(person.ngay_sinh);
  return Object.assign(empty, {
    co_tren_he_thong: "Co",
    khop_ho_ten: nameOk ? "Dung" : "Sai",
    khop_gioi_tinh: genderOk ? "Dung" : "Sai",
    khop_ngay_sinh: dobOk ? "Dung" : "Sai",
    ket_luan: nameOk && genderOk && dobOk ? "DUNG_HET" : "SAI_THONG_TIN",
    ho_ten_web: webName,
    gioi_tinh_web: gender(webGender) || webGender,
    ngay_sinh_web: parseDate(webDob) || webDob,
    ghi_chu: nameOk && genderOk && dobOk ? `Khớp ${exact.length} dòng.` : `web: ${webName} | ${webGender} | ${webDob}`,
  });
}

function ensureOverlay() {
  let panel = document.querySelector("#ksk-check-panel");
  if (panel) return panel;
  panel = document.createElement("div");
  panel.id = "ksk-check-panel";
  panel.innerHTML = `
    <strong id="ksk-title">Đang kiểm tra danh sách khám sức khỏe</strong>
    <div id="ksk-status">Chuẩn bị</div>
    <progress id="ksk-progress" max="1" value="0"></progress>
    <div class="ksk-actions">
      <button id="ksk-pause" type="button">Tạm dừng</button>
      <button id="ksk-stop" type="button">Dừng</button>
      <button id="ksk-download" type="button" hidden>Tải CSV</button>
      <button id="ksk-off" type="button">Tắt</button>
    </div>`;
  const style = document.createElement("style");
  style.id = "ksk-check-style";
  style.textContent = `
    #ksk-shield { position: fixed; inset: 0; z-index: 2147483646; background: rgba(16, 24, 32, 0.45); }
    #ksk-check-panel { position: fixed; z-index: 2147483647; top: 16px; right: 16px; width: 340px;
      background: #16324f; color: white; padding: 14px; border-radius: 12px; font: 14px "Segoe UI", sans-serif;
      box-shadow: 0 8px 24px rgba(0,0,0,.3); }
    #ksk-check-panel progress { width: 100%; margin: 8px 0; }
    #ksk-check-panel .ksk-actions { display: flex; gap: 8px; }
    #ksk-check-panel button { border: 0; border-radius: 6px; padding: 7px 10px; cursor: pointer; }
    #ksk-stop, #ksk-off { background: #9d1c1c; color: white; }
    #ksk-download { background: #2f6f4e; color: white; }
  `;
  const shield = document.createElement("div");
  shield.id = "ksk-shield";
  document.documentElement.append(style, shield, panel);
  panel.querySelector("#ksk-pause").onclick = async () => {
    if (!runningJob) return;
    runningJob.paused = !runningJob.paused;
    panel.querySelector("#ksk-pause").textContent = runningJob.paused ? "Tiếp tục" : "Tạm dừng";
    await chrome.storage.local.set({ kskJob: runningJob });
  };
  panel.querySelector("#ksk-stop").onclick = async () => {
    if (!runningJob) return;
    runningJob.stopped = true;
    runningJob.running = false;
    document.querySelector("#ksk-shield")?.remove();
    await chrome.storage.local.set({ kskJob: runningJob });
  };
  panel.querySelector("#ksk-off").onclick = () => turnOff();
  panel.querySelector("#ksk-download").onclick = () => {
    if (lastResults.length) download(lastResults);
  };
  return panel;
}

let lastResults = [];

async function turnOff() {
  const job = runningJob;
  if (job) {
    job.stopped = true;
    job.closed = true;
    job.running = false;
  }
  runningJob = null;
  await chrome.storage.local.remove("kskJob");
  if (job && job.results.length) {
    chrome.runtime.sendMessage({ type: "save-results", rows: job.results });
  }
  document.querySelector("#ksk-shield")?.remove();
  document.querySelector("#ksk-check-panel")?.remove();
}

function showProgress(job) {
  const panel = ensureOverlay();
  const person = job.people[job.index];
  panel.querySelector("#ksk-title").textContent = "Đang kiểm tra danh sách khám sức khỏe";
  panel.querySelector("#ksk-pause").hidden = false;
  panel.querySelector("#ksk-stop").hidden = false;
  panel.querySelector("#ksk-pause").textContent = job.paused ? "Tiếp tục" : "Tạm dừng";
  panel.querySelector("#ksk-status").textContent = job.stopped
    ? "Đã dừng"
    : `${Math.min(job.index + 1, job.people.length)}/${job.people.length} · ${person ? person.ho_ten || person.cccd : "xong"}`;
  const progress = panel.querySelector("#ksk-progress");
  progress.max = job.people.length || 1;
  progress.value = job.results.length;
}

async function waitUntil(label, ready) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (ready()) return true;
    showProgress(runningJob);
    await sleep(500);
    if (runningJob && runningJob.stopped) return false;
    if (attempt === 39) throw new Error(label);
  }
  return false;
}

function removeShield() {
  document.querySelector("#ksk-shield")?.remove();
}

function csvText(rows) {
  const fields = ["Anh", "STT", "Ho_ten", "Ngay_sinh", "Gioi_tinh", "CCCD", "Dia_chi", "Co_tren_he_thong", "Khop_ho_ten", "Khop_gioi_tinh", "Khop_ngay_sinh", "Ket_luan", "Ho_ten_web", "Gioi_tinh_web", "Ngay_sinh_web", "Ghi_chu"];
  const keys = ["anh", "stt", "ho_ten", "ngay_sinh", "gioi_tinh", "cccd", "dia_chi", "co_tren_he_thong", "khop_ho_ten", "khop_gioi_tinh", "khop_ngay_sinh", "ket_luan", "ho_ten_web", "gioi_tinh_web", "ngay_sinh_web", "ghi_chu"];
  const lines = [fields.join(",")];
  for (const row of rows) {
    lines.push(keys.map((key) => `"${String(row[key] ?? "").replace(/"/g, '""')}"`).join(","));
  }
  return lines.join("\r\n");
}

function download(rows) {
  const blob = new Blob(["\uFEFF" + csvText(rows)], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "ket_qua_kiem_tra.csv";
  document.body.append(link);
  link.click();
  link.remove();
}

async function finish(job, note) {
  if (job.closed) return;
  job.running = false;
  removeShield();
  await chrome.storage.local.set({ kskJob: job });
  lastResults = job.results.slice();
  const panel = ensureOverlay();
  const downloadButton = panel.querySelector("#ksk-download");
  downloadButton.hidden = lastResults.length === 0;
  panel.querySelector("#ksk-pause").hidden = true;
  panel.querySelector("#ksk-stop").hidden = true;
  panel.querySelector("#ksk-title").textContent = "Đã kiểm tra xong";
  panel.querySelector("#ksk-status").textContent = `${note} ${job.results.length} dòng.`;
  if (job.results.length) {
    const response = await chrome.runtime.sendMessage({ type: "save-results", rows: job.results });
    panel.querySelector("#ksk-status").textContent += response && response.ok
      ? " Đã gửi về máy cục bộ. Bấm Tải CSV nếu muốn lưu file."
      : " Chưa gửi được về máy cục bộ. Bấm Tải CSV để lưu file.";
  }
  runningJob = null;
}

async function run(job) {
  if (runningJob && runningJob !== job) return;
  runningJob = job;
  showProgress(job);
  try {
    const patient = searchField('input[name="filter"]');
    const button = searchButton();
    if (!patient || !button) {
      throw new Error("Hãy đứng ở trang Danh sách khám sức khỏe. Không thấy ô Thông tin bệnh nhân hoặc nút Tìm kiếm.");
    }
    while (job.index < job.people.length) {
      while (job.paused && !job.stopped && !job.closed) {
        showProgress(job);
        await sleep(300);
      }
      if (job.closed) return;
      if (job.stopped) {
        await finish(job, "Đã dừng sau");
        return;
      }
      const person = job.people[job.index];
      showProgress(job);
      await typeText(patient, person.cccd);
      if (!patient.value.includes(person.cccd)) throw new Error("Không ghi được CCCD vào ô Thông tin bệnh nhân.");
      button.click();
      await waitForRows(job);
      if (job.closed) return;
      job.results.push(compare(person, bestTable()));
      job.index += 1;
      await chrome.storage.local.set({ kskJob: job });
    }
    await finish(job, "Xong");
  } catch (error) {
    if (job.closed) return;
    const failed = job.people[job.index];
    if (failed) {
      job.results.push({
        id: failed.id, anh: failed.anh, stt: failed.stt, ho_ten: failed.ho_ten, ngay_sinh: failed.ngay_sinh,
        gioi_tinh: failed.gioi_tinh, cccd: failed.cccd, dia_chi: failed.dia_chi,
        co_tren_he_thong: "Khong_ro", khop_ho_ten: "Khong_kiem_tra", khop_gioi_tinh: "Khong_kiem_tra",
        khop_ngay_sinh: "Khong_kiem_tra", ket_luan: "LOI_KIEM_TRA", ho_ten_web: "", gioi_tinh_web: "",
        ngay_sinh_web: "", ghi_chu: error.message,
      });
    }
    await finish(job, error.message + " · đã ghi");
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "start") return;
  const job = {
    people: message.people,
    index: 0,
    results: [],
    tu: message.tu,
    den: message.den,
    running: true,
    paused: false,
    stopped: false,
  };
  chrome.storage.local.set({ kskJob: job }).then(() => run(job));
  sendResponse({ ok: true });
});

chrome.storage.local.get("kskJob", ({ kskJob }) => {
  if (!kskJob || !kskJob.running || kskJob.closed) return;
  run(kskJob);
});
