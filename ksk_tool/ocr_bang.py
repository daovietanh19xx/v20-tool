"""Đọc bảng giấy thành từng người.

Lưới được dò từ đường kẻ. Mỗi ô đọc bằng Tesseract trên CPU, hai kiểu ảnh
khác nhau. Hai lần đọc lệch nhau, hoặc ngày sinh/CCCD/giới tính không hợp lệ,
thì dòng được gắn cờ để sửa trên giao diện. Không tự sửa cho khớp CCCD.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
TESSDATA = ROOT / "tessdata"
TESSERACT_EXE = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
KINDS = ("stt", "ho_ten", "ngay_sinh", "gioi_tinh", "cccd", "dia_chi")


@dataclass
class PersonRow:
    anh: str
    stt: str
    ho_ten: str
    ngay_sinh: str
    gioi_tinh: str
    cccd: str
    dia_chi: str
    khong_chac_chan: int
    ly_do: str
    xac_nhan: int = 0
    dong_tho: str = ""
    anh_dong: str = ""
    row_id: str = ""
    chi_tiet: dict = field(default_factory=dict)
    do_tin_cay: int = 0

    def as_csv_row(self) -> dict:
        return {
            "STT": self.stt,
            "Ho_ten": self.ho_ten,
            "Ngay_sinh": self.ngay_sinh,
            "Gioi_tinh": self.gioi_tinh,
            "CCCD": self.cccd,
            "Dia_chi": self.dia_chi,
            "Khong_chac_chan": self.khong_chac_chan,
            "Ly_do": self.ly_do,
        }

    def as_dict(self) -> dict:
        return {
            "id": self.row_id,
            "anh": self.anh,
            "stt": self.stt,
            "ho_ten": self.ho_ten,
            "ngay_sinh": self.ngay_sinh,
            "gioi_tinh": self.gioi_tinh,
            "cccd": self.cccd,
            "dia_chi": self.dia_chi,
            "khong_chac_chan": self.khong_chac_chan,
            "xac_nhan": self.xac_nhan,
            "ly_do": self.ly_do,
            "dong_tho": self.dong_tho,
            "anh_dong": self.anh_dong,
            "do_tin_cay": self.do_tin_cay,
        }


def _configure_tesseract() -> None:
    if TESSERACT_EXE.exists():
        pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
    if not (TESSDATA / "vie.traineddata").exists():
        raise FileNotFoundError(f"Thiếu file ngôn ngữ: {TESSDATA / 'vie.traineddata'}")
    os.environ["TESSDATA_PREFIX"] = str(TESSDATA) + os.sep


def load_gray(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("L")
        return np.array(image)


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("Đ", "D").replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def canonical_gender(text: str) -> str:
    folded = re.sub(r"[^a-z]", "", strip_accents(text).lower())
    if folded in {"nam", "male"}:
        return "Nam"
    if folded in {"nu", "female"}:
        return "Nữ"
    return ""


def name_key(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").upper()
    cleaned = "".join(ch if (ch.isalpha() or ch.isspace()) else " " for ch in text)
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_date(text: str) -> datetime | None:
    raw = re.sub(r"\s+", "", text or "").replace(".", "/").replace("-", "/")
    raw = re.sub(r"[^0-9/]", "", raw)
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def format_date(text: str) -> str:
    parsed = parse_date(text)
    if parsed is None:
        return re.sub(r"\s+", "", text or "")
    return parsed.strftime("%d/%m/%Y")


def _cccd_year_gender(number: str) -> tuple[int, str] | None:
    if re.fullmatch(r"\d{12}", number or "") is None:
        return None
    digit = int(number[3])
    year = (19 + digit // 2) * 100 + int(number[4:6])
    if not 1900 <= year <= 2499:
        return None
    return year, "Nam" if digit % 2 == 0 else "Nữ"


def reconcile_identity(
    cccd: str,
    cccd_confidence: float,
    birth: str,
    birth_confidence: float,
    gender: str,
    gender_confidence: float,
) -> tuple[str, str, str, list[str]]:
    """Sửa trường yếu bằng trường chắc theo cấu trúc 12 số CCCD."""
    notes: list[str] = []
    number = re.sub(r"\D", "", cccd or "")
    parsed = parse_date(birth or "")
    current_gender = canonical_gender(gender or "")
    high = 80

    def confident(score: float) -> bool:
        return score >= high

    decoded = _cccd_year_gender(number)
    if decoded:
        year, cccd_gender = decoded
        if current_gender != cccd_gender:
            current_gender = cccd_gender
            notes.append(f"giới tính sửa theo CCCD thành {cccd_gender}")
        if confident(cccd_confidence) and parsed is not None and not confident(birth_confidence) and parsed.year != year:
            try:
                parsed = parsed.replace(year=year)
                notes.append(f"năm sinh sửa theo CCCD thành {year}")
            except ValueError:
                notes.append("không đổi năm sinh vì ngày không có trong năm của CCCD")
        elif confident(cccd_confidence) and parsed is not None and confident(birth_confidence) and parsed.year != year:
            notes.append("CCCD và ngày sinh không cùng năm")

    if len(number) == 12 and not confident(cccd_confidence) and parsed is not None and confident(birth_confidence):
        year_digits = f"{parsed.year % 100:02d}"
        if number[4:6] != year_digits:
            number = number[:4] + year_digits + number[6:]
            notes.append("hai số năm trong CCCD sửa theo ngày sinh")

    birth_text = parsed.strftime("%d/%m/%Y") if parsed is not None else (birth or "")
    return number, birth_text, current_gender or (gender or ""), notes


def correct_row_gender(row: dict) -> bool:
    decoded = _cccd_year_gender(re.sub(r"\D", "", str(row.get("cccd") or "")))
    if decoded is None:
        return False
    gender = decoded[1]
    if row.get("gioi_tinh") == gender:
        return False
    row["gioi_tinh"] = gender
    note = f"giới tính sửa theo CCCD thành {gender}"
    reason = row.get("ly_do") or ""
    if note not in reason:
        row["ly_do"] = f"{reason}; {note}".strip("; ")
    return True


def _peaks(projection: np.ndarray, limit: float, gap: int) -> list[int]:
    found: list[int] = []
    for index in range(1, len(projection) - 1):
        if projection[index] < limit:
            continue
        if projection[index] < projection[index - 1] or projection[index] < projection[index + 1]:
            continue
        if not found or index - found[-1] > gap:
            found.append(index)
        elif projection[index] > projection[found[-1]]:
            found[-1] = index
    return found


def _line_set_score(lines: list[int]) -> int:
    if len(lines) < 5:
        return -1
    gaps = np.diff(np.array(lines, dtype=float))
    pitch = float(np.median(gaps))
    if not 55 <= pitch <= 150:
        return -1
    regular = np.abs(gaps - pitch) <= max(14, pitch * 0.28)
    return int(regular.sum()) * 10 - int((~regular).sum()) * 25


def _horizontal_lines(gray: np.ndarray) -> list[int]:
    height, width = gray.shape
    background = cv2.GaussianBlur(gray, (0, 0), 15)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (90, 1))
    best: list[int] = []
    best_score = -1
    for band in (750, 1400, width):
        band = min(band, width)
        region = gray[:, :band]
        dark = (region.astype(np.int16) < background[:, :band].astype(np.int16) - 18).astype(np.uint8) * 255
        opened = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel)
        projection = opened.sum(axis=1) / 255.0
        for fraction in (0.35, 0.22, 0.12):
            lines = [y for y in _peaks(projection, limit=fraction * band, gap=18) if 40 < y < height - 40]
            score = _line_set_score(lines)
            if score > best_score:
                best_score = score
                best = lines
    if len(best) < 5:
        raise RuntimeError("Không thấy đủ đường kẻ ngang của bảng.")
    return best


def _line_score(gray: np.ndarray, y: int, x1: int, x2: int) -> int:
    if y < 0 or y >= gray.shape[0]:
        return 0
    dark = gray[y, x1:x2] < 160
    total = run = 0
    for value in dark:
        if value:
            run += 1
        else:
            if run > 40:
                total += run
            run = 0
    if run > 40:
        total += run
    return total


def _right_shifts(gray: np.ndarray, lines: list[int]) -> np.ndarray:
    measured_y = []
    measured_shift = []
    for y in lines:
        best_score = -1
        best_y = y
        for candidate in range(max(0, y - 15), min(gray.shape[0], y + 55)):
            score = _line_score(gray, candidate, 2100, 2850)
            if score > best_score:
                best_score = score
                best_y = candidate
        if best_score >= 200:
            measured_y.append(y)
            measured_shift.append(best_y - y)
    if len(measured_y) < 4:
        return np.zeros(len(lines))
    slope, intercept = np.polyfit(np.array(measured_y, dtype=float), np.array(measured_shift, dtype=float), 1)
    return slope * np.array(lines, dtype=float) + intercept


def _warp_row(gray: np.ndarray, y1: int, y2: int, shift1: float, shift2: float) -> np.ndarray:
    height, width = gray.shape
    top_left = min(height - 2, max(0, int(round(y1 + 1))))
    bot_left = min(height - 1, max(top_left + 8, int(round(y2 - 1))))
    top_right = min(height - 2, max(0, int(round(y1 + shift1 + 1))))
    bot_right = min(height - 1, max(top_right + 8, int(round(y2 + shift2 - 1))))
    source = np.float32([[0, top_left], [width - 1, top_right], [width - 1, bot_right], [0, bot_left]])
    out_h = max(36, int(max(bot_left - top_left, bot_right - top_right)))
    dest = np.float32([[0, 0], [width - 1, 0], [width - 1, out_h - 1], [0, out_h - 1]])
    matrix = cv2.getPerspectiveTransform(source, dest)
    return cv2.warpPerspective(gray, matrix, (width, out_h), borderValue=255)


def _vertical_peaks(row: np.ndarray) -> list[int]:
    band = row[int(row.shape[0] * 0.18) : int(row.shape[0] * 0.82)]
    if band.size == 0:
        return []
    dark = (band < 155).astype(np.uint8) * 255
    kernel = max(8, int(band.shape[0] * 0.75))
    opened = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel)))
    projection = opened.sum(axis=0) / 255.0
    peaks = _peaks(projection, limit=kernel * 0.65, gap=28)
    return [x for x in peaks if 60 < x < row.shape[1] - 40]


def _choose_bounds(peak_lists: list[list[int]], width: int) -> list[int]:
    histogram = np.zeros(width, dtype=np.float32)
    for peaks in peak_lists:
        for x in peaks:
            histogram[max(0, x - 6) : min(width, x + 7)] += 1
    if histogram.max() < 2:
        raise RuntimeError("Không thấy đủ đường kẻ dọc để chia cột.")
    centers = _peaks(histogram, limit=max(2, histogram.max() * 0.35), gap=40)
    if len(centers) < 8:
        centers = _peaks(histogram, limit=max(2, histogram.max() * 0.22), gap=30)
    if len(centers) < 4:
        raise RuntimeError("Không chia được cột của bảng.")
    if len(centers) == 8:
        return centers
    # Chọn 8 mốc có khoảng cách giống bảng: STT hẹp, họ tên rộng, giới tính hẹp.
    template = np.array([0.07, 0.27, 0.12, 0.055, 0.14, 0.12, 0.22])
    best: tuple[float, list[int]] | None = None
    indexes = range(len(centers))
    # Các mốc thường nằm trải đều; duyệt tổ hợp khi số mốc không quá lớn.
    from itertools import combinations

    pool = centers
    if len(pool) > 14:
        strength = [float(histogram[x]) for x in pool]
        order = np.argsort(strength)[::-1][:14]
        pool = [pool[i] for i in sorted(order)]
    for choice in combinations(pool, 8):
        bounds = list(choice)
        widths = np.diff(bounds).astype(float)
        if np.any(widths < 70):
            continue
        ratios = widths / widths.sum()
        score = -float(np.abs(ratios - template).sum())
        score += 0.002 * sum(float(histogram[x]) for x in bounds)
        if best is None or score > best[0]:
            best = (score, bounds)
    if best is None:
        return centers[:8]
    return best[1]


def _prepare(cell: np.ndarray) -> np.ndarray:
    if cell.size == 0:
        return np.full((64, 64), 255, np.uint8)
    image = cv2.resize(cell, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    height = image.shape[0]
    for y in list(range(min(15, height))) + list(range(max(0, height - 15), height)):
        if (image[y] < 165).mean() > 0.55:
            image[y] = 255
    return cv2.copyMakeBorder(image, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)


def _tess(image: np.ndarray, kind: str) -> tuple[str, float]:
    psm = 6 if kind in {"ho_ten", "dia_chi"} else 7
    base = f"--oem 1 --psm {psm}"
    if kind in {"stt", "cccd"}:
        lang, config = "eng", base + " -c tessedit_char_whitelist=0123456789"
    elif kind == "ngay_sinh":
        lang, config = "eng", base + " -c tessedit_char_whitelist=0123456789/"
    else:
        lang, config = "vie", base
    data = pytesseract.image_to_data(image, lang=lang, config=config, output_type=pytesseract.Output.DICT)
    words = []
    scores = []
    for text, conf in zip(data["text"], data["conf"]):
        token = str(text).strip()
        try:
            score = float(conf)
        except ValueError:
            score = -1
        if token and score >= 0:
            words.append(token)
            scores.append(score)
    return " ".join(words), (float(np.mean(scores)) if scores else 0.0)


def _normalize(kind: str, text: str) -> str:
    if kind in {"stt", "cccd"}:
        return re.sub(r"\D", "", text)
    if kind == "ngay_sinh":
        digits = re.sub(r"\D", "", text or "")
        if len(digits) == 8:
            guessed = f"{digits[:2]}/{digits[2:4]}/{digits[4:]}"
            if parse_date(guessed):
                return guessed
        return format_date(text)
    if kind == "gioi_tinh":
        return canonical_gender(text) or name_key(text)
    return name_key(text)


def _read_cell(cell: np.ndarray, kind: str) -> tuple[str, float]:
    text, confidence = _tess(_prepare(cell), kind)
    return _normalize(kind, text), confidence


def _snap_bounds(peaks: list[int], template: list[int]) -> list[int]:
    snapped = []
    for position in template:
        nearby = [peak for peak in peaks if abs(peak - position) <= 80]
        snapped.append(min(nearby, key=lambda peak: abs(peak - position)) if nearby else position)
    for index in range(1, len(snapped)):
        if snapped[index] <= snapped[index - 1] + 50:
            snapped[index] = snapped[index - 1] + max(60, template[index] - template[index - 1])
    return snapped


def _row_hint(row: np.ndarray) -> str:
    image = _prepare(row[:, 80:2900] if row.shape[1] > 3000 else row)
    config = "--oem 1 --psm 6"
    text = pytesseract.image_to_string(image, lang="vie", config=config)
    return " ".join(text.split())


def split_table_rows(path: Path) -> list[tuple[str, Path]]:
    gray = load_gray(path)
    lines = _horizontal_lines(gray)
    shifts = _right_shifts(gray, lines)
    image_dir = ROOT / "output" / "dong"
    image_dir.mkdir(parents=True, exist_ok=True)
    saved: list[tuple[str, Path]] = []
    index = 0
    for top, bottom, shift_top, shift_bottom in zip(lines, lines[1:], shifts, shifts[1:]):
        if bottom - top < 28 or bottom - top > 180:
            continue
        row = _warp_row(gray, top, bottom, float(shift_top), float(shift_bottom))
        view = row[:, 40:2960] if row.shape[1] > 2000 else row
        preview = cv2.resize(view, (1600, 96), interpolation=cv2.INTER_CUBIC)
        row_id = f"{path.stem}-{index}"
        destination = image_dir / f"{row_id}.jpg"
        cv2.imwrite(str(destination), preview, [cv2.IMWRITE_JPEG_QUALITY, 90])
        saved.append((row_id, destination))
        index += 1
    if not saved:
        raise RuntimeError("Không cắt được dòng nào từ bảng.")
    return saved


def read_table_image(path: Path, debug_dir: Path | None = None) -> list[PersonRow]:
    _configure_tesseract()
    gray = load_gray(path)
    lines = _horizontal_lines(gray)
    shifts = _right_shifts(gray, lines)
    rows = []
    peaks = []
    for index, (top, bottom) in enumerate(zip(lines, lines[1:])):
        if bottom - top < 28 or bottom - top > 180:
            continue
        row = _warp_row(gray, top, bottom, float(shifts[index]), float(shifts[index + 1]))
        rows.append(row)
        peaks.append(_vertical_peaks(row))
    if not rows:
        raise RuntimeError("Không cắt được dòng nào từ bảng.")
    bounds = _choose_bounds(peaks, gray.shape[1])
    image_dir = (debug_dir.parent / "dong") if debug_dir is not None else (ROOT / "output" / "dong")
    image_dir.mkdir(parents=True, exist_ok=True)
    people: list[PersonRow] = []
    for index, row in enumerate(rows):
        reasons = []
        values: dict[str, str] = {}
        confidences = []
        row_bounds = _snap_bounds(_vertical_peaks(row), bounds)
        for kind, left, right in zip(KINDS, row_bounds, row_bounds[1:]):
            cell = row[:, max(0, left + 4) : max(left + 5, right - 4)]
            value, confidence = _read_cell(cell, kind)
            values[kind] = value
            confidences.append(confidence)
            if confidence < 40 and kind in {"ho_ten", "cccd", "ngay_sinh", "gioi_tinh"}:
                reasons.append(f"{kind} độ tin cậy {confidence:.0f}")
        score = dict(zip(KINDS, confidences))
        values["cccd"], values["ngay_sinh"], values["gioi_tinh"], fixes = reconcile_identity(
            values["cccd"], score.get("cccd", 0),
            values["ngay_sinh"], score.get("ngay_sinh", 0),
            values["gioi_tinh"], score.get("gioi_tinh", 0),
        )
        reasons.extend(fixes)
        identity_ok = (
            re.fullmatch(r"\d{3,5}", values["stt"] or "") is not None
            and len(name_key(values["ho_ten"]).split()) >= 2
            and parse_date(values["ngay_sinh"]) is not None
            and canonical_gender(values["gioi_tinh"]) in {"Nam", "Nữ"}
            and re.fullmatch(r"\d{12}", values["cccd"] or "") is not None
        )
        sure = identity_ok and min(confidences[:5]) >= 45 and not fixes
        if not identity_ok:
            reasons.append("thiếu họ tên, ngày sinh, giới tính hoặc CCCD hợp lệ")
        elif not sure:
            reasons.append("độ tin cậy OCR thấp")
        row_id = f"{path.stem}-{index}"
        preview = cv2.resize(row[:, 40:2960] if row.shape[1] > 2000 else row, (1200, 72), interpolation=cv2.INTER_AREA)
        preview_name = f"{row_id}.jpg"
        cv2.imwrite(str(image_dir / preview_name), preview)
        people.append(
            PersonRow(
                anh=path.name,
                stt=values["stt"],
                ho_ten=name_key(values["ho_ten"]),
                ngay_sinh=format_date(values["ngay_sinh"]) if parse_date(values["ngay_sinh"]) else values["ngay_sinh"],
                gioi_tinh=canonical_gender(values["gioi_tinh"]) or values["gioi_tinh"],
                cccd=values["cccd"],
                dia_chi=name_key(values["dia_chi"]),
                khong_chac_chan=0 if sure else 1,
                ly_do="; ".join(reasons),
                xac_nhan=1 if re.fullmatch(r"\d{12}", values["cccd"] or "") else 0,
                dong_tho="",
                anh_dong=preview_name,
                row_id=row_id,
            )
        )
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"{path.stem}_cot.txt").write_text(str(bounds), encoding="utf-8")
    return [person for person in people if person.stt or person.ho_ten or person.cccd]
