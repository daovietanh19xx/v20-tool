"""Giao diện cục bộ để sửa dòng OCR rồi tra cứu, không ghi dữ liệu lên trang y tế."""

from __future__ import annotations

import csv
import json
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from ksk_tool.kiem_tra_web import load_account, run_checks, skipped
from ksk_tool.llm_doc import read_table_with_llm
from ksk_tool.ocr_bang import (
    canonical_gender,
    correct_row_gender,
    format_date,
    parse_date,
    read_table_image,
)

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}

ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "anh_can_check"
OUTPUT = ROOT / "output"
STATE_PATH = OUTPUT / "bang.json"
RESULT_CSV = OUTPUT / "ket_qua_kiem_tra.csv"

app = Flask(__name__, template_folder=str(ROOT / "templates"))
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
_lock = threading.Lock()
_state = {
    "rows": [],
    "log": [],
    "busy": False,
    "error": "",
    "tu_ngay": "01/06/2026",
    "den_ngay": "21/11/2026",
}


def _log(message: str) -> None:
    with _lock:
        _state["log"].append(message)
        del _state["log"][:-40]


def _save() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(_state["rows"], ensure_ascii=False, indent=2), encoding="utf-8")
    _write_image_csvs()
    _write_result_csv()


def _write_image_csvs() -> None:
    folder = OUTPUT / "csv"
    folder.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[dict]] = {}
    for row in _state["rows"]:
        groups.setdefault(row["anh"], []).append(row)
    for name, rows in groups.items():
        path = folder / f"{Path(name).stem}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["STT", "Ho_ten", "Ngay_sinh", "Gioi_tinh", "CCCD", "Dia_chi", "Khong_chac_chan", "Ly_do"],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "STT": row["stt"],
                        "Ho_ten": row["ho_ten"],
                        "Ngay_sinh": row["ngay_sinh"],
                        "Gioi_tinh": row["gioi_tinh"],
                        "CCCD": row["cccd"],
                        "Dia_chi": row["dia_chi"],
                        "Khong_chac_chan": row["khong_chac_chan"],
                        "Ly_do": row["ly_do"],
                    }
                )


def _write_result_csv() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "Anh", "STT", "Ho_ten", "Ngay_sinh", "Gioi_tinh", "CCCD", "Dia_chi",
        "Khong_chac_chan", "Da_xac_nhan", "Co_tren_he_thong", "Khop_ho_ten",
        "Khop_gioi_tinh", "Khop_ngay_sinh", "Ket_luan", "Ho_ten_web",
        "Gioi_tinh_web", "Ngay_sinh_web", "Ghi_chu",
    ]
    with RESULT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in _state["rows"]:
            writer.writerow(
                {
                    "Anh": row["anh"],
                    "STT": row["stt"],
                    "Ho_ten": row["ho_ten"],
                    "Ngay_sinh": row["ngay_sinh"],
                    "Gioi_tinh": row["gioi_tinh"],
                    "CCCD": row["cccd"],
                    "Dia_chi": row["dia_chi"],
                    "Khong_chac_chan": row["khong_chac_chan"],
                    "Da_xac_nhan": row.get("xac_nhan", 0),
                    "Co_tren_he_thong": row.get("co_tren_he_thong", ""),
                    "Khop_ho_ten": row.get("khop_ho_ten", ""),
                    "Khop_gioi_tinh": row.get("khop_gioi_tinh", ""),
                    "Khop_ngay_sinh": row.get("khop_ngay_sinh", ""),
                    "Ket_luan": row.get("ket_luan", ""),
                    "Ho_ten_web": row.get("ho_ten_web", ""),
                    "Gioi_tinh_web": row.get("gioi_tinh_web", ""),
                    "Ngay_sinh_web": row.get("ngay_sinh_web", ""),
                    "Ghi_chu": row.get("ghi_chu", ""),
                }
            )


def _load_dates() -> None:
    try:
        account = load_account()
        _state["tu_ngay"] = account.get("tu_ngay") or _state["tu_ngay"]
        _state["den_ngay"] = account.get("den_ngay") or _state["den_ngay"]
    except Exception:
        pass
    if STATE_PATH.exists():
        _state["rows"] = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if any(correct_row_gender(row) for row in _state["rows"]):
            _save()


def _apply_edits(payload: list[dict]) -> None:
    by_id = {row["id"]: row for row in _state["rows"]}
    for item in payload:
        current = by_id.get(item.get("id"))
        if current is None:
            continue
        for key in ("stt", "ho_ten", "ngay_sinh", "gioi_tinh", "cccd", "dia_chi"):
            if key in item:
                current[key] = str(item[key] or "").strip()
        current["gioi_tinh"] = canonical_gender(current["gioi_tinh"]) or current["gioi_tinh"]
        if parse_date(current["ngay_sinh"]):
            current["ngay_sinh"] = format_date(current["ngay_sinh"])
        current["xac_nhan"] = 1 if item.get("xac_nhan") else 0
        current["khong_chac_chan"] = 0 if current["xac_nhan"] else current["khong_chac_chan"]


def _valid(row: dict) -> str:
    if not row.get("ho_ten") or len(str(row["ho_ten"]).split()) < 2:
        return "Họ tên chưa đủ"
    if parse_date(row.get("ngay_sinh", "")) is None:
        return "Ngày sinh không hợp lệ"
    if canonical_gender(row.get("gioi_tinh", "")) not in {"Nam", "Nữ"}:
        return "Giới tính phải là Nam hoặc Nữ"
    if len(str(row.get("cccd", ""))) != 12 or not str(row["cccd"]).isdigit():
        return "CCCD phải đủ 12 số"
    return ""


def _image_files() -> list[Path]:
    if not IMAGE_DIR.exists():
        return []
    return sorted(path for path in IMAGE_DIR.iterdir() if path.suffix.lower() in IMAGE_TYPES)


def _image_status() -> list[dict]:
    counts: dict[str, int] = {}
    for row in _state["rows"]:
        counts[row["anh"]] = counts.get(row["anh"], 0) + 1
    return [
        {"ten": path.name, "da_doc": path.name in counts, "so_dong": counts.get(path.name, 0)}
        for path in _image_files()
    ]


def _public_row(row: dict) -> dict:
    return {
        "id": row.get("id", ""),
        "anh": row.get("anh", ""),
        "stt": row.get("stt", ""),
        "ho_ten": row.get("ho_ten", ""),
        "ngay_sinh": row.get("ngay_sinh", ""),
        "gioi_tinh": row.get("gioi_tinh", ""),
        "cccd": row.get("cccd", ""),
        "dia_chi": row.get("dia_chi", ""),
    }


def _read_images(names: list[str], engine: str, api_base: str, api_key: str, model: str) -> None:
    secret = api_key
    try:
        chosen = {Path(name).name for name in names}
        images = [path for path in _image_files() if not chosen or path.name in chosen]
        if not images:
            raise RuntimeError("Chưa có ảnh để đọc. Hãy tải ảnh lên hoặc chọn ảnh đã có.")
        total = 0
        uncertain = 0
        for image in images:
            _log(f"Đang đọc {image.name} bằng {'API' if engine == 'llm' else 'OCR máy'}")
            if engine == "llm":
                people = read_table_with_llm(image, api_base, secret, model)
            else:
                people = read_table_image(image, OUTPUT / "debug")
            rows = [person.as_dict() for person in people]
            with _lock:
                _state["rows"] = [row for row in _state["rows"] if row["anh"] != image.name] + rows
                _state["error"] = ""
                _save()
            total += len(rows)
            uncertain += sum(1 for row in rows if row["khong_chac_chan"])
        _log(f"Đọc xong {total} dòng, {uncertain} dòng cần xem lại.")
    except Exception as error:
        message = str(error)
        if secret:
            message = message.replace(secret, "***")
        with _lock:
            _state["error"] = message
        _log(f"Lỗi đọc ảnh: {message}")
    finally:
        secret = ""
        with _lock:
            _state["busy"] = False


def _check(start: str, end: str) -> None:
    try:
        with _lock:
            selected = [row for row in _state["rows"] if row.get("xac_nhan")]
        if not selected:
            raise RuntimeError("Chưa có dòng nào được xác nhận để kiểm tra.")
        problems = [f"{row['ho_ten'] or row['stt']}: {_valid(row)}" for row in selected if _valid(row)]
        if problems:
            raise RuntimeError("Sửa các dòng này trước khi kiểm tra: " + "; ".join(problems[:6]))

        class Person:
            def __init__(self, row):
                self.ho_ten = row["ho_ten"]
                self.ngay_sinh = row["ngay_sinh"]
                self.gioi_tinh = row["gioi_tinh"]
                self.cccd = row["cccd"]
                self.row = row

        people = [Person(row) for row in selected]
        results = run_checks(people, start, end, progress=_log)
        by_cccd = {person.cccd: result for person, result in zip(people, results)}
        with _lock:
            for row in _state["rows"]:
                if not row.get("xac_nhan"):
                    result = skipped(row.get("ly_do") or "Chưa xác nhận")
                else:
                    result = by_cccd.get(row["cccd"])
                if result is None:
                    continue
                row.update(result.as_dict())
            _state["error"] = ""
            _save()
        _log("Kiểm tra xong. File ket_qua_kiem_tra.csv đã được ghi.")
    except Exception as error:
        with _lock:
            _state["error"] = str(error)
        _log(f"Lỗi kiểm tra: {error}")
    finally:
        with _lock:
            _state["busy"] = False


def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


def _start(target, *args) -> tuple[bool, str]:
    with _lock:
        if _state["busy"]:
            return False, "Hệ thống đang bận."
        _state["busy"] = True
        _state["error"] = ""
    threading.Thread(target=target, args=args, daemon=True).start()
    return True, ""


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/trang-thai")
def status():
    with _lock:
        uncertain = sum(1 for row in _state["rows"] if row.get("khong_chac_chan") and not row.get("xac_nhan"))
        return jsonify(
            {
                "busy": _state["busy"],
                "error": _state["error"],
                "log": _state["log"],
                "tu_ngay": _state["tu_ngay"],
                "den_ngay": _state["den_ngay"],
                "rows": _state["rows"],
                "tong": len(_state["rows"]),
                "can_sua": uncertain,
                "anh": _image_status(),
            }
        )


@app.post("/api/anh")
def upload_images():
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for item in request.files.getlist("anh"):
        name = Path(item.filename or "").name
        if Path(name).suffix.lower() not in IMAGE_TYPES:
            continue
        item.save(IMAGE_DIR / name)
        saved.append(name)
    if not saved:
        return jsonify({"ok": False, "message": "Chọn file JPG, PNG hoặc WEBP."}), 400
    return jsonify({"ok": True, "tep": saved})


@app.post("/api/doc")
def read_photos():
    payload = request.get_json(silent=True) or {}
    engine = "llm" if payload.get("engine") == "llm" else "local"
    api_base = str(payload.get("api_base") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    model = str(payload.get("model") or "").strip()
    if engine == "llm" and (not api_base or not api_key or not model):
        return jsonify({"ok": False, "message": "Nhập địa chỉ API, tên model và khóa. Khóa không được lưu."}), 400
    names = [Path(str(name)).name for name in (payload.get("anh") or [])]
    ok, message = _start(_read_images, names, engine, api_base, api_key, model)
    if not ok:
        return jsonify({"ok": False, "message": message}), 409
    return jsonify({"ok": True})


@app.route("/api/extension/danh-sach", methods=["GET", "OPTIONS"])
def extension_rows():
    if request.method == "OPTIONS":
        return _cors(jsonify({}))
    image_name = Path(request.args.get("anh", "")).name
    with _lock:
        chosen = []
        for row in _state["rows"]:
            if image_name and row.get("anh") != image_name:
                continue
            if not row.get("xac_nhan") or _valid(row):
                continue
            chosen.append(_public_row(row))
        payload = {
            "ok": True,
            "rows": chosen,
            "tu_ngay": _state["tu_ngay"],
            "den_ngay": _state["den_ngay"],
        }
    return _cors(jsonify(payload))


@app.route("/api/extension/ket-qua", methods=["POST", "OPTIONS"])
def extension_results():
    if request.method == "OPTIONS":
        return _cors(jsonify({}))
    payload = request.get_json(silent=True) or {}
    incoming = payload.get("rows") or []
    fields = (
        "co_tren_he_thong", "khop_ho_ten", "khop_gioi_tinh", "khop_ngay_sinh",
        "ket_luan", "ho_ten_web", "gioi_tinh_web", "ngay_sinh_web", "ghi_chu",
    )
    with _lock:
        by_id = {row.get("id"): row for row in _state["rows"]}
        by_cccd = {row.get("cccd"): row for row in _state["rows"]}
        updated = 0
        for item in incoming:
            target = by_id.get(item.get("id")) or by_cccd.get(str(item.get("cccd", "")))
            if target is None:
                continue
            for key in fields:
                if key in item:
                    target[key] = item[key]
            updated += 1
        _save()
    return _cors(jsonify({"ok": True, "cap_nhat": updated}))


@app.post("/api/luu")
def save_rows():
    payload = request.get_json(silent=True) or {}
    with _lock:
        if _state["busy"]:
            return jsonify({"ok": False, "message": "Hệ thống đang bận."}), 409
        _apply_edits(payload.get("rows") or [])
        if payload.get("tu_ngay"):
            _state["tu_ngay"] = payload["tu_ngay"]
        if payload.get("den_ngay"):
            _state["den_ngay"] = payload["den_ngay"]
        _save()
    return jsonify({"ok": True})


@app.post("/api/kiem-tra")
def check_rows():
    payload = request.get_json(silent=True) or {}
    with _lock:
        if _state["busy"]:
            return jsonify({"ok": False, "message": "Hệ thống đang bận."}), 409
        _apply_edits(payload.get("rows") or [])
        start = payload.get("tu_ngay") or _state["tu_ngay"]
        end = payload.get("den_ngay") or _state["den_ngay"]
        _state["tu_ngay"] = start
        _state["den_ngay"] = end
        _save()
        _state["busy"] = True
    threading.Thread(target=_check, args=(start, end), daemon=True).start()
    return jsonify({"ok": True})


@app.get("/anh-dong/<name>")
def row_image(name: str):
    safe = Path(name).name
    path = OUTPUT / "dong" / safe
    if not path.exists():
        return "Không có ảnh dòng", 404
    return send_file(path)


@app.get("/ket-qua.csv")
def download_csv():
    if not RESULT_CSV.exists():
        _write_result_csv()
    return send_file(RESULT_CSV, as_attachment=True, download_name="ket_qua_kiem_tra.csv")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _load_dates()
    app.run(host="0.0.0.0", port=8765, debug=False, threaded=True)
