"""Tra cứu danh sách khám sức khỏe. Chỉ tìm kiếm, không thêm, sửa, xóa."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from ksk_tool.ocr_bang import canonical_gender, format_date, name_key, parse_date

ROOT = Path(__file__).resolve().parents[1]
HOME_URL = "https://v20.ytecoso.vn/"
FORBIDDEN = re.compile(
    r"thêm|tạo mới|sửa|xóa|xoá|lưu|cập nhật|duyệt|delete|update|save|edit",
    re.IGNORECASE,
)


@dataclass
class CheckResult:
    co_tren_he_thong: str
    khop_ho_ten: str
    khop_gioi_tinh: str
    khop_ngay_sinh: str
    ket_luan: str
    ho_ten_web: str
    gioi_tinh_web: str
    ngay_sinh_web: str
    ghi_chu: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def load_account() -> dict:
    path = ROOT / "config.local.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("username") or not data.get("password"):
        raise RuntimeError("Thiếu tài khoản trong config.local.json")
    return data


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, target)
        return
    except OSError:
        pass
    completed = subprocess.run(
        ["esentutl", "/y", str(source), "/d", str(target), "/o"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not target.exists():
        detail = (completed.stderr or completed.stdout or "").strip()
        raise OSError(f"Không sao chép được {source.name}. {detail[:180]}")


def _copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    for path in source.rglob("*"):
        if not path.is_file() or path.name in {"LOCK", "lockfile"}:
            continue
        _copy_file(path, target / path.relative_to(source))


def prepare_profile_copy(destination: Path, profile_name: str) -> None:
    user_data = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data"
    local_state = user_data / "Local State"
    profile = user_data / profile_name
    if not local_state.exists() or not profile.exists():
        raise FileNotFoundError("Không thấy hồ sơ Chrome trong Local AppData.")
    _copy_file(local_state, destination / "Local State")
    for name in ("Preferences", "Secure Preferences"):
        source = profile / name
        if source.exists():
            _copy_file(source, destination / "Default" / name)
    for folder in ("Network", "Local Storage", "Session Storage"):
        _copy_tree(profile / folder, destination / "Default" / folder)
    indexed = profile / "IndexedDB"
    if indexed.exists():
        for child in indexed.iterdir():
            if child.is_dir() and re.search(r"ytecoso|sso", child.name, re.IGNORECASE):
                _copy_tree(child, destination / "Default" / "IndexedDB" / child.name)


def _driver(profile_dir: Path) -> webdriver.Chrome:
    options = Options()
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-session-crashed-bubble")
    options.add_argument("--hide-crash-restore-bubble")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=options)


def _click_text(driver, pattern: str) -> None:
    compiled = re.compile(pattern, re.IGNORECASE)
    elements = driver.find_elements(By.XPATH, "//a | //button | //span | //div | //li | //p")
    for element in elements:
        try:
            text = (element.text or "").strip()
        except Exception:
            continue
        if not text or len(text) > 80 or not compiled.search(text):
            continue
        if FORBIDDEN.search(text):
            continue
        if not element.is_displayed():
            continue
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        element.click()
        return
    raise RuntimeError(f"Không thấy mục menu: {pattern}")


def _visible_inputs(driver):
    return [item for item in driver.find_elements(By.CSS_SELECTOR, "input, textarea") if item.is_displayed()]


def _fill(element, value: str) -> None:
    element.click()
    element.clear()
    element.send_keys(value)


def _login_if_needed(driver, account: dict) -> None:
    driver.get(HOME_URL)
    WebDriverWait(driver, 30).until(lambda d: d.execute_script("return document.readyState") == "complete")
    driver.implicitly_wait(0)
    if "sso.ytecoso.vn" not in driver.current_url and "đăng nhập" not in driver.page_source.lower():
        return
    username = None
    password = None
    for field in driver.find_elements(By.CSS_SELECTOR, "input"):
        name = ((field.get_attribute("name") or "") + " " + (field.get_attribute("id") or "")).lower()
        kind = (field.get_attribute("type") or "").lower()
        if kind == "password" or "pass" in name:
            password = field
        elif kind in {"text", "email", ""} and any(token in name for token in ("user", "ten", "login", "email")):
            username = field
    if username is None or password is None:
        texts = [field for field in driver.find_elements(By.CSS_SELECTOR, "input") if (field.get_attribute("type") or "") != "hidden"]
        visible = [field for field in texts if field.is_displayed()]
        if len(visible) >= 2:
            username, password = visible[0], visible[1]
    if username is None or password is None:
        raise RuntimeError("Trang đăng nhập không có ô tài khoản.")
    _fill(username, account["username"])
    _fill(password, account["password"])
    buttons = driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit']")
    clicked = False
    for button in buttons:
        label = (button.text or button.get_attribute("value") or "").strip()
        if re.search(r"đăng nhập", label, re.IGNORECASE):
            button.click()
            clicked = True
            break
    if not clicked:
        password.submit()
    WebDriverWait(driver, 40).until(lambda d: "v20.ytecoso.vn" in d.current_url and "sso.ytecoso" not in d.current_url)
    if re.search(r"otp|xác thực hai", driver.page_source, re.IGNORECASE):
        raise RuntimeError("Trang yêu cầu OTP. Hãy đăng nhập sẵn trên Chrome rồi chạy lại.")


def _open_list(driver) -> None:
    driver.get(HOME_URL)
    WebDriverWait(driver, 30).until(lambda d: "v20.ytecoso.vn" in d.current_url)
    _click_text(driver, r"Khám\s*Chữa\s*Bệnh")
    driver.implicitly_wait(1)
    try:
        _click_text(driver, r"Khám\s*Chữa\s*Bệnh\s*Định\s*Kỳ")
    except RuntimeError:
        pass
    _click_text(driver, r"Danh\s*Sách\s*Khám\s*Sức\s*Khỏe")
    WebDriverWait(driver, 20).until(lambda d: "khám" in d.page_source.lower())


def _set_dates(driver, start: str, end: str) -> None:
    start_text = format_date(start)
    end_text = format_date(end)
    candidates = []
    for field in _visible_inputs(driver):
        blob = " ".join(
            [
                field.get_attribute("placeholder") or "",
                field.get_attribute("name") or "",
                field.get_attribute("aria-label") or "",
            ]
        ).lower()
        if any(token in blob for token in ("ngày", "ngay", "date", "thời", "thoi", "dd/mm", "yyyy")):
            candidates.append(field)
    if len(candidates) < 2:
        candidates = [field for field in _visible_inputs(driver) if (field.get_attribute("type") or "text") in {"text", "search", ""}][:2]
    if len(candidates) < 2:
        raise RuntimeError("Không thấy ô từ ngày và đến ngày.")
    _fill(candidates[0], start_text)
    _fill(candidates[1], end_text)


def _patient_box(driver):
    for field in _visible_inputs(driver):
        blob = " ".join(
            [
                field.get_attribute("placeholder") or "",
                field.get_attribute("name") or "",
                field.get_attribute("aria-label") or "",
            ]
        ).lower()
        if "bệnh nhân" in blob or "benh nhan" in blob:
            return field
    labels = driver.find_elements(By.XPATH, "//*[contains(., 'Thông tin bệnh nhân')]")
    for label in labels:
        if not label.is_displayed():
            continue
        following = label.find_elements(By.XPATH, "./following::input[1]")
        if following and following[0].is_displayed():
            return following[0]
    raise RuntimeError("Không thấy ô Thông tin bệnh nhân.")


def _click_search(driver) -> None:
    for element in driver.find_elements(By.XPATH, "//button | //a | //input[@type='button'] | //input[@type='submit']"):
        label = (element.text or element.get_attribute("value") or "").strip()
        if re.fullmatch(r"Tìm\s*kiếm", label, flags=re.IGNORECASE) and element.is_displayed():
            if FORBIDDEN.search(label):
                continue
            element.click()
            return
    raise RuntimeError("Không thấy nút Tìm kiếm.")


def _table_rows(driver) -> list[list[str]]:
    tables = driver.find_elements(By.CSS_SELECTOR, "table")
    best: list[list[str]] = []
    for table in tables:
        if not table.is_displayed():
            continue
        rows = []
        for tr in table.find_elements(By.CSS_SELECTOR, "tr"):
            cells = [cell.text.strip() for cell in tr.find_elements(By.CSS_SELECTOR, "th, td")]
            if any(cells):
                rows.append(cells)
        blob = " ".join(" ".join(row) for row in rows).lower()
        if "cccd" in blob or "họ" in blob or "giới" in blob:
            if len(rows) > len(best):
                best = rows
    return best


def _header_map(header: list[str]) -> dict[str, int]:
    folded = [name_key(cell) for cell in header]
    found = {}
    for key, needles in {
        "ho_ten": ("HO VA TEN", "HO TEN", "HỌ VÀ TÊN"),
        "gioi_tinh": ("GIOI TINH", "GIỚI TÍNH"),
        "ngay_sinh": ("NGAY SINH", "NGÀY SINH", "NAM SINH"),
        "cccd": ("CCCD", "CMND", "CAN CUOC", "CĂN CƯỚC", "GIAY TO"),
    }.items():
        for index, cell in enumerate(folded):
            if any(name_key(needle) in cell for needle in needles):
                found[key] = index
                break
    return found


def compare_person(person, rows: list[list[str]], page_text: str) -> CheckResult:
    if not rows:
        if any(marker in page_text.lower() for marker in ("không có dữ liệu", "không tìm thấy", "no data")) or person.cccd not in page_text:
            return CheckResult("Khong", "Khong_co_du_lieu", "Khong_co_du_lieu", "Khong_co_du_lieu", "KHONG_CO_TREN_HE_THONG", "", "", "", "Không có dòng khám sức khỏe khớp CCCD.")
        return CheckResult("Khong_ro", "Khong_kiem_tra", "Khong_kiem_tra", "Khong_kiem_tra", "LOI_KIEM_TRA", "", "", "", "Không đọc được bảng kết quả.")
    mapping = _header_map(rows[0])
    body = rows[1:] if mapping else rows
    exact = []
    for row in body:
        blob = " ".join(row)
        if person.cccd in re.sub(r"\s+", "", blob) or person.cccd in blob:
            exact.append(row)
    if not exact:
        if len(body) >= 15 and person.cccd not in page_text:
            return CheckResult("Khong_ro", "Khong_kiem_tra", "Khong_kiem_tra", "Khong_kiem_tra", "LOI_KIEM_TRA", "", "", "", "Bộ lọc chưa áp dụng, bảng vẫn còn nhiều dòng khác.")
        return CheckResult("Khong", "Khong_co_du_lieu", "Khong_co_du_lieu", "Khong_co_du_lieu", "KHONG_CO_TREN_HE_THONG", "", "", "", "Không có dòng trùng CCCD.")

    def cell(row, key):
        index = mapping.get(key, -1)
        return row[index] if 0 <= index < len(row) else ""

    sample = exact[0]
    web_name = cell(sample, "ho_ten")
    web_gender = cell(sample, "gioi_tinh")
    web_dob = cell(sample, "ngay_sinh")
    if not web_name or not web_gender or not web_dob:
        # Bảng không có tiêu đề chuẩn: tìm trong cả dòng.
        for part in sample:
            if not web_name and len(name_key(part).split()) >= 2 and not re.search(r"\d{4}", part):
                web_name = part
            if not web_gender and canonical_gender(part):
                web_gender = part
            if not web_dob and parse_date(part):
                web_dob = part
    name_ok = bool(web_name) and name_key(web_name) == name_key(person.ho_ten)
    gender_ok = bool(web_gender) and canonical_gender(web_gender) == canonical_gender(person.gioi_tinh)
    dob_ok = bool(web_dob) and parse_date(web_dob) == parse_date(person.ngay_sinh)
    if name_ok and gender_ok and dob_ok:
        conclusion, note = "DUNG_HET", f"Khớp {len(exact)} dòng."
    else:
        conclusion = "SAI_THONG_TIN"
        note = f"web: {web_name} | {web_gender} | {web_dob}"
    return CheckResult(
        "Co",
        "Dung" if name_ok else "Sai",
        "Dung" if gender_ok else "Sai",
        "Dung" if dob_ok else "Sai",
        conclusion,
        name_key(web_name),
        canonical_gender(web_gender) or web_gender,
        format_date(web_dob) if parse_date(web_dob) else web_dob,
        note,
    )


def skipped(reason: str) -> CheckResult:
    return CheckResult("Khong_kiem_tra", "Khong_kiem_tra", "Khong_kiem_tra", "Khong_kiem_tra", "CHUA_KIEM_TRA_OCR_KHONG_CHAC", "", "", "", reason)


def run_checks(people: list, start: str, end: str, progress=None) -> list[CheckResult]:
    account = load_account()
    profile_root = Path(tempfile.mkdtemp(prefix="ksk-chrome-"))
    driver = None
    results: list[CheckResult] = []
    try:
        try:
            prepare_profile_copy(profile_root, account.get("chrome_profile") or "Default")
            if progress:
                progress("Đã lấy phiên Chrome trong AppData. Nếu phiên hết hạn sẽ đăng nhập bằng tài khoản đã lưu.")
        except OSError as error:
            shutil.rmtree(profile_root, ignore_errors=True)
            profile_root = Path(tempfile.mkdtemp(prefix="ksk-chrome-"))
            if progress:
                progress("Chrome đang mở nên không copy được cookie. Sẽ đăng nhập bằng tài khoản đã lưu trong config.local.json.")
            _ = error
        driver = _driver(profile_root)
        driver.set_window_size(1440, 900)
        _login_if_needed(driver, account)
        _open_list(driver)
        _set_dates(driver, start, end)
        for person in people:
            if progress:
                progress(f"Đang tra {person.ho_ten}")
            try:
                box = _patient_box(driver)
                _fill(box, person.cccd)
                typed = re.sub(r"\s+", "", box.get_attribute("value") or "")
                if person.cccd not in typed:
                    raise RuntimeError("Ô bệnh nhân không nhận đúng CCCD.")
                _click_search(driver)
                WebDriverWait(driver, 20).until(lambda d: person.cccd in d.page_source or "không có" in d.page_source.lower())
                rows = _table_rows(driver)
                results.append(compare_person(person, rows, driver.page_source))
            except (TimeoutException, RuntimeError, Exception) as error:
                debug = ROOT / "output" / "debug_trang.html"
                debug.parent.mkdir(parents=True, exist_ok=True)
                try:
                    debug.write_text(driver.page_source, encoding="utf-8")
                    driver.save_screenshot(str(ROOT / "output" / "debug_trang.png"))
                except Exception:
                    pass
                results.append(CheckResult("Khong_ro", "Khong_kiem_tra", "Khong_kiem_tra", "Khong_kiem_tra", "LOI_KIEM_TRA", "", "", "", str(error)))
            if progress:
                progress(f"{person.ho_ten}: {results[-1].ket_luan}")
    finally:
        if driver is not None:
            driver.quit()
        shutil.rmtree(profile_root, ignore_errors=True)
    return results
