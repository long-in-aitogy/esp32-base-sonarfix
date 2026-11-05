# Wi-Fi trên ESP32

Firmware mới không chứa thông tin đăng nhập Wi-Fi mặc định. Cấu hình thiết bị mới bằng các lệnh dưới đây.

Firmware không phát AP và không phục vụ trang cấu hình Wi-Fi. Chỉ giữ một
SSID/mật khẩu đang dùng trong cấu hình kết nối. Cài qua Serial 115200:

```text
ATG ESP SET WIFI SSID <ten-mang>
ATG ESP SET WIFI PASS <mat-khau>
```

Bộ phân tích lệnh hiện dùng dấu cách để tách tham số; tên mạng/mật khẩu nhập
qua ATG không hỗ trợ khoảng trắng. Thiết lập được áp dụng ở lần kết nối lại.
Kết nối Wi-Fi/4G dự phòng vẫn hoạt động theo cấu hình thiết bị.

Khi nâng từ firmware có portal, lần thử Wi-Fi đầu kiểm tra danh sách cũ và
chọn mạng đầu tiên kết nối thành công. Chỉ giữ mạng đó sau khi đọc lại đúng
SSID và mật khẩu vừa lưu. Mạng ưu tiên bị lỗi vẫn có thể chuyển sang mạng kế
tiếp trong bước chuyển đổi này. Nếu chưa kết nối được hoặc lưu bị lỗi, giữ
danh sách cũ để thử lại lần sau. Khi chuyển đổi xong, không dùng danh sách
nhiều mạng nữa. Có thể xóa dữ liệu portal cũ từ System
Monitor trên web sau khi thiết bị chạy firmware mới.

## Prog_Config.h và NVS

`include/Prog_Config.h` là nơi điền mặc định. Cấu hình đã lưu trong NVS luôn
được ưu tiên; sửa header, nạp firmware mới hoặc reboot không tự ghi đè chúng.
Chỉ khi bộ nhớ chưa có cấu hình, hoặc sau lệnh xóa/reset phần tương ứng,
firmware mới dùng mặc định trong header. Không tự xóa NVS khi phát hiện header
thay đổi.

`CONNECTION_PREFERENCE` chọn mặc định `"4G"` hoặc `"WIFI"`. APN đã lưu được
ưu tiên; giá trị `"auto"` cho phép chọn APN theo nhà mạng. `ATG CONFIG RESET`
reset cấu hình kết nối; cấu hình dịch vụ/Base trong vùng dữ liệu trạm được
quản lý riêng. Hai thao tác dọn Wi-Fi portal cũ/lịch sử Auto Base trên web
không reset mạng đang dùng, license hoặc cấu hình dịch vụ.

Thông tin NVS chỉ báo số ô đã dùng/còn trống, không gửi SSID, mật khẩu hoặc
license lên web. Xem thêm [bộ nhớ ESP32](memory-storage.md).
