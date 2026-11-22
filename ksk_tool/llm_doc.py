import base64
import json
import re
import urllib.error
import urllib.request

from .ocr_bang import (
    PersonRow,
    canonical_gender,
    format_date,
    parse_date,
    reconcile_identity,
    split_table_rows,
)

PROMPT = """Bạn đang đọc một dòng trong bảng giấy khám sức khỏe Việt Nam.
Ảnh có các cột theo thứ tự: số thứ tự, họ tên, ngày sinh, giới tính, CCCD 12 số, địa chỉ, rồi cột tên bố hoặc mẹ ở ngoài cùng.
Bỏ qua cột tên bố hoặc mẹ. Chỉ chép đúng chữ nhìn thấy, không suy đoán số còn thiếu.
Trả về đúng một JSON với các khóa:
stt, ho_ten, ngay_sinh, gioi_tinh, cccd, dia_chi, do_tin_cay, tin_cccd, tin_ngay_sinh, tin_gioi_tinh.
do_tin_cay, tin_cccd, tin_ngay_sinh, tin_gioi_tinh là số nguyên từ 0 đến 100.
ngay_sinh theo dạng dd/mm/yyyy. gioi_tinh chỉ là Nam hoặc Nữ. Ô không đọc được thì để chuỗi rỗng."""


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("API không trả JSON.")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("API không trả một đối tượng JSON.")
    return data


def _chat(base_url: str, api_key: str, model: str, image_bytes: bytes) -> dict:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
                        },
                    },
                ],
            }
        ],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError("API từ chối khóa hoặc không có quyền.") from None
        raise RuntimeError(f"API trả lỗi HTTP {exc.code}.") from None
    except urllib.error.URLError:
        raise RuntimeError("Không kết nối được máy chủ API.") from None
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("API trả dữ liệu không đúng định dạng chat.") from None
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return _parse_json(str(content))


def read_table_with_llm(path, base_url: str, api_key: str, model: str) -> list[PersonRow]:
    people = []
    for row_id, image_path in split_table_rows(path):
        data = _chat(base_url, api_key, model, image_path.read_bytes())
        birth_raw = str(data.get("ngay_sinh", ""))
        birth = format_date(birth_raw) if parse_date(birth_raw) else ""
        gender = canonical_gender(str(data.get("gioi_tinh", "")))
        number = re.sub(r"\D", "", str(data.get("cccd", "")))
        name = " ".join(str(data.get("ho_ten", "")).split())
        stt = re.sub(r"\D", "", str(data.get("stt", "")))
        address = " ".join(str(data.get("dia_chi", "")).split())
        try:
            confidence = int(float(data.get("do_tin_cay", 0)))
        except (TypeError, ValueError):
            confidence = 0
        confidence = max(0, min(100, confidence))

        def field_score(key: str) -> int:
            raw = data.get(key, "")
            if raw in ("", None):
                return confidence
            try:
                return max(0, min(100, int(float(raw))))
            except (TypeError, ValueError):
                return confidence

        number, birth, gender, fixes = reconcile_identity(
            number, field_score("tin_cccd"),
            birth, field_score("tin_ngay_sinh"),
            gender, field_score("tin_gioi_tinh"),
        )
        reasons = list(fixes)
        if not 3 <= len(stt) <= 5:
            reasons.append("STT")
        if len(name.split()) < 2:
            reasons.append("Họ tên")
        if not birth:
            reasons.append("Ngày sinh")
        if gender not in {"Nam", "Nữ"}:
            reasons.append("Giới tính")
        if len(number) != 12:
            reasons.append("CCCD")
        if confidence < 75:
            reasons.append(f"Độ tin cậy {confidence}")
        people.append(
            PersonRow(
                anh=path.name,
                stt=stt,
                ho_ten=name,
                ngay_sinh=birth,
                gioi_tinh=gender,
                cccd=number,
                dia_chi=address,
                khong_chac_chan=1 if reasons else 0,
                ly_do=", ".join(reasons),
                xac_nhan=1 if len(number) == 12 else 0,
                row_id=row_id,
                anh_dong=f"{row_id}.jpg",
                do_tin_cay=confidence,
            )
        )
    return people
