# Kiểm tra danh sách khám sức khỏe

Chương trình chạy trên máy này. Ảnh bảng được cắt thành từng dòng, đọc bằng OCR hoặc API, rồi đối chiếu CCCD trên trang https://v20.ytecoso.vn bằng extension Chrome. Khóa API không được ghi ra đĩa.

## Cài đặt

1. Cài [Python 3.12](https://www.python.org/downloads/windows/) và chọn **Add python.exe to PATH**.
2. Cài [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki). File ngôn ngữ tiếng Việt `tessdata\vie.traineddata` đã nằm trong thư mục dự án.
3. Bấm đúp `chay-web.bat`. Lần đầu file này tạo `.venv` và cài thư viện trong `requirements.txt`.
4. Trình duyệt mở http://127.0.0.1:8765. Máy khác trong cùng mạng mở bằng địa chỉ IP của máy này, cổng 8765. Giữ cửa sổ đen để trang web tiếp tục chạy. Đóng cửa sổ đó là tắt web.

## Dùng trang web

1. **Tải ảnh lên** để đưa ảnh vào thư mục `anh_can_check`. Có thể bỏ ảnh thẳng vào thư mục đó.
2. Chọn ảnh, chọn **OCR trên máy** hoặc **API tương thích OpenAI**, rồi bấm **Đọc ảnh đang chọn**.
3. Với API, nhập địa chỉ, tên model và khóa. Khóa chỉ dùng cho lần đọc đó.
4. Sửa dòng chưa chắc. CCCD đủ 12 số thì giới tính được lấy từ số thứ 4, ba số đầu được đưa về `033`.
5. Tích **Đưa vào kiểm tra** ở các dòng muốn tra cứu, rồi bấm **Lưu chỉnh sửa**.

Dòng trạng thái phía trên danh sách cho biết tác vụ đang chạy hay đã xong.

## Cài extension

1. Mở Chrome, vào `chrome://extensions`.
2. Bật **Chế độ dành cho nhà phát triển**.
3. Bấm **Tải tiện ích đã giải nén** và chọn thư mục `extension` trong dự án này.
4. Sau mỗi lần sửa extension, bấm nút tải lại trên thẻ tiện ích đó.

## Tra cứu trên v20

1. Đăng nhập https://v20.ytecoso.vn/ và mở **Danh sách khám sức khỏe**.
2. Tự lọc khoảng ngày trên trang.
3. Bấm biểu tượng extension, chọn ảnh, rồi bấm **Kiểm tra**.
4. Extension nhập CCCD và bấm **Tìm kiếm**. Có thể tạm dừng, dừng hoặc tắt. Khi xong, bấm **Tải CSV** nếu muốn lưu file. Kết quả cũng được gửi về trang web cục bộ.

Dòng không có trên hệ thống có nền hồng nhạt.
