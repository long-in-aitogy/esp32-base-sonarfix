# Đối chiếu lịch sử sync-functions

Phạm vi: 37 commit từ `develop` (`c921c25`) đến `sync-functions` (`8af74b7`). Commit `19d2de0` trong repo này đã nhập đúng cây nội dung của `8af74b7`; các thay đổi sau đó được áp dụng từng commit. Nguồn CORS được đối chiếu tại `7db656b`.

Các commit CORS mới nhất liên quan đến ESP32 đã đối chiếu theo hành vi:

| Commit CORS | Kết quả đối chiếu trên `main` |
| --- | --- |
| `7db656b` | Giữ tùy chọn GNSS khi áp dụng Fixed LLA, xác nhận receiver và báo cấu hình đã áp dụng. Kiểm tra bằng `check_fixed_output_options.py`, `check_autobase_config.py` và `check_workflow_restore.py`. Accuracy giữ 5 m. |
| `d5a9e61` | AutoNearest mặc định dùng host và mountpoint tương ứng; các mặc định MQTT/NTRIP độc lập vẫn giữ theo `develop`. |
| `149014a` | Auto Base báo Fixed LLA sau áp dụng; fallback Survey-In được lưu và báo hoàn thành. Kiểm tra bằng `check_auto_base_status.py` và `check_auto_nearest_workflow.py`. |
| `84371e0` | Giữ cấu hình AutoNearest trong `Prog_Config.h`, như nguồn sau revert. |
| `b2f4254`, `1d89155` | Hai SOURCE và lỗi ghi thiếu được kiểm tra bằng `check_ntrip_source_connect.py`; tách thông tin AutoNearest khỏi SOURCE đang chạy. |
| `540d46b`, `754f3ca` | Kiểm tra handshake, khởi động và khôi phục bằng bộ host tương ứng trong repo này; cấu trúc bài kiểm tra có khác nguồn. |
| `ef0631c`, `236072e`, `e43b82a` | Có log từ chối caster, fallback và bộ khởi động AutoNearest tại thiết bị; kiểm tra bằng `check_auto_nearest_workflow.py`, `check_autocors_scheduler.py`. |
| `376b9f9` | Chủ ý không đặt lại Base sang AutoNearest ở mọi lần khởi động: giữ cấu hình đã lưu theo yêu cầu bảo toàn `develop`. |
| `7141523`, `88edbe0` | Giữ kết nối khi cấu hình dịch vụ không đổi và xử lý SOURCE ACK; kiểm tra bằng `check_service_config.py`, `check_ntrip_handshake.py`. |
| `ae200f9` | Có AutoNearest, lựa chọn mountpoint và fallback Survey-In; bảo toàn cấu hình cũ để phục hồi nếu workflow thất bại. |
| `87e0f62` | Xác minh cấu hình Unicore bằng MODE BASE, hỗ trợ chọn cổng và thử lại xác nhận Fixed LLA đến muộn. Các bài `check_unicore_verify_command.py`, `check_unicore_fixed_readback.py`, `check_workflow_restore.py` đạt. |
| `c60bd2b` | Parser xác minh cấu hình Unicore trong hai cây giống nhau; các bài kiểm tra response không đầy đủ, cổng và checksum BESTNAV đạt. |

Bộ tạo lệnh Survey-In và Fixed LLA của hai cây cho cùng chuỗi byte trong 72 trường hợp đại diện: hai loại receiver, RTCM-only/diagnostics, MSM4/MSM7/cả hai và ba tập chòm sao, với accuracy 5 m và tọa độ trên lưới receiver. Đây không phải xác nhận receiver thực đã nhận hoặc áp dụng lệnh.

Tên bài kiểm tra chỉ chỉ ra phạm vi liên quan, không tự chứng minh mọi nhánh hoặc hoạt động thực tế trên receiver và caster.

Ngày 12/11/2026, 23 bài kiểm tra Python độc lập trong danh sách dưới đây đã chạy đạt trên firmware hiện tại. `check_cors_accuracy.py` được chạy riêng với mã backend CORS và binary host. Tên bài kiểm tra là bằng chứng kiểm tra liên quan, không chứng minh mọi hành vi của commit; các mục không có bài Python cần xem mã hoặc chạy bài C++ tương ứng.

Kiểm tra lại sau các thay đổi đồng bộ: cây Git của `19d2de0` và `sync-functions` đều là `5c5890e`; so với điểm nhập đó, không có tệp nào bị xóa khỏi cây `main` hiện tại. Các bài nhận diện GNSS, MON-VER, BESTNAV, Rover và ghi NTRIP đều đạt. Điều này xác nhận điểm xuất phát và các luồng được kiểm thử, không thay thế việc xem xét hành vi trong các tệp đã sửa.

| Commit | Nội dung | Bài kiểm tra gắn với commit |
| --- | --- | --- |
| `39bbbee` | fix(ntrip): preserve streams on repeated config | Không có bài trong commit |
| `113db51` | fix(ntrip): accept immediate SOURCE acknowledgements | `check_ntrip_handshake.py` |
| `e84d345` | fix(backend): own workflow progress JSON keys | `check_workflow_progress.py` |
| `a935437` | fix(backend): snapshot active Survey-In duration | `check_survey_snapshot.py` |
| `621132c` | fix(backend): restore receiver mode after workflows | `check_workflow_restore.py` |
| `1feb849` | refactor(backend): separate codecs and stored state | Không có bài trong commit |
| `f85e87d` | build(sonar): align scanner scopes and compile inputs | Không có bài trong commit |
| `0448286` | fix(backend): own dynamic service config keys | `check_service_config.py` |
| `282369f` | fix(backend): preserve workflow restore invariants | `check_survey_snapshot.py`, `check_workflow_restore.py`, `check_workflow_validation.py` |
| `ad8bd21` | chore: enforce consistent incremental merge checks | `check_rover_gga.py` |
| `0489fbd` | fix(ntrip): separate rover status from byte counts | `check_rover_status.py` |
| `d5670c2` | fix(ntrip): report reconnect success immediately | `check_ntrip_reconnect.py` |
| `2f4437e` | fix(ntrip): log connection state changes only | Không có bài trong commit |
| `67afe60` | fix(gnss): derive ellipsoid height from GGA | `check_gga_position.py` |
| `089da8c` | fix(gnss): align Unicore coordinate precision | `base_checks.cpp` |
| `498ee33` | fix(backend): preserve Auto Base configuration | `check_autobase_config.py` |
| `52976fc` | fix(backend): handle Auto Base transport restore failure | `check_autobase_config.py` |
| `9d3e5a3` | fix(backend): verify Auto Base receiver readback | `check_autobase_config.py` |
| `8383284` | fix(gnss): enforce 5 m base accuracy | `base_checks.cpp`, `check_autobase_config.py`, `check_base_accuracy.py`, `check_cors_accuracy.py`, `check_workflow_restore.py` |
| `5a25387` | fix(gnss): preserve fixed Base output options | `check_fixed_output_options.py` |
| `a33f493` | fix(ntrip): detect incomplete GNSS UART writes | `check_rover_status.py` |
| `fca143f` | fix(gnss): recover delayed fixed position readback | `check_workflow_restore.py` |
| `8f09442` | feat(gnss): report u-blox navigation quality | `check_ublox_navigation.py` |
| `612c661` | feat(gnss): report Unicore horizontal quality | `check_ublox_navigation.py`, `check_unicore_quality.py` |
| `4aeeb9d` | fix(websocket): validate upgrade handshake | `check_websocket_upgrade.py`, `protocol_checks.cpp` |
| `d24ae80` | fix(websocket): reject unsupported server frames | `check_websocket_frames.py` |
| `9fb12cf` | fix(websocket): release unused receive buffers | `check_websocket_frames.py` |
| `93b39b4` | fix(ntrip): report actionable rover errors | `check_rover_connect.py` |
| `74b95b3` | feat(ntrip): send fresh GGA in rover request | `check_rover_connect.py` |
| `4ff3734` | feat(ntrip): capture caster-selected mountpoint | `check_ntrip_handshake.py`, `check_rover_connect.py` |
| `45bedd6` | fix(backend): validate workflow caster port before conversion | `check_workflow_connection_config.py` |
| `1f4a53f` | feat(backend): use caster selection for AutoNearest | `check_auto_nearest_workflow.py`, `check_rover_connect.py` |
| `65ab601` | fix(backend): restore rover when AutoNearest is unconfigured | `check_auto_nearest_workflow.py`, `check_workflow_restore.py`, `check_workflow_validation.py` |
| `25d2e79` | fix(backend): reject failed Auto Base coordinate conversion | `check_auto_base_transform.py` |
| `95cdca7` | fix(backend): require auto apply for measured base position | `check_auto_base_transform.py`, `check_auto_nearest_workflow.py`, `check_autobase_command.py` |
| `2750929` | fix(backend): preserve AutoNearest source in base config | `check_autobase_config.py` |
| `8af74b7` | fix(backend): report Survey-In fallback as completed | `check_auto_base_status.py` |

Lệnh đổi tỉnh VN2000 được giữ theo lựa chọn của người dùng; firmware lưu tọa độ gốc, yêu cầu readback xác nhận và báo lỗi nếu lưu thất bại. CORS hiện yêu cầu xem lại trước khi áp dụng. Bản build `tdm240x_dev_general` dùng `no_ota.csv` và NVS cũ, khác bảng phân vùng CORS có `agent_state`; chưa thay bảng vì cần bảo toàn dữ liệu thiết bị.

Danh mục 34 tỉnh trong firmware được đối chiếu với `coordinate_provinces.json` của CORS: Lai Châu dùng 103°; 17 tỉnh có nhiều kinh tuyến cũ yêu cầu lệnh gửi thêm `l0_deg` thuộc danh sách tương ứng. Lệnh thiếu lựa chọn hoặc chọn ngoài danh sách bị từ chối trước khi ghi receiver. Chạy `python3 test/host/compare_province_catalog.py /duong-dan/cors` để đối chiếu lại danh mục.

Đã đối chiếu luồng NTRIP của CORS với ba mô-đun `ntrip_base`, `ntrip_common` và `ntrip_rover`. Giữ xử lý hiện tại: không kết thúc luồng chunked khi chờ dữ liệu, đóng riêng kết nối ghi thiếu, và phân biệt phiên Rover đang hoạt động với workflow đang khôi phục SOURCE. Các bài host kiểm tra bắt tay, hai SOURCE, ghi thiếu, Rover và khóa khi khôi phục đều đạt; chưa kiểm tra với caster thực.

Các tệp không còn cùng đường dẫn đã được đối chiếu theo chức năng: quản lý mạng nằm trong `main.cpp`; nhận diện GNSS nằm trong `ntrip_base.cpp`; định tuyến log Unicore nằm trong `Unicore_Log.h`; NTRIP được tách thành ba mô-đun. `math_functions.c` phía CORS là tệp rỗng. Các hàm đọc datum RTCM được chuyển sang `Vn2000_Datum.cpp` và đã kiểm tra cùng dữ liệu tham chiếu Python.

Đối chiếu trực tiếp `Unicore_Output.h` của CORS với `routeUnicoreOutput` trong `Unicore_Log.h`: kết quả trùng nhau trên 200.000 trường hợp đầu vào và cổng, gồm lệnh RTCM, NMEA, lệnh khác và dữ liệu ngẫu nhiên (seed 12345). Đây là kiểm thử host, chưa xác nhận cổng vật lý trên receiver.

Đối chiếu bộ giải mã Base64 dùng cho lệnh receiver: hai bản cho cùng kết quả trên 100.000 đầu vào ngẫu nhiên (seed 3248); bản hiện tại bổ sung kiểm tra bộ đệm null. Kiểm thử batch lệnh và ghi thiếu vẫn giữ trong bộ host.

Tại CORS `7db656b`, toàn bộ nội dung `Vn2000_Datum.cpp` trùng phần đầu `Backend_Agent_Projection.cpp` của nguồn. Bộ host kiểm tra CRC, chia nhỏ và reset RTCM, gói 1025 M3/M6 và phép chuyển với dữ liệu tham chiếu đạt. Dữ liệu datum thuộc phiên Rover: khởi tạo lại khi bắt đầu phiên mới; kiểm tra luồng Rover và trường hợp đọc 504 byte đạt.

Khởi động có chủ ý khác CORS: CORS đặt lại Base sang AutoNearest mỗi lần khởi động; nhánh này giữ và khôi phục chế độ, tọa độ hoặc thời gian Survey-In đã lưu theo yêu cầu bảo toàn cấu hình. Fixed LLA chỉ được xác nhận sau readback phù hợp. Đã đối chiếu tên 17 lệnh backend trong CORS với nhánh này; trùng tên không tự chứng minh toàn bộ hành vi giống nhau. Nền tảng PlatformIO đã đồng bộ 7.1.3 với CORS; ba môi trường firmware và bộ kiểm tra modem đều biên dịch thành công; bảng phân vùng vẫn giữ theo từng môi trường của nhánh này.

Các bài host và build không thay thế nghiệm thu trên receiver thật: cần kiểm tra BESTPOS, accuracy cấu hình 5 m, nguồn RTCM, mất kết nối, khởi động lại và tọa độ ngoài thực địa.

Với Unicore, trường JSON `bestpos` hiện được tạo từ bản tin receiver `BESTNAVA` (giống CORS và `develop`), không phải từ lệnh `BESTPOSA`. Firmware kiểm tra trạng thái FIXEDPOS, tọa độ và độ cao từ readback; kiểm thử host dùng phản hồi mô phỏng, chưa xác minh bản tin trên thiết bị thực.

Đã đối chiếu phục hồi mạng và chuyển SIM/Wi-Fi với `Network_Manager.cpp` của CORS. Giữ giá trị mật khẩu dự phòng của `develop` khi NVS chưa có `WIFI_PASS`; CORS dùng `WIFI_PASSWORD`. Đổi mặc định có thể khiến thiết bị cũ thiếu khóa này không kết nối được. Các mạng đã lưu vẫn được ưu tiên; bộ kiểm tra host xác minh chuyển cấu hình, phục hồi Wi-Fi và lệnh nhập thông tin.

Cấu hình mặc định MQTT và NTRIP cũng khác CORS: `develop` dùng MQTT `45.117.179.134`, NTRIP `aitogy.com.vn` và mountpoint `/test`; CORS dùng MQTT `aitogy.click` và mountpoint `test_esp`. Giữ mặc định của `develop` vì chưa xác minh được tính tương đương của các máy chủ và mountpoint. Cấu hình đã lưu trong NVS vẫn được ưu tiên; các giá trị mặc định ảnh hưởng thiết bị chưa có cấu hình hoặc sau khi đặt lại. Cấu hình AutoNearest riêng đã đồng bộ với CORS tại `d5a9e61`.

Phần SIM giữ cách chọn APN của `main`: ưu tiên APN đã lưu, tự nhận diện nhà mạng nếu để trống hoặc `auto`, rồi dùng APN cấu hình nếu không nhận diện được. CORS dùng APN mặc định ngay khi thiếu khóa lưu; không thay hành vi này để tránh bỏ qua lựa chọn nhà mạng trên thiết bị hiện tại. Kiểm tra APN, receiver và các luồng NTRIP liên quan đã được đưa vào CI.

Ngày 12/11/2026, kiểm tra lại tại `afeb4e5`: 71 bài `check_*.py` chạy không cần thiết bị đều đạt; hai bài tích hợp lệnh CORS chạy riêng với bộ tạo lệnh thực cũng đạt. Ba cấu hình firmware `tdm240x_dev_general`, `tdm240x_dev_general_debug` và `tdm240x_dev_general_test` biên dịch thành công. `check_status_flash.py` cần cổng ESP32 thật và chưa được chạy; lúc kiểm tra không có cổng thiết bị phù hợp. Kết quả này không chứng minh hoạt động thực địa hay CI GitHub đã chạy.

Khi đối chiếu lưu NVS với CORS, giữ phần chuyển `SURVEY_RESULT` và thử lưu lại kết quả Survey-In khi ghi thất bại của `main`. Các kiểm tra chuyển dữ liệu, lỗi NVS, che thông tin nhạy cảm và khôi phục tiến độ đã đạt và được bổ sung vào CI. Chưa thay phân vùng lưu trên thiết bị.

Build bổ sung tại `d1ba249` với cả `BACKEND_WEBSOCKET_ENABLED=1` và `BACKEND_PUBLISH_RAW_RTCM=1` đã thành công. Đây là kiểm tra biên dịch hai tùy chọn, chưa chứng minh kết nối thực hoặc lượng heap khi chạy.

Đã đối chiếu đọc cấu hình u-blox với CORS và giữ kiểm tra đầu vào, lỗi mã hóa và giới hạn tuổi dữ liệu của `main`. Kiểm tra MON-VER, TMODE3, VALGET, NAV-SAT, NAV-PVT/NAV-DOP và bộ đệm phản hồi đã đạt trên host và được thêm vào CI.

Đã đối chiếu WebSocket với CORS và giữ kiểm tra bắt tay, khung không hỗ trợ, giải phóng bộ đệm và xử lý ghi thiếu của `sync-functions`. Các kiểm tra handshake, khung dữ liệu, ghi điều khiển và bản tin trạng thái lớn đều đạt trên host và đã thêm vào CI.

Đối chiếu các khóa JSON được gán trực tiếp trong `Backend_Agent_Status.cpp` của CORS `7db656b` không thấy khóa nguồn bị thiếu trong tệp tương ứng; đây là kiểm tra tên trường, không chứng minh toàn bộ giá trị tương đương. Bản hiện tại chỉ báo hỗ trợ xác minh GNSS với chip đã nhận diện và bỏ kết quả xác minh cũ sau 60 giây. Kiểm tra trạng thái gần đầy, WebSocket trên 8 KB, lỗi publish và fallback Survey-In đều đạt trên host.

Với lệnh AutoNearest đã có địa chỉ CORS, `main` giữ cấu hình Base trước đó khi tác vụ đang chạy; CORS lưu `AUTO_CORS` ngay khi nhận lệnh. Giữ hành vi `main` để có thể khôi phục cấu hình cũ nếu tác vụ thất bại hoặc bị dừng. Với yêu cầu AutoNearest chưa có nguồn, firmware vẫn lưu yêu cầu và bản chụp cấu hình cũ để chờ nguồn.

Kiểm tra lại tại `2345ed8`: 76 bài host không cần thiết bị đều đạt; hai bài dùng bộ tạo lệnh CORS thực cũng đạt, gồm kiểm tra accuracy 5 m cho Survey-In và Fixed LLA. Danh mục kinh tuyến 34 tỉnh khớp CORS. Ba cấu hình firmware `general`, `general_debug` và `general_test` cùng chương trình test modem biên dịch thành công; test modem chưa được chạy. Bộ tạo lệnh u-blox và báo cáo Auto Base dùng cùng cách tính tọa độ để giữ nguyên kết quả khi áp dụng lại. Chưa chạy kiểm tra flash hoặc xác nhận BESTPOS trên thiết bị thật; không có cổng ESP32 được kết nối. Các thay đổi CI mới chưa được chạy trên GitHub.

Kiểm tra lại tại `55ccb7d`: 79 bài Python host không cần thiết bị đều đạt. Hai bài tích hợp CORS chạy riêng với bộ lệnh thực đều đạt, gồm kiểm tra accuracy 5 m trên u-blox TMODE3 và VALSET; danh mục kinh tuyến 34 tỉnh khớp CORS. Bộ kiểm tra lệnh receiver C++ và ba bản build `general`, `general_debug`, `general_test` đều đạt. Các bài kiểm tra mới xác nhận việc cấp thiết bị, chuyển failover và chuyển từ Wi-Fi dự phòng về SIM không chủ động ngắt workflow Rover trong các tình huống đã mô phỏng. Chưa có cổng ESP32 để kiểm tra flash, BESTPOS hoặc hoạt động mạng và receiver thực; CI GitHub cho các commit mới chưa được xác nhận.

Đối chiếu bổ sung các commit CORS trước nhóm AutoNearest: `0ca16f3` về xem NVS và Wi-Fi, `eab8af7` về UNILOGLIST, `5d915cd` về phiên bản receiver, `74a204b` về vệ tinh, `305eaa9` và `1a759a1` về DOP/chất lượng, `befb69d` về cấu hình theo cổng. Các bài host tương ứng `check_nvs_inventory.py`, `check_wifi_migration.py`, `check_unicore_log_list.py`, `check_ublox_version.py`, `check_ublox_satellites.py`, `check_ublox_navigation.py` và `check_ublox_output_readback.py` đạt trên `f931459`. CORS đã gỡ chẩn đoán RF khỏi ESP32 tại `a0e8fd8`; không phục hồi các commit RF cũ. Firmware báo `V2.4.2`. Những bài này kiểm tra các trường hợp mô phỏng, không xác nhận thiết bị thật.

Đối chiếu bộ tách dữ liệu GNSS tại `13b0329` với CORS `7db656b`: cả hai chuyển tiếp khung RTCM đầy đủ mà không tự kiểm tra CRC; byte đầu khung không hợp lệ được xét lại để bắt đầu khung khác. Bản hiện tại kiểm tra tọa độ GGA chặt hơn và xóa tọa độ cũ khi GGA thiếu vị trí. Kiểm tra 30 chu kỳ GGA/UBX/RTCM xen kẽ, phục hồi dữ liệu lỗi, GGA, 504 byte Rover, ghi NTRIP thiếu và chuyển VN2000 đều đạt trên host. Đây không phải kiểm tra dòng UART thực hoặc chất lượng dữ liệu caster.

Danh sách tệp kiểm thử CORS không có cùng tên trên `main`, đối chiếu tại `4eb9225`: `check_auto_base_boot.py`, `check_backend_lifecycle.py`, `check_backend_storage.py`, `check_base_startup_confirmation.py`, `check_command_dispatch.py`, `check_gnss_lifecycle.py`, `check_network_lifecycle.py`, `check_ntrip_source.py`, `check_projection_audit.py`, `check_status_stream.py`, `check_ublox_verification.py`, `check_wifi_handover.py`, `check_wifi_nvs.py`, `check_workflow_lifecycle.py`, `codec_checks.cpp`, `config_verification_checks.cpp`, `firmware_coverage_inventory.py`, `host_coverage.py`, `readback_checks.cpp`, `run_coverage.py`, `sample_checks.cpp`, `test_coverage_report.py`, `test_firmware_inventory.py`. Đây là danh sách tên tệp, không phải 23 tính năng bị thiếu: mã đích đã có các bài kiểm tra riêng cho nhiều luồng tương ứng. Cần đối chiếu từng nội dung và cách tổ chức khác nhau trước khi kết luận phạm vi còn thiếu.

Đã chạy trực tiếp hai bài C++ từ cây CORS với header và mã đích: `sample_checks.cpp` đạt các biên thời gian mẫu, tràn đồng hồ và độ cao GGA; `config_verification_checks.cpp` đạt các trường hợp xác minh u-blox/Unicore, danh sách log và checksum. `codec_checks.cpp` cũng đạt khi biên dịch mã đích sau khi điều chỉnh tạm lời gọi Base64 theo API đích và bổ sung `substring` vào Arduino giả lập; không sửa bài kiểm tra gốc. Chưa đối chiếu hết các tệp còn lại trong danh sách trên.

Tại `45f2699`, 83/83 bài `check_*.py` không cần thiết bị và không cần đường dẫn CORS riêng đã chạy đạt. Đối chiếu `check_backend_storage.py` và `check_base_startup_confirmation.py` của CORS: nhánh đích có các bài kiểm tra riêng cho giữ cấu hình dịch vụ, cấu hình quá lớn, xác minh Unicore theo cổng và readback Fixed LLA. Đây là đối chiếu những trường hợp đã nêu, chưa phải chứng minh toàn bộ nhánh của hai bài CORS. Thay đổi gần nhất đã build `tdm240x_dev_general`; chưa kiểm tra phần cứng hoặc CI GitHub.

Ba bài CORS `check_backend_storage.py`, `check_base_startup_confirmation.py`, `check_workflow_lifecycle.py` chưa thể chạy trực tiếp trên cây đích: harness phụ thuộc cấu trúc hàm và kiểu dữ liệu trước khi tách mô-đun. Đích đã kiểm tra riêng nhiều phần, bao gồm chờ RTK, lấy mẫu và phục hồi, nhưng chưa có bằng chứng tương đương cho toàn bộ bài workflow tích hợp CORS. Cần chuyển harness hoặc đối chiếu từng kịch bản trước khi coi mục này hoàn tất.
