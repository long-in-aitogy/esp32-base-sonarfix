# Nhật ký ngoại lệ SonarQube

Project [`tundzai001_esp32-base-sonarfix`](https://sonarcloud.io/project/overview?id=tundzai001_esp32-base-sonarfix), nhánh `main` tại commit `e4aec07` (18-11-2026).

Trạng thái hiện tại: **0 issue Open/Confirmed**, chỉ còn **5 issue Accepted** có lý do kỹ thuật rõ ràng:

| Issue | Quy tắc | Vị trí | Trạng thái | Lý do chấp nhận |
| --- | --- | --- | --- | --- |
| [AaHvFOkjRdtTDdCBWRPu](https://sonarcloud.io/project/issues?id=tundzai001_esp32-base-sonarfix&open=AaHvFOkjRdtTDdCBWRPu) | `cpp:S1238` | `src/functions/mqtt/MQTT_Manager.cpp:32` | Accepted | Bắt buộc khớp chữ ký hàm thuần ảo `virtual int connect(IPAddress ip, uint16_t port) = 0;` trong `Client.h` của Arduino SDK; không thể đổi sang `const IPAddress &`. |
| [AaHT6_xzDfen3veeSkHa](https://sonarcloud.io/project/issues?id=tundzai001_esp32-base-sonarfix&open=AaHT6_xzDfen3veeSkHa) | `cpp:S5566` | `src/functions/backend/Backend_Agent_Gnss.cpp:59` | Accepted | `ArduinoJson::JsonArrayConst::iterator` ở ArduinoJson v6 không tương thích với `std::any_of` (gây lỗi biên dịch). |
| [AaHAB4UGwAMFQ7NSc-iF](https://sonarcloud.io/project/issues?id=tundzai001_esp32-base-sonarfix&open=AaHAB4UGwAMFQ7NSc-iF) | `cpp:S1448` | `include/functions/backend/Backend_Agent.h:26` | Accepted | `BackendAgent` đã được tách mã nguồn theo từng file trách nhiệm (`Commands`, `Status`, `Storage`, `Workflows`, `Gnss`, `Startup`, `Websocket`); tách class sẽ ảnh hưởng hơn 30 test harness hiện có. |
| [AaHAB4UGwAMFQ7NSc-iE](https://sonarcloud.io/project/issues?id=tundzai001_esp32-base-sonarfix&open=AaHAB4UGwAMFQ7NSc-iE) | `cpp:S1820` | `include/functions/backend/Backend_Agent.h:26` | Accepted | Cùng phạm vi với `cpp:S1448` trên `BackendAgent`; giữ nguyên cấu trúc trường nội bộ để tránh rủi ro lệch trạng thái và vỡ test harness. |
| [AaHT6_xUDfen3veeSkGp](https://sonarcloud.io/project/issues?id=tundzai001_esp32-base-sonarfix&open=AaHT6_xUDfen3veeSkGp) | `cpp:S2068` | `include/Prog_Config.h:53` | Accepted | Mật khẩu mặc định `AUTO_BASE_CASTER_PASSWORD` cho profile AutoNearest nội bộ, có thể ghi đè qua cấu hình thực tế. |
