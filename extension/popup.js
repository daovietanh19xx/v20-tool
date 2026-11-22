const localBox = document.querySelector("#local");
const csvBox = document.querySelector("#csvBox");
const message = document.querySelector("#message");
let localReady = false;

function say(text) {
  message.textContent = text;
}

async function loadLocal() {
  try {
    const response = await fetch("http://127.0.0.1:8765/api/trang-thai");
    if (!response.ok) throw new Error("offline");
    const data = await response.json();
    const select = document.querySelector("#anh");
    select.innerHTML = "";
    for (const image of data.anh || []) {
      const option = document.createElement("option");
      option.value = image.ten;
      option.textContent = image.ten + (image.da_doc ? ` · ${image.so_dong} dòng` : " · chưa đọc");
      select.appendChild(option);
    }
    localReady = true;
  } catch (_error) {
    localBox.classList.add("hidden");
    csvBox.classList.remove("hidden");
  }
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  const source = text.replace(/^\uFEFF/, "");
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (quoted) {
      if (char === '"') {
        if (source[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else quoted = false;
      } else cell += char;
    } else if (char === '"') quoted = true;
    else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") cell += char;
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  if (!rows.length) return [];
  const header = rows[0].map((item) => item.trim());
  return rows.slice(1).filter((item) => item.some((value) => value.trim())).map((item) => {
    const record = {};
    header.forEach((key, index) => { record[key] = (item[index] || "").trim(); });
    return record;
  });
}

function peopleFromCsv(records) {
  return records.map((record) => ({
    id: record.id || "",
    anh: record.Anh || record.anh || "",
    stt: record.STT || record.stt || "",
    ho_ten: record.Ho_ten || record.ho_ten || "",
    ngay_sinh: record.Ngay_sinh || record.ngay_sinh || "",
    gioi_tinh: record.Gioi_tinh || record.gioi_tinh || "",
    cccd: (record.CCCD || record.cccd || "").replace(/\D/g, ""),
    dia_chi: record.Dia_chi || record.dia_chi || "",
    khong_chac_chan: record.Khong_chac_chan || record.khong_chac_chan || "",
    xac_nhan: record.Da_xac_nhan || record.xac_nhan || "",
  })).filter((person) => person.cccd.length === 12);
}

async function peopleFromLocal() {
  const name = document.querySelector("#anh").value;
  const response = await fetch("http://127.0.0.1:8765/api/extension/danh-sach?anh=" + encodeURIComponent(name));
  const data = await response.json();
  return data.rows || [];
}

document.querySelector("#go").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url || !tab.url.startsWith("https://v20.ytecoso.vn/")) {
    say("Hãy mở https://v20.ytecoso.vn/ rồi bấm lại.");
    return;
  }
  let people = [];
  if (localReady) people = await peopleFromLocal();
  else {
    const file = document.querySelector("#csv").files[0];
    if (!file) {
      say("Chọn file CSV.");
      return;
    }
    people = peopleFromCsv(parseCsv(await file.text()));
  }
  if (!people.length) {
    say("Không có dòng đủ CCCD để kiểm tra. Với máy cục bộ, hãy xác nhận dòng trên giao diện trước.");
    return;
  }
  await chrome.tabs.sendMessage(tab.id, {
    type: "start",
    people,
  });
  say(`Đã gửi ${people.length} dòng. Xem lớp phủ trên trang.`);
  window.close();
};

loadLocal();
