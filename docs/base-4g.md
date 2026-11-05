# Base 4G di động và CORS

ESP32 chạy firmware C++, nhận lệnh và gửi trạng thái theo giao thức của
`cors/geodetic/agent_universal.py`. Python agent không chạy trên ESP32.
Mặc định thiết bị dùng 4G; có thể chuyển sang Wi-Fi bằng lệnh cấu hình sẵn có.

## Chức năng

Khi bật nguồn, firmware nhận diện receiver và thiết lập Base trước khi chờ
Wi-Fi/4G. Survey-In tự động lúc bật nguồn luôn chạy 120 giây. Thiết bị chưa
có cấu hình dùng RTCM-only MSM4 + MSM7 và ngưỡng mặc định 5 m cho u-blox;
cấu hình đầu ra đã lưu được giữ nguyên. UM đặt undulation bằng 0 trước khảo
sát, không dùng giá trị 5 m làm tham số Distance.

Thời lượng cấu hình Survey-In từ UI chỉ áp dụng cho lệnh người dùng bấm áp dụng;
giá trị đó không đổi thời lượng tự động lúc khởi động.

Fixed LLA đã lưu được khôi phục cùng quy ước độ cao và được đối chiếu với
receiver trước khi cho phép kết nối phát NTRIP. Auto Base đã lưu được giữ
nguyên. Khóa toàn bộ thiết bị ngăn bước tự cấu hình. Lỗi đọc/cấu hình được
báo qua `system_info.base_startup`; không tự chuyển Fixed LLA lỗi sang Survey-In.

Mỗi lần ESP khởi động trong chế độ Survey-In, firmware gửi lại cấu hình khảo
sát 120 giây, kể cả receiver vẫn báo MODE Survey-In. MODE không
chứng minh anten chưa di chuyển; không suy đoán có thể dùng lại tọa độ cũ.
Kết quả cũ chỉ là lịch sử;
UI chỉ cho dùng tọa độ có readback mới và trạng thái receiver xác nhận hoàn tất.
Muốn giữ nguyên tọa độ qua các lần mất điện, kiểm tra kết quả rồi lưu Fixed LLA.

u-blox được đọc bằng CFG-TMODE3 và NAV-SVIN, gồm thời gian, số mẫu, sai số ước
tính và cờ valid/active; chỉ lưu kết quả khi valid=1 và active=0. Tọa độ ECEF
được đổi sang vĩ độ/kinh độ và h ellipsoid WGS 84, không dùng độ cao MSL của GGA.

| Chọn trên CORS | Lệnh xuống ESP32 | Hoạt động |
| --- | --- | --- |
| Tọa độ chính xác (`FIXED_LLA`) | `EXECUTE_RAW_COMMANDS` + `original_config` | Gửi nguyên lệnh tọa độ do backend tạo, lưu cấu hình và loại chip. |
| Survey-in (`SURVEY_IN`) | `EXECUTE_RAW_COMMANDS` + `original_config` | Gửi lệnh khảo sát do backend tạo. Unicore dùng thời gian khảo sát; u-blox có thêm ngưỡng chính xác, đúng theo command builder của CORS. |
| Auto base (`AUTO_CORS`) | `TRIGGER_AUTO_BASE` | Chuyển rover, nhận cải chính CORS, đợi RTK_FIXED với GGA mới, lấy mẫu, đặt lại base rồi phát RTCM tới caster. |
| Khóa/mở trạm | `LOCK_DEVICE` / `UNLOCK_DEVICE` | Giữ kênh quản lý; ngừng output RTCM theo phạm vi khóa. |

Base di động ở đây là bộ base có thể mang đến điểm đặt mới. Khi phát cải chính,
anten vẫn phải đứng yên. Sau khi chuyển vị trí, chọn lại một trong ba chế độ;
không tiếp tục dùng tọa độ của điểm đặt cũ.

Loại GNSS được chọn từ CORS (`sensor_type`: `Ublox` hoặc `Unicorecomm`), lưu
trong NVS và dùng cho auto base. Cùng một firmware chứa cả hai bộ lệnh.
Boot chờ 2 giây rồi dò receiver bằng UBX-MON-VER hoặc VERSIONA trên các baud hỗ trợ;
`UNKNOWN` có thể xuất hiện trước khi nhận diện hoặc khi chưa có phản hồi. Nhánh u-blox yêu cầu receiver hỗ trợ
UBX-CFG-TMODE3, như ZED-F9P. Nhánh Unicore dùng bộ lệnh UM980/UM982 trong CORS.

Survey-In Unicore xuất theo cấu hình UI: `RTCM only` gửi `unlogall` để tắt
output cũ, rồi bật bộ RTCM MSM4/MSM7 đã chọn và lưu cấu hình. Firmware
không tự hỏi GGA/GSA/GSV/GST định kỳ.
Trước khi bắt đầu Survey-In, luồng Unicore đặt `config undulation 0.0` để
receiver báo trực tiếp độ cao ellipsoid WGS 84. UI vẫn tính h bằng độ cao
chip báo cộng undulation của từng BESTNAV, nên đọc được cả cấu hình cũ.
Firmware tự đọc `MODE` và `BESTNAVA` mỗi 30 giây, kể cả sau reboot, để cập nhật UI.
`BESTNAV: FIXEDPOS` xác nhận UM đang giữ tọa độ Base; đây không phải phần trăm
hay số giây lấy mẫu hợp lệ bên trong UM. Kết quả Survey-In gần nhất lưu NVS,
vẫn có thể đối chiếu sau khi chuyển Fixed LLA hoặc khởi động lại ESP32.
Thông tin vệ tinh trên dashboard dùng decoder RTCM; backend chỉ ưu tiên NMEA
khi thực sự có GSV mới, không ẩn dữ liệu RTCM theo cấu hình NMEA đã lưu cũ.

Truy vấn đọc UM được xử lý trong `Unicore_Readback.cpp`. Firmware gửi CRLF trước
`MODE`/`BESTNAVA` để kết thúc dòng đầu vào còn dang dở; thao tác này không đổi
mode hoặc chạy lại Survey-In. Log `[GNSS][READBACK]` ghi lệnh gửi, ACK và số byte
nhận để phân biệt timeout với lỗi phản hồi/checksum.
Các byte RTCM/NMEA đi qua trong lúc truy vấn vẫn được đưa qua bộ đọc UART và
giữ frame RTCM để luồng NTRIP gửi tiếp. NTRIP ghi nguyên dòng phản hồi lỗi caster
vào Serial và `ntrip_status.serverN.error`; tốc độ nhận từ chip và tốc độ gửi
lên caster là hai số riêng.

Khi BESTNAV báo `SOL_COMPUTED,FIXEDPOS`, UI hiển thị tọa độ Base đang giữ và cho
sao chép hoặc điền vào Fixed LLA để người dùng kiểm tra/hiệu chỉnh trước khi áp
dụng. Vĩ độ, kinh độ lấy từ chuỗi BESTNAV gốc để giữ số lẻ. Độ cao h ellipsoid
được tính từ độ cao báo trong BESTNAV cộng undulation trong **cùng bản tin**;
undulation bằng 0 thì giữ nguyên độ cao. Giá trị này phụ thuộc cấu hình undulation
của chip, không phải geoid địa phương đã hiệu chỉnh. Khi áp dụng Fixed LLA với
`altitude_reference=ELLIPSOID`, backend hiện có đặt `config undulation 0.0` trước
`mode base`. Sao chép/điền form không gửi lệnh cấu hình xuống chip.

`Backend_Agent.cpp` giữ khởi tạo, kết nối và vòng lặp điều phối. Xử lý lệnh nằm
trong `Backend_Agent_Commands.cpp`, payload trạng thái trong `Backend_Agent_Status.cpp`,
workflow Auto Base/đối chiếu trong `Backend_Agent_Workflows.cpp`, phép chiếu tọa độ
trong `Backend_Agent_Projection.cpp`. Các phần này dùng chung lớp `BackendAgent`.

## Kết nối phần cứng

- ESP32 TDM240x: RX GNSS GPIO18, TX GNSS GPIO19; UART GNSS 115200 baud.
- Unicore: mặc định `GNSS_UNICORE_PORT = 0`; output sau cấu hình BASE dùng ngay
  cổng receiver đang nhận lệnh từ ESP32, không giả định dây nối COM2. Giá trị 1–3
  buộc output sang COM1–3 nếu phần cứng cần cổng cụ thể.
- u-blox: nối UART1, đặt UART1 115200 baud trước khi dùng. Firmware chuyển
  cấu hình output USB/UART2 do backend tạo sang UART1 và tính lại checksum UBX.
- Modem: RX ESP32 GPIO16, TX ESP32 GPIO17; APN theo SIM/nhà mạng.

Luồng bật nguồn dùng cùng command builder với cấu hình Base hiện có, không
chạy bootstrap COM2 cũ. Với Unicore, các lệnh log COM3 do backend tạo được
chuyển sang cổng nối ESP32. Tọa độ và thời gian khảo sát đã lưu được giữ nguyên.

Nếu GGA đã báo Base cố định mà UART vẫn không có RTCM, sau khi nạp firmware mới
có thể thử `ATG GNSS BASE 1006 CURRENT ON` qua Serial Monitor. Lệnh này bật RTCM1006
trên cổng nhận lệnh, không đổi tọa độ hoặc chạy lại khảo sát. Khi thấy frame RTCM
tăng, dùng `ATG GNSS BASE ALL CURRENT ON` để bật toàn bộ danh sách RTCM hỗ trợ.

## Đưa thiết bị lên CORS

1. Build và nạp firmware, mở Serial Monitor 115200 baud:

   ```sh
   pio run -e tdm240x_dev_general
   pio run -e tdm240x_dev_general -t upload
   pio device monitor -b 115200
   ```

2. Cấu hình APN và broker MQTT **cùng broker backend CORS đang dùng**. Thay
   các giá trị ví dụ bằng thông tin triển khai thực tế:

   ```text
   ATG ESP SET 4G APN <apn>
   ATG MQTT SET SERVER <mqtt-host>
   ATG MQTT SET PORT 1883
   ATG MQTT SET USER <mqtt-user>
   ATG MQTT SET PASS <mqtt-password>
   ATG ESP SET BACKEND HOST <backend-host>
   ATG ESP SET BACKEND PORT 8000
   ATG ESP SET CONNECTION 4G
   ```

   Lệnh cuối khởi động lại để áp dụng. Kênh WebSocket hiện dùng `ws`, không hỗ
   trợ `wss`; MQTT vẫn là kênh quản lý khi không dùng được WebSocket. Host/port
   phải trỏ tới endpoint thiết bị thực tế của CORS, không phải URL trang web.

3. Lấy serial `esp_...` từ log `[BACKEND] Device Serial`. Trên CORS, tìm thiết
   bị này, nhận/cấp thiết bị và triển khai license theo luồng quản lý hiện có.
   Khi chưa có license, thiết bị vẫn báo trạng thái nhưng không phát RTCM.

4. Chọn đúng chip và một trong ba chế độ. Với auto base, backend phải có tài
   khoản/mountpoint cải chính trong `AUTO_BASE_CORS_*`. Với fixed, độ cao là
   độ cao ellipsoid, không tự thay bằng độ cao thủy chuẩn.

5. Cấu hình dịch vụ caster/mountpoint đích từ CORS. Thiết bị hỗ trợ hai máy
   chủ NTRIP. Theo dõi trạng thái GNSS, tọa độ, RTK FIX, vệ tinh, tốc độ RTCM,
   kết nối từng máy chủ và `last_command_result` trên hệ thống hiện có.

Không cần tạo dashboard hoặc API riêng cho ESP32. Các topic sử dụng:

```text
pi/devices/<serial>/status
pi/devices/<serial>/raw_data
pi/devices/<serial>/command
pi/devices/<serial>/control_ack
```

WebSocket dùng `/ws/pi/<serial>?token=<license>` và các gói `status_update`,
`nmea_update` tương ứng backend hiện có. Firmware nhận cả token `dt_...` do
backend cấp và license số cũ. `DEPLOY_LICENSE` chỉ báo thành công sau khi token
hợp lệ và lưu NVS thành công; token sai không ghi đè token đang dùng.
Không ghi license vào log.

## Khóa trạm

- `LOCK_DEVICE`, payload `{}`: khóa toàn thiết bị, chặn lệnh ngoài khóa/mở và
  yêu cầu dừng workflow đang chạy.
- `LOCK_DEVICE`, payload `{"locked_servers":[2]}`: chỉ chặn máy chủ 2; máy
  chủ 1 và điều khiển GNSS tiếp tục hoạt động.
- `[1,2]`: khóa cả hai output, vẫn cho quản lý GNSS như Python agent.
- `[]` hoặc `UNLOCK_DEVICE`: bỏ khóa. Việc mở khóa không tự bật một máy chủ
  đã bị tắt trong cấu hình dịch vụ.
- Lưu khóa vào NVS, nạp lại sau reboot. Khóa output luôn ưu tiên hơn fail-open.
- `system_info.device_lock` báo `scoped`, `all`, `locked_servers`, để CORS nhận
  biết firmware hỗ trợ khóa theo từng máy chủ.

Các payload trên mô tả nội dung lệnh; gửi qua cơ chế command dispatcher của
CORS để giữ đúng envelope, command ID và quyền người vận hành.

## Kiểm tra

Build firmware, không cần gắn ESP32:

```sh
pio run -e tdm240x_dev_general
git diff --check
```

Kiểm tra thực địa còn cần: nhận đúng GNSS, survey hoàn tất, auto base đạt FIX,
rover nhận được cải chính, độ đúng tọa độ và khóa/mở từng máy chủ sau reboot.
Auto base hướng tới 60 mẫu trong 60 giây, chỉ lấy RTK_FIXED và cần ít nhất 15
mẫu hợp lệ. Không mặc định chấp nhận RTK_FLOAT hoặc luôn có đủ 60 mẫu.
Với Unicore qua backend và auto base, lệnh cấu hình chỉ thành công khi nhận phản hồi đúng tên lệnh,
`$command,<command>,response: OK`, trong 8 giây. Checksum được kiểm tra nếu có.
Phản hồi lỗi (kể cả `NO MATCHING FUNC`), ghi UART thiếu hoặc timeout sẽ dừng
batch và báo lỗi về backend. Task đọc GNSS nhường UART trong lúc chờ ACK.
Reset chỉ gửi một lần; sau ACK đợi thêm 2 giây trước lệnh tiếp theo.
ACK xác nhận receiver nhận lệnh; chưa thay thế readback cấu hình sau reboot.
Các lệnh ATG qua terminal và cấu hình khởi động cũ vẫn dùng cơ chế gửi UART.

Với u-blox, bước chuyển Rover trong auto base kiểm tra ACK và đọc lại
CFG-TMODE3; các batch cấu hình base còn lại vẫn chỉ xác nhận gửi UART.
ESP32 chuyển tiếp RTCM nguyên byte, không giải
mã datum RTCM 1021/1023/1025 như Python agent. Phần chuyển VN2000 hiện có của
ESP32 dùng tham số tích hợp/tỉnh; cần kiểm chứng hệ tọa độ thực tế trước khi
dùng kết quả auto base cho đo đạc.

## Tách giao thức GNSS

- `gnss_cmd_builder.h/.cpp`: kiểu dữ liệu chung và chọn bộ tạo lệnh theo chip.
- `ublox_commands.h/.cpp`: tạo/routing gói UBX nhị phân cho u-blox.
- `Ubx_Reply.h`: đọc khung UBX, kiểm tra checksum; auto base dùng cho ACK/NAK và readback.
- `unicore_commands.h/.cpp`: tạo lệnh ASCII cho UM980/UM982.
- `Backend_Agent_Startup.cpp`: chọn cấu hình khởi động từ NVS, đọc receiver trước
  khi quyết định khôi phục Fixed LLA hoặc tiếp tục Survey-In.
- `Ublox_Readback.cpp` và `Ubx_Base_Status.h`: đọc CFG-TMODE3/NAV-SVIN, chỉ xác nhận
  tọa độ Survey-In khi receiver báo hợp lệ và kết thúc khảo sát.
- Cấu hình fixed/survey chọn ephemeris theo hệ vệ tinh được bật. Survey-In UM
  gửi `mode base time <giây> 0`, không dùng lại tọa độ cũ qua tham số Distance.
- `Unicore_Reply.h`: đọc phản hồi ASCII của UM, khớp tên lệnh và kiểm tra `OK` chính xác.

Luồng Unicore từ chối dữ liệu nhị phân và nhiều dòng lệnh trong cùng một gói,
để mỗi lệnh gửi đi có một phản hồi được kiểm tra riêng. Các truy vấn trạng thái
`mode`/`log` vẫn đi theo luồng truy vấn, không yêu cầu ACK cấu hình.

## Cấu hình Wi-Fi không cần Internet

ESP không phát mạng cấu hình. Chỉ giữ một mạng Wi-Fi cho kết nối dự phòng; xem [hướng dẫn Wi-Fi](wifi-config.md). Quản lý RAM, flash và dữ liệu NVS tại System Monitor trên web.

## Xác minh cấu hình u-blox và UM

Sau khi lưu Fixed LLA, chọn **Xác minh cấu hình** trong phần trạng thái Base.
Cần cập nhật backend, giao diện và agent thiết bị: firmware ESP32 hoặc
`agent_universal.py`. Cả hai hỗ trợ u-blox và Unicore/UM. Backend lấy cấu hình
mong muốn từ bản đã lưu, không dùng tọa độ hay key do trình duyệt gửi lên.
Lệnh xác minh không lưu NVS/cấu hình, không thay đổi mode, không bật thêm
bản tin định kỳ hoặc tự khởi động lại chip. Truy vấn đi qua luồng UART đang
sở hữu cổng, không mở thêm một serial reader.

Với u-blox, chỉ poll CFG-TMODE3 và CFG-VALGET ở lớp RAM. Kết quả gồm bốn
nhóm: Fixed LLA/độ chính xác, giao thức đầu ra, các bản tin
NMEA/UBX đã cấu hình và 10 bản tin RTCM trong bộ cấu hình. Mỗi nhóm hiển thị
Khớp, Sai hoặc Chưa đọc được. Thiếu phản hồi, sai checksum, thiếu/trùng key,
phản hồi sai lớp đều không được coi là khớp. Tọa độ được so theo tổng phần
nguyên và HP; dung sai một bước lượng tử hóa: 1e-9 độ, 0.1 mm độ cao và
0.1 mm fixedPosAcc, để tránh báo lệch do chuyển đổi số thập phân/số thực.

ESP32 chuyển đầu ra USB/UART2 về UART1 nối GNSS; phép so sánh dùng UART1
cùng quy tắc đó. RTCM-only tắt NMEA và tốc độ định kỳ NAV-PVT/HPPOSLLH;
UBX protocol vẫn bật để chip trả lời lệnh đọc cấu hình. Nhận ACK không
đủ để kết luận các tham số đã khớp. `agent_universal.py` giữ đúng danh sách
cổng UART1/UART2/USB đã chọn; truy vấn được chia thành từng nhóm tối đa 40 key.

Với UM, đọc MODE, BESTNAVA và UNILOGLIST, kiểm tra checksum rồi đối chiếu
Fixed LLA, danh sách bản tin NMEA/RTCM và chu kỳ 1 giây. BESTNAV phải xác nhận
SOL_COMPUTED/FIXEDPOS/WGS84. Cấu hình ELLIPSOID so h = height_msl + undulation;
cấu hình LEGACY giữ cách hiểu độ cao cũ. Không so trường accuracy của u-blox
cho UM vì bộ tạo lệnh UM không thiết lập trường này. UNILOGLIST phải đủ số
dòng đã khai báo; sai CRC, trùng dòng, thiếu dữ liệu hoặc trigger chưa hỗ trợ
được coi là chưa đọc được, không coi là đã khớp.

Universal đối chiếu cổng COM3, đúng với bộ tạo lệnh UM trên backend. ESP32
đối chiếu GNSS_UNICORE_PORT = 1–3. Nếu dùng giá trị 0 (cổng hiện tại),
UNILOGLIST không chứng minh được số COM vật lý đang nối ESP32: phần bản tin
báo Chưa đọc được cùng ghi chú cổng, vẫn xác minh mode/tọa độ độc lập. Không
tự đoán COM hoặc thay đổi cấu hình đang chạy để lấy kết quả xanh.

Lệnh đọc UM theo [Unicore N4 Commands and Logs R1.2](https://ms.unicore.com/uploads/file/unicore-reference-commands-manual-for-n4-high-precision-products-v2-en-r1.2.pdf),
mục MODE, BESTNAV và UNILOGLIST (7.3.24).

Kết quả gắn command_id, hết hạn sau 60 giây và bị bỏ trên giao diện khi đổi
cấu hình hoặc thiết bị. Snapshot firmware chỉ tồn tại tạm trong RAM.
Kiểm tra này xác minh cấu hình đang chạy, không xác nhận toàn bộ bản tin
RTCM thực sự đang phát, tọa độ giải mã từ 1005 hoặc việc lưu bền qua mất
nguồn. Cần kiểm tra luồng RTCM và xác minh lại sau khởi động trên phần cứng.

Key Galileo 1094/1097 và BeiDou 1127, giới hạn 64 key mỗi VALSET,
CFG-VALGET v0 request/v1 response theo tài liệu chính thức:
[u-blox F9 HPG 1.32, UBX-22008968](https://content.u-blox.com/sites/default/files/documents/u-blox-F9-HPG-1.32_InterfaceDescription_UBX-22008968.pdf),
trang 89–90, 95–96 và 239–241. Kiểm tra host dùng các key độc lập từ tài
liệu, không chỉ so bảng Python với bảng C++.

### Bảng dữ liệu đọc trực tiếp từ chip

Kết quả xác minh hiện kèm bảng giá trị chip trả về, không chỉ số lượng khớp:

- u-blox: đọc riêng cả I2C, UART1, UART2, USB và SPI, kể cả cổng không được chọn
  trong cấu hình mong muốn. Mỗi cổng gồm ENABLED, ba OUTPROT UBX/NMEA/RTCM3X,
  tốc độ các bản tin trong bộ cấu hình Base (NMEA, NAV-PVT/HPPOSLLH, RTCM).
  UART1/UART2 đọc baud bằng CFG-PRT. Truy vấn CFG-VALGET RAM chứa tối đa 32
  key/cổng; không dùng wildcard, không phát VALSET và không thay đổi routing.
- TMODE3 trả về mode, kiểu tọa độ, tọa độ nguyên+HP và fixedPosAcc; UI hiển thị
  riêng giá trị thực tế và giá trị yêu cầu. Chu kỳ bản tin u-blox là số chu kỳ
  sự kiện/đo, không tự coi là giây hoặc Hz.
- UM: hiển thị toàn bộ log UNILOGLIST đã kiểm CRC, chia theo COM1/COM2/COM3,
  tên bản tin và period/ONCE. Kể cả ESP32 dùng cổng hiện tại chưa biết số COM,
  danh sách log thực tế vẫn được hiển thị; phần đối chiếu cổng giữ trạng thái
  chưa xác minh. BESTNAV hiển thị tọa độ, height_msl, undulation, datum và loại
  nghiệm độc lập với dữ liệu mong muốn.

Không có phản hồi thì hiển thị Chưa đọc được, không đổi thành giá trị 0/Tắt.
Giao thức bật không đồng nghĩa cổng vật lý bật: ENABLED được đọc và hiển thị
riêng; cổng yêu cầu nhưng ENABLED=0 được đánh dấu lệch. Người dùng chọn cổng
để xem tốc độ từng bản tin, bật/tắt bộ lọc hiển thị log đang bật.

Agent vẫn giải phóng snapshot RAM sau 60 giây. Trình duyệt giữ lần đọc để xem
chi tiết, đánh dấu cũ sau 60 giây; đổi trạm/cấu hình sẽ bỏ snapshot. ESP32 bỏ
snapshot NVS trước khi tạo snapshot GNSS, tránh cộng dồn hai bảng theo yêu cầu.
