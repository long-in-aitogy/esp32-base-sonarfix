# Bộ nhớ ESP32 — 31/10/2026

## Thay đổi

Firmware bỏ AP cấu hình, HTTP server, trang HTML, quét mạng và task phục vụ
portal. Chỉ một SSID/mật khẩu kết nối được giữ trong cấu hình đang dùng.
Khi nâng firmware, danh sách cũ chỉ dùng cho bước chuyển đổi: thử lần lượt
để chọn mạng kết nối được, ghi và đọc lại thông tin mạng đó, sau đó mới xóa
`wifi_config/profiles` và `wifi_config/ap_pass`. Nếu chưa kết nối được hoặc
chưa lưu được thì giữ dữ liệu cũ để lần sau thử lại. Xem [Wi-Fi](wifi-config.md).

Các khoản RAM bỏ đi:

- Stack portal: 8.192 byte cùng tài nguyên task/HTTP server/AP.
- Hàng đợi raw RTCM: 4 × 1.032 byte payload khi `BACKEND_PUBLISH_RAW_RTCM`
  tắt. Hàng đợi NMEA và buffer UART giữ nguyên để bảo toàn luồng dữ liệu.
- Không tạo đối tượng WebSocket khi tính năng tắt. Khi bật, gói status mượn
  JSON đã serialize thay cho hai document tạm 8.704 và 8.192 byte; document
  bọc chỉ còn 256 byte.
- Bộ đệm WebSocket được giải phóng khi ngắt kết nối và khi xử lý xong một
  batch lớn hơn 4 KB. Giới hạn dung lượng được kiểm tra trước khi chèn byte.
- Khi xóa lịch sử Auto Base, giải phóng buffer String cũ thay vì chỉ đặt độ
  dài về 0. Không giảm stack các task GNSS/mạng khi chưa có đo đạc trên máy.

## Số liệu build

Cùng cấu hình `tdm240x_dev_general`, trước/sau khi bỏ portal và thêm quản lý
bộ nhớ:

| Chỉ số | Trước | Sau |
| --- | ---: | ---: |
| Firmware | 1.092.881 byte (83,4%) | 1.036.805 byte (79,1%) |
| RAM tĩnh | 49.860 byte | 49.396 byte |

Giảm 56.076 byte firmware và 464 byte RAM tĩnh. Những vùng cấp phát động ở
trên không được tính trong số RAM tĩnh của linker. Chưa nạp phần cứng để đo
heap hoặc mức sử dụng stack thực tế; không cộng các khoản lý thuyết thành một
con số RAM thực tế đã tiết kiệm.

Sau đợt tách trách nhiệm NVS/nhận diện chip/đổi mạng, build general là
1.037.849 byte firmware (79,2%) và 49.388 byte RAM tĩnh. Việc chia đơn vị biên
dịch có thể thay đổi kích thước mã máy; phần dọn cấu trúc này không được tính
là một khoản tiết kiệm flash mới.

## System Monitor trên web

Mục **Bộ nhớ ESP32** hiển thị:

- Heap trống hiện tại, mức trống thấp nhất từ khi bật và khối trống lớn nhất.
- Dung lượng flash vật lý và firmware/vùng ứng dụng đang chạy.
- Dung lượng hai phân vùng NVS; số ô đã dùng, còn trống và tổng ô.
- Khả năng dọn từng nhóm dữ liệu, trạng thái yêu cầu và ACK của thiết bị.

NVS dùng các ô lưu trữ với overhead riêng. Số ô không phải dung lượng byte của
các giá trị. Xóa dữ liệu cho phép NVS tái sử dụng ô; không thu nhỏ phân vùng
flash và không biến flash thành RAM. Vùng OTA/dữ liệu cũng không phải khoảng
trống để firmware đang chạy tùy ý sử dụng.

Chỉ quản trị viên có quyền gửi hai lệnh qua endpoint command hiện có:

- `CHECK_STORAGE_STATUS`: yêu cầu trạng thái mới.
- `CLEAR_NVS_DATA`: payload `group` và `confirm` phải trùng nhau và nằm trong
  danh sách cố định. `unused_wifi` chỉ xóa hai key portal cũ; `auto_base_history`
  chỉ xóa kết quả Auto Base đã lưu. Bản ghi lệnh cuối cùng vẫn được giữ để ACK.

Luồng xóa giữ nguyên license, serial/tên trạm, khóa, mạng đang dùng,
cấu hình MQTT/NTRIP, cấu hình Base và kết quả Survey-In. Không cung cấp lệnh
xóa toàn bộ NVS/phân vùng hoặc namespace tùy ý. Firmware từ chối dọn trong
workflow GNSS hoặc Survey-In chưa hoàn tất. Firmware cũ, thiết bị ngoại tuyến
hoặc bị khóa không có nút thao tác khả dụng. Web chỉ báo hoàn tất khi nhận
đúng command ID từ thiết bị; hết thời gian chờ không được coi là xóa thành công.

## Kiểm tra

Ba cấu hình `tdm240x_dev_general`, `tdm240x_dev_general_debug` và
`tdm240x_dev_general_test` build thành công. Các kiểm tra GNSS/CORS, GGA,
chuyển mạng, ACK vị trí, VN2000, bảo mật và chuyển đổi dữ liệu đều qua.

Đã kiểm tra giao diện desktop/390 px, xác nhận và hủy xóa, trạng thái chờ,
ACK, firmware cũ, thiết bị ngoại tuyến và không tràn ngang. Số liệu trong
kiểm tra giao diện là fixture, không phải telemetry phần cứng.

Chưa triển khai backend/frontend hoặc flash ESP32 trong lần làm này. Chỉ
firmware mới mới gửi các trường bộ nhớ và xử lý hai lệnh trên.

## Bảng dữ liệu NVS

Trong System Monitor, bấm **Kiểm tra NVS** để đọc từ thiết bị và mở bảng.
Mỗi trang tối đa 6 trường, gồm tên cấu hình, key, trường con, kiểu, dung lượng
và giá trị đã đọc trực tiếp từ NVS. Wi-Fi được hiển thị trước, tiếp theo là
cấu hình ứng dụng, cuối cùng là dữ liệu hệ thống. Dùng Trước/Sau để xem trang khác, Kiểm tra lại
để đọc từ đầu. Trên điện thoại có thể vuốt ngang bảng. Escape/Đóng đóng bảng.

Firmware liệt kê hai phân vùng `nvs` và `agent_state` bằng handle chỉ đọc.
Giá trị đơn dùng danh sách cho phép. BASE_JSON, SERVICE_JSON, PROGRESS_JSON,
CMD_RESULT và SURVEY_RESULT được tách thành từng trường con để xem mode, tọa độ,
Survey-In, máy chủ, cổng và mountpoint. Trường chứa mật khẩu/token/license/auth
được che ngay trên thiết bị; blob và key chưa được nhận diện chỉ gửi metadata.
Giá trị trường JSON dài hơn 96 ký tự có cờ truncated; UI báo rõ bị rút gọn.
JSON gốc chỉ được đọc khi không quá 8192 byte; lỗi đọc/parse giữ cách xem metadata.
Dung lượng của trường JSON là độ dài giá trị JSON, không phải một key NVS riêng. Mỗi trang có command ID và thời điểm đọc; các trang là các lần đọc
riêng nên nếu dữ liệu thay đổi trong lúc xem, hãy kiểm tra lại từ đầu.

Lệnh dùng lại `CHECK_STORAGE_STATUS` với payload `{"inspect":true,"offset":0}`.
Backend yêu cầu quyền admin và firmware có capability `inventory_supported`.
Offset phải là số nguyên 0–8192. Kết quả nằm ở `system_info.nvs.inventory`;
UI chỉ nhận bảng có command ID đúng yêu cầu. Snapshot chỉ giữ trong RAM tối đa 60 giây,
không ghi bản kiểm kê vào NVS; trang xóa dữ liệu sẽ hủy snapshot đã đọc.
Document kiểm kê giới hạn 3072 byte và chỉ thêm dung lượng JSON status khi có
snapshot. Không có API ghi/xóa key tùy ý trong bảng này.

Đã kiểm tra phân trang, che giá trị bí mật, đọc metadata, đóng handle/iterator,
phân vùng không khả dụng, phân quyền/offset và giao diện desktop/390 px bằng
fixture. Kiểm tra host: `check_nvs_inventory.py` xác nhận tách trường, phân trang
và che bí mật; `check_wifi_nvs.py` xác nhận đọc cấu hình đã lưu và chỉ lưu cặp
mặc định khi thiếu key và kết nối thành công. Chưa đo trên ESP32 thật hoặc
triển khai lên web vận hành.

Wi-Fi hiện lưu tại myPrefs/WIFI_SSID và myPrefs/WIFI_PASS. Khi thiếu các key này,
firmware chỉ lưu cặp mặc định sau khi đã kết nối thành công và kiểm tra đọc lại.
Vùng wifi_config cũ được dò bằng native NVS chỉ đọc: không tồn tại là trạng thái
bình thường, không còn tạo log Preferences NOT_FOUND.
