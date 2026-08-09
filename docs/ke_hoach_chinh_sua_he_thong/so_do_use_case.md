# Tinh chỉnh lại hệ thống

Hệ thống hiện tại đang xây dựng theo notebookLM. Tuy nhiên, sau những góp ý mentor thì theo phán đoán thì hệ thống các anh muốn hướng đến là như sau:
 - Sẽ có người upload dữ liệu lên, và nhân viên có thể truy vấn thông tin trong chat bot
 - Yêu cầu đầu vào chất lượng , đầu ra nhanh và chính xác

# Sơ đồ usecase 

flowchart LR

    %% =========================
    %% ACTORS
    %% =========================

    EMP["👤 Employee<br/>Nhân viên"]

    ADMIN["👤 Admin<br/>Quản trị hệ thống"]


    %% =========================
    %% SYSTEM
    %% =========================

    subgraph SYS["ENTERPRISE RAG PLATFORM"]

        direction TB


        %% =====================
        %% COMMON
        %% =====================

        subgraph COMMON["1. TÀI KHOẢN"]
            UC_LOGIN(["Đăng nhập"])
            UC_LOGOUT(["Đăng xuất"])
        end


        %% =====================
        %% EMPLOYEE
        %% =====================

        subgraph EMPLOYEE_UC["2. TRA CỨU TRI THỨC"]

            UC_SEARCH(["Tìm kiếm tài liệu"])

            UC_FILTER(["Lọc tài liệu"])

            UC_VIEW_DOC(["Xem chi tiết tài liệu"])

            UC_DOWNLOAD(["Tải tài liệu"])

            UC_ASK(["Đặt câu hỏi"])

            UC_VIEW_ANSWER(["Xem câu trả lời"])

            UC_CITATION(["Xem nguồn trích dẫn"])

            UC_OPEN_SOURCE(["Mở tài liệu nguồn"])

            UC_FEEDBACK(["Đánh giá câu trả lời"])

            UC_REPORT(["Báo cáo câu trả lời có vấn đề"])
        end


        %% =====================
        %% ADMIN DOCUMENT
        %% =====================

        subgraph DOCUMENT_UC["3. QUẢN LÝ TÀI LIỆU"]

            UC_UPLOAD(["Upload tài liệu"])

            UC_LIST_DOC(["Xem danh sách tài liệu"])

            UC_ADMIN_VIEW_DOC(["Xem chi tiết tài liệu"])

            UC_EDIT_META(["Chỉnh sửa metadata"])

            UC_NEW_VERSION(["Tạo phiên bản mới"])

            UC_VIEW_VERSION(["Xem lịch sử phiên bản"])

            UC_REVIEW(["Kiểm duyệt tài liệu"])

            UC_APPROVE(["Phê duyệt"])

            UC_REJECT(["Từ chối"])

            UC_PUBLISH(["Publish tài liệu"])

            UC_ARCHIVE(["Archive tài liệu"])

            UC_REPROCESS(["Yêu cầu xử lý lại"])
        end


        %% =====================
        %% ADMIN PERMISSION
        %% =====================

        subgraph PERMISSION_UC["4. QUẢN LÝ NGƯỜI DÙNG & PHÂN QUYỀN"]

            UC_USER(["Quản lý người dùng"])

            UC_ROLE(["Quản lý vai trò"])

            UC_GROUP(["Quản lý nhóm"])

            UC_DEPARTMENT(["Quản lý phòng ban"])

            UC_ACCESS_POLICY(["Thiết lập quyền truy cập tài liệu"])

            UC_GRANT(["Cấp quyền"])

            UC_REVOKE(["Thu hồi quyền"])

            UC_ACCESS_MATRIX(["Xem ma trận quyền"])

            UC_TEST_ACCESS(["Kiểm tra quyền truy cập"])
        end


        %% =====================
        %% ADMIN MONITORING
        %% =====================

        subgraph GOVERNANCE_UC["5. GIÁM SÁT & QUẢN TRỊ"]

            UC_PROCESS_STATUS(["Xem trạng thái xử lý tài liệu"])

            UC_FAILED(["Xem tài liệu xử lý lỗi"])

            UC_RETRY(["Retry xử lý"])

            UC_AUDIT(["Xem Audit Log"])

            UC_ANALYTICS(["Xem thống kê truy vấn"])

            UC_FEEDBACK_ADMIN(["Xem feedback người dùng"])
        end

    end


    %% =========================
    %% EMPLOYEE RELATIONSHIPS
    %% =========================

    EMP --> UC_LOGIN

    EMP --> UC_SEARCH

    EMP --> UC_VIEW_DOC

    EMP --> UC_ASK

    EMP --> UC_FEEDBACK

    EMP --> UC_REPORT

    EMP --> UC_LOGOUT


    %% =========================
    %% ADMIN RELATIONSHIPS
    %% =========================

    ADMIN --> UC_LOGIN

    ADMIN --> UC_UPLOAD

    ADMIN --> UC_LIST_DOC

    ADMIN --> UC_ADMIN_VIEW_DOC

    ADMIN --> UC_EDIT_META

    ADMIN --> UC_NEW_VERSION

    ADMIN --> UC_VIEW_VERSION

    ADMIN --> UC_REVIEW

    ADMIN --> UC_PUBLISH

    ADMIN --> UC_ARCHIVE

    ADMIN --> UC_REPROCESS

    ADMIN --> UC_USER

    ADMIN --> UC_ROLE

    ADMIN --> UC_GROUP

    ADMIN --> UC_DEPARTMENT

    ADMIN --> UC_ACCESS_POLICY

    ADMIN --> UC_ACCESS_MATRIX

    ADMIN --> UC_TEST_ACCESS

    ADMIN --> UC_PROCESS_STATUS

    ADMIN --> UC_FAILED

    ADMIN --> UC_AUDIT

    ADMIN --> UC_ANALYTICS

    ADMIN --> UC_FEEDBACK_ADMIN

    ADMIN --> UC_LOGOUT


    %% =========================
    %% INCLUDE / EXTEND
    %% =========================

    UC_SEARCH -. "«include»" .-> UC_FILTER

    UC_SEARCH -. "«include»" .-> UC_VIEW_DOC

    UC_VIEW_DOC -. "«extend»" .-> UC_DOWNLOAD


    UC_ASK -. "«include»" .-> UC_VIEW_ANSWER

    UC_VIEW_ANSWER -. "«include»" .-> UC_CITATION

    UC_CITATION -. "«extend»" .-> UC_OPEN_SOURCE

    UC_VIEW_ANSWER -. "«extend»" .-> UC_FEEDBACK

    UC_VIEW_ANSWER -. "«extend»" .-> UC_REPORT


    UC_REVIEW -. "«extend»" .-> UC_APPROVE

    UC_REVIEW -. "«extend»" .-> UC_REJECT

    UC_APPROVE -. "«include»" .-> UC_PUBLISH


    UC_ACCESS_POLICY -. "«include»" .-> UC_GRANT

    UC_ACCESS_POLICY -. "«include»" .-> UC_REVOKE

    UC_ACCESS_POLICY -. "«include»" .-> UC_TEST_ACCESS


    UC_FAILED -. "«extend»" .-> UC_RETRY


## Đặt tả usecase

### Use case đăng ký bằng tài khoản công ty

| Thuộc tính                  | Mô tả                                                                                                                                                                                                                                               |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**            | Đăng ký bằng tài khoản công ty                                                                                                                                                                                                                      |
| **Actor chính**             | Nhân viên                                                                                                                                                                                                                                           |
| **Mục tiêu**                | Cho phép nhân viên sử dụng email và mật khẩu do công ty cấp để xác minh danh tính và tạo tài khoản sử dụng hệ thống.                                                                                                                 |
| **Điều kiện kích hoạt**     | Nhân viên lần đầu truy cập hệ thống và chọn chức năng **Đăng ký bằng tài khoản công ty**.                                                                                                                                            |
| **Điều kiện tiên quyết**    | 1. Nhân viên đã được công ty cấp email và mật khẩu hợp lệ.<br>2. Tài khoản công ty của nhân viên đang hoạt động.<br>3. Nhân viên chưa có tài khoản tương ứng trên hệ thống.<br>4. Dịch vụ xác thực tài khoản công ty đang hoạt động. |
| **Đầu vào**                 | Email công ty và mật khẩu do công ty cấp.                                                                                                                                                                                                           |
| **Trạng thái — Thành công** | Danh tính nhân viên được xác minh; tài khoản sử dụng hệ thống được tạo hoặc kích hoạt và liên kết với tài khoản công ty; nhân viên có thể sử dụng hệ thống theo quyền được cấp.                                                      |
| **Trạng thái — Thất bại**   | Không tạo hoặc kích hoạt tài khoản hệ thống, nhân viên không được truy cập các chức năng yêu cầu xác thực.                                                                                                                                    |
| **Use Cases liên quan**     | Đăng nhập                                                                                                                                                                                                                                           |

### Main Flow

| Bước | Actor     | Hành động                                                                                                       |
| ---: | --------- | --------------------------------------------------------------------------------------------------------------- |
|    1 | Nhân viên | Truy cập Enterprise RAG Platform lần đầu.                                                                       |
|    2 | Nhân viên | Chọn chức năng **Đăng ký bằng tài khoản công ty**.                                                              |
|    3 | System    | Hiển thị giao diện yêu cầu nhập tài khoản công ty.                                                              |
|    4 | Nhân viên | Nhập email công ty và mật khẩu đã được công ty cấp.                                                             |
|    5 | Nhân viên | Gửi yêu cầu đăng ký.                                                                                            |
|    6 | System    | Kiểm tra tính đầy đủ và hợp lệ của dữ liệu đầu vào.                                                             |
|    7 | System    | Xác minh email và mật khẩu với hệ thống quản lý tài khoản của công ty.                                          |
|    8 | System    | Kiểm tra trạng thái tài khoản công ty của nhân viên.                                                            |
|    9 | System    | Kiểm tra tài khoản công ty đã được liên kết với tài khoản Enterprise RAG nào chưa.                              |
|   10 | System    | Xác định thông tin định danh của nhân viên từ tài khoản công ty.                                                |
|   11 | System    | Tạo tài khoản hoặc hồ sơ người dùng tương ứng trong Enterprise RAG Platform.                                    |
|   12 | System    | Gán vai trò mặc định `EMPLOYEE` cho nhân viên.                                                                  |
|   13 | System    | Liên kết tài khoản Enterprise RAG với danh tính tài khoản công ty.                                              |
|   14 | System    | Xác định các thông tin tổ chức như phòng ban, nhóm và quyền của nhân viên từ dữ liệu do công ty quản lý nếu có. |
|   15 | System    | Đặt tài khoản Enterprise RAG ở trạng thái `ACTIVE`.                                                             |
|   16 | System    | Ghi nhận sự kiện tạo/kích hoạt tài khoản theo chính sách audit.                                                 |
|   17 | System    | Thông báo đăng ký thành công.                                                                                   |
|   18 | Nhân viên | Có thể tiếp tục sử dụng Use Case **Đăng nhập** để truy cập hệ thống.                                            |

### Luồng thay thế/ luồng ngoại lệ

| Điều kiện                                                       | Luồng xử lý                                                                                                                                      |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Nhân viên nhập thiếu email hoặc mật khẩu                        | Hệ thống không thực hiện xác minh và yêu cầu nhân viên nhập đầy đủ thông tin.                                                                    |
| Email không đúng định dạng                                      | Hệ thống thông báo email không hợp lệ và yêu cầu nhập lại.                                                                                       |
| Email không thuộc miền email của công ty                        | Hệ thống từ chối đăng ký.                                                                                                                        |
| Email hoặc mật khẩu không chính xác                             | Hệ thống không xác minh được danh tính, không tạo tài khoản Enterprise RAG và thông báo xác thực không thành công.                               |
| Tài khoản công ty không tồn tại                                 | Hệ thống từ chối đăng ký và hướng dẫn nhân viên liên hệ bộ phận quản trị tài khoản của công ty.                                                  |
| Tài khoản công ty bị khóa hoặc vô hiệu hóa                      | Hệ thống từ chối đăng ký và không tạo tài khoản Enterprise RAG.                                                                                  |
| Tài khoản công ty đã được đăng ký trên Enterprise RAG Platform  | Hệ thống không tạo tài khoản mới và hướng nhân viên sang chức năng **Đăng nhập**.                                                                |
| Không xác định được thông tin phòng ban hoặc nhóm của nhân viên | Hệ thống có thể tạo tài khoản với quyền mặc định tối thiểu hoặc chuyển sang trạng thái chờ Admin bổ sung thông tin, tùy chính sách doanh nghiệp. |
| Dịch vụ xác thực tài khoản công ty không khả dụng               | Hệ thống không tạo tài khoản và trả thông báo lỗi có kiểm soát.                                                                                  |
| Số lần xác thực thất bại vượt ngưỡng cho phép                   | Hệ thống áp dụng chính sách bảo mật như tạm thời giới hạn yêu cầu hoặc yêu cầu nhân viên thử lại sau.                                            |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                                                          |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ nhân viên có tài khoản công ty hợp lệ và đang hoạt động mới được đăng ký sử dụng Enterprise RAG Platform.                                                                    |
| Email sử dụng để đăng ký phải là email do công ty cấp.                                                                                                                           |
| Mỗi tài khoản công ty chỉ được liên kết với một tài khoản Enterprise RAG hợp lệ.                                                                                                 |
| Nhân viên không được sử dụng email cá nhân để đăng ký nếu hệ thống chỉ phục vụ nội bộ doanh nghiệp.                                                                              |
| Nhân viên không được tự tạo email hoặc mật khẩu mới trong quá trình đăng ký Enterprise RAG.                                                                                      |
| Nhân viên không được tự gán Role, Group, Department hoặc quyền truy cập tài liệu.                                                                                                |
| Vai trò mặc định của tài khoản mới là `EMPLOYEE`, trừ khi dữ liệu quản trị của công ty xác định khác.                                                                            |
| Group, Department và các quyền nghiệp vụ phải được xác định từ dữ liệu do công ty/Admin quản lý.                                                                                 |
| Đăng ký thành công không đồng nghĩa nhân viên được truy cập toàn bộ tài liệu của công ty.                                                                                        |
| Mỗi lần truy cập tài liệu vẫn phải kiểm tra quyền theo ACL hiện tại của nhân viên.                                                                                               |
| Khi tài khoản công ty bị vô hiệu hóa, tài khoản Enterprise RAG tương ứng phải không còn được phép truy cập hệ thống theo chính sách đồng bộ danh tính.                           |
| Thông tin xác thực nhạy cảm không được ghi vào application log hoặc audit log dưới dạng plaintext.                                                                               |
| Hệ thống Enterprise RAG không nên tạo một bản sao độc lập của mật khẩu công ty nếu việc xác thực được thực hiện thông qua hệ thống quản lý danh tính tập trung của doanh nghiệp. |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                              |
| -------------------------------------------------------------------------------------------------------------------------- |
| Nhân viên có email và mật khẩu công ty hợp lệ có thể đăng ký/kích hoạt tài khoản Enterprise RAG thành công.                |
| Email không thuộc công ty không được sử dụng để đăng ký.                                                                   |
| Email hoặc mật khẩu công ty không chính xác không được tạo tài khoản Enterprise RAG.                                       |
| Tài khoản công ty bị khóa hoặc vô hiệu hóa không được sử dụng để đăng ký.                                                  |
| Một tài khoản công ty không thể tạo nhiều tài khoản Enterprise RAG khác nhau.                                              |
| Nếu tài khoản đã tồn tại trên Enterprise RAG, hệ thống hướng nhân viên sang chức năng đăng nhập thay vì tạo tài khoản mới. |
| Nhân viên không thể tự chọn Role `ADMIN` hoặc các quyền quản trị.                                                          |
| Nhân viên không thể tự thay đổi Department hoặc Group trong quá trình đăng ký.                                             |
| Sau khi đăng ký thành công, tài khoản được liên kết đúng với danh tính nhân viên của công ty.                              |
| Sau khi đăng ký thành công, nhân viên chỉ được truy cập các tài nguyên nằm trong phạm vi ACL được cấp.                     |
| Mật khẩu công ty không được lưu hoặc ghi log dưới dạng plaintext.                                                          |
| Khi dịch vụ xác thực công ty không khả dụng, hệ thống không được tự động bỏ qua bước xác minh để tạo tài khoản.            |

### Dữ liệu liên quan

| Dữ liệu           | Mục đích                                                                         |
| ----------------- | -------------------------------------------------------------------------------- |
| `user_id`         | Định danh người dùng trong Enterprise RAG Platform.                              |
| `company_user_id` | Định danh nhân viên trong hệ thống quản lý danh tính của công ty.                |
| `company_email`   | Email do công ty cấp và được sử dụng để xác định nhân viên.                      |
| `account_status`  | Xác định trạng thái tài khoản Enterprise RAG như `ACTIVE`, `LOCKED`, `DISABLED`. |
| `roles`           | Xác định vai trò chức năng của nhân viên; mặc định là `EMPLOYEE`.                |
| `department`      | Phòng ban của nhân viên do công ty/Admin quản lý.                                |
| `groups`          | Các nhóm mà nhân viên được công ty/Admin phân vào.                               |
| `created_at`      | Thời điểm tài khoản Enterprise RAG được tạo/kích hoạt.                           |

### Ghi chú thiết kế

Luồng nghiệp vụ được hiểu như sau:

```text
Công ty
   │
   ├── Cấp email
   └── Cấp mật khẩu
           │
           ↓
       Nhân viên
           │
           ↓
Đăng ký bằng tài khoản công ty
           │
           ↓
      Xác minh danh tính
           │
      ┌────┴─────┐
      │          │
    Hợp lệ    Không hợp lệ
      │          │
      ↓          ↓
Tạo/kích hoạt   Từ chối
tài khoản RAG
      │
      ↓
Role = EMPLOYEE
      │
      ↓
Department / Group / ACL
do công ty quản lý
      │
      ↓
   Đăng nhập
```

Điểm quan trọng là:

```text
Email công ty + mật khẩu công ty
```

được **tái sử dụng để xác minh danh tính**, chứ Enterprise RAG không nên coi đây là một bộ credential hoàn toàn mới do Employee tự tạo.

Nếu doanh nghiệp có một hệ thống quản lý danh tính tập trung, mô hình mong muốn về mặt kỹ thuật là:

```text
Enterprise RAG
      │
      │ yêu cầu xác thực
      ↓
Hệ thống tài khoản công ty
      │
      ├── Hợp lệ → trả danh tính
      │
      └── Không hợp lệ → từ chối
```

thay vì:

```text
Enterprise RAG
      ↓
copy email + password công ty
      ↓
lưu thêm một bản password riêng
```

Use Case chỉ cần mô tả việc **nhân viên sử dụng tài khoản do công ty cấp để đăng ký/kích hoạt**, còn cơ chế xác thực cụ thể sẽ được thiết kế ở Sequence Diagram và Authentication Architecture.

### Use case đăng nhập


| Thuộc tính                      | Mô tả                                                                                                                             |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------                                                                                                                     |
| **Tên Use Case**                | Đăng nhập                                                                                                                         |
| **Actor chính**                 | Nhân viên, quản trị viên                                                                                                                          |
| **Mục tiêu**                    | Cho phép nhân viên, quản trị viên xác thực danh tính để truy cập hệ thống và sử dụng các chức năng được cấp quyền.                 |
| **ĐIều kiện kích hoạt**                     | Nhân viên, quản trị viên truy cập hệ thống và thực hiện thao tác đăng nhập.                                                                       |
| **ĐIều kiện tiên quyết**               | 1. Nhân viên đã có tài khoản trong hệ thống.<br>2. Tài khoản chưa bị vô hiệu hóa hoặc khóa.<br>3. Dịch vụ xác thực đang hoạt động. |
| **Đầu vào**                       | Thông tin xác thực của nhân viên, ví dụ email/tên đăng nhập và mật khẩu hoặc phương thức đăng nhập doanh nghiệp được cấu hình.     |
| **Trạng thái — Thành công** | Employee được xác thực; phiên đăng nhập hợp lệ được tạo; hệ thống xác định được danh tính và quyền hiện tại của Employee.         |
| **Trạng thái — Thất bại**   | Không tạo phiên đăng nhập hợp lệ; Employee không được truy cập các chức năng và tài nguyên yêu cầu xác thực. |
| **Use Cases liên quan**           | Đăng xuất, Tìm kiếm tài liệu, Đặt câu hỏi về tri thức, Xem chi tiết tài liệu                                                      |

### Main Flow

| Bước | Actor    | Hành động                                                                               |
| ---: | -------- | --------------------------------------------------------------------------------------- |
|    1 | Employee | Truy cập Enterprise RAG Platform.                                                       |
|    2 | System   | Phát hiện Employee chưa có phiên đăng nhập hợp lệ và hiển thị giao diện đăng nhập.      |
|    3 | Employee | Nhập thông tin xác thực.                                                                |
|    4 | Employee | Gửi yêu cầu đăng nhập.                                                                  |
|    5 | System   | Kiểm tra tính hợp lệ của thông tin đầu vào.                                             |
|    6 | System   | Xác thực danh tính Employee.                                                            |
|    7 | System   | Kiểm tra trạng thái tài khoản Employee.                                                 |
|    8 | System   | Xác định quyền, vai trò, nhóm và phòng ban hiện tại của Employee theo dữ liệu hệ thống. |
|    9 | System   | Tạo phiên đăng nhập hợp lệ.                                                             |
|   10 | System   | Ghi nhận sự kiện đăng nhập theo chính sách audit của hệ thống.                          |
|   11 | System   | Chuyển Employee tới giao diện chính.                                                    |
|   12 | System   | Hiển thị các chức năng và dữ liệu Employee được phép truy cập.                          |

### Luồng thay thế/ luồng ngoại lệ

 Điều kiện                                               | Luồng xử lý                                                                                            |
 ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
 Employee nhập thiếu thông tin bắt buộc                  | Hệ thống không gửi yêu cầu xác thực và yêu cầu Employee bổ sung thông tin còn thiếu.                   |
Thông tin xác thực không chính xác                      | Hệ thống từ chối đăng nhập, không tạo session và thông báo đăng nhập không thành công.                 |
Tài khoản không tồn tại                                 | Hệ thống từ chối đăng nhập và trả thông báo phù hợp mà không làm lộ thông tin bảo mật không cần thiết. |
 Tài khoản bị khóa hoặc vô hiệu hóa                      | Hệ thống từ chối đăng nhập và hướng dẫn Employee liên hệ Admin nếu cần.                                |
 Employee đã có phiên đăng nhập hợp lệ                   | Hệ thống không yêu cầu đăng nhập lại và chuyển Employee tới giao diện chính.                           |
Phiên đăng nhập cũ đã hết hạn                           | Hệ thống yêu cầu Employee xác thực lại.                                                                |
 Dịch vụ xác thực tạm thời không khả dụng                | Hệ thống không tạo session và trả thông báo lỗi có kiểm soát.                                          |
 Phát hiện số lần đăng nhập thất bại vượt ngưỡng bảo mật | Hệ thống áp dụng chính sách bảo vệ tài khoản như tạm khóa hoặc yêu cầu xác minh bổ sung theo cấu hình. |

### Quy tắc nghiệp vụ

 Quy tắc                                                                                                              |
-------------------------------------------------------------------------------------------------------------------- |
 Chỉ tài khoản có trạng thái `ACTIVE` mới được đăng nhập thành công.                                                  |
 Employee phải được xác thực trước khi sử dụng các chức năng yêu cầu authentication.                                  |
 Employee không được tự gán Role, Group hoặc Department cho chính mình thông qua quá trình đăng nhập.                 |
 Quyền truy cập phải được xác định từ dữ liệu quyền hiện tại của hệ thống.                                            |
 Đăng nhập thành công không đồng nghĩa Employee có quyền truy cập mọi tài liệu.                                       |
 Quyền truy cập từng tài liệu vẫn phải được kiểm tra khi Employee thực hiện Search, View, Download hoặc Ask Question. |
 Thông tin xác thực nhạy cảm không được ghi trực tiếp vào application log hoặc audit log.                             |
 Session hết hạn hoặc không hợp lệ phải bị từ chối.                                                                   |
 Các lần đăng nhập thành công và thất bại có thể được ghi nhận phục vụ security audit theo chính sách doanh nghiệp.   |
 Hệ thống phải áp dụng cơ chế bảo vệ trước hành vi thử đăng nhập bất thường theo security policy.                     |

### Các điều kiện nghiệm thu

 Acceptance Criteria                                                                               |
------------------------------------------------------------------------------------------------- |
 Employee có tài khoản `ACTIVE` và cung cấp thông tin xác thực hợp lệ có thể đăng nhập thành công. |
 Employee nhập sai thông tin xác thực không được tạo session.                                      |
 Tài khoản `LOCKED` hoặc `DISABLED` không thể đăng nhập.                                           |
 Người dùng chưa xác thực không thể truy cập API hoặc tài nguyên yêu cầu đăng nhập.                |
 Sau khi đăng nhập thành công, hệ thống xác định đúng Employee hiện tại.                           |
 Sau đăng nhập, hệ thống áp dụng đúng Role, Group và Department hiện tại của Employee.             |
 Đăng nhập thành công không cho phép Employee truy cập tài liệu nằm ngoài ACL của mình.            |
 Session hết hạn không được sử dụng tiếp để truy cập tài nguyên bảo vệ.                            |
 Password/token hoặc credential nhạy cảm không xuất hiện dưới dạng plaintext trong log.            |
 Khi dịch vụ xác thực lỗi, hệ thống trả lỗi có kiểm soát và không cấp quyền truy cập ngoài ý muốn. |

### Dữ liệu liên quan

| Dữ liệu          | Mục đích                                      |
| ---------------- | --------------------------------------------- |
| `user_id`        | Định danh nhân viên                            |
| `account_status` | Xác định tài khoản có được phép đăng nhập     |
| `roles`          | Xác định nhóm quyền chức năng                 |
| `groups`         | Xác định các nhóm nhân viên đang tham gia      |
| `department`     | Xác định đơn vị tổ chức của nhân vuên          |
| `session`        | Duy trì trạng thái xác thực của phiên sử dụng |

### Ghi chú thiết kế

Use Case này chỉ mô tả nghiệp vụ:

```text
Employee
   ↓
Xác thực danh tính
   ↓
Truy cập hệ thống
```

Các chi tiết như:

```text
JWT
OAuth2
Supabase Auth
Access Token
Refresh Token
Cookie
SSO
```

không cần mô tả sâu trong Use Case Specification. Chúng sẽ được xác định ở **Sequence Diagram, Authentication Design và API/Security Specification**.

### Use case truy vấn tài liệu

| Thuộc tính                            | Mô tả                                                                                                                                            |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |              
| **Tên Use Case**                      | Đặt câu hỏi về tài liệu                                                                                                                         |
| **Actor chính**                       | Nhân viên                                                                                                                                         |
| **Mục tiêu**                          | Cho phép nhân viên đặt câu hỏi bằng ngôn ngữ tự nhiên và nhận câu trả lời dựa trên các tài liệu nội bộ mà nhân viên được phép truy cập.            |
| **Điều kiện kích hoạt**                           | nhân viên nhập câu hỏi và chọn gửi.                                                                                                               |
| **Điều kiện tiên quyết**                     | 1. Nhân viên đã đăng nhập.<br>2. Tài khoản đang hoạt động.<br>3. Employee có quyền sử dụng chức năng hỏi đáp.<br>4. Knowledge Base đang khả dụng. |
| **Đầu vào**                             | Câu hỏi của Employee.<br>Có thể kèm `conversation_id`, phạm vi tài liệu hoặc bộ lọc.                                                             |
| **Trạng thái — Thành công**       | Câu hỏi và câu trả lời được ghi nhận trong conversation; answer liên kết với các citation/source đã sử dụng.                                     |
| **Trạng thái — Không đủ dữ liệu** | Câu hỏi được ghi nhận nhưng hệ thống trả Controlled No-Answer; không tạo câu trả lời khẳng định thiếu căn cứ. |
| **Use Cases liên quan**                 | Xem nguồn trích dẫn, Mở tài liệu nguồn, Đánh giá câu trả lời, Báo cáo câu trả lời có vấn đề                                                      |

### Main Flow

| Bước | Actor    | Hành động                                                               |
| ---: | -------- | ----------------------------------------------------------------------- |
|    1 | Employee | Nhập câu hỏi vào giao diện hỏi đáp.                                     |
|    2 | Employee | Gửi câu hỏi.                                                            |
|    3 | System   | Kiểm tra phiên đăng nhập và xác định Employee hiện tại.                 |
|    4 | System   | Xác định phạm vi tài liệu Employee được phép truy cập.                  |
|    5 | System   | Phân tích yêu cầu của Employee.                                         |
|    6 | System   | Tìm các thông tin liên quan trong phạm vi tài liệu được phép.           |
|    7 | System   | Đánh giá mức độ đầy đủ của thông tin tìm được.                          |
|    8 | System   | Xây dựng câu trả lời dựa trên evidence hợp lệ.                          |
|    9 | System   | Liên kết các thông tin trong câu trả lời với nguồn trích dẫn tương ứng. |
|   10 | System   | Trả câu trả lời và danh sách nguồn cho Employee.                        |
|   11 | Employee | Đọc câu trả lời và có thể tiếp tục đặt câu hỏi trong cùng conversation. |

### Luồng thay thế/ luồng ngoại lệ

 Điều kiện                                           | Luồng xử lý                                                                                                                        |
 --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
 Không tìm được đủ evidence                          | Hệ thống không tạo câu trả lời suy đoán và trả thông báo rằng chưa có đủ thông tin trong các tài liệu Employee được phép truy cập. |
 Câu hỏi không rõ nghĩa                              | Hệ thống yêu cầu Employee cung cấp thêm thông tin hoặc làm rõ câu hỏi.                                                             |
 Có tài liệu liên quan nhưng Employee không có quyền | Tài liệu không được sử dụng làm evidence và không được gửi tới quá trình tạo câu trả lời.                                          |
 Tài liệu chưa được publish                          | Tài liệu không được sử dụng.                                                                                                       |
 Tài liệu có nhiều version                           | Mặc định chỉ sử dụng version đang `ACTIVE`, trừ khi Employee hỏi rõ về thông tin lịch sử.                                          |
 Knowledge service gặp lỗi                           | Hệ thống trả lỗi có kiểm soát và không tạo answer không có căn cứ.                                                                 |
 Câu hỏi nằm ngoài Knowledge Base                    | Hệ thống trả thông báo không có đủ thông tin nội bộ; không tự động sử dụng Internet nếu hệ thống được cấu hình internal-only.      |

### Quy tăc nghiệp vụ

 Quy tắc                                                                 |
----------------------------------------------------------------------- |
 Chỉ được sử dụng tài liệu Employee có quyền `READ`.                     |
 Tài liệu chưa `PUBLISHED` không được sử dụng để trả lời.                |
 Mặc định chỉ sử dụng `DocumentVersion = ACTIVE`.                        |
 Unauthorized evidence không được truyền tới bước tạo câu trả lời.       |
 Không đủ evidence thì phải trả Controlled No-Answer.                    |
 Các claim dựa trên Knowledge Base phải có khả năng truy ngược về nguồn. |
 Citation phải tham chiếu đúng DocumentVersion đã được sử dụng.          |
 Permission hiện tại phải được áp dụng cho từng request.                 |
 Không được tiết lộ tài liệu mà Employee không có quyền truy cập.        |
 Follow-up question phải được xử lý trong đúng context của conversation. |

### Các điều kiện nghiệm thu

Các điều kiện                                                         |
--------------------------------------------------------------------------- |
 Khi có evidence phù hợp, nhân viên nhận được câu trả lời có nguồn trích dẫn. |
 Khi không đủ evidence, hệ thống trả Cơ chế từ chối câu trả lời có kiểm soát.                   |
 Tài liệu nhân viên không có quyền không được dùng làm evidence.              |
 Tài liệu chưa công khai không được sử dụng.                                   |
 Version cũ không được sử dụng mặc định khi đã có active version mới.        |
 thông tin trích dẫn nguồn mở được đúng tài liệu và version đã sử dụng.                       |
 Khi quyền bị thu hồi, request tiếp theo không còn sử dụng tài liệu đó.      |
Câu hỏi follow-up có thể sử dụng context của conversation trước đó.         |

### Use case upload tài liệu

| Thuộc tính                  | Mô tả                                                                                                                                                                                                                             |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**            | Upload tài liệu                                                                                                                                                                                                                   |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                                                     |
| **Mục tiêu**                | Cho phép quản trị viên đưa một tài liệu mới vào hệ thống để tài liệu được lưu trữ, xử lý và chuẩn bị cho quá trình kiểm duyệt trước khi được sử dụng trong kho tri thức.                                                          |
| **Điều kiện kích hoạt**     | Quản trị viên chọn chức năng **Upload tài liệu** và lựa chọn file cần đưa vào hệ thống.                                                                                                                                           |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản đang hoạt động.<br>3. Quản trị viên có quyền quản lý tài liệu.<br>4. File thuộc định dạng và kích thước mà hệ thống hỗ trợ.<br>5. Dịch vụ lưu trữ và xử lý tài liệu đang khả dụng. |
| **Đầu vào**                 | File tài liệu và các thông tin tài liệu bắt buộc theo chính sách hệ thống, ví dụ: tên tài liệu, loại tài liệu, phòng ban, mô tả hoặc phạm vi sử dụng.                                                                             |
| **Trạng thái — Thành công** | Tài liệu và phiên bản đầu tiên được tạo trong hệ thống; file nguồn được lưu trữ; yêu cầu xử lý tài liệu được khởi tạo; tài liệu chưa được sử dụng để trả lời người dùng cho đến khi hoàn tất xử lý, kiểm duyệt và xuất bản.       |
| **Trạng thái — Thất bại**   | Tài liệu không được tạo hoặc không được đưa vào kho tri thức; hệ thống thông báo nguyên nhân lỗi và không để lại dữ liệu ở trạng thái không nhất quán.                                                                            |
| **Use Cases liên quan**     | Xem chi tiết tài liệu, Theo dõi trạng thái xử lý, Kiểm duyệt tài liệu, Tạo phiên bản tài liệu mới, Yêu cầu xử lý lại tài liệu                                                                                                     |

### Main Flow

| Bước | Actor         | Hành động                                                                                 |
| ---: | ------------- | ----------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Truy cập chức năng **Upload tài liệu**.                                                   |
|    2 | System        | Hiển thị giao diện upload tài liệu và các thông tin cần khai báo.                         |
|    3 | Quản trị viên | Chọn file tài liệu cần upload.                                                            |
|    4 | Quản trị viên | Nhập hoặc xác nhận các thông tin bắt buộc của tài liệu.                                   |
|    5 | Quản trị viên | Gửi yêu cầu upload.                                                                       |
|    6 | System        | Kiểm tra phiên đăng nhập và quyền quản lý tài liệu của quản trị viên.                     |
|    7 | System        | Kiểm tra file có đáp ứng các điều kiện về định dạng, kích thước và tính hợp lệ hay không. |
|    8 | System        | Kiểm tra file có trùng hoàn toàn với tài liệu đã tồn tại trong hệ thống hay không.        |
|    9 | System        | Kiểm tra các thông tin tài liệu bắt buộc.                                                 |
|   10 | System        | Tạo tài liệu mới trong hệ thống.                                                          |
|   11 | System        | Tạo phiên bản đầu tiên của tài liệu.                                                      |
|   12 | System        | Lưu file nguồn vào vùng lưu trữ của hệ thống.                                             |
|   13 | System        | Lưu các thông tin nghiệp vụ và thông tin cần thiết để quản lý tài liệu.                   |
|   14 | System        | Khởi tạo yêu cầu xử lý tài liệu.                                                          |
|   15 | System        | Chuyển tài liệu sang trạng thái đang chờ hoặc đang được xử lý.                            |
|   16 | System        | Ghi nhận sự kiện upload tài liệu theo chính sách audit.                                   |
|   17 | System        | Thông báo upload thành công cho quản trị viên.                                            |
|   18 | Quản trị viên | Có thể theo dõi trạng thái xử lý của tài liệu.                                            |

### Luồng thay thế/ luồng ngoại lệ

| Điều kiện                                                     | Luồng xử lý                                                                                                                                    |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên chưa chọn file                                  | Hệ thống không gửi yêu cầu upload và yêu cầu quản trị viên chọn file.                                                                          |
| Thiếu thông tin tài liệu bắt buộc                             | Hệ thống yêu cầu quản trị viên bổ sung thông tin trước khi tiếp tục.                                                                           |
| File có định dạng không được hỗ trợ                           | Hệ thống từ chối upload và thông báo định dạng file không được hỗ trợ.                                                                         |
| File vượt quá giới hạn kích thước cho phép                    | Hệ thống từ chối upload và thông báo giới hạn kích thước file.                                                                                 |
| File bị hỏng hoặc không thể đọc                               | Hệ thống từ chối đưa tài liệu vào quá trình xử lý và thông báo lỗi.                                                                            |
| File trùng hoàn toàn với một file đã tồn tại                  | Hệ thống không tạo thêm tài liệu trùng lặp và thông báo cho quản trị viên rằng tài liệu đã tồn tại.                                            |
| Nội dung thuộc một tài liệu đã tồn tại nhưng là phiên bản mới | Hệ thống không tạo một tài liệu logic độc lập; quản trị viên được hướng sang Use Case **Tạo phiên bản tài liệu mới**.                          |
| Quản trị viên không có quyền upload tài liệu                  | Hệ thống từ chối yêu cầu và không lưu file vào kho tài liệu.                                                                                   |
| Lưu file nguồn thất bại                                       | Hệ thống không hoàn tất việc tạo tài liệu và trả thông báo lỗi có kiểm soát.                                                                   |
| Không thể khởi tạo quá trình xử lý                            | Tài liệu được ghi nhận ở trạng thái phù hợp để quản trị viên có thể theo dõi hoặc yêu cầu xử lý lại; tài liệu không được sử dụng cho truy vấn. |
| Quá trình xử lý tài liệu thất bại sau khi upload              | Hệ thống ghi nhận trạng thái xử lý thất bại; quản trị viên có thể xem nguyên nhân và thực hiện Use Case **Yêu cầu xử lý lại tài liệu**.        |
| Dịch vụ hệ thống tạm thời không khả dụng                      | Hệ thống trả thông báo lỗi có kiểm soát và không tạo dữ liệu tài liệu không hoàn chỉnh.                                                        |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                        |
| ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền quản lý tài liệu mới được phép upload tài liệu.                                                                     |
| File upload phải thuộc định dạng và kích thước được hệ thống hỗ trợ.                                                                           |
| Một file trùng hoàn toàn với file đã tồn tại không được ingest lại như một tài liệu mới.                                                       |
| Một tài liệu nghiệp vụ đã tồn tại nhưng có nội dung cập nhật phải được quản lý dưới dạng phiên bản mới thay vì tạo một tài liệu logic độc lập. |
| Khi tạo một tài liệu mới, hệ thống phải tạo phiên bản đầu tiên gắn với tài liệu đó.                                                            |
| File nguồn phải được lưu và liên kết với đúng phiên bản tài liệu.                                                                              |
| Tài liệu vừa upload chưa được coi là tri thức chính thức của hệ thống.                                                                         |
| Tài liệu chưa hoàn tất xử lý không được sử dụng để trả lời câu hỏi của nhân viên.                                                              |
| Tài liệu chưa được kiểm duyệt và xuất bản không được tham gia vào phạm vi truy vấn của nhân viên.                                              |
| Lỗi ở một bước xử lý không được làm tài liệu tự động trở thành tài liệu đã xuất bản.                                                           |
| Việc upload tài liệu không đồng nghĩa với việc tài liệu được cấp quyền truy cập cho toàn bộ nhân viên.                                         |
| Quyền truy cập tài liệu phải được thiết lập và kiểm tra độc lập theo chính sách phân quyền của hệ thống.                                       |
| Hệ thống phải giữ được mối liên hệ giữa tài liệu, phiên bản tài liệu và file nguồn tương ứng.                                                  |
| Hệ thống phải ghi nhận người thực hiện và thời điểm upload để phục vụ quản trị và audit.                                                       |
| Quá trình tạo tài liệu và lưu thông tin liên quan phải đảm bảo không để lại dữ liệu ở trạng thái không nhất quán khi có lỗi.                   |
| Chỉ phiên bản tài liệu đã được phê duyệt, xuất bản và đang có hiệu lực mới được sử dụng mặc định trong quá trình truy vấn tri thức.            |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                                                   |
| ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền quản lý tài liệu có thể chọn file và thực hiện upload.                                                                   |
| Người dùng không có quyền quản lý tài liệu không thể upload tài liệu.                                                                           |
| File có định dạng hợp lệ và kích thước trong giới hạn được hệ thống chấp nhận.                                                                  |
| File không hợp lệ hoặc vượt giới hạn phải bị từ chối trước khi được đưa vào quá trình xử lý.                                                    |
| Sau khi upload thành công, hệ thống tạo đúng một tài liệu và phiên bản đầu tiên tương ứng.                                                      |
| File nguồn được liên kết đúng với phiên bản tài liệu vừa tạo.                                                                                   |
| Upload lại chính xác cùng một file không tạo thêm một bản tài liệu trùng lặp.                                                                   |
| Nếu file là nội dung cập nhật của một tài liệu đã tồn tại, hệ thống không tạo một tài liệu logic mới khi quản trị viên chọn cập nhật phiên bản. |
| Sau khi upload thành công, tài liệu phải có trạng thái phản ánh đúng giai đoạn xử lý hiện tại.                                                  |
| Tài liệu vừa upload chưa được xuất hiện trong phạm vi tri thức mà nhân viên có thể truy vấn.                                                    |
| Tài liệu xử lý thất bại không được sử dụng để tạo câu trả lời.                                                                                  |
| Khi xử lý thất bại, quản trị viên có thể xác định tài liệu đang lỗi và thực hiện xử lý lại.                                                     |
| Khi xảy ra lỗi trong quá trình upload, hệ thống không để lại tài liệu hoặc phiên bản ở trạng thái dữ liệu không nhất quán.                      |
| Hệ thống ghi nhận được quản trị viên đã upload tài liệu và thời điểm thực hiện.                                                                 |
| Sau khi tài liệu hoàn tất xử lý, tài liệu có thể chuyển sang bước **Kiểm duyệt tài liệu**.                                                      |

### Dữ liệu liên quan

| Dữ liệu               | Mục đích                                                                  |
| --------------------- | ------------------------------------------------------------------------- |
| `document_id`         | Định danh tài liệu logic trong hệ thống.                                  |
| `document_version_id` | Định danh phiên bản cụ thể của tài liệu.                                  |
| `version_number`      | Xác định số phiên bản; tài liệu mới thường bắt đầu từ phiên bản đầu tiên. |
| `file_name`           | Tên file nguồn được upload.                                               |
| `file_type`           | Xác định định dạng của file.                                              |
| `file_size`           | Kiểm tra giới hạn kích thước và phục vụ quản lý file.                     |
| `file_hash`           | Hỗ trợ xác định file trùng hoàn toàn.                                     |
| `storage_location`    | Xác định vị trí lưu file nguồn.                                           |
| `title`               | Tên nghiệp vụ của tài liệu.                                               |
| `document_type`       | Phân loại tài liệu.                                                       |
| `department`          | Đơn vị hoặc phòng ban liên quan đến tài liệu nếu có.                      |
| `description`         | Mô tả nội dung hoặc mục đích của tài liệu.                                |
| `document_status`     | Trạng thái nghiệp vụ của tài liệu.                                        |
| `version_status`      | Trạng thái của phiên bản tài liệu.                                        |
| `processing_status`   | Phản ánh tình trạng xử lý file sau khi upload.                            |
| `uploaded_by`         | Xác định quản trị viên thực hiện upload.                                  |
| `uploaded_at`         | Thời điểm upload tài liệu.                                                |

### Ghi chú thiết kế

Use Case **Upload tài liệu** chỉ mô tả mục tiêu nghiệp vụ:

```text
Quản trị viên
      ↓
Chọn tài liệu
      ↓
Khai báo thông tin
      ↓
Upload
      ↓
Hệ thống kiểm tra
      ↓
Lưu tài liệu + phiên bản
      ↓
Khởi tạo xử lý
      ↓
Chờ kiểm duyệt
```

Cần phân biệt ba đối tượng:

```text
Document
   │
   │ Tài liệu nghiệp vụ logic
   │
   └── DocumentVersion
            │
            │ Phiên bản cụ thể
            │
            └── Source File
```

Ví dụ:

```text
Document:
"Quy định nghỉ phép"

├── Version 1
│     └── quy_dinh_nghi_phep_2025.pdf
│
└── Version 2
      └── quy_dinh_nghi_phep_2026.pdf
```

Vì vậy:

```text
Upload tài liệu mới
```

khác với:

```text
Tạo phiên bản tài liệu mới
```

Nếu chưa tồn tại tài liệu:

```text
Upload
   ↓
Document mới
   ↓
Version 1
```

Nếu tài liệu đã tồn tại và Admin đang cập nhật nội dung:

```text
Document hiện có
   ↓
Tạo phiên bản mới
   ↓
Version 2
```

không nên tạo:

```text
Document A — Quy định nghỉ phép 2025
Document B — Quy định nghỉ phép 2026
```

như hai tài liệu nghiệp vụ hoàn toàn độc lập nếu thực chất chúng là các phiên bản của cùng một tài liệu.

---

Các xử lý kỹ thuật sau upload như:

```text
File Validation
Checksum / Hash
Duplicate Detection
Malware Scan
Extraction / OCR
Structure Parsing
Metadata Extraction
Chunking
Embedding
Indexing
```

không phải là các Use Case riêng của Admin.

Chúng là các bước xử lý nội bộ của hệ thống và nên được thể hiện chi tiết trong **Sequence Diagram của Use Case Upload tài liệu** hoặc **RAG Ingestion Architecture**.

Luồng kỹ thuật ở mức khái quát có thể là:

```text
Admin
  ↓
Upload
  ↓
Validate file
  ↓
Kiểm tra duplicate
  ↓
Lưu source file
  ↓
Tạo Document + DocumentVersion
  ↓
Khởi tạo Processing Job
  ↓
Extract
  ↓
Chunk
  ↓
Index
  ↓
READY_FOR_REVIEW
  ↓
Admin kiểm duyệt
  ↓
Phê duyệt & xuất bản
  ↓
PUBLISHED + ACTIVE
  ↓
Employee mới có thể truy vấn
```

Nguyên tắc quan trọng nhất:

```text
UPLOAD SUCCESS
      ≠
PUBLISHED
```

Upload thành công chỉ có nghĩa là **hệ thống đã tiếp nhận tài liệu thành công**.

Để được dùng làm tri thức trả lời cho nhân viên, tài liệu vẫn phải đáp ứng:

```text
Đã xử lý thành công
        AND
Đã kiểm duyệt
        AND
Đã phê duyệt/xuất bản
        AND
Version đang ACTIVE
        AND
Employee có quyền READ
```

### Use case xem danh sách tài liệu

| Thuộc tính                        | Mô tả                                                                                                                                                                                                                                 |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**                  | Xem danh sách tài liệu                                                                                                                                                                                                                |
| **Actor chính**                   | Quản trị viên                                                                                                                                                                                                                         |
| **Mục tiêu**                      | Cho phép quản trị viên xem và theo dõi toàn bộ các tài liệu đang được quản lý trong hệ thống cùng các thông tin và trạng thái liên quan.                                                                                              |
| **Điều kiện kích hoạt**           | Quản trị viên truy cập chức năng **Quản lý tài liệu** hoặc **Danh sách tài liệu**.                                                                                                                                                    |
| **Điều kiện tiên quyết**          | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản đang hoạt động.<br>3. Quản trị viên có quyền xem và quản lý tài liệu.<br>4. Dịch vụ quản lý tài liệu đang khả dụng.                                                                    |
| **Đầu vào**                       | Không bắt buộc. Quản trị viên có thể cung cấp từ khóa tìm kiếm, bộ lọc, trạng thái tài liệu, loại tài liệu, phòng ban hoặc các tiêu chí sắp xếp để thu hẹp danh sách.                                                                 |
| **Trạng thái — Thành công**       | Hệ thống hiển thị danh sách các tài liệu mà quản trị viên được phép quản lý cùng các thông tin cần thiết như tên tài liệu, phiên bản hiện tại, trạng thái tài liệu, trạng thái xử lý, loại tài liệu, phòng ban và thời điểm cập nhật. |
| **Trạng thái — Không có dữ liệu** | Hệ thống hiển thị trạng thái danh sách trống hoặc thông báo không có tài liệu phù hợp với điều kiện hiện tại.                                                                                                                         |
| **Use Cases liên quan**           | Upload tài liệu, Xem chi tiết tài liệu, Tạo phiên bản tài liệu mới, Xem lịch sử phiên bản, Kiểm duyệt tài liệu, Theo dõi trạng thái xử lý                                                                                             |

### Main Flow

| Bước | Actor         | Hành động                                                                                         |
| ---: | ------------- | ------------------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Truy cập chức năng **Quản lý tài liệu**.                                                          |
|    2 | System        | Kiểm tra phiên đăng nhập và quyền quản lý tài liệu của quản trị viên.                             |
|    3 | System        | Xác định phạm vi tài liệu mà quản trị viên được phép xem và quản lý.                              |
|    4 | System        | Lấy danh sách tài liệu thuộc phạm vi được phép.                                                   |
|    5 | System        | Xác định phiên bản hiện tại và các trạng thái liên quan của từng tài liệu.                        |
|    6 | System        | Sắp xếp danh sách theo tiêu chí mặc định, ví dụ thời điểm cập nhật gần nhất.                      |
|    7 | System        | Hiển thị danh sách tài liệu cho quản trị viên.                                                    |
|    8 | System        | Với mỗi tài liệu, hiển thị các thông tin tóm tắt cần thiết.                                       |
|    9 | Quản trị viên | Xem danh sách tài liệu.                                                                           |
|   10 | Quản trị viên | Có thể nhập từ khóa hoặc áp dụng các bộ lọc để thu hẹp danh sách.                                 |
|   11 | System        | Áp dụng điều kiện tìm kiếm, lọc và sắp xếp trên phạm vi tài liệu quản trị viên được phép quản lý. |
|   12 | System        | Hiển thị danh sách kết quả tương ứng.                                                             |
|   13 | Quản trị viên | Có thể chọn một tài liệu để thực hiện Use Case **Xem chi tiết tài liệu**.                         |

### Thông tin hiển thị trong danh sách

| Thông tin                | Mục đích                                                                                                           |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| **Tên tài liệu**         | Giúp quản trị viên xác định tài liệu nghiệp vụ.                                                                    |
| **Loại tài liệu**        | Phân biệt quy định, quy trình, hướng dẫn, báo cáo, hợp đồng hoặc loại tài liệu khác.                               |
| **Phiên bản hiện tại**   | Cho biết phiên bản đang được quản lý hoặc đang có hiệu lực của tài liệu.                                           |
| **Trạng thái tài liệu**  | Cho biết tài liệu đang ở trạng thái như `DRAFT`, `PUBLISHED`, `ARCHIVED`.                                          |
| **Trạng thái phiên bản** | Cho biết phiên bản hiện tại đang `READY_FOR_REVIEW`, `ACTIVE`, `REJECTED`, `SUPERSEDED` hoặc trạng thái tương ứng. |
| **Trạng thái xử lý**     | Cho biết quá trình xử lý tài liệu đang `PENDING`, `PROCESSING`, `SUCCEEDED`, `FAILED` hoặc trạng thái tương ứng.   |
| **Phòng ban**            | Xác định đơn vị nghiệp vụ liên quan đến tài liệu.                                                                  |
| **Người upload**         | Xác định người đã đưa tài liệu vào hệ thống.                                                                       |
| **Thời gian cập nhật**   | Giúp quản trị viên biết tài liệu được thay đổi gần nhất khi nào.                                                   |

### Luồng thay thế/ luồng ngoại lệ

| Điều kiện                                                     | Luồng xử lý                                                                                                                                                                |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Hệ thống chưa có tài liệu                                     | Hệ thống hiển thị danh sách trống và có thể cung cấp chức năng **Upload tài liệu** cho quản trị viên.                                                                      |
| Không có tài liệu phù hợp với từ khóa hoặc bộ lọc             | Hệ thống thông báo không có kết quả phù hợp và cho phép quản trị viên thay đổi điều kiện lọc.                                                                              |
| Quản trị viên không có quyền xem danh sách tài liệu           | Hệ thống từ chối truy cập chức năng và không trả dữ liệu tài liệu.                                                                                                         |
| Quản trị viên chỉ được quản lý một phạm vi tài liệu nhất định | Hệ thống chỉ hiển thị các tài liệu thuộc phạm vi quyền tương ứng.                                                                                                          |
| Một tài liệu đang được xử lý                                  | Hệ thống vẫn có thể hiển thị tài liệu nhưng phải phản ánh đúng trạng thái xử lý hiện tại.                                                                                  |
| Một tài liệu xử lý thất bại                                   | Hệ thống hiển thị trạng thái `FAILED` hoặc trạng thái tương đương để quản trị viên có thể xác định tài liệu cần xử lý.                                                     |
| Một tài liệu đang chờ kiểm duyệt                              | Hệ thống hiển thị trạng thái tương ứng để quản trị viên biết tài liệu cần được review.                                                                                     |
| Một tài liệu đã được lưu trữ                                  | Tài liệu không xuất hiện trong danh sách mặc định nếu hệ thống mặc định chỉ hiển thị tài liệu đang hoạt động; quản trị viên có thể chọn bộ lọc để xem tài liệu đã lưu trữ. |
| Dữ liệu danh sách có số lượng lớn                             | Hệ thống phân trang hoặc giới hạn số lượng bản ghi hiển thị mỗi lần.                                                                                                       |
| Dịch vụ quản lý tài liệu không khả dụng                       | Hệ thống trả thông báo lỗi có kiểm soát và không hiển thị dữ liệu không đầy đủ như một danh sách hợp lệ.                                                                   |
| Quyền của quản trị viên vừa thay đổi                          | Hệ thống áp dụng quyền hiện tại khi lấy lại danh sách; tài liệu ngoài phạm vi quyền không còn được hiển thị.                                                               |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                                         |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ người dùng có quyền quản lý tài liệu mới được truy cập danh sách tài liệu quản trị.                                                                         |
| Danh sách phải được giới hạn theo phạm vi quyền hiện tại của quản trị viên.                                                                                     |
| Hệ thống phải phân biệt rõ trạng thái nghiệp vụ của tài liệu, trạng thái của phiên bản và trạng thái xử lý kỹ thuật.                                            |
| Một tài liệu đang xử lý hoặc xử lý thất bại vẫn có thể xuất hiện trong danh sách quản trị để Admin theo dõi và xử lý.                                           |
| Tài liệu chưa được xuất bản không được coi là tài liệu đang được Employee sử dụng trong Knowledge Base.                                                         |
| Mỗi tài liệu trong danh sách phải đại diện cho một `Document` logic, không phải mỗi phiên bản được hiển thị như một tài liệu độc lập.                           |
| Danh sách mặc định nên hiển thị thông tin của phiên bản hiện tại hoặc phiên bản mới nhất có liên quan đến tài liệu.                                             |
| Các phiên bản cũ phải được truy cập thông qua chức năng **Xem lịch sử phiên bản**, thay vì hiển thị tất cả như các dòng tài liệu độc lập trong danh sách chính. |
| Bộ lọc và tìm kiếm chỉ làm thu hẹp tập dữ liệu, không được mở rộng phạm vi quyền của quản trị viên.                                                             |
| Trạng thái hiển thị phải phản ánh dữ liệu hiện tại của hệ thống tại thời điểm yêu cầu.                                                                          |
| Tài liệu đã `ARCHIVED` phải được phân biệt rõ với tài liệu đã bị xóa.                                                                                           |
| Hệ thống không nên hard-delete tài liệu chỉ vì tài liệu không còn xuất hiện trong danh sách mặc định.                                                           |
| Các thao tác quản trị quan trọng phát sinh từ danh sách phải được kiểm tra quyền lại tại thời điểm thực hiện.                                                   |
| Danh sách phải hỗ trợ số lượng tài liệu lớn thông qua phân trang hoặc cơ chế tải dữ liệu phù hợp.                                                               |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                         |
| --------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền quản lý tài liệu có thể truy cập và xem danh sách tài liệu.                                    |
| Người không có quyền quản lý tài liệu không thể truy cập danh sách quản trị.                                          |
| Danh sách hiển thị đúng các tài liệu thuộc phạm vi quản trị viên được phép quản lý.                                   |
| Mỗi tài liệu được hiển thị tối đa một lần trong danh sách chính dưới dạng một tài liệu logic.                         |
| Phiên bản hiện tại của tài liệu được hiển thị đúng.                                                                   |
| Trạng thái tài liệu được hiển thị đúng với dữ liệu trong hệ thống.                                                    |
| Trạng thái xử lý của tài liệu được hiển thị đúng, bao gồm trường hợp đang xử lý và xử lý thất bại.                    |
| Tài liệu đang `READY_FOR_REVIEW` có thể được nhận biết từ danh sách.                                                  |
| Tài liệu đã `PUBLISHED` có thể được phân biệt với tài liệu chưa xuất bản.                                             |
| Tài liệu `ARCHIVED` không xuất hiện trong danh sách mặc định nếu chính sách mặc định chỉ hiển thị tài liệu hoạt động. |
| Quản trị viên có thể lọc để xem tài liệu `ARCHIVED` khi có quyền.                                                     |
| Khi nhập từ khóa hoặc áp dụng bộ lọc, hệ thống chỉ trả về các tài liệu phù hợp.                                       |
| Bộ lọc không thể làm xuất hiện tài liệu ngoài phạm vi quyền của quản trị viên.                                        |
| Khi không có tài liệu phù hợp, hệ thống hiển thị trạng thái không có kết quả thay vì báo lỗi.                         |
| Khi có nhiều tài liệu, hệ thống hỗ trợ phân trang hoặc cơ chế tải dữ liệu tương đương.                                |
| Quản trị viên có thể chọn một tài liệu trong danh sách để mở Use Case **Xem chi tiết tài liệu**.                      |
| Khi quyền quản trị viên bị thu hồi, các request tiếp theo không còn trả về tài liệu ngoài phạm vi mới.                |

### Dữ liệu liên quan

| Dữ liệu              | Mục đích                                           |
| -------------------- | -------------------------------------------------- |
| `document_id`        | Định danh tài liệu logic trong hệ thống.           |
| `title`              | Tên tài liệu hiển thị trong danh sách.             |
| `document_type`      | Phân loại tài liệu.                                |
| `document_status`    | Xác định trạng thái nghiệp vụ của tài liệu.        |
| `current_version_id` | Xác định phiên bản hiện tại của tài liệu.          |
| `version_number`     | Số phiên bản hiện tại.                             |
| `version_status`     | Trạng thái nghiệp vụ của phiên bản hiện tại.       |
| `processing_status`  | Trạng thái xử lý kỹ thuật của phiên bản.           |
| `department`         | Phòng ban hoặc đơn vị quản lý tài liệu.            |
| `uploaded_by`        | Người upload tài liệu hoặc phiên bản hiện tại.     |
| `created_at`         | Thời điểm tài liệu được tạo.                       |
| `updated_at`         | Thời điểm tài liệu được cập nhật gần nhất.         |
| `published_at`       | Thời điểm tài liệu được xuất bản nếu có.           |
| `search_query`       | Từ khóa quản trị viên nhập để tìm trong danh sách. |
| `filters`            | Các điều kiện lọc đang được áp dụng.               |
| `sort`               | Tiêu chí sắp xếp danh sách.                        |
| `page`               | Trang dữ liệu hiện tại khi sử dụng phân trang.     |
| `page_size`          | Số lượng tài liệu hiển thị trên mỗi trang.         |

### Ghi chú thiết kế

Use Case này mô tả nghiệp vụ:

```text
Quản trị viên
      ↓
Truy cập quản lý tài liệu
      ↓
Hệ thống kiểm tra quyền
      ↓
Lấy danh sách Document
      ↓
Lấy thông tin phiên bản hiện tại
      ↓
Hiển thị trạng thái
      ↓
Tìm kiếm / lọc / sắp xếp
      ↓
Chọn tài liệu
      ↓
Xem chi tiết tài liệu
```

Điểm quan trọng nhất là danh sách chính nên hiển thị theo **Document**, không phải theo từng file hoặc từng version.

Ví dụ đúng:

```text
TÊN TÀI LIỆU          VERSION     STATUS        PROCESSING

Quy định nghỉ phép      v3        PUBLISHED      SUCCEEDED
Quy trình mua hàng      v2        DRAFT          PROCESSING
Quy định bảo mật        v5        PUBLISHED      SUCCEEDED
```

Trong đó:

```text
Quy định nghỉ phép
        │
        └── Document
              ├── v1
              ├── v2
              └── v3 ← current
```

Danh sách chính chỉ có:

```text
Quy định nghỉ phép | v3
```

không nên hiển thị:

```text
Quy định nghỉ phép | v1
Quy định nghỉ phép | v2
Quy định nghỉ phép | v3
```

như ba tài liệu khác nhau.

Nếu Admin muốn xem v1, v2, v3 thì thực hiện:

```text
Xem danh sách tài liệu
        ↓
Xem chi tiết tài liệu
        ↓
Xem lịch sử phiên bản
```

---

Cũng cần phân biệt ba loại trạng thái.

**1. Trạng thái Document**

```text
DRAFT
PUBLISHED
ARCHIVED
```

Phản ánh trạng thái nghiệp vụ của tài liệu.

**2. Trạng thái DocumentVersion**

```text
DRAFT
READY_FOR_REVIEW
ACTIVE
REJECTED
SUPERSEDED
```

Phản ánh vòng đời của một phiên bản.

**3. Trạng thái ProcessingJob**

```text
PENDING
RUNNING
SUCCEEDED
FAILED
```

Phản ánh quá trình xử lý kỹ thuật.

Ví dụ một dòng có thể là:

```text
Quy định nghỉ phép

Document:
PUBLISHED

Current Version:
v3 — ACTIVE

Processing:
SUCCEEDED
```

Trong khi một tài liệu vừa upload có thể là:

```text
Quy định bảo mật

Document:
DRAFT

Version:
v1 — DRAFT

Processing:
RUNNING
```

Hai loại tài liệu này đều cần xuất hiện trong **màn hình quản trị**, vì Admin phải biết tài liệu nào đang xử lý.

---

Các chức năng UI như:

```text
Search box
Filter
Sort
Pagination
Status badge
Table
Infinite scroll
```

không cần tách thành Use Case riêng nếu chúng chỉ phục vụ mục tiêu:

```text
Xem và quản lý danh sách tài liệu
```

Ví dụ:

```text
[Xem danh sách tài liệu]

Tìm kiếm...

Status: [All ▼]
Type:   [All ▼]
Dept:   [All ▼]

──────────────────────────────────────────────
Tên                  Version   Status
──────────────────────────────────────────────
Quy định nghỉ phép     v3      PUBLISHED
Quy trình mua hàng     v2      PROCESSING
Quy định bảo mật       v1      READY_FOR_REVIEW
──────────────────────────────────────────────
```

Tức là `Search`, `Filter`, `Sort`, `Pagination` ở đây là **chức năng hỗ trợ Use Case**, không nhất thiết là bốn Use Case riêng.

### Use case xem chi tiết tài liệu

| Thuộc tính                  | Mô tả                                                                                                                                                                                                                       |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**            | Xem chi tiết tài liệu                                                                                                                                                                                                       |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                                               |
| **Mục tiêu**                | Cho phép quản trị viên xem đầy đủ thông tin của một tài liệu, bao gồm thông tin nghiệp vụ, phiên bản hiện tại, trạng thái xử lý, file nguồn và các thông tin liên quan để phục vụ quản lý, kiểm duyệt và cập nhật tài liệu. |
| **Điều kiện kích hoạt**     | Quản trị viên chọn một tài liệu từ danh sách tài liệu hoặc truy cập trực tiếp vào trang chi tiết của tài liệu.                                                                                                              |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản đang hoạt động.<br>3. Quản trị viên có quyền xem hoặc quản lý tài liệu tương ứng.<br>4. Tài liệu tồn tại trong hệ thống.                                                     |
| **Đầu vào**                 | Tài liệu được quản trị viên lựa chọn, được xác định thông qua `document_id`.                                                                                                                                                |
| **Trạng thái — Thành công** | Hệ thống hiển thị đầy đủ các thông tin mà quản trị viên được phép xem của tài liệu, phiên bản hiện tại và trạng thái xử lý liên quan.                                                                                       |
| **Trạng thái — Thất bại**   | Hệ thống không hiển thị nội dung tài liệu nếu tài liệu không tồn tại, quản trị viên không có quyền hoặc xảy ra lỗi hệ thống.                                                                                                |
| **Use Cases liên quan**     | Xem danh sách tài liệu, Cập nhật thông tin tài liệu, Tạo phiên bản tài liệu mới, Xem lịch sử phiên bản, Kiểm duyệt tài liệu, Phê duyệt và xuất bản tài liệu, Từ chối tài liệu, Lưu trữ tài liệu, Yêu cầu xử lý lại tài liệu |

### Main Flow

| Bước | Actor         | Hành động                                                                                                              |
| ---: | ------------- | ---------------------------------------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Truy cập chức năng **Quản lý tài liệu**.                                                                               |
|    2 | Quản trị viên | Chọn một tài liệu cần xem chi tiết.                                                                                    |
|    3 | System        | Nhận thông tin định danh của tài liệu được lựa chọn.                                                                   |
|    4 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                                                            |
|    5 | System        | Kiểm tra quyền của quản trị viên đối với tài liệu.                                                                     |
|    6 | System        | Kiểm tra tài liệu có tồn tại trong hệ thống hay không.                                                                 |
|    7 | System        | Lấy thông tin nghiệp vụ của tài liệu.                                                                                  |
|    8 | System        | Xác định phiên bản hiện tại hoặc phiên bản đang được xử lý của tài liệu.                                               |
|    9 | System        | Lấy thông tin của phiên bản tương ứng.                                                                                 |
|   10 | System        | Lấy trạng thái xử lý hiện tại của phiên bản tài liệu.                                                                  |
|   11 | System        | Lấy thông tin về file nguồn của phiên bản tài liệu.                                                                    |
|   12 | System        | Lấy các thông tin quản trị có liên quan như người upload, thời gian upload, thời gian cập nhật và trạng thái xuất bản. |
|   13 | System        | Hiển thị giao diện chi tiết tài liệu cho quản trị viên.                                                                |
|   14 | Quản trị viên | Xem thông tin tài liệu và trạng thái hiện tại.                                                                         |
|   15 | Quản trị viên | Có thể thực hiện các thao tác quản lý tiếp theo tùy theo trạng thái tài liệu và quyền hiện tại.                        |

### Thông tin hiển thị trong chi tiết tài liệu

| Nhóm thông tin          | Thông tin có thể hiển thị                                                                    |
| ----------------------- | -------------------------------------------------------------------------------------------- |
| **Thông tin tài liệu**  | Tên tài liệu, loại tài liệu, mô tả, phòng ban, danh mục, ngày hiệu lực, trạng thái tài liệu. |
| **Thông tin phiên bản** | Số phiên bản, trạng thái phiên bản, ngày tạo phiên bản, người tạo hoặc upload phiên bản.     |
| **File nguồn**          | Tên file, định dạng, kích thước, thời điểm upload.                                           |
| **Trạng thái xử lý**    | Trạng thái hiện tại như `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`.                         |
| **Thông tin xử lý**     | Thời điểm bắt đầu, thời điểm hoàn thành, cảnh báo hoặc lỗi xử lý nếu có.                     |
| **Thông tin xuất bản**  | Trạng thái publish, thời điểm publish, người thực hiện publish nếu có.                       |
| **Thông tin quản trị**  | Người tạo tài liệu, thời điểm tạo, người cập nhật gần nhất, thời điểm cập nhật.              |
| **Lịch sử phiên bản**   | Thông tin tóm tắt hoặc liên kết tới chức năng **Xem lịch sử phiên bản**.                     |

### Luồng thay thế/ luồng ngoại lệ

| Điều kiện                                 | Luồng xử lý                                                                                                                                   |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Tài liệu không tồn tại                    | Hệ thống thông báo tài liệu không tồn tại hoặc không còn khả dụng.                                                                            |
| Quản trị viên không có quyền xem tài liệu | Hệ thống từ chối truy cập và không hiển thị nội dung hoặc metadata nhạy cảm của tài liệu.                                                     |
| Tài liệu vừa bị lưu trữ                   | Hệ thống hiển thị trạng thái `ARCHIVED` nếu quản trị viên có quyền xem tài liệu lưu trữ.                                                      |
| Tài liệu chưa có phiên bản hoàn tất xử lý | Hệ thống hiển thị phiên bản hiện tại cùng trạng thái xử lý đang diễn ra.                                                                      |
| Phiên bản đang được xử lý                 | Hệ thống hiển thị trạng thái `PENDING` hoặc `RUNNING` và chưa cho phép thực hiện các thao tác yêu cầu dữ liệu xử lý hoàn chỉnh.               |
| Phiên bản xử lý thất bại                  | Hệ thống hiển thị trạng thái `FAILED`, thông tin lỗi phù hợp và cho phép quản trị viên thực hiện **Yêu cầu xử lý lại tài liệu** nếu có quyền. |
| Phiên bản đang chờ kiểm duyệt             | Hệ thống hiển thị trạng thái `READY_FOR_REVIEW` và cho phép quản trị viên chuyển sang Use Case **Kiểm duyệt tài liệu**.                       |
| Phiên bản đã bị từ chối                   | Hệ thống hiển thị trạng thái `REJECTED` và lý do từ chối nếu thông tin này được lưu.                                                          |
| Tài liệu có nhiều phiên bản               | Hệ thống mặc định hiển thị phiên bản hiện tại; quản trị viên có thể sử dụng **Xem lịch sử phiên bản** để xem các phiên bản cũ.                |
| File nguồn không còn khả dụng             | Hệ thống vẫn hiển thị metadata tài liệu nếu có thể nhưng thông báo file nguồn không khả dụng.                                                 |
| Dịch vụ quản lý tài liệu gặp lỗi          | Hệ thống trả thông báo lỗi có kiểm soát và không hiển thị dữ liệu sai hoặc không đầy đủ như dữ liệu hợp lệ.                                   |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                 |
| --------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền phù hợp mới được xem chi tiết tài liệu.                                                                      |
| Quyền truy cập phải được kiểm tra lại tại thời điểm mở trang chi tiết tài liệu.                                                         |
| Việc biết `document_id` hoặc URL của tài liệu không được phép bypass kiểm tra quyền.                                                    |
| Hệ thống phải phân biệt rõ `Document`, `DocumentVersion` và trạng thái xử lý của phiên bản.                                             |
| Trang chi tiết mặc định phải hiển thị thông tin của tài liệu logic và phiên bản hiện tại hoặc phiên bản cần quản trị.                   |
| Các phiên bản cũ không được hiển thị như phiên bản đang có hiệu lực nếu đã có phiên bản `ACTIVE` mới hơn.                               |
| Tài liệu chưa được xuất bản phải được hiển thị rõ là chưa được sử dụng chính thức trong Knowledge Base.                                 |
| Tài liệu có phiên bản đang `READY_FOR_REVIEW` phải được nhận biết rõ để phục vụ kiểm duyệt.                                             |
| Tài liệu xử lý thất bại phải hiển thị trạng thái lỗi nhưng không được tự động chuyển sang trạng thái sẵn sàng kiểm duyệt hoặc xuất bản. |
| Chỉ phiên bản xử lý thành công mới có thể tiếp tục sang bước kiểm duyệt theo workflow.                                                  |
| File nguồn phải liên kết đúng với `DocumentVersion` tương ứng.                                                                          |
| Các thao tác như cập nhật, tạo phiên bản, phê duyệt, từ chối, lưu trữ hoặc xử lý lại phải tuân theo trạng thái hiện tại của tài liệu.   |
| Hệ thống phải kiểm tra quyền riêng cho từng thao tác quản trị, không chỉ dựa vào việc quản trị viên đã mở được trang chi tiết.          |
| Thông tin kỹ thuật nhạy cảm như credential, secret, internal stack trace không được hiển thị trên giao diện chi tiết tài liệu.          |
| Các thay đổi quan trọng đối với tài liệu phải được ghi nhận phục vụ audit.                                                              |
| Tài liệu `ARCHIVED` không được coi là đã bị xóa khỏi hệ thống.                                                                          |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                     |
| ----------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể mở trang chi tiết của một tài liệu từ danh sách tài liệu.                           |
| Người dùng không có quyền không thể xem chi tiết tài liệu kể cả khi biết trực tiếp `document_id`.                 |
| Hệ thống hiển thị đúng tên, loại, trạng thái và các thông tin nghiệp vụ của tài liệu.                             |
| Hệ thống hiển thị đúng phiên bản hiện tại của tài liệu.                                                           |
| Hệ thống hiển thị đúng số phiên bản và trạng thái phiên bản.                                                      |
| Hệ thống hiển thị đúng trạng thái xử lý hiện tại của phiên bản.                                                   |
| Tài liệu đang `RUNNING` phải được nhận biết rõ là đang được xử lý.                                                |
| Tài liệu xử lý `FAILED` phải được hiển thị rõ trạng thái lỗi.                                                     |
| Tài liệu `READY_FOR_REVIEW` phải có thể được nhận biết để quản trị viên thực hiện kiểm duyệt.                     |
| Tài liệu đã `PUBLISHED` phải được phân biệt với tài liệu chưa xuất bản.                                           |
| Phiên bản `ACTIVE` phải được xác định đúng khi tài liệu có nhiều phiên bản.                                       |
| Phiên bản `SUPERSEDED` không được hiển thị như phiên bản hiện tại.                                                |
| File nguồn hiển thị phải thuộc đúng phiên bản tài liệu tương ứng.                                                 |
| Quản trị viên có thể chuyển từ trang chi tiết sang chức năng **Xem lịch sử phiên bản**.                           |
| Quản trị viên có quyền phù hợp có thể chuyển từ trang chi tiết sang **Cập nhật thông tin tài liệu**.              |
| Khi phiên bản xử lý thất bại, quản trị viên có thể chuyển sang **Yêu cầu xử lý lại tài liệu** nếu được cấp quyền. |
| Khi tài liệu đang chờ kiểm duyệt, quản trị viên có thể chuyển sang **Kiểm duyệt tài liệu**.                       |
| Khi quyền quản trị viên bị thu hồi, lần truy cập tiếp theo phải bị từ chối.                                       |
| Khi tài liệu không tồn tại, hệ thống trả thông báo phù hợp và không phát sinh lỗi không kiểm soát.                |

### Dữ liệu liên quan

| Dữ liệu               | Mục đích                                                                                      |
| --------------------- | --------------------------------------------------------------------------------------------- |
| `document_id`         | Định danh tài liệu logic đang được xem.                                                       |
| `title`               | Tên của tài liệu.                                                                             |
| `description`         | Mô tả nội dung hoặc mục đích tài liệu.                                                        |
| `document_type`       | Phân loại tài liệu.                                                                           |
| `department`          | Phòng ban hoặc đơn vị liên quan.                                                              |
| `document_status`     | Xác định trạng thái nghiệp vụ như `DRAFT`, `PUBLISHED`, `ARCHIVED`.                           |
| `current_version_id`  | Xác định phiên bản hiện tại của tài liệu.                                                     |
| `document_version_id` | Định danh phiên bản cụ thể đang được xem.                                                     |
| `version_number`      | Số phiên bản của tài liệu.                                                                    |
| `version_status`      | Trạng thái của phiên bản như `DRAFT`, `READY_FOR_REVIEW`, `ACTIVE`, `REJECTED`, `SUPERSEDED`. |
| `file_name`           | Tên file nguồn của phiên bản.                                                                 |
| `file_type`           | Định dạng file nguồn.                                                                         |
| `file_size`           | Kích thước file.                                                                              |
| `storage_location`    | Tham chiếu tới nơi lưu file nguồn.                                                            |
| `processing_status`   | Trạng thái quá trình xử lý tài liệu.                                                          |
| `processing_error`    | Thông tin lỗi xử lý phù hợp để quản trị viên theo dõi nếu có.                                 |
| `uploaded_by`         | Người upload phiên bản tài liệu.                                                              |
| `uploaded_at`         | Thời điểm upload phiên bản.                                                                   |
| `created_at`          | Thời điểm tài liệu được tạo.                                                                  |
| `updated_at`          | Thời điểm cập nhật gần nhất.                                                                  |
| `published_at`        | Thời điểm tài liệu được xuất bản nếu có.                                                      |

### Ghi chú thiết kế

Use Case này có thể được hiểu theo luồng:

```text
Quản trị viên
      ↓
Xem danh sách tài liệu
      ↓
Chọn một Document
      ↓
Kiểm tra quyền
      ↓
Lấy thông tin Document
      ↓
Xác định phiên bản hiện tại
      ↓
Lấy DocumentVersion
      ↓
Lấy trạng thái Processing
      ↓
Hiển thị chi tiết
      ↓
Quản trị viên quyết định thao tác tiếp theo
```

Trang chi tiết nên đóng vai trò như **trung tâm quản trị của một tài liệu**.

Ví dụ:

```text
QUY ĐỊNH NGHỈ PHÉP
────────────────────────────────

Document status:
PUBLISHED

Current version:
v3

Version status:
ACTIVE

Processing:
SUCCEEDED

Department:
Human Resources

Effective date:
01/01/2026

File:
quy_dinh_nghi_phep_2026.pdf

Uploaded by:
Admin A
```

Từ màn hình này, tùy trạng thái, quản trị viên có thể thực hiện:

```text
                    Xem chi tiết tài liệu
                             │
            ┌────────────────┼────────────────┐
            │                │                │
            ↓                ↓                ↓
    Cập nhật thông tin   Xem lịch sử     Tạo phiên bản mới
                             │
                             │
          ┌──────────────────┼────────────────────┐
          ↓                  ↓                    ↓
     Kiểm duyệt         Xử lý lại            Lưu trữ
```

Không phải thao tác nào cũng được phép ở mọi trạng thái.

Ví dụ:

```text
Version = RUNNING
→ Không thể phê duyệt

Version = FAILED
→ Có thể xử lý lại
→ Không thể publish

Version = READY_FOR_REVIEW
→ Có thể kiểm duyệt

Version = ACTIVE
→ Có thể tạo phiên bản mới

Document = ARCHIVED
→ Không được sử dụng cho truy vấn hiện tại
```

---

Cần tiếp tục giữ rõ ba lớp trạng thái:

```text
Document
DRAFT
PUBLISHED
ARCHIVED
```

```text
DocumentVersion
DRAFT
READY_FOR_REVIEW
ACTIVE
REJECTED
SUPERSEDED
```

```text
ProcessingJob
PENDING
RUNNING
SUCCEEDED
FAILED
```

Ví dụ một tài liệu mới:

```text
Document
└── DRAFT

DocumentVersion v1
└── DRAFT

ProcessingJob
└── RUNNING
```

Sau khi xử lý:

```text
Document
└── DRAFT

DocumentVersion v1
└── READY_FOR_REVIEW

ProcessingJob
└── SUCCEEDED
```

Sau khi được phê duyệt và xuất bản:

```text
Document
└── PUBLISHED

DocumentVersion v1
└── ACTIVE

ProcessingJob
└── SUCCEEDED
```

Đây là lý do trang **Xem chi tiết tài liệu** không nên chỉ có một field chung:

```text
status = READY
```

vì Admin sẽ không biết `READY` đang nói về:

* quá trình xử lý đã xong;
* phiên bản đã được review;
* hay tài liệu đã được publish.

Ba trạng thái cần được quản lý riêng.

---

Các thông tin kỹ thuật sâu như:

```text
Chunk count
Embedding model
Vector IDs
OCR engine
Parser name
RRF score
Embedding dimension
```

không phải thông tin nghiệp vụ bắt buộc của Use Case này.

Nếu cần phục vụ vận hành/debug, chúng có thể được đặt trong một phần riêng như:

```text
Technical Information
Processing Details
Diagnostics
```

và chỉ hiển thị cho Admin phù hợp.

Mục tiêu chính của Use Case **Xem chi tiết tài liệu** vẫn là:

```text
Tài liệu này là gì?
        +
Đang ở phiên bản nào?
        +
Đang ở trạng thái nào?
        +
Đã xử lý thành công chưa?
        +
Đã được publish chưa?
        +
Admin có thể làm gì tiếp theo?
```

### Use case cập nhật metadata tài liệu

| Thuộc tính                  | Mô tả                                                                                                                                                                                                                                     |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**            | Cập nhật thông tin tài liệu                                                                                                                                                                                                               |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                                                             |
| **Mục tiêu**                | Cho phép quản trị viên cập nhật các metadata nghiệp vụ của tài liệu nhằm đảm bảo tài liệu được mô tả, phân loại và quản lý chính xác mà không làm thay đổi trực tiếp nội dung file nguồn.                                                 |
| **Điều kiện kích hoạt**     | Quản trị viên đang xem chi tiết một tài liệu và chọn chức năng **Chỉnh sửa thông tin tài liệu**.                                                                                                                                          |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản đang hoạt động.<br>3. Quản trị viên có quyền cập nhật tài liệu tương ứng.<br>4. Tài liệu tồn tại trong hệ thống.<br>5. Tài liệu không ở trạng thái cấm chỉnh sửa theo chính sách hệ thống. |
| **Đầu vào**                 | Các metadata nghiệp vụ được phép chỉnh sửa như tên tài liệu, loại tài liệu, mô tả, danh mục, từ khóa, phòng ban phụ trách, ngày ban hành, ngày hiệu lực hoặc các thông tin nghiệp vụ khác theo cấu hình hệ thống.                         |
| **Trạng thái — Thành công** | Metadata mới được lưu; tài liệu phản ánh thông tin cập nhật; hệ thống ghi nhận người thực hiện, thời gian và nội dung thay đổi phục vụ audit.                                                                                             |
| **Trạng thái — Thất bại**   | Metadata cũ được giữ nguyên; hệ thống thông báo nguyên nhân và không lưu dữ liệu ở trạng thái không nhất quán.                                                                                                                            |
| **Use Cases liên quan**     | Xem chi tiết tài liệu, Xem danh sách tài liệu, Tạo phiên bản tài liệu mới, Kiểm duyệt tài liệu, Thiết lập quyền truy cập tài liệu                                                                                                         |

### Main Flow

| Bước | Actor         | Hành động                                                                                       |
| ---: | ------------- | ----------------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Mở **Xem chi tiết tài liệu**.                                                                   |
|    2 | Quản trị viên | Chọn chức năng **Chỉnh sửa thông tin tài liệu**.                                                |
|    3 | System        | Kiểm tra phiên đăng nhập và quyền cập nhật tài liệu của quản trị viên.                          |
|    4 | System        | Lấy metadata hiện tại của tài liệu.                                                             |
|    5 | System        | Hiển thị các trường metadata được phép chỉnh sửa.                                               |
|    6 | Quản trị viên | Chỉnh sửa một hoặc nhiều trường metadata.                                                       |
|    7 | Quản trị viên | Chọn **Lưu thay đổi**.                                                                          |
|    8 | System        | Kiểm tra tính đầy đủ và hợp lệ của metadata mới.                                                |
|    9 | System        | Kiểm tra các giá trị có tuân thủ quy tắc nghiệp vụ của từng trường hay không.                   |
|   10 | System        | Xác định thay đổi có thuộc phạm vi được phép cập nhật trực tiếp hay yêu cầu một quy trình khác. |
|   11 | System        | Lưu metadata mới cho tài liệu nếu dữ liệu hợp lệ.                                               |
|   12 | System        | Ghi nhận giá trị trước và sau của các trường thay đổi theo chính sách audit.                    |
|   13 | System        | Ghi nhận quản trị viên thực hiện và thời điểm cập nhật.                                         |
|   14 | System        | Thông báo cập nhật thành công.                                                                  |
|   15 | System        | Hiển thị lại trang chi tiết tài liệu với metadata mới.                                          |

### Các metadata có thể chỉnh sửa

| Metadata                | Ý nghĩa                                                                      |
| ----------------------- | ---------------------------------------------------------------------------- |
| **Tên tài liệu**        | Tên nghiệp vụ được hiển thị cho quản trị viên và người dùng.                 |
| **Mô tả**               | Mô tả ngắn về nội dung hoặc mục đích của tài liệu.                           |
| **Loại tài liệu**       | Phân loại như Quy định, Quy trình, Hướng dẫn, Báo cáo, Biểu mẫu...           |
| **Danh mục**            | Nhóm chủ đề hoặc lĩnh vực mà tài liệu thuộc về.                              |
| **Từ khóa / Tags**      | Các từ khóa hỗ trợ phân loại và truy xuất tài liệu.                          |
| **Phòng ban phụ trách** | Đơn vị nghiệp vụ chịu trách nhiệm quản lý tài liệu.                          |
| **Số / mã văn bản**     | Mã nghiệp vụ của tài liệu nếu có.                                            |
| **Ngày ban hành**       | Ngày tài liệu được ban hành theo nghiệp vụ.                                  |
| **Ngày hiệu lực**       | Thời điểm tài liệu bắt đầu có hiệu lực.                                      |
| **Ngày hết hiệu lực**   | Thời điểm tài liệu hết hiệu lực nếu có.                                      |
| **Nguồn tài liệu**      | Thông tin về nguồn phát hành hoặc đơn vị cung cấp tài liệu nếu được quản lý. |

### Metadata không được chỉnh sửa trực tiếp

| Metadata              | Lý do                                                                                    |
| --------------------- | ---------------------------------------------------------------------------------------- |
| `document_id`         | Định danh hệ thống, không phải dữ liệu nghiệp vụ có thể chỉnh sửa.                       |
| `document_version_id` | Định danh phiên bản tài liệu.                                                            |
| `version_number`      | Do cơ chế quản lý phiên bản của hệ thống quyết định.                                     |
| `file_hash`           | Được sinh từ nội dung file nhằm kiểm tra tính toàn vẹn và duplicate.                     |
| `storage_location`    | Do hệ thống lưu trữ quản lý.                                                             |
| `processing_status`   | Do quá trình xử lý tài liệu quyết định.                                                  |
| `version_status`      | Phải thay đổi thông qua workflow tương ứng, không được sửa trực tiếp bằng form metadata. |
| `document_status`     | Phải thay đổi thông qua các nghiệp vụ như xuất bản hoặc lưu trữ.                         |
| `uploaded_by`         | Thông tin lịch sử của người upload.                                                      |
| `uploaded_at`         | Thời điểm upload do hệ thống ghi nhận.                                                   |
| `created_at`          | Thời điểm tạo dữ liệu do hệ thống quản lý.                                               |

### Luồng thay thế/ luồng ngoại lệ

| Điều kiện                                                                   | Luồng xử lý                                                                                                                                        |
| --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền chỉnh sửa tài liệu                             | Hệ thống từ chối thao tác và không hiển thị hoặc vô hiệu hóa chức năng chỉnh sửa.                                                                  |
| Tài liệu không tồn tại                                                      | Hệ thống thông báo tài liệu không tồn tại hoặc không còn khả dụng.                                                                                 |
| Trường bắt buộc bị để trống                                                 | Hệ thống không lưu thay đổi và yêu cầu quản trị viên bổ sung dữ liệu.                                                                              |
| Giá trị metadata không đúng định dạng                                       | Hệ thống thông báo trường không hợp lệ và yêu cầu chỉnh sửa.                                                                                       |
| Ngày hiệu lực không hợp lệ                                                  | Hệ thống từ chối lưu và yêu cầu kiểm tra lại thông tin thời gian.                                                                                  |
| Giá trị loại tài liệu hoặc danh mục không thuộc danh mục cho phép           | Hệ thống không lưu giá trị không hợp lệ và yêu cầu chọn giá trị phù hợp.                                                                           |
| Quản trị viên cố chỉnh sửa metadata hệ thống                                | Hệ thống không cho phép cập nhật các trường được quản lý tự động.                                                                                  |
| Quản trị viên muốn thay đổi nội dung file                                   | Hệ thống không xử lý trong Use Case này và hướng sang **Tạo phiên bản tài liệu mới**.                                                              |
| Quản trị viên thay đổi trường liên quan đến quyền truy cập                  | Nếu trường thuộc chính sách ACL, hệ thống không xử lý như metadata thông thường và yêu cầu sử dụng Use Case **Thiết lập quyền truy cập tài liệu**. |
| Thay đổi metadata ảnh hưởng đến trạng thái kiểm duyệt theo chính sách       | Hệ thống có thể yêu cầu tài liệu được kiểm duyệt lại trước khi metadata mới được sử dụng chính thức.                                               |
| Metadata đã được người khác cập nhật trong lúc quản trị viên đang chỉnh sửa | Hệ thống phát hiện xung đột cập nhật và yêu cầu quản trị viên tải lại dữ liệu mới trước khi tiếp tục.                                              |
| Lưu metadata thất bại                                                       | Hệ thống giữ dữ liệu cũ, không tạo bản cập nhật một phần và trả thông báo lỗi có kiểm soát.                                                        |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                                                |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền cập nhật tài liệu mới được thay đổi metadata.                                                                                               |
| Hệ thống phải phân biệt metadata nghiệp vụ có thể chỉnh sửa với metadata kỹ thuật do hệ thống quản lý.                                                                 |
| `document_id`, `document_version_id`, `file_hash`, trạng thái xử lý và các định danh hệ thống không được chỉnh sửa thủ công.                                           |
| Thay đổi metadata không được làm thay đổi trực tiếp nội dung của file nguồn.                                                                                           |
| Nếu nội dung file thay đổi, quản trị viên phải sử dụng Use Case **Tạo phiên bản tài liệu mới**.                                                                        |
| Việc đổi tên hiển thị, mô tả, tags hoặc danh mục không tự động tạo một `DocumentVersion` mới nếu nội dung tài liệu không thay đổi, trừ khi doanh nghiệp quy định khác. |
| Những metadata mang tính pháp lý hoặc ảnh hưởng đến hiệu lực tài liệu có thể phải được kiểm duyệt lại theo chính sách doanh nghiệp.                                    |
| Quyền truy cập tài liệu không được thay đổi gián tiếp thông qua các trường metadata thông thường.                                                                      |
| Các thay đổi về Role, Group, Department ACL hoặc Access Policy phải được thực hiện thông qua nghiệp vụ phân quyền riêng.                                               |
| Nếu `department` chỉ là thông tin phân loại thì có thể cập nhật ở đây; nếu `department` quyết định quyền truy cập thì thay đổi phải tuân thủ quy trình phân quyền.     |
| Hệ thống phải kiểm tra giá trị metadata trước khi lưu.                                                                                                                 |
| Các trường sử dụng danh mục chuẩn phải nhận giá trị thuộc danh mục được hệ thống cho phép.                                                                             |
| Hệ thống phải lưu được người thực hiện và thời điểm thay đổi metadata.                                                                                                 |
| Các thay đổi quan trọng phải có khả năng truy vết giá trị trước và sau phục vụ audit.                                                                                  |
| Cập nhật metadata của tài liệu `PUBLISHED` không được vô tình làm tài liệu chưa được kiểm duyệt trở thành nguồn tri thức hợp lệ.                                       |
| Cập nhật metadata không được làm thay đổi trạng thái `PUBLISHED`, `ACTIVE`, `ARCHIVED`, `READY_FOR_REVIEW`... nếu không thông qua đúng workflow nghiệp vụ.             |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                                |
| ---------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể mở chức năng chỉnh sửa metadata từ trang chi tiết tài liệu.                                    |
| Hệ thống hiển thị đúng metadata hiện tại của tài liệu.                                                                       |
| Quản trị viên có thể chỉnh sửa các trường metadata nghiệp vụ được phép.                                                      |
| Metadata hợp lệ được lưu và hiển thị chính xác sau khi cập nhật.                                                             |
| Trường bắt buộc không được phép để trống.                                                                                    |
| Metadata không đúng định dạng không được lưu.                                                                                |
| Quản trị viên không thể chỉnh sửa `document_id`.                                                                             |
| Quản trị viên không thể chỉnh sửa trực tiếp `version_number`.                                                                |
| Quản trị viên không thể thay đổi `processing_status` bằng chức năng cập nhật metadata.                                       |
| Quản trị viên không thể thay đổi `version_status` bằng chức năng cập nhật metadata.                                          |
| Thay đổi tên, mô tả hoặc tags không tạo phiên bản file mới nếu nội dung tài liệu không thay đổi.                             |
| Khi quản trị viên muốn thay file nguồn, hệ thống yêu cầu thực hiện **Tạo phiên bản tài liệu mới** thay vì cập nhật metadata. |
| Quyền truy cập của tài liệu không được tự động thay đổi chỉ vì metadata thông thường được chỉnh sửa.                         |
| Thay đổi metadata phải ghi nhận được người thực hiện và thời điểm cập nhật.                                                  |
| Các metadata quan trọng có thể truy vết được giá trị trước và sau khi thay đổi theo chính sách audit.                        |
| Khi hai quản trị viên cập nhật cùng một tài liệu gây xung đột, hệ thống không được âm thầm ghi đè dữ liệu mới hơn.           |
| Khi lưu thất bại, metadata trước khi chỉnh sửa vẫn được giữ nguyên.                                                          |
| Sau khi cập nhật thành công, trang chi tiết tài liệu hiển thị metadata mới nhất.                                             |

### Dữ liệu liên quan

| Dữ liệu           | Mục đích                                       |
| ----------------- | ---------------------------------------------- |
| `document_id`     | Xác định tài liệu cần cập nhật.                |
| `title`           | Tên hiển thị của tài liệu.                     |
| `description`     | Mô tả tài liệu.                                |
| `document_type`   | Phân loại nghiệp vụ của tài liệu.              |
| `category`        | Danh mục hoặc chủ đề tài liệu.                 |
| `keywords`        | Các từ khóa liên quan.                         |
| `tags`            | Các nhãn phục vụ quản lý và truy xuất.         |
| `department`      | Đơn vị phụ trách hoặc phân loại tài liệu.      |
| `document_number` | Mã hoặc số hiệu nghiệp vụ của tài liệu nếu có. |
| `issued_date`     | Ngày ban hành tài liệu.                        |
| `effective_date`  | Ngày tài liệu bắt đầu có hiệu lực.             |
| `expiration_date` | Ngày hết hiệu lực nếu có.                      |
| `source`          | Nguồn tài liệu.                                |
| `updated_by`      | Quản trị viên thực hiện thay đổi gần nhất.     |
| `updated_at`      | Thời điểm metadata được cập nhật gần nhất.     |

### Ghi chú thiết kế

Cần phân biệt rõ hai trường hợp:

```text
TRƯỜNG HỢP 1
Chỉ thay đổi metadata
────────────────────────

"Quy định nghỉ phép"
        ↓
Sửa title / mô tả / category / tags
        ↓
Document vẫn là DOC-001
        ↓
File nguồn không thay đổi
        ↓
Không tạo version mới
```

Ví dụ:

```text
Trước:
Title = "Quy định nghỉ phép"

Sau:
Title = "Quy định về chế độ nghỉ phép"

File:
quy_dinh_nghi_phep_2026.pdf

→ File không đổi
→ Nội dung không đổi
→ Không cần DocumentVersion mới
```

Trong khi:

```text
TRƯỜNG HỢP 2
Nội dung tài liệu thay đổi
──────────────────────────

Admin có file mới
        ↓
quy_dinh_nghi_phep_2027.pdf
        ↓
Không dùng "Cập nhật metadata"
        ↓
Tạo phiên bản tài liệu mới
```

Kết quả:

```text
Document DOC-001
"Quy định nghỉ phép"

├── v1 — SUPERSEDED
├── v2 — SUPERSEDED
└── v3 — ACTIVE
```

---

Một nguyên tắc quan trọng khác là phân biệt:

```text
Business Metadata
```

với:

```text
System Metadata
```

**Business Metadata** có thể được Admin quản lý:

```text
Title
Description
Document Type
Category
Keywords
Tags
Department
Document Number
Issued Date
Effective Date
Source
```

**System Metadata** do hệ thống quản lý:

```text
document_id
document_version_id
file_hash
storage_location
processing_status
version_status
created_at
uploaded_at
embedding information
chunk identifiers
```

Admin không nên sửa trực tiếp nhóm thứ hai.

---

Đặc biệt với `Department` cần xác định rõ ý nghĩa.

Nếu:

```text
department = "Human Resources"
```

chỉ để nói:

> Đây là tài liệu thuộc lĩnh vực/phòng ban Nhân sự.

thì có thể xem nó là metadata.

Nhưng nếu:

```text
Department = HR
→ chỉ nhân viên HR được đọc
```

thì đây không còn chỉ là metadata mà đã tham gia vào **Access Control**.

Khi đó nên xử lý:

```text
Cập nhật metadata
        │
        └── Department = HR
             chỉ là thông tin phân loại

Thiết lập quyền truy cập
        │
        └── HR Department → READ
             là chính sách ACL
```

Không nên trộn hai khái niệm thành một.

---

Use Case này về bản chất là:

```text
Quản trị viên
      ↓
Xem chi tiết tài liệu
      ↓
Chọn chỉnh sửa
      ↓
Thay đổi metadata nghiệp vụ
      ↓
Validate
      ↓
Lưu thay đổi
      ↓
Audit
      ↓
Hiển thị metadata mới
```

chứ không phải:

```text
Admin sửa metadata
      ↓
Re-extract
      ↓
Re-chunk
      ↓
Re-embed toàn bộ
```

Mặc định, thay đổi metadata hiển thị thông thường **không nhất thiết phải chạy lại toàn bộ ingestion pipeline**.

Tuy nhiên nếu một metadata được sử dụng trực tiếp cho retrieval/filter/index, ví dụ:

```text
document_type
category
department
effective_date
tags
```

thì hệ thống có thể cần đồng bộ metadata mới xuống search/vector index.

Đó là **xử lý kỹ thuật nội bộ**, không phải Use Case riêng:

```text
Admin cập nhật metadata
        ↓
Database cập nhật
        ↓
System đồng bộ metadata index
```

Chi tiết này nên được thể hiện trong **Sequence Diagram của Use Case Cập nhật thông tin tài liệu**, không cần đưa thành một Use Case mới.

### Use case tạo phiên bản tài liệu mới

| Thuộc tính                  | Mô tả                                                                                                                                                                                                                                                                                                                        |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**            | Tạo phiên bản tài liệu mới                                                                                                                                                                                                                                                                                                   |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                                                                                                                                                |
| **Mục tiêu**                | Cho phép quản trị viên cập nhật nội dung của một tài liệu đã tồn tại bằng cách tải lên một file mới và tạo một phiên bản mới, đồng thời giữ lại lịch sử các phiên bản trước đó.                                                                                                                                              |
| **Điều kiện kích hoạt**     | Quản trị viên đang xem chi tiết một tài liệu và chọn chức năng **Tạo phiên bản mới**.                                                                                                                                                                                                                                        |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản đang hoạt động.<br>3. Quản trị viên có quyền cập nhật tài liệu tương ứng.<br>4. Tài liệu đã tồn tại trong hệ thống.<br>5. File phiên bản mới thuộc định dạng và kích thước hệ thống hỗ trợ.<br>6. Tài liệu không ở trạng thái cấm tạo phiên bản mới theo chính sách hệ thống. |
| **Đầu vào**                 | File tài liệu mới; có thể kèm thông tin của phiên bản như mô tả thay đổi, ngày ban hành, ngày hiệu lực hoặc ghi chú phiên bản nếu hệ thống yêu cầu.                                                                                                                                                                          |
| **Trạng thái — Thành công** | Một `DocumentVersion` mới được tạo và liên kết với đúng `Document`; file nguồn mới được lưu; quá trình xử lý phiên bản mới được khởi tạo; phiên bản hiện hành trước đó vẫn được giữ nguyên cho đến khi phiên bản mới được kiểm duyệt và xuất bản thành công.                                                                 |
| **Trạng thái — Thất bại**   | Không tạo phiên bản mới hoặc phiên bản được ghi nhận ở trạng thái lỗi phù hợp; phiên bản đang có hiệu lực của tài liệu không bị thay đổi.                                                                                                                                                                                    |
| **Use Cases liên quan**     | Xem chi tiết tài liệu, Xem lịch sử phiên bản, Theo dõi trạng thái xử lý, Kiểm duyệt tài liệu, Phê duyệt và xuất bản tài liệu, Từ chối tài liệu, Yêu cầu xử lý lại tài liệu                                                                                                                                                   |

### Main Flow

| Bước | Actor         | Hành động                                                                                                    |
| ---: | ------------- | ------------------------------------------------------------------------------------------------------------ |
|    1 | Quản trị viên | Mở chức năng **Xem chi tiết tài liệu**.                                                                      |
|    2 | Quản trị viên | Chọn **Tạo phiên bản mới**.                                                                                  |
|    3 | System        | Kiểm tra phiên đăng nhập và quyền cập nhật tài liệu của quản trị viên.                                       |
|    4 | System        | Kiểm tra tài liệu tồn tại và có được phép tạo phiên bản mới hay không.                                       |
|    5 | System        | Hiển thị thông tin tài liệu hiện tại và giao diện tải lên phiên bản mới.                                     |
|    6 | Quản trị viên | Chọn file chứa nội dung phiên bản mới.                                                                       |
|    7 | Quản trị viên | Nhập hoặc xác nhận các thông tin cần thiết của phiên bản mới.                                                |
|    8 | Quản trị viên | Gửi yêu cầu tạo phiên bản mới.                                                                               |
|    9 | System        | Kiểm tra định dạng, kích thước và tính hợp lệ của file.                                                      |
|   10 | System        | Kiểm tra file mới có trùng hoàn toàn với phiên bản đã tồn tại hay không.                                     |
|   11 | System        | Xác định phiên bản hiện tại của tài liệu.                                                                    |
|   12 | System        | Xác định số phiên bản mới tiếp theo.                                                                         |
|   13 | System        | Tạo một `DocumentVersion` mới và liên kết với `Document` hiện tại.                                           |
|   14 | System        | Lưu file nguồn của phiên bản mới.                                                                            |
|   15 | System        | Lưu thông tin phiên bản và quan hệ với phiên bản trước đó.                                                   |
|   16 | System        | Khởi tạo quá trình xử lý phiên bản mới.                                                                      |
|   17 | System        | Đặt phiên bản mới ở trạng thái phù hợp như `DRAFT` và quá trình xử lý ở trạng thái `PENDING` hoặc `RUNNING`. |
|   18 | System        | Giữ nguyên phiên bản `ACTIVE` hiện tại; chưa thay đổi phiên bản đang được Employee sử dụng.                  |
|   19 | System        | Ghi nhận sự kiện tạo phiên bản mới theo chính sách audit.                                                    |
|   20 | System        | Thông báo tạo phiên bản mới thành công.                                                                      |
|   21 | Quản trị viên | Có thể theo dõi trạng thái xử lý của phiên bản mới.                                                          |

### Luồng sau khi xử lý thành công

| Bước | Actor         | Hành động                                                                 |
| ---: | ------------- | ------------------------------------------------------------------------- |
|    1 | System        | Hoàn tất quá trình xử lý phiên bản mới.                                   |
|    2 | System        | Xác nhận dữ liệu cần thiết của phiên bản đã được xử lý thành công.        |
|    3 | System        | Chuyển phiên bản mới sang trạng thái `READY_FOR_REVIEW`.                  |
|    4 | Quản trị viên | Thực hiện Use Case **Kiểm duyệt tài liệu**.                               |
|    5 | Quản trị viên | Nếu phiên bản đạt yêu cầu, thực hiện **Phê duyệt và xuất bản tài liệu**.  |
|    6 | System        | Chuyển phiên bản mới thành `ACTIVE`.                                      |
|    7 | System        | Chuyển phiên bản `ACTIVE` trước đó thành `SUPERSEDED`.                    |
|    8 | System        | Cập nhật phiên bản hiện tại của `Document` sang phiên bản mới.            |
|    9 | System        | Phiên bản mới bắt đầu được sử dụng cho các truy vấn phù hợp của Employee. |

### Luồng thay thế/ luồng ngoại lệ

| Điều kiện                                          | Luồng xử lý                                                                                                                                  |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền tạo phiên bản mới     | Hệ thống từ chối thao tác và không tạo `DocumentVersion`.                                                                                    |
| Tài liệu không tồn tại                             | Hệ thống thông báo tài liệu không tồn tại hoặc không còn khả dụng.                                                                           |
| Quản trị viên chưa chọn file                       | Hệ thống yêu cầu chọn file trước khi tiếp tục.                                                                                               |
| File có định dạng không được hỗ trợ                | Hệ thống từ chối file và thông báo định dạng không hợp lệ.                                                                                   |
| File vượt quá kích thước cho phép                  | Hệ thống từ chối và thông báo giới hạn kích thước.                                                                                           |
| File bị hỏng hoặc không thể đọc                    | Hệ thống không đưa file vào quá trình xử lý và thông báo lỗi.                                                                                |
| File mới trùng hoàn toàn với phiên bản hiện tại    | Hệ thống không tạo thêm phiên bản trùng và thông báo phiên bản này đã tồn tại.                                                               |
| File mới trùng với một phiên bản cũ                | Hệ thống cảnh báo hoặc từ chối tạo phiên bản theo chính sách hệ thống để tránh tạo version lặp lại không cần thiết.                          |
| Tài liệu đang có một phiên bản mới khác được xử lý | Hệ thống áp dụng chính sách đồng thời: có thể từ chối tạo thêm phiên bản hoặc yêu cầu quản trị viên xử lý xong phiên bản đang tồn tại trước. |
| Quá trình lưu file thất bại                        | Hệ thống không hoàn tất việc tạo phiên bản và không làm thay đổi phiên bản đang `ACTIVE`.                                                    |
| Quá trình xử lý phiên bản mới thất bại             | Phiên bản mới được ghi nhận trạng thái xử lý `FAILED`; phiên bản hiện tại vẫn tiếp tục `ACTIVE`.                                             |
| Phiên bản mới bị từ chối khi kiểm duyệt            | Phiên bản mới chuyển sang `REJECTED`; phiên bản cũ vẫn giữ trạng thái `ACTIVE`.                                                              |
| Tài liệu đã được lưu trữ                           | Hệ thống có thể từ chối tạo phiên bản mới hoặc yêu cầu khôi phục tài liệu trước, tùy chính sách nghiệp vụ.                                   |
| Hai quản trị viên đồng thời tạo phiên bản mới      | Hệ thống phải kiểm soát xung đột version để không tạo hai phiên bản có cùng `version_number`.                                                |
| Dịch vụ hệ thống không khả dụng                    | Hệ thống trả lỗi có kiểm soát và không thay đổi phiên bản hiện hành.                                                                         |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền cập nhật tài liệu mới được tạo phiên bản mới.                                                                    |
| Phiên bản mới phải thuộc về một `Document` đã tồn tại.                                                                                      |
| Tạo phiên bản mới không được tạo một `Document` logic mới nếu nội dung mới là bản cập nhật của cùng một tài liệu nghiệp vụ.                 |
| Mỗi `DocumentVersion` phải có định danh riêng và liên kết với đúng `Document`.                                                              |
| `version_number` phải duy nhất trong phạm vi một `Document`.                                                                                |
| Số phiên bản phải được hệ thống quản lý, không cho quản trị viên tự sửa trực tiếp.                                                          |
| File nguồn của mỗi phiên bản phải được lưu và liên kết đúng với `DocumentVersion` tương ứng.                                                |
| File trùng hoàn toàn với phiên bản đã tồn tại không nên tạo thêm phiên bản mới.                                                             |
| Phiên bản mới không được tự động trở thành phiên bản `ACTIVE` ngay sau khi upload.                                                          |
| Phiên bản hiện tại phải tiếp tục phục vụ người dùng cho đến khi phiên bản mới được xử lý, kiểm duyệt và xuất bản thành công.                |
| Phiên bản mới chưa được phê duyệt không được sử dụng làm nguồn trả lời chính thức cho Employee.                                             |
| Khi phiên bản mới được xuất bản thành công, phiên bản `ACTIVE` cũ phải chuyển thành `SUPERSEDED`.                                           |
| Tại một thời điểm, một tài liệu chỉ nên có tối đa một phiên bản `ACTIVE`.                                                                   |
| Phiên bản `SUPERSEDED` phải được giữ lại phục vụ lịch sử, audit hoặc truy vấn lịch sử khi được phép.                                        |
| Phiên bản `REJECTED` không được sử dụng để trả lời Employee.                                                                                |
| Phiên bản xử lý `FAILED` không được chuyển sang `READY_FOR_REVIEW`.                                                                         |
| Khi quá trình tạo phiên bản mới thất bại, phiên bản đang `ACTIVE` không được bị ảnh hưởng.                                                  |
| Hệ thống phải ghi nhận người tạo phiên bản, thời điểm tạo và quan hệ với phiên bản trước đó.                                                |
| Việc chuyển trạng thái phiên bản phải tuân thủ đúng workflow, không được chỉnh sửa trạng thái trực tiếp từ chức năng cập nhật metadata.     |
| Quyền truy cập của tài liệu mới phải tiếp tục tuân theo Access Policy tương ứng; tạo version mới không được tự động mở rộng quyền truy cập. |
| Nếu phiên bản mới thay đổi phạm vi bảo mật hoặc phân loại nhạy cảm, chính sách truy cập phải được kiểm tra lại trước khi xuất bản.          |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                           |
| ------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể tạo phiên bản mới từ trang chi tiết tài liệu.                             |
| Người không có quyền không thể tạo phiên bản mới.                                                       |
| Phiên bản mới phải được liên kết đúng với `Document` hiện tại.                                          |
| Việc tạo phiên bản mới không tạo một `Document` nghiệp vụ mới.                                          |
| Hệ thống tự động xác định đúng `version_number` tiếp theo.                                              |
| Hai phiên bản của cùng một tài liệu không được có cùng `version_number`.                                |
| File nguồn được lưu đúng với phiên bản mới.                                                             |
| Upload lại chính xác file của phiên bản hiện tại không tạo version mới.                                 |
| Sau khi tạo thành công, phiên bản mới chưa được đánh dấu `ACTIVE`.                                      |
| Trong khi phiên bản mới đang xử lý, phiên bản cũ vẫn tiếp tục `ACTIVE`.                                 |
| Phiên bản mới xử lý `FAILED` không ảnh hưởng đến phiên bản đang `ACTIVE`.                               |
| Phiên bản mới xử lý thành công có thể chuyển sang `READY_FOR_REVIEW`.                                   |
| Phiên bản `READY_FOR_REVIEW` chưa được sử dụng mặc định cho truy vấn Employee.                          |
| Khi phiên bản mới bị `REJECTED`, phiên bản cũ vẫn tiếp tục `ACTIVE`.                                    |
| Khi phiên bản mới được phê duyệt và xuất bản, phiên bản mới trở thành `ACTIVE`.                         |
| Khi phiên bản mới trở thành `ACTIVE`, phiên bản trước đó phải chuyển thành `SUPERSEDED`.                |
| Tại một thời điểm không tồn tại hai phiên bản `ACTIVE` của cùng một tài liệu.                           |
| Employee mặc định truy vấn đúng phiên bản `ACTIVE` mới sau khi quá trình publish hoàn tất.              |
| Các phiên bản cũ vẫn có thể được xem trong **Xem lịch sử phiên bản**.                                   |
| Hệ thống ghi nhận được người tạo phiên bản và thời điểm tạo.                                            |
| Khi xảy ra lỗi trong quá trình tạo phiên bản, không để lại version number hoặc dữ liệu không nhất quán. |
| Khi hai yêu cầu tạo phiên bản xảy ra đồng thời, hệ thống không tạo hai phiên bản có cùng số phiên bản.  |

### Dữ liệu liên quan

| Dữ liệu               | Mục đích                                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------------------- |
| `document_id`         | Định danh tài liệu logic cần tạo phiên bản mới.                                                         |
| `document_version_id` | Định danh duy nhất của phiên bản mới.                                                                   |
| `version_number`      | Số thứ tự của phiên bản.                                                                                |
| `previous_version_id` | Xác định phiên bản trước của phiên bản mới nếu hệ thống lưu quan hệ trực tiếp.                          |
| `version_status`      | Trạng thái nghiệp vụ của phiên bản như `DRAFT`, `READY_FOR_REVIEW`, `ACTIVE`, `REJECTED`, `SUPERSEDED`. |
| `file_name`           | Tên file nguồn của phiên bản mới.                                                                       |
| `file_type`           | Định dạng file.                                                                                         |
| `file_size`           | Kích thước file.                                                                                        |
| `file_hash`           | Hỗ trợ phát hiện file trùng hoàn toàn.                                                                  |
| `storage_location`    | Vị trí lưu file nguồn của phiên bản.                                                                    |
| `processing_status`   | Trạng thái xử lý phiên bản mới.                                                                         |
| `change_summary`      | Mô tả nội dung thay đổi của phiên bản nếu có.                                                           |
| `issued_date`         | Ngày ban hành của phiên bản nếu nghiệp vụ yêu cầu.                                                      |
| `effective_date`      | Ngày phiên bản bắt đầu có hiệu lực.                                                                     |
| `created_by`          | Quản trị viên tạo phiên bản.                                                                            |
| `created_at`          | Thời điểm phiên bản được tạo.                                                                           |
| `approved_by`         | Người phê duyệt phiên bản nếu có.                                                                       |
| `approved_at`         | Thời điểm phê duyệt.                                                                                    |
| `published_at`        | Thời điểm phiên bản trở thành nguồn chính thức.                                                         |

### Ghi chú thiết kế

Cần phân biệt rõ:

```text
Document
```

và:

```text
DocumentVersion
```

Ví dụ tài liệu:

```text
Document DOC-001
"Quy định nghỉ phép"
```

có thể tồn tại:

```text
DOC-001
│
├── Version 1
│   ├── File: quy_dinh_nghi_phep_2024.pdf
│   └── Status: SUPERSEDED
│
├── Version 2
│   ├── File: quy_dinh_nghi_phep_2025.pdf
│   └── Status: SUPERSEDED
│
└── Version 3
    ├── File: quy_dinh_nghi_phep_2026.pdf
    └── Status: ACTIVE
```

Khi công ty ban hành bản 2027:

```text
Admin
  ↓
Chọn DOC-001
  ↓
Tạo phiên bản mới
  ↓
Upload quy_dinh_nghi_phep_2027.pdf
  ↓
Version 4
```

Lúc này:

```text
v3 = ACTIVE
v4 = DRAFT / PROCESSING
```

Employee vẫn phải sử dụng:

```text
v3
```

không phải v4.

---

Sau khi v4 được xử lý xong:

```text
v3 = ACTIVE

v4 = READY_FOR_REVIEW
```

Employee vẫn dùng:

```text
v3
```

Sau khi Admin phê duyệt và xuất bản:

```text
v3
ACTIVE
  ↓
SUPERSEDED

v4
READY_FOR_REVIEW
  ↓
ACTIVE
```

Kết quả cuối:

```text
Document DOC-001
        │
        ├── v1 SUPERSEDED
        ├── v2 SUPERSEDED
        ├── v3 SUPERSEDED
        └── v4 ACTIVE
```

Employee từ thời điểm này mới sử dụng v4.

---

Đây là nguyên tắc rất quan trọng:

```text
NEW VERSION
    ≠
ACTIVE VERSION
```

Việc tạo phiên bản mới chỉ có nghĩa là:

```text
Có một candidate version mới
```

Nó chưa phải:

```text
Nguồn tri thức chính thức
```

cho đến khi hoàn tất:

```text
Upload
   ↓
Processing
   ↓
READY_FOR_REVIEW
   ↓
Review
   ↓
Approve
   ↓
Publish
   ↓
ACTIVE
```

---

Một lỗi thiết kế nên tránh là:

```text
Admin upload v2
      ↓
System ngay lập tức:
v1 → SUPERSEDED
v2 → ACTIVE
```

Nếu sau đó:

```text
v2 OCR lỗi
```

hoặc:

```text
v2 upload nhầm
```

thì hệ thống đã vô tình loại bỏ phiên bản tốt đang hoạt động.

Thiết kế an toàn hơn:

```text
             v1 ACTIVE
                  │
Admin upload v2   │
        ↓         │
     v2 DRAFT     │
        ↓         │
    Processing    │
        ↓         │
READY_FOR_REVIEW  │
        ↓         │
      Review      │
        ↓         │
      Approve     │
        ↓         │
      Publish     │
        ↓         │
 ┌───────────────┴───────────────┐
 ↓                               ↓
v1 SUPERSEDED                  v2 ACTIVE
```

Việc đổi `ACTIVE` nên xảy ra **nguyên tử** trong cùng một nghiệp vụ publish:

```text
BEGIN TRANSACTION

1. Kiểm tra v2 đã đủ điều kiện publish
2. v1: ACTIVE → SUPERSEDED
3. v2: READY_FOR_REVIEW → ACTIVE
4. Document.current_version_id = v2
5. Ghi Audit Event

COMMIT
```

Nếu có lỗi:

```text
ROLLBACK
```

và:

```text
v1 vẫn ACTIVE
```

---

Các bước kỹ thuật như:

```text
Checksum
Duplicate Detection
Extraction
OCR
Chunking
Embedding
Indexing
```

không phải Use Case riêng.

Chúng nằm bên trong quá trình xử lý phiên bản:

```text
Tạo phiên bản mới
        ↓
DocumentVersion vN
        ↓
Processing Job
        ↓
Extract
        ↓
Chunk
        ↓
Embed
        ↓
Index
        ↓
READY_FOR_REVIEW
```

và nên được mô tả chi tiết trong **Sequence Diagram Tạo phiên bản tài liệu mới** hoặc **Ingestion Architecture**.

---

Điểm khác biệt với Use Case **Cập nhật metadata**:

```text
CẬP NHẬT METADATA

Document DOC-001
Version v3

Title:
"Quy định nghỉ phép"

        ↓ sửa

"Quy định về chế độ nghỉ phép"

File không đổi
Content không đổi

→ Không tạo v4
```

Trong khi:

```text
TẠO PHIÊN BẢN MỚI

Document DOC-001
Version v3

        ↓

Admin có file mới
nội dung quy định đã thay đổi

        ↓

Tạo Version v4
```

Có thể dùng quy tắc đơn giản:

```text
Metadata thay đổi
        ↓
Cập nhật thông tin tài liệu

Nội dung/file thay đổi
        ↓
Tạo phiên bản tài liệu mới
```

Đây là ranh giới rất quan trọng để tránh hệ thống sinh version không cần thiết hoặc ngược lại làm mất lịch sử nội dung.

### Use case xem lịch sử phiên bản

| Thuộc tính                  | Mô tả                                                                                                                                                                                               |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**            | Xem lịch sử phiên bản                                                                                                                                                                               |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                       |
| **Mục tiêu**                | Cho phép quản trị viên xem toàn bộ các phiên bản đã được tạo của một tài liệu, trạng thái của từng phiên bản và các thông tin liên quan để theo dõi quá trình thay đổi của tài liệu theo thời gian. |
| **Điều kiện kích hoạt**     | Quản trị viên đang xem chi tiết một tài liệu và chọn chức năng **Xem lịch sử phiên bản**.                                                                                                           |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản đang hoạt động.<br>3. Quản trị viên có quyền xem tài liệu tương ứng.<br>4. Tài liệu tồn tại trong hệ thống.<br>5. Tài liệu có ít nhất một phiên bản. |
| **Đầu vào**                 | Tài liệu cần xem lịch sử, được xác định thông qua `document_id`. Có thể kèm tiêu chí lọc hoặc sắp xếp nếu hệ thống hỗ trợ.                                                                          |
| **Trạng thái — Thành công** | Hệ thống hiển thị danh sách các phiên bản thuộc đúng tài liệu cùng thông tin như số phiên bản, trạng thái, file nguồn, người tạo, ngày tạo, ngày hiệu lực và quan hệ giữa các phiên bản.            |
| **Trạng thái — Thất bại**   | Hệ thống không hiển thị dữ liệu nếu tài liệu không tồn tại, quản trị viên không có quyền hoặc xảy ra lỗi khi lấy dữ liệu.                                                                           |
| **Use Cases liên quan**     | Xem chi tiết tài liệu, Tạo phiên bản tài liệu mới, Kiểm duyệt tài liệu, Phê duyệt và xuất bản tài liệu, Từ chối tài liệu                                                                            |

### Main Flow

| Bước | Actor         | Hành động                                                                        |
| ---: | ------------- | -------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Mở **Xem chi tiết tài liệu**.                                                    |
|    2 | Quản trị viên | Chọn chức năng **Xem lịch sử phiên bản**.                                        |
|    3 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                      |
|    4 | System        | Kiểm tra quyền xem tài liệu của quản trị viên.                                   |
|    5 | System        | Xác định `Document` cần xem lịch sử.                                             |
|    6 | System        | Lấy toàn bộ các `DocumentVersion` thuộc tài liệu đó.                             |
|    7 | System        | Xác định trạng thái hiện tại của từng phiên bản.                                 |
|    8 | System        | Xác định phiên bản nào đang `ACTIVE`.                                            |
|    9 | System        | Xác định quan hệ giữa các phiên bản, ví dụ phiên bản nào thay thế phiên bản nào. |
|   10 | System        | Sắp xếp danh sách phiên bản theo số phiên bản hoặc thời gian tạo.                |
|   11 | System        | Hiển thị lịch sử phiên bản cho quản trị viên.                                    |
|   12 | Quản trị viên | Xem thông tin từng phiên bản.                                                    |
|   13 | Quản trị viên | Có thể chọn một phiên bản cụ thể để xem thêm thông tin nếu hệ thống hỗ trợ.      |

### Thông tin hiển thị trong lịch sử phiên bản

| Thông tin                | Ý nghĩa                                                                                                            |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| **Số phiên bản**         | Xác định thứ tự của phiên bản trong vòng đời tài liệu, ví dụ v1, v2, v3.                                           |
| **Trạng thái phiên bản** | Cho biết phiên bản đang `DRAFT`, `READY_FOR_REVIEW`, `ACTIVE`, `REJECTED`, `SUPERSEDED` hoặc trạng thái tương ứng. |
| **Tên file nguồn**       | Xác định file đã được upload cho phiên bản đó.                                                                     |
| **Người tạo phiên bản**  | Quản trị viên đã upload hoặc tạo phiên bản.                                                                        |
| **Ngày tạo**             | Thời điểm phiên bản được tạo trong hệ thống.                                                                       |
| **Ngày ban hành**        | Thời điểm tài liệu được ban hành nếu có.                                                                           |
| **Ngày hiệu lực**        | Thời điểm phiên bản bắt đầu có hiệu lực nếu có.                                                                    |
| **Mô tả thay đổi**       | Nội dung tóm tắt những thay đổi của phiên bản so với phiên bản trước nếu có.                                       |
| **Người phê duyệt**      | Quản trị viên đã phê duyệt phiên bản nếu có.                                                                       |
| **Ngày xuất bản**        | Thời điểm phiên bản được đưa vào sử dụng chính thức.                                                               |
| **Phiên bản trước**      | Phiên bản mà phiên bản hiện tại kế nhiệm.                                                                          |
| **Trạng thái xử lý**     | Cho biết quá trình xử lý kỹ thuật của phiên bản đã thành công, đang xử lý hay thất bại.                            |

### Luồng thay thế/ luồng ngoại lệ

| Điều kiện                                            | Luồng xử lý                                                                                                |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền xem tài liệu            | Hệ thống từ chối truy cập và không hiển thị lịch sử phiên bản.                                             |
| Tài liệu không tồn tại                               | Hệ thống thông báo tài liệu không tồn tại hoặc không còn khả dụng.                                         |
| Tài liệu mới chỉ có một phiên bản                    | Hệ thống vẫn hiển thị phiên bản duy nhất và thông báo chưa có phiên bản trước đó.                          |
| Một phiên bản đang được xử lý                        | Hệ thống hiển thị phiên bản cùng trạng thái xử lý hiện tại như `PENDING` hoặc `RUNNING`.                   |
| Một phiên bản xử lý thất bại                         | Hệ thống hiển thị trạng thái `FAILED` của quá trình xử lý nhưng vẫn giữ phiên bản trong lịch sử.           |
| Một phiên bản bị từ chối                             | Hệ thống hiển thị phiên bản ở trạng thái `REJECTED` và lý do từ chối nếu có.                               |
| Một phiên bản đã bị thay thế                         | Hệ thống hiển thị trạng thái `SUPERSEDED` và phiên bản mới đã thay thế nó.                                 |
| Không xác định được quan hệ giữa một số phiên bản cũ | Hệ thống vẫn hiển thị các phiên bản hiện có và không tự suy diễn quan hệ nếu dữ liệu không đủ.             |
| Dịch vụ quản lý phiên bản không khả dụng             | Hệ thống trả thông báo lỗi có kiểm soát và không hiển thị dữ liệu lịch sử không đầy đủ như dữ liệu hợp lệ. |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                 |
| ----------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền xem tài liệu mới được xem lịch sử phiên bản của tài liệu đó.                                 |
| Tất cả các phiên bản trong lịch sử phải thuộc cùng một `Document`.                                                      |
| Mỗi phiên bản phải có `document_version_id` riêng.                                                                      |
| `version_number` phải duy nhất trong phạm vi một `Document`.                                                            |
| Hệ thống phải xác định rõ phiên bản nào đang `ACTIVE`.                                                                  |
| Tại một thời điểm, một tài liệu chỉ được có tối đa một phiên bản `ACTIVE`.                                              |
| Phiên bản `SUPERSEDED` phải được giữ lại trong lịch sử và không được coi là phiên bản hiện hành.                        |
| Phiên bản `REJECTED` phải được giữ lại phục vụ quản trị và audit nhưng không được sử dụng để trả lời Employee.          |
| Phiên bản xử lý `FAILED` vẫn phải được lưu trong lịch sử nếu `DocumentVersion` đã được tạo hợp lệ.                      |
| Lịch sử phiên bản không được thay đổi chỉ vì phiên bản cũ không còn được sử dụng trong truy vấn hiện tại.               |
| Việc tạo phiên bản mới không được xóa hoặc ghi đè lên phiên bản cũ.                                                     |
| Khi phiên bản mới trở thành `ACTIVE`, phiên bản `ACTIVE` trước đó phải chuyển sang `SUPERSEDED`.                        |
| Hệ thống phải giữ được thông tin người tạo, thời điểm tạo và các sự kiện quan trọng của mỗi phiên bản.                  |
| Các phiên bản cũ không được tự động sử dụng cho truy vấn hiện tại nếu đã có phiên bản `ACTIVE` mới hơn.                 |
| Việc xem lịch sử phiên bản không làm thay đổi trạng thái của bất kỳ phiên bản nào.                                      |
| Lịch sử phiên bản phải phản ánh đúng dữ liệu hiện tại của hệ thống và không được tạo thông tin lịch sử giả từ tên file. |
| Nếu hệ thống hỗ trợ quan hệ `supersedes`, quan hệ này phải liên kết đúng giữa các phiên bản.                            |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                                |
| ---------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể mở lịch sử phiên bản từ trang chi tiết tài liệu.                                               |
| Người không có quyền không thể xem lịch sử phiên bản.                                                                        |
| Hệ thống hiển thị đầy đủ các phiên bản thuộc tài liệu được chọn.                                                             |
| Phiên bản của tài liệu khác không được xuất hiện trong lịch sử.                                                              |
| Các phiên bản được sắp xếp đúng theo số phiên bản hoặc thời gian.                                                            |
| Hệ thống xác định đúng phiên bản đang `ACTIVE`.                                                                              |
| Phiên bản `SUPERSEDED` được hiển thị rõ là phiên bản cũ.                                                                     |
| Phiên bản `REJECTED` được hiển thị đúng trạng thái.                                                                          |
| Phiên bản xử lý `FAILED` vẫn có thể được xem trong lịch sử.                                                                  |
| Mỗi phiên bản hiển thị đúng file nguồn tương ứng.                                                                            |
| Người tạo và thời điểm tạo phiên bản được hiển thị chính xác nếu dữ liệu tồn tại.                                            |
| Ngày hiệu lực và ngày xuất bản được hiển thị đúng nếu có.                                                                    |
| Khi tài liệu chỉ có một phiên bản, hệ thống vẫn hiển thị bình thường.                                                        |
| Hệ thống không tạo hai phiên bản có cùng `version_number` trong cùng một tài liệu.                                           |
| Khi phiên bản mới được xuất bản, lịch sử phản ánh phiên bản cũ chuyển sang `SUPERSEDED` và phiên bản mới trở thành `ACTIVE`. |
| Việc xem lịch sử không làm thay đổi nội dung, trạng thái hoặc quyền của tài liệu.                                            |
| Khi quyền quản trị viên bị thu hồi, request tiếp theo không thể xem lịch sử phiên bản.                                       |

### Dữ liệu liên quan

| Dữ liệu                 | Mục đích                                                     |
| ----------------------- | ------------------------------------------------------------ |
| `document_id`           | Xác định tài liệu cần xem lịch sử phiên bản.                 |
| `document_version_id`   | Định danh riêng của từng phiên bản.                          |
| `version_number`        | Xác định số thứ tự phiên bản.                                |
| `previous_version_id`   | Liên kết phiên bản với phiên bản trước nếu hệ thống sử dụng. |
| `supersedes_version_id` | Xác định phiên bản bị thay thế nếu có.                       |
| `version_status`        | Xác định trạng thái của từng phiên bản.                      |
| `file_name`             | Tên file nguồn của phiên bản.                                |
| `file_hash`             | Hỗ trợ nhận biết nội dung file của từng phiên bản.           |
| `processing_status`     | Trạng thái xử lý kỹ thuật của phiên bản.                     |
| `change_summary`        | Mô tả nội dung thay đổi giữa các phiên bản nếu có.           |
| `issued_date`           | Ngày ban hành của phiên bản.                                 |
| `effective_date`        | Ngày bắt đầu có hiệu lực.                                    |
| `created_by`            | Quản trị viên tạo phiên bản.                                 |
| `created_at`            | Thời điểm phiên bản được tạo.                                |
| `approved_by`           | Người phê duyệt phiên bản nếu có.                            |
| `approved_at`           | Thời điểm phê duyệt.                                         |
| `published_at`          | Thời điểm phiên bản được xuất bản.                           |

### Ghi chú thiết kế

Ví dụ một tài liệu:

```text
Document DOC-001
"Quy định nghỉ phép"
```

có lịch sử:

```text
v1
│
├── Created: 01/01/2024
├── Status: SUPERSEDED
└── File: quy_dinh_nghi_phep_2024.pdf

v2
│
├── Created: 01/01/2025
├── Status: SUPERSEDED
└── File: quy_dinh_nghi_phep_2025.pdf

v3
│
├── Created: 01/01/2026
├── Status: ACTIVE
└── File: quy_dinh_nghi_phep_2026.pdf
```

Có thể hiển thị trên UI:

```text
LỊCH SỬ PHIÊN BẢN
────────────────────────────────────────────────────────
Version     Status        Effective Date      Created By
────────────────────────────────────────────────────────
v3          ACTIVE        01/01/2026          Admin A
v2          SUPERSEDED    01/01/2025          Admin B
v1          SUPERSEDED    01/01/2024          Admin A
────────────────────────────────────────────────────────
```

---

Use Case này phải hiển thị **DocumentVersion**, không phải tạo nhiều Document khác nhau.

Cấu trúc đúng:

```text
Document DOC-001
      │
      ├── DocumentVersion v1
      ├── DocumentVersion v2
      └── DocumentVersion v3
```

không phải:

```text
DOC-001 — Quy định nghỉ phép 2024
DOC-002 — Quy định nghỉ phép 2025
DOC-003 — Quy định nghỉ phép 2026
```

nếu ba file trên thực chất là các phiên bản kế tiếp của cùng một tài liệu nghiệp vụ.

---

### Quan hệ giữa các phiên bản

Nếu hệ thống lưu quan hệ version, có thể biểu diễn:

```text
v1
 ↓
v2
 ↓
v3
 ↓
v4
```

hoặc rõ hơn:

```text
v4
 └── supersedes → v3

v3
 └── supersedes → v2

v2
 └── supersedes → v1
```

Khi đó lịch sử có thể được dựng theo quan hệ:

```text
v1 → v2 → v3 → v4
```

---

### Liên hệ với duplicate/version detection sau này

Use Case này cũng rất hữu ích khi bạn bổ sung cơ chế phát hiện duplicate và version candidate.

Ví dụ Admin upload:

```text
quy_dinh_nghi_phep_2027.pdf
```

Hệ thống nhận ra:

```text
Same logical document:
DOC-001

Closest version:
v3

Detected changes:
- Effective date changed
- Annual leave: 12 → 14 days

Classification:
VERSION_CANDIDATE
```

Sau khi Admin xác nhận:

```text
DOC-001
│
├── v1 SUPERSEDED
├── v2 SUPERSEDED
├── v3 ACTIVE
└── v4 DRAFT
```

Lúc này **Xem lịch sử phiên bản** đã có thể hiển thị cả v4:

```text
v4 — DRAFT / PROCESSING
v3 — ACTIVE
v2 — SUPERSEDED
v1 — SUPERSEDED
```

Sau khi v4 được phê duyệt:

```text
v4 → ACTIVE
v3 → SUPERSEDED
```

Lịch sử tự động phản ánh:

```text
v4 ACTIVE
v3 SUPERSEDED
v2 SUPERSEDED
v1 SUPERSEDED
```

---

### Không nên coi lịch sử phiên bản chỉ là file history

Ngoài file, một phiên bản nên có khả năng truy vết:

```text
Ai tạo?
     +
Tạo khi nào?
     +
File nào?
     +
Thay đổi gì?
     +
Xử lý thành công không?
     +
Ai phê duyệt?
     +
Có từng ACTIVE không?
     +
Khi nào bị thay thế?
```

Vì vậy **Version History** là dữ liệu nghiệp vụ và audit, không đơn thuần là:

```text
v1.pdf
v2.pdf
v3.pdf
```

---

Use Case này về bản chất:

```text
Quản trị viên
      ↓
Xem chi tiết Document
      ↓
Xem lịch sử phiên bản
      ↓
System lấy các DocumentVersion
      ↓
Sắp xếp theo version
      ↓
Xác định trạng thái
      ↓
Hiển thị timeline
      ↓
Admin kiểm tra quá trình thay đổi
```

Và quan trọng:

```text
XEM LỊCH SỬ PHIÊN BẢN
          ≠
KHÔI PHỤC PHIÊN BẢN
```

Use Case hiện tại chỉ là **read-only**.

Nếu sau này bạn muốn Admin đưa một phiên bản cũ quay trở lại sử dụng, nên thiết kế thêm Use Case riêng:

```text
Khôi phục phiên bản
```

vì thao tác đó làm thay đổi trạng thái/version hiện hành và có ảnh hưởng trực tiếp đến Knowledge Base.

### Use case kiểm duyệt tài liệu

| Thuộc tính                      | Mô tả                                                                                                                                                                                                                                                                                        |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**                | Kiểm duyệt tài liệu                                                                                                                                                                                                                                                                          |
| **Actor chính**                 | Quản trị viên                                                                                                                                                                                                                                                                                |
| **Mục tiêu**                    | Cho phép quản trị viên kiểm tra tính đầy đủ, chính xác và phù hợp của một phiên bản tài liệu sau khi hệ thống hoàn tất xử lý, trước khi quyết định phê duyệt và xuất bản hoặc từ chối phiên bản đó.                                                                                          |
| **Điều kiện kích hoạt**         | Quản trị viên mở một phiên bản tài liệu có trạng thái `READY_FOR_REVIEW` và chọn chức năng **Kiểm duyệt tài liệu**.                                                                                                                                                                          |
| **Điều kiện tiên quyết**        | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản đang hoạt động.<br>3. Quản trị viên có quyền kiểm duyệt tài liệu tương ứng.<br>4. Tài liệu và phiên bản cần kiểm duyệt tồn tại.<br>5. Quá trình xử lý phiên bản đã hoàn tất thành công.<br>6. Phiên bản đang ở trạng thái `READY_FOR_REVIEW`. |
| **Đầu vào**                     | `document_id`, `document_version_id` và toàn bộ thông tin phục vụ kiểm duyệt như file nguồn, metadata, nội dung đã trích xuất, trạng thái xử lý, cảnh báo xử lý và các thông tin liên quan đến phiên bản.                                                                                    |
| **Trạng thái — Thành công**     | Quản trị viên hoàn tất việc kiểm tra và đưa ra kết quả kiểm duyệt. Phiên bản có thể tiếp tục sang **Phê duyệt và xuất bản** hoặc **Từ chối tài liệu**.                                                                                                                                       |
| **Trạng thái — Không hoàn tất** | Phiên bản vẫn giữ trạng thái `READY_FOR_REVIEW`; không được xuất bản và không được sử dụng làm nguồn tri thức chính thức.                                                                                                                                                                    |
| **Use Cases liên quan**         | Xem chi tiết tài liệu, Xem lịch sử phiên bản, Phê duyệt và xuất bản tài liệu, Từ chối tài liệu, Yêu cầu xử lý lại tài liệu, Cập nhật thông tin tài liệu                                                                                                                                      |

### Main Flow

| Bước | Actor         | Hành động                                                                                                               |
| ---: | ------------- | ----------------------------------------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Truy cập trang chi tiết của tài liệu cần kiểm duyệt.                                                                    |
|    2 | System        | Hiển thị phiên bản đang ở trạng thái `READY_FOR_REVIEW`.                                                                |
|    3 | Quản trị viên | Chọn chức năng **Kiểm duyệt tài liệu**.                                                                                 |
|    4 | System        | Kiểm tra phiên đăng nhập và quyền kiểm duyệt của quản trị viên.                                                         |
|    5 | System        | Kiểm tra phiên bản vẫn tồn tại và đang ở trạng thái phù hợp để kiểm duyệt.                                              |
|    6 | System        | Hiển thị thông tin nghiệp vụ của tài liệu và phiên bản.                                                                 |
|    7 | System        | Hiển thị file nguồn hoặc cho phép quản trị viên mở file nguồn.                                                          |
|    8 | System        | Hiển thị nội dung đã được hệ thống trích xuất từ file.                                                                  |
|    9 | System        | Hiển thị các metadata của tài liệu và phiên bản.                                                                        |
|   10 | System        | Hiển thị trạng thái xử lý và các cảnh báo hoặc lỗi chất lượng nếu có.                                                   |
|   11 | Quản trị viên | Đối chiếu nội dung đã xử lý với file nguồn.                                                                             |
|   12 | Quản trị viên | Kiểm tra metadata và thông tin nghiệp vụ của tài liệu.                                                                  |
|   13 | Quản trị viên | Kiểm tra các cảnh báo hoặc vấn đề phát hiện trong quá trình xử lý.                                                      |
|   14 | Quản trị viên | Xác định phiên bản có đáp ứng yêu cầu để sử dụng trong Knowledge Base hay không.                                        |
|   15 | Quản trị viên | Chọn hành động tiếp theo: **Phê duyệt và xuất bản**, **Từ chối** hoặc yêu cầu **Xử lý lại** nếu phát hiện lỗi kỹ thuật. |
|   16 | System        | Kiểm tra quyền và trạng thái trước khi cho phép thực hiện hành động được chọn.                                          |
|   17 | System        | Ghi nhận kết quả và thông tin kiểm duyệt theo chính sách audit.                                                         |

### Nội dung cần kiểm duyệt

| Nhóm kiểm tra           | Nội dung                                                                                                      |
| ----------------------- | ------------------------------------------------------------------------------------------------------------- |
| **File nguồn**          | File có đúng tài liệu cần quản lý hay không; có bị upload nhầm, lỗi hoặc thiếu trang hay không.               |
| **Thông tin tài liệu**  | Tên tài liệu, loại tài liệu, phòng ban, mã tài liệu, ngày ban hành, ngày hiệu lực và metadata nghiệp vụ khác. |
| **Nội dung trích xuất** | Nội dung sau extraction/OCR có phản ánh đúng file nguồn hay không.                                            |
| **Cấu trúc tài liệu**   | Heading, đoạn văn, bảng và các thành phần quan trọng có được giữ đúng ở mức cần thiết hay không.              |
| **Bảng và số liệu**     | Các bảng, số, ngày tháng, đơn vị và giá trị nghiệp vụ quan trọng có bị sai lệch hay không.                    |
| **Phiên bản**           | File có thực sự thuộc phiên bản đang kiểm duyệt và đúng `Document` hay không.                                 |
| **Trạng thái xử lý**    | Quá trình xử lý có hoàn tất thành công hay không.                                                             |
| **Cảnh báo hệ thống**   | Các cảnh báo về OCR, parsing, duplicate, version hoặc vấn đề chất lượng nếu có.                               |
| **Khả năng sử dụng**    | Nội dung có đủ chất lượng để trở thành nguồn tri thức phục vụ truy vấn hay không.                             |
| **Phạm vi truy cập**    | Các chính sách truy cập cần thiết đã được cấu hình phù hợp trước khi xuất bản hay chưa.                       |

### Luồng thay thế/ luồng ngoại lệ

| Điều kiện                                                            | Luồng xử lý                                                                                                                |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền kiểm duyệt                              | Hệ thống từ chối thao tác và không cho phép thay đổi kết quả kiểm duyệt.                                                   |
| Tài liệu hoặc phiên bản không tồn tại                                | Hệ thống thông báo tài liệu/phiên bản không còn khả dụng.                                                                  |
| Phiên bản chưa hoàn tất xử lý                                        | Hệ thống không cho phép kiểm duyệt và yêu cầu chờ quá trình xử lý hoàn tất.                                                |
| Quá trình xử lý đang `RUNNING`                                       | Hệ thống không cho phép phiên bản chuyển sang kiểm duyệt.                                                                  |
| Quá trình xử lý `FAILED`                                             | Hệ thống không cho phép phê duyệt; quản trị viên có thể thực hiện **Yêu cầu xử lý lại tài liệu**.                          |
| Nội dung extraction/OCR có lỗi                                       | Quản trị viên không phê duyệt phiên bản và có thể yêu cầu xử lý lại.                                                       |
| Metadata không chính xác nhưng nội dung file đúng                    | Quản trị viên có thể chuyển sang **Cập nhật thông tin tài liệu** trước khi tiếp tục kiểm duyệt.                            |
| File nguồn bị upload nhầm                                            | Quản trị viên từ chối phiên bản hoặc tạo phiên bản mới đúng theo chính sách hệ thống.                                      |
| Phiên bản mới trùng hoàn toàn với phiên bản đã tồn tại               | Hệ thống hiển thị cảnh báo duplicate; quản trị viên không nên phê duyệt một phiên bản trùng không cần thiết.               |
| Hệ thống phát hiện phiên bản có khả năng là duplicate/near-duplicate | Hệ thống hiển thị thông tin đối chiếu để quản trị viên xem xét trước khi quyết định.                                       |
| Hệ thống phát hiện thay đổi quan trọng so với phiên bản hiện tại     | Hệ thống hiển thị thông tin thay đổi để hỗ trợ quản trị viên xác minh đây có phải phiên bản cập nhật hợp lệ hay không.     |
| Hệ thống phát hiện conflict với tài liệu khác                        | Hệ thống cảnh báo quản trị viên để kiểm tra; không tự động phê duyệt hoặc loại bỏ tài liệu chỉ dựa trên cảnh báo conflict. |
| Quyền truy cập tài liệu chưa được cấu hình                           | Hệ thống có thể không cho phép xuất bản cho tới khi chính sách truy cập cần thiết được thiết lập.                          |
| Quản trị viên thoát trước khi đưa ra quyết định                      | Phiên bản giữ nguyên `READY_FOR_REVIEW`.                                                                                   |
| Phiên bản đã được một quản trị viên khác xử lý                       | Hệ thống tải lại trạng thái mới và không cho phép ghi đè quyết định đã hoàn tất.                                           |
| Dịch vụ kiểm duyệt gặp lỗi                                           | Hệ thống không thay đổi trạng thái phiên bản và trả lỗi có kiểm soát.                                                      |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền kiểm duyệt mới được thực hiện Use Case này.                                                                                                    |
| Chỉ phiên bản có trạng thái `READY_FOR_REVIEW` mới được đưa vào kiểm duyệt.                                                                                               |
| Phiên bản có quá trình xử lý `FAILED` không được phê duyệt hoặc xuất bản.                                                                                                 |
| Kiểm duyệt phải được thực hiện trên một `DocumentVersion` cụ thể, không chỉ trên `Document` logic chung.                                                                  |
| File nguồn hiển thị trong quá trình kiểm duyệt phải thuộc đúng `DocumentVersion`.                                                                                         |
| Nội dung đã trích xuất phải có khả năng đối chiếu với file nguồn.                                                                                                         |
| Quản trị viên phải có khả năng nhận biết phiên bản nào đang `ACTIVE` để so sánh khi cần.                                                                                  |
| Phiên bản đang được kiểm duyệt chưa được sử dụng mặc định để trả lời Employee.                                                                                            |
| Việc mở màn hình kiểm duyệt không làm thay đổi trạng thái phiên bản.                                                                                                      |
| Chỉ hành động phê duyệt/xuất bản hoặc từ chối mới làm thay đổi lifecycle của phiên bản theo workflow tương ứng.                                                           |
| Cảnh báo duplicate, near-duplicate hoặc conflict chỉ hỗ trợ quyết định; hệ thống không được tự động phê duyệt hoặc từ chối tài liệu chỉ dựa vào similarity.               |
| Nếu phát hiện file mới thực chất trùng hoàn toàn với phiên bản hiện có, không nên tạo thêm một phiên bản `ACTIVE` không cần thiết.                                        |
| Nếu phát hiện thay đổi nội dung thuộc cùng `Document`, phiên bản phải tiếp tục được quản lý trong lịch sử version của tài liệu đó.                                        |
| Nếu phát hiện conflict giữa các tài liệu khác nhau, hệ thống phải giữ quan hệ conflict phục vụ review thay vì tự coi một tài liệu là phiên bản của tài liệu còn lại.      |
| Thay đổi metadata trong quá trình review phải tuân theo Use Case cập nhật thông tin tài liệu.                                                                             |
| Thay đổi nội dung file phải được thực hiện thông qua việc tạo phiên bản mới hoặc quy trình xử lý phù hợp; không chỉnh sửa trực tiếp file nguồn của phiên bản đang review. |
| Quyền truy cập phải được xác minh trước khi phiên bản được xuất bản.                                                                                                      |
| Kết quả kiểm duyệt phải ghi nhận người thực hiện và thời điểm thực hiện.                                                                                                  |
| Các nhận xét hoặc lý do từ chối quan trọng phải được lưu để phục vụ audit.                                                                                                |
| Không được làm mất phiên bản `ACTIVE` hiện tại chỉ vì một candidate version mới đang được review.                                                                         |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                          |
| ---------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể mở phiên bản `READY_FOR_REVIEW` để kiểm duyệt.                                           |
| Người không có quyền không thể thực hiện kiểm duyệt.                                                                   |
| Phiên bản `DRAFT`, `RUNNING` hoặc `FAILED` không thể được phê duyệt trực tiếp.                                         |
| Hệ thống hiển thị đúng file nguồn của phiên bản đang review.                                                           |
| Hệ thống hiển thị đúng metadata của tài liệu và phiên bản.                                                             |
| Hệ thống hiển thị nội dung đã được xử lý để quản trị viên kiểm tra.                                                    |
| Hệ thống hiển thị đúng trạng thái processing của phiên bản.                                                            |
| Các cảnh báo xử lý có thể được quản trị viên nhận biết.                                                                |
| Phiên bản đang `READY_FOR_REVIEW` chưa được Employee sử dụng mặc định trong truy vấn.                                  |
| Khi Admin chỉ xem hoặc kiểm tra tài liệu nhưng chưa ra quyết định, trạng thái vẫn là `READY_FOR_REVIEW`.               |
| Khi phát hiện lỗi xử lý, quản trị viên có thể chuyển sang **Yêu cầu xử lý lại tài liệu**.                              |
| Khi metadata sai, quản trị viên có thể thực hiện **Cập nhật thông tin tài liệu** theo quyền được cấp.                  |
| Khi tài liệu đạt yêu cầu, quản trị viên có thể thực hiện **Phê duyệt và xuất bản tài liệu**.                           |
| Khi tài liệu không đạt yêu cầu, quản trị viên có thể thực hiện **Từ chối tài liệu**.                                   |
| Kết quả kiểm duyệt phải gắn đúng với `document_version_id`.                                                            |
| Hệ thống ghi nhận được quản trị viên thực hiện kiểm duyệt và thời điểm thực hiện.                                      |
| Cảnh báo duplicate/conflict không tự động làm thay đổi trạng thái phiên bản nếu chưa có quyết định phù hợp.            |
| Khi phiên bản mới bị từ chối, phiên bản `ACTIVE` hiện tại vẫn tiếp tục hoạt động.                                      |
| Khi có thay đổi trạng thái đồng thời từ quản trị viên khác, hệ thống không ghi đè quyết định cũ bằng dữ liệu lỗi thời. |

### Dữ liệu liên quan

| Dữ liệu               | Mục đích                                                     |
| --------------------- | ------------------------------------------------------------ |
| `document_id`         | Xác định tài liệu logic chứa phiên bản đang được kiểm duyệt. |
| `document_version_id` | Xác định chính xác phiên bản được kiểm duyệt.                |
| `version_number`      | Số phiên bản đang kiểm duyệt.                                |
| `version_status`      | Xác định phiên bản có đang `READY_FOR_REVIEW` hay không.     |
| `processing_status`   | Xác định quá trình xử lý đã hoàn tất thành công hay chưa.    |
| `file_name`           | Tên file nguồn của phiên bản.                                |
| `file_hash`           | Phục vụ kiểm tra tính toàn vẹn và duplicate.                 |
| `storage_location`    | Tham chiếu tới file nguồn.                                   |
| `title`               | Tên nghiệp vụ của tài liệu.                                  |
| `document_type`       | Loại tài liệu.                                               |
| `department`          | Đơn vị phụ trách tài liệu.                                   |
| `issued_date`         | Ngày ban hành nếu có.                                        |
| `effective_date`      | Ngày hiệu lực nếu có.                                        |
| `extracted_content`   | Nội dung hệ thống đã trích xuất phục vụ đối chiếu.           |
| `processing_warnings` | Các cảnh báo phát sinh trong quá trình xử lý.                |
| `processing_error`    | Lỗi xử lý nếu có.                                            |
| `duplicate_status`    | Kết quả/cảnh báo duplicate nếu cơ chế này được triển khai.   |
| `conflict_status`     | Kết quả/cảnh báo conflict nếu cơ chế này được triển khai.    |
| `reviewed_by`         | Quản trị viên thực hiện kiểm duyệt.                          |
| `reviewed_at`         | Thời điểm kiểm duyệt.                                        |
| `review_note`         | Ghi chú của quản trị viên khi kiểm duyệt nếu có.             |
| `rejection_reason`    | Lý do từ chối nếu phiên bản bị từ chối.                      |

### Ghi chú thiết kế

Use Case này nằm ở vị trí:

```text
Upload tài liệu
      ↓
hoặc
Tạo phiên bản mới
      ↓
Processing
      ↓
PENDING
      ↓
RUNNING
      ↓
SUCCEEDED
      ↓
READY_FOR_REVIEW
      ↓
KIỂM DUYỆT TÀI LIỆU
```

Từ đây có ba hướng chính:

```text
                   Kiểm duyệt
                       │
          ┌────────────┼─────────────┐
          │            │             │
          ↓            ↓             ↓
       Đạt yêu cầu   Lỗi nghiệp vụ   Lỗi xử lý
          │            │             │
          ↓            ↓             ↓
      Phê duyệt      Từ chối      Xử lý lại
      & xuất bản
```

---

### Kiểm duyệt không phải là xử lý kỹ thuật

Các bước:

```text
OCR
Extraction
Chunking
Embedding
Indexing
```

đã xảy ra trước đó.

Kiểm duyệt là việc Admin xác nhận:

```text
File đúng chưa?
        +
Nội dung extract đúng chưa?
        +
Metadata đúng chưa?
        +
Số liệu/bảng quan trọng đúng chưa?
        +
Đúng Document và Version chưa?
        +
Có cảnh báo nghiêm trọng không?
        +
Có đủ điều kiện trở thành knowledge chính thức không?
```

---

### Ví dụ

Hệ thống đang có:

```text
Document DOC-001
"Quy định nghỉ phép"

v3 — ACTIVE
```

Admin tạo:

```text
v4
```

Sau xử lý:

```text
DOC-001

v3
Status: ACTIVE

v4
Status: READY_FOR_REVIEW
Processing: SUCCEEDED
```

Lúc này Employee vẫn dùng:

```text
v3
```

Admin mở v4 và kiểm duyệt.

Nếu đạt yêu cầu:

```text
v4
READY_FOR_REVIEW
       ↓
Phê duyệt & xuất bản
       ↓
ACTIVE
```

đồng thời:

```text
v3
ACTIVE
  ↓
SUPERSEDED
```

Nếu không đạt:

```text
v4
READY_FOR_REVIEW
       ↓
REJECTED
```

và:

```text
v3 vẫn ACTIVE
```

---

### Trường hợp lỗi kỹ thuật

Ví dụ file gốc ghi:

```text
Mức phụ cấp: 15.000.000 VNĐ
```

nhưng extraction lại thành:

```text
Mức phụ cấp: 150.000.000 VNĐ
```

Đây không nên được xử lý bằng:

```text
Admin sửa text extract
→ Publish
```

Mà nên:

```text
Phát hiện extraction sai
        ↓
Không phê duyệt
        ↓
Yêu cầu xử lý lại
        ↓
Processing Job mới
        ↓
READY_FOR_REVIEW
        ↓
Kiểm duyệt lại
```

để đảm bảo dữ liệu trong pipeline vẫn có thể tái lập và audit.

---

### Trường hợp duplicate/version candidate

Sau này khi triển khai duplicate detection, giao diện review có thể hiển thị:

```text
Potential Version Match

Document:
Quy định nghỉ phép

Current:
v3

Candidate:
v4

Similarity:
96%

Detected changes:
- Annual leave: 12 → 14 days
- Effective date: 2025 → 2026
```

Admin kiểm tra và xác nhận:

```text
Đúng là phiên bản mới
```

rồi mới tiếp tục publish.

Nếu:

```text
Similarity: 100%
No material changes
```

Admin có thể từ chối candidate vì đây là duplicate không cần thiết.

---

### Trường hợp conflict

Ví dụ tài liệu đang review ghi:

```text
Phụ cấp = 1.500.000
```

trong khi một tài liệu `ACTIVE` khác ghi:

```text
Phụ cấp = 1.200.000
```

Hệ thống có thể đưa cảnh báo:

```text
Potential Conflict
```

nhưng không được tự kết luận:

```text
Candidate sai
```

vì có thể:

* hai tài liệu áp dụng cho hai phòng ban khác nhau;
* hai giai đoạn hiệu lực khác nhau;
* một tài liệu có thẩm quyền cao hơn;
* hoặc thực sự đang có conflict cần giải quyết.

Vì vậy:

```text
Conflict Detection
      ↓
Warning
      ↓
Admin Review
      ↓
Decision
```

phù hợp hơn:

```text
Conflict Detection
      ↓
Auto Reject
```

---

### Ranh giới với Phê duyệt và xuất bản

Hai Use Case cần phân biệt:

```text
KIỂM DUYỆT

"Phiên bản này có đạt yêu cầu không?"
```

và:

```text
PHÊ DUYỆT & XUẤT BẢN

"Cho phép phiên bản này trở thành
nguồn tri thức chính thức."
```

Trong MVP, cùng một Admin có thể thực hiện cả hai, nhưng về mặt nghiệp vụ vẫn nên tách logic để sau này có thể mở rộng:

```text
Reviewer
   ↓
Review

Knowledge Admin
   ↓
Publish
```

mà không phải thiết kế lại toàn bộ workflow.

---

Nguyên tắc cuối cùng của Use Case này:

```text
PROCESSING SUCCESS
        ≠
READY TO PUBLISH
```

Phải là:

```text
Processing thành công
        ↓
READY_FOR_REVIEW
        ↓
Admin kiểm duyệt
        ↓
Đạt yêu cầu
        ↓
Phê duyệt & xuất bản
        ↓
ACTIVE
```

Như vậy tài liệu chưa được con người kiểm tra sẽ không tự động trở thành nguồn tri thức chính thức của hệ thống.

### Use case Archive tài liệu

| Thuộc tính                  | Mô tả                                                                                                                                                                                                                    |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Tên Use Case**            | Lưu trữ tài liệu                                                                                                                                                                                                         |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                                            |
| **Mục tiêu**                | Cho phép quản trị viên ngừng sử dụng một tài liệu trong Knowledge Base hiện hành nhưng vẫn bảo toàn tài liệu, các phiên bản và lịch sử quản trị để phục vụ tra cứu, audit hoặc khôi phục trong tương lai.                |
| **Điều kiện kích hoạt**     | Quản trị viên đang xem chi tiết một tài liệu và chọn chức năng **Archive tài liệu**.                                                                                                                                     |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản đang hoạt động.<br>3. Quản trị viên có quyền quản lý hoặc lưu trữ tài liệu tương ứng.<br>4. Tài liệu tồn tại trong hệ thống.<br>5. Tài liệu chưa ở trạng thái `ARCHIVED`. |
| **Đầu vào**                 | `document_id` của tài liệu cần lưu trữ; có thể kèm lý do lưu trữ hoặc ghi chú nếu chính sách hệ thống yêu cầu.                                                                                                           |
| **Trạng thái — Thành công** | Tài liệu được chuyển sang trạng thái `ARCHIVED`; tài liệu không còn được sử dụng mặc định trong truy vấn hiện tại của Employee; file nguồn, phiên bản, metadata và lịch sử audit vẫn được giữ lại.                       |
| **Trạng thái — Thất bại**   | Trạng thái tài liệu không thay đổi; tài liệu vẫn hoạt động theo trạng thái trước đó và hệ thống thông báo nguyên nhân lỗi.                                                                                               |
| **Use Cases liên quan**     | Xem chi tiết tài liệu, Xem danh sách tài liệu, Xem lịch sử phiên bản, Phê duyệt và xuất bản tài liệu                                                                                                                     |

### Main Flow

| Bước | Actor         | Hành động                                                                            |
| ---: | ------------- | ------------------------------------------------------------------------------------ |
|    1 | Quản trị viên | Mở chức năng **Xem chi tiết tài liệu**.                                              |
|    2 | Quản trị viên | Chọn chức năng **Archive tài liệu**.                                                 |
|    3 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                          |
|    4 | System        | Kiểm tra quyền lưu trữ tài liệu của quản trị viên.                                   |
|    5 | System        | Kiểm tra tài liệu tồn tại và chưa ở trạng thái `ARCHIVED`.                           |
|    6 | System        | Xác định trạng thái hiện tại và phiên bản `ACTIVE` của tài liệu nếu có.              |
|    7 | System        | Hiển thị cảnh báo về ảnh hưởng của việc lưu trữ tài liệu.                            |
|    8 | System        | Yêu cầu quản trị viên xác nhận thao tác.                                             |
|    9 | Quản trị viên | Xác nhận lưu trữ tài liệu.                                                           |
|   10 | System        | Chuyển trạng thái `Document` sang `ARCHIVED`.                                        |
|   11 | System        | Loại tài liệu khỏi phạm vi Knowledge Base được sử dụng cho các truy vấn hiện hành.   |
|   12 | System        | Giữ nguyên file nguồn, metadata, các `DocumentVersion` và thông tin lịch sử.         |
|   13 | System        | Ghi nhận người thực hiện, thời điểm và lý do lưu trữ nếu có.                         |
|   14 | System        | Ghi Audit Event cho thao tác Archive.                                                |
|   15 | System        | Thông báo lưu trữ thành công cho quản trị viên.                                      |
|   16 | System        | Cập nhật giao diện chi tiết và danh sách tài liệu để phản ánh trạng thái `ARCHIVED`. |

### Luồng thay thế/ luồng ngoại lệ

| Điều kiện                                                   | Luồng xử lý                                                                                                                                               |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền Archive                        | Hệ thống từ chối thao tác và không thay đổi trạng thái tài liệu.                                                                                          |
| Tài liệu không tồn tại                                      | Hệ thống thông báo tài liệu không tồn tại hoặc không còn khả dụng.                                                                                        |
| Tài liệu đã ở trạng thái `ARCHIVED`                         | Hệ thống không thực hiện lại thao tác và thông báo tài liệu đã được lưu trữ.                                                                              |
| Quản trị viên hủy xác nhận                                  | Hệ thống không thay đổi trạng thái tài liệu.                                                                                                              |
| Tài liệu đang có phiên bản mới `PROCESSING`                 | Hệ thống cảnh báo rằng tài liệu đang có quá trình xử lý chưa hoàn tất; tùy chính sách có thể yêu cầu quản trị viên xử lý hoặc hủy job trước khi Archive.  |
| Tài liệu đang có phiên bản `READY_FOR_REVIEW`               | Hệ thống cảnh báo đang có phiên bản chờ kiểm duyệt; tùy chính sách có thể yêu cầu xử lý phiên bản này trước khi lưu trữ toàn bộ tài liệu.                 |
| Tài liệu đang được sử dụng bởi một workflow khác            | Hệ thống kiểm tra trạng thái hiện tại và có thể từ chối Archive nếu thao tác gây trạng thái không nhất quán.                                              |
| Cập nhật trạng thái tài liệu thất bại                       | Hệ thống rollback thay đổi; tài liệu giữ trạng thái trước Archive.                                                                                        |
| Không thể đồng bộ trạng thái xuống hệ thống retrieval/index | Hệ thống không được coi Archive là hoàn tất nếu tài liệu vẫn có nguy cơ được Employee truy xuất; thao tác phải được rollback hoặc đánh dấu lỗi cần xử lý. |
| Hai quản trị viên đồng thời thay đổi trạng thái tài liệu    | Hệ thống áp dụng kiểm soát concurrency và không ghi đè một trạng thái mới hơn bằng dữ liệu cũ.                                                            |
| Dịch vụ hệ thống không khả dụng                             | Hệ thống trả lỗi có kiểm soát và không thay đổi trạng thái tài liệu.                                                                                      |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                                                                                                 |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền phù hợp mới được Archive tài liệu.                                                                                                                                                           |
| Archive là thay đổi trạng thái của `Document`, không phải xóa vật lý tài liệu.                                                                                                                                          |
| Tài liệu ở trạng thái `ARCHIVED` không được sử dụng mặc định để trả lời các truy vấn hiện hành của Employee.                                                                                                            |
| Các `DocumentVersion` thuộc tài liệu phải được giữ lại sau khi Archive.                                                                                                                                                 |
| File nguồn của các phiên bản phải được giữ lại theo chính sách lưu trữ dữ liệu.                                                                                                                                         |
| Metadata và lịch sử thay đổi của tài liệu phải được giữ lại để phục vụ audit.                                                                                                                                           |
| Archive tài liệu không được hard-delete embeddings, chunks hoặc dữ liệu liên quan nếu việc xóa làm mất khả năng audit hoặc khôi phục; hệ thống có thể loại chúng khỏi retrieval thông qua trạng thái hoặc index policy. |
| Tài liệu Archive phải được loại khỏi phạm vi retrieval trước khi được coi là thao tác Archive hoàn tất.                                                                                                                 |
| Employee không được nhận tài liệu `ARCHIVED` làm evidence cho các câu hỏi hiện tại, trừ khi sau này hệ thống có Use Case tra cứu lịch sử được cho phép rõ ràng.                                                         |
| Việc Archive không làm thay đổi nội dung các phiên bản đã tồn tại.                                                                                                                                                      |
| Phiên bản `ACTIVE` trước thời điểm Archive vẫn được giữ trong lịch sử nhưng không còn được coi là nguồn tri thức hiện hành khi `Document = ARCHIVED`.                                                                   |
| Archive không đồng nghĩa `DocumentVersion = REJECTED`.                                                                                                                                                                  |
| Archive không đồng nghĩa xóa tài liệu.                                                                                                                                                                                  |
| Hệ thống phải ghi nhận người thực hiện và thời điểm Archive.                                                                                                                                                            |
| Nếu chính sách yêu cầu lý do lưu trữ, lý do phải được cung cấp trước khi xác nhận.                                                                                                                                      |
| Các thao tác Archive phải có khả năng truy vết trong Audit Log.                                                                                                                                                         |
| Nếu tài liệu đang có workflow chưa hoàn tất, hệ thống phải kiểm tra và xử lý xung đột trạng thái trước khi Archive.                                                                                                     |
| Một tài liệu `ARCHIVED` chỉ có thể quay lại Knowledge Base thông qua một nghiệp vụ khôi phục hoặc tái kích hoạt được định nghĩa riêng.                                                                                  |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể Archive tài liệu từ trang chi tiết tài liệu.                                                |
| Người không có quyền không thể Archive tài liệu.                                                                          |
| Hệ thống yêu cầu xác nhận trước khi thực hiện Archive.                                                                    |
| Nếu quản trị viên hủy xác nhận, trạng thái tài liệu không thay đổi.                                                       |
| Sau khi Archive thành công, `document_status = ARCHIVED`.                                                                 |
| Tài liệu `ARCHIVED` không còn xuất hiện trong danh sách tài liệu hoạt động mặc định.                                      |
| Quản trị viên có thể xem tài liệu Archive khi sử dụng bộ lọc phù hợp và có quyền.                                         |
| Tài liệu `ARCHIVED` không được sử dụng trong retrieval cho câu hỏi hiện hành của Employee.                                |
| Chunk hoặc dữ liệu từ tài liệu `ARCHIVED` không được truyền tới bước reranking hoặc generation cho truy vấn thông thường. |
| Các phiên bản của tài liệu vẫn tồn tại sau khi Archive.                                                                   |
| File nguồn của từng phiên bản vẫn được giữ theo chính sách hệ thống.                                                      |
| Lịch sử phiên bản vẫn có thể được quản trị viên xem sau khi Archive.                                                      |
| Metadata của tài liệu không bị mất khi Archive.                                                                           |
| Hệ thống ghi nhận đúng quản trị viên thực hiện Archive.                                                                   |
| Hệ thống ghi nhận đúng thời điểm Archive.                                                                                 |
| Lý do Archive được lưu nếu chính sách yêu cầu.                                                                            |
| Audit Log có sự kiện Archive tương ứng.                                                                                   |
| Nếu cập nhật trạng thái thất bại, tài liệu vẫn ở trạng thái trước đó.                                                     |
| Không tồn tại tình trạng `Document = ARCHIVED` nhưng Employee vẫn retrieve được tài liệu sau khi thao tác hoàn tất.       |
| Archive không làm biến mất hoặc hard-delete lịch sử tài liệu.                                                             |

### Dữ liệu liên quan

| Dữ liệu               | Mục đích                                                                  |
| --------------------- | ------------------------------------------------------------------------- |
| `document_id`         | Xác định tài liệu cần Archive.                                            |
| `document_status`     | Trạng thái nghiệp vụ của tài liệu; được chuyển thành `ARCHIVED`.          |
| `current_version_id`  | Xác định phiên bản hiện tại trước khi tài liệu được Archive.              |
| `document_version_id` | Định danh các phiên bản thuộc tài liệu.                                   |
| `version_status`      | Giữ trạng thái lịch sử của các phiên bản.                                 |
| `archived_by`         | Xác định quản trị viên thực hiện Archive.                                 |
| `archived_at`         | Thời điểm tài liệu được Archive.                                          |
| `archive_reason`      | Lý do lưu trữ nếu hệ thống yêu cầu.                                       |
| `updated_at`          | Thời điểm cập nhật trạng thái tài liệu.                                   |
| `access_policy`       | Chính sách truy cập được giữ lại để phục vụ audit hoặc khôi phục sau này. |
| `audit_event`         | Ghi nhận sự kiện Archive.                                                 |

### Ghi chú thiết kế

Cần phân biệt rất rõ:

```text
ARCHIVE
   ≠
DELETE
```

Ví dụ trước khi Archive:

```text
Document DOC-001
"Quy định nghỉ phép"

Status:
PUBLISHED

Versions:
├── v1 SUPERSEDED
├── v2 SUPERSEDED
└── v3 ACTIVE
```

Sau khi Admin Archive:

```text
Document DOC-001
"Quy định nghỉ phép"

Status:
ARCHIVED

Versions:
├── v1 SUPERSEDED
├── v2 SUPERSEDED
└── v3 ACTIVE (historical state)
```

Tuy nhiên vì:

```text
Document.status = ARCHIVED
```

nên v3 **không còn được retrieval sử dụng cho câu hỏi hiện hành**.

Có thể hiểu điều kiện retrieval:

```text
Document.status = PUBLISHED
AND
DocumentVersion.status = ACTIVE
AND
Employee có quyền READ
```

Khi Document chuyển:

```text
PUBLISHED
    ↓
ARCHIVED
```

thì điều kiện đầu tiên không còn thỏa mãn:

```text
Document.status != PUBLISHED
```

và tài liệu tự động bị loại khỏi Knowledge Base hiện hành.

---

### Vì sao không đổi Version `ACTIVE → SUPERSEDED` khi Archive?

Hai khái niệm khác nhau.

`SUPERSEDED` nghĩa là:

> Phiên bản này đã được **một phiên bản mới hơn của cùng tài liệu thay thế**.

Ví dụ:

```text
v3 ACTIVE
   ↓
Publish v4
   ↓
v3 SUPERSEDED
v4 ACTIVE
```

Trong khi Archive nghĩa là:

> **Toàn bộ tài liệu không còn được sử dụng hiện hành**.

Không nhất thiết có một version mới thay thế.

Ví dụ:

```text
DOC-001
v3 ACTIVE
    ↓
Archive Document
    ↓
DOC-001 = ARCHIVED
```

Không có v4, vì vậy nếu đổi v3 thành `SUPERSEDED` sẽ sai nghĩa nghiệp vụ.

---

### Retrieval sau Archive

Trước:

```text
Employee question
       ↓
ACL Filter
       ↓
Document = PUBLISHED
       ↓
Version = ACTIVE
       ↓
DOC-001 v3
       ↓
Retrieval
```

Sau Archive:

```text
Employee question
       ↓
ACL Filter
       ↓
Document = PUBLISHED ?
       ↓
       NO
       ↓
DOC-001 bị loại
```

Do đó tài liệu không được đi tiếp tới:

```text
Dense Search
BM25
RRF
Reranker
Evidence Gate
LLM
```

Đặc biệt không nên thiết kế:

```text
Retrieve cả ARCHIVED
       ↓
đến cuối mới filter
```

vì dữ liệu đã ngừng hiệu lực không nên trở thành candidate evidence ngay từ đầu.

---

### Archive và Delete

Tôi khuyên MVP áp dụng:

```text
DRAFT / upload nhầm
       ↓
có thể cho phép xóa theo policy

PUBLISHED
       ↓
không hard-delete thông thường
       ↓
ARCHIVE
```

Ví dụ:

```text
PUBLISHED
    ↓
ARCHIVED
    ↓
Giữ:
- Document
- Versions
- Source files
- Metadata
- Audit
- History
```

Điều này phù hợp hơn với hệ thống tri thức doanh nghiệp vì sau này bạn còn cần trả lời:

```text
Tài liệu nào đã từng được áp dụng?
Phiên bản nào có hiệu lực năm 2025?
Ai Archive tài liệu?
Tại sao tài liệu không còn sử dụng?
```

---

### Archive khi có version đang xử lý

Ví dụ:

```text
DOC-001

v3 ACTIVE

v4 PROCESSING
```

Admin chọn Archive.

Không nên bỏ qua v4 một cách âm thầm.

Hệ thống nên cảnh báo:

```text
Tài liệu đang có phiên bản v4
trong quá trình xử lý.

Archive sẽ làm toàn bộ tài liệu
ngừng được sử dụng.
```

Tùy policy có thể:

```text
Option A:
Không cho Archive cho tới khi xử lý v4 xong/hủy.

Option B:
Cho Archive và cancel processing v4.

Option C:
Cho Archive nhưng v4 tiếp tục xử lý,
sau đó vẫn không được publish.
```

Với MVP, tôi khuyên **Option A** vì đơn giản và ít tạo trạng thái khó kiểm soát.

---

### Archive khi có version chờ review

Ví dụ:

```text
v3 ACTIVE
v4 READY_FOR_REVIEW
```

Admin Archive Document.

Hệ thống nên cảnh báo:

```text
Tài liệu có một phiên bản đang chờ kiểm duyệt.
```

Không nên để:

```text
DOC = ARCHIVED

nhưng sau đó Admin vô tình:
Publish v4
→ DOC lại trở thành PUBLISHED
```

mà không có nghiệp vụ rõ ràng.

Vì vậy:

```text
Document = ARCHIVED
```

phải chặn:

```text
Publish version
Create new version
```

trừ khi tài liệu được khôi phục trước.

---

### State transition

State machine của `Document` có thể đơn giản:

```text
DRAFT
  │
  │ Publish
  ↓
PUBLISHED
  │
  │ Archive
  ↓
ARCHIVED
```

Sau này nếu cần khôi phục:

```text
ARCHIVED
   │
   │ Restore
   ↓
PUBLISHED
```

Nhưng tôi khuyên **Restore Document** là Use Case riêng, không gộp vào Archive.

---

### Quan hệ với Duplicate / Conflict

Archive cũng rất quan trọng cho conflict resolution sau này.

Ví dụ có hai tài liệu:

```text
DOC-001
Quy định nghỉ phép cũ

DOC-017
Quy định nghỉ phép mới
```

Sau review, doanh nghiệp xác nhận:

```text
DOC-017 thay thế DOC-001
```

Nếu chúng **không phải cùng logical Document** vì nghiệp vụ của doanh nghiệp đã tạo hai văn bản độc lập, có thể:

```text
DOC-001 → ARCHIVED
DOC-017 → PUBLISHED
```

và lưu quan hệ:

```text
DOC-017
   └── SUPERSEDES_DOCUMENT → DOC-001
```

Trong trường hợp chúng thực chất là cùng một tài liệu có version:

```text
DOC-001

v3 → SUPERSEDED
v4 → ACTIVE
```

thì không cần Archive cả Document.

Vì vậy cần phân biệt:

```text
Cùng Document
→ Version Management

Document mới thay thế một Document khác
→ Archive old Document + relationship
```

---

Use Case này về bản chất:

```text
Admin
  ↓
Xem chi tiết tài liệu
  ↓
Chọn Archive
  ↓
System kiểm tra quyền
  ↓
Kiểm tra workflow đang chạy
  ↓
Cảnh báo ảnh hưởng
  ↓
Admin xác nhận
  ↓
Document → ARCHIVED
  ↓
Loại khỏi Knowledge Base hiện hành
  ↓
Giữ file + versions + history
  ↓
Audit
```

Nguyên tắc quan trọng nhất:

```text
ARCHIVED
=
Không còn sử dụng hiện hành

KHÔNG PHẢI

Không còn tồn tại
```
### Use case Archive tài liệu

| Thuộc tính                  | Mô tả                                                                                                                                                                                                                    |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Tên Use Case**            | Lưu trữ tài liệu                                                                                                                                                                                                         |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                                            |
| **Mục tiêu**                | Cho phép quản trị viên ngừng sử dụng một tài liệu trong Knowledge Base hiện hành nhưng vẫn bảo toàn tài liệu, các phiên bản và lịch sử quản trị để phục vụ tra cứu, audit hoặc khôi phục trong tương lai.                |
| **Điều kiện kích hoạt**     | Quản trị viên đang xem chi tiết một tài liệu và chọn chức năng **Archive tài liệu**.                                                                                                                                     |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản đang hoạt động.<br>3. Quản trị viên có quyền quản lý hoặc lưu trữ tài liệu tương ứng.<br>4. Tài liệu tồn tại trong hệ thống.<br>5. Tài liệu chưa ở trạng thái `ARCHIVED`. |
| **Đầu vào**                 | `document_id` của tài liệu cần lưu trữ; có thể kèm lý do lưu trữ hoặc ghi chú nếu chính sách hệ thống yêu cầu.                                                                                                           |
| **Trạng thái — Thành công** | Tài liệu được chuyển sang trạng thái `ARCHIVED`; tài liệu không còn được sử dụng mặc định trong truy vấn hiện tại của Employee; file nguồn, phiên bản, metadata và lịch sử audit vẫn được giữ lại.                       |
| **Trạng thái — Thất bại**   | Trạng thái tài liệu không thay đổi; tài liệu vẫn hoạt động theo trạng thái trước đó và hệ thống thông báo nguyên nhân lỗi.                                                                                               |
| **Use Cases liên quan**     | Xem chi tiết tài liệu, Xem danh sách tài liệu, Xem lịch sử phiên bản, Phê duyệt và xuất bản tài liệu                                                                                                                     |

### Main Flow

| Bước | Actor         | Hành động                                                                            |
| ---: | ------------- | ------------------------------------------------------------------------------------ |
|    1 | Quản trị viên | Mở chức năng **Xem chi tiết tài liệu**.                                              |
|    2 | Quản trị viên | Chọn chức năng **Archive tài liệu**.                                                 |
|    3 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                          |
|    4 | System        | Kiểm tra quyền lưu trữ tài liệu của quản trị viên.                                   |
|    5 | System        | Kiểm tra tài liệu tồn tại và chưa ở trạng thái `ARCHIVED`.                           |
|    6 | System        | Xác định trạng thái hiện tại và phiên bản `ACTIVE` của tài liệu nếu có.              |
|    7 | System        | Hiển thị cảnh báo về ảnh hưởng của việc lưu trữ tài liệu.                            |
|    8 | System        | Yêu cầu quản trị viên xác nhận thao tác.                                             |
|    9 | Quản trị viên | Xác nhận lưu trữ tài liệu.                                                           |
|   10 | System        | Chuyển trạng thái `Document` sang `ARCHIVED`.                                        |
|   11 | System        | Loại tài liệu khỏi phạm vi Knowledge Base được sử dụng cho các truy vấn hiện hành.   |
|   12 | System        | Giữ nguyên file nguồn, metadata, các `DocumentVersion` và thông tin lịch sử.         |
|   13 | System        | Ghi nhận người thực hiện, thời điểm và lý do lưu trữ nếu có.                         |
|   14 | System        | Ghi Audit Event cho thao tác Archive.                                                |
|   15 | System        | Thông báo lưu trữ thành công cho quản trị viên.                                      |
|   16 | System        | Cập nhật giao diện chi tiết và danh sách tài liệu để phản ánh trạng thái `ARCHIVED`. |

### Luồng thay thế/ luồng ngoại lệ

| Điều kiện                                                   | Luồng xử lý                                                                                                                                               |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền Archive                        | Hệ thống từ chối thao tác và không thay đổi trạng thái tài liệu.                                                                                          |
| Tài liệu không tồn tại                                      | Hệ thống thông báo tài liệu không tồn tại hoặc không còn khả dụng.                                                                                        |
| Tài liệu đã ở trạng thái `ARCHIVED`                         | Hệ thống không thực hiện lại thao tác và thông báo tài liệu đã được lưu trữ.                                                                              |
| Quản trị viên hủy xác nhận                                  | Hệ thống không thay đổi trạng thái tài liệu.                                                                                                              |
| Tài liệu đang có phiên bản mới `PROCESSING`                 | Hệ thống cảnh báo rằng tài liệu đang có quá trình xử lý chưa hoàn tất; tùy chính sách có thể yêu cầu quản trị viên xử lý hoặc hủy job trước khi Archive.  |
| Tài liệu đang có phiên bản `READY_FOR_REVIEW`               | Hệ thống cảnh báo đang có phiên bản chờ kiểm duyệt; tùy chính sách có thể yêu cầu xử lý phiên bản này trước khi lưu trữ toàn bộ tài liệu.                 |
| Tài liệu đang được sử dụng bởi một workflow khác            | Hệ thống kiểm tra trạng thái hiện tại và có thể từ chối Archive nếu thao tác gây trạng thái không nhất quán.                                              |
| Cập nhật trạng thái tài liệu thất bại                       | Hệ thống rollback thay đổi; tài liệu giữ trạng thái trước Archive.                                                                                        |
| Không thể đồng bộ trạng thái xuống hệ thống retrieval/index | Hệ thống không được coi Archive là hoàn tất nếu tài liệu vẫn có nguy cơ được Employee truy xuất; thao tác phải được rollback hoặc đánh dấu lỗi cần xử lý. |
| Hai quản trị viên đồng thời thay đổi trạng thái tài liệu    | Hệ thống áp dụng kiểm soát concurrency và không ghi đè một trạng thái mới hơn bằng dữ liệu cũ.                                                            |
| Dịch vụ hệ thống không khả dụng                             | Hệ thống trả lỗi có kiểm soát và không thay đổi trạng thái tài liệu.                                                                                      |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                                                                                                 |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền phù hợp mới được Archive tài liệu.                                                                                                                                                           |
| Archive là thay đổi trạng thái của `Document`, không phải xóa vật lý tài liệu.                                                                                                                                          |
| Tài liệu ở trạng thái `ARCHIVED` không được sử dụng mặc định để trả lời các truy vấn hiện hành của Employee.                                                                                                            |
| Các `DocumentVersion` thuộc tài liệu phải được giữ lại sau khi Archive.                                                                                                                                                 |
| File nguồn của các phiên bản phải được giữ lại theo chính sách lưu trữ dữ liệu.                                                                                                                                         |
| Metadata và lịch sử thay đổi của tài liệu phải được giữ lại để phục vụ audit.                                                                                                                                           |
| Archive tài liệu không được hard-delete embeddings, chunks hoặc dữ liệu liên quan nếu việc xóa làm mất khả năng audit hoặc khôi phục; hệ thống có thể loại chúng khỏi retrieval thông qua trạng thái hoặc index policy. |
| Tài liệu Archive phải được loại khỏi phạm vi retrieval trước khi được coi là thao tác Archive hoàn tất.                                                                                                                 |
| Employee không được nhận tài liệu `ARCHIVED` làm evidence cho các câu hỏi hiện tại, trừ khi sau này hệ thống có Use Case tra cứu lịch sử được cho phép rõ ràng.                                                         |
| Việc Archive không làm thay đổi nội dung các phiên bản đã tồn tại.                                                                                                                                                      |
| Phiên bản `ACTIVE` trước thời điểm Archive vẫn được giữ trong lịch sử nhưng không còn được coi là nguồn tri thức hiện hành khi `Document = ARCHIVED`.                                                                   |
| Archive không đồng nghĩa `DocumentVersion = REJECTED`.                                                                                                                                                                  |
| Archive không đồng nghĩa xóa tài liệu.                                                                                                                                                                                  |
| Hệ thống phải ghi nhận người thực hiện và thời điểm Archive.                                                                                                                                                            |
| Nếu chính sách yêu cầu lý do lưu trữ, lý do phải được cung cấp trước khi xác nhận.                                                                                                                                      |
| Các thao tác Archive phải có khả năng truy vết trong Audit Log.                                                                                                                                                         |
| Nếu tài liệu đang có workflow chưa hoàn tất, hệ thống phải kiểm tra và xử lý xung đột trạng thái trước khi Archive.                                                                                                     |
| Một tài liệu `ARCHIVED` chỉ có thể quay lại Knowledge Base thông qua một nghiệp vụ khôi phục hoặc tái kích hoạt được định nghĩa riêng.                                                                                  |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể Archive tài liệu từ trang chi tiết tài liệu.                                                |
| Người không có quyền không thể Archive tài liệu.                                                                          |
| Hệ thống yêu cầu xác nhận trước khi thực hiện Archive.                                                                    |
| Nếu quản trị viên hủy xác nhận, trạng thái tài liệu không thay đổi.                                                       |
| Sau khi Archive thành công, `document_status = ARCHIVED`.                                                                 |
| Tài liệu `ARCHIVED` không còn xuất hiện trong danh sách tài liệu hoạt động mặc định.                                      |
| Quản trị viên có thể xem tài liệu Archive khi sử dụng bộ lọc phù hợp và có quyền.                                         |
| Tài liệu `ARCHIVED` không được sử dụng trong retrieval cho câu hỏi hiện hành của Employee.                                |
| Chunk hoặc dữ liệu từ tài liệu `ARCHIVED` không được truyền tới bước reranking hoặc generation cho truy vấn thông thường. |
| Các phiên bản của tài liệu vẫn tồn tại sau khi Archive.                                                                   |
| File nguồn của từng phiên bản vẫn được giữ theo chính sách hệ thống.                                                      |
| Lịch sử phiên bản vẫn có thể được quản trị viên xem sau khi Archive.                                                      |
| Metadata của tài liệu không bị mất khi Archive.                                                                           |
| Hệ thống ghi nhận đúng quản trị viên thực hiện Archive.                                                                   |
| Hệ thống ghi nhận đúng thời điểm Archive.                                                                                 |
| Lý do Archive được lưu nếu chính sách yêu cầu.                                                                            |
| Audit Log có sự kiện Archive tương ứng.                                                                                   |
| Nếu cập nhật trạng thái thất bại, tài liệu vẫn ở trạng thái trước đó.                                                     |
| Không tồn tại tình trạng `Document = ARCHIVED` nhưng Employee vẫn retrieve được tài liệu sau khi thao tác hoàn tất.       |
| Archive không làm biến mất hoặc hard-delete lịch sử tài liệu.                                                             |

### Dữ liệu liên quan

| Dữ liệu               | Mục đích                                                                  |
| --------------------- | ------------------------------------------------------------------------- |
| `document_id`         | Xác định tài liệu cần Archive.                                            |
| `document_status`     | Trạng thái nghiệp vụ của tài liệu; được chuyển thành `ARCHIVED`.          |
| `current_version_id`  | Xác định phiên bản hiện tại trước khi tài liệu được Archive.              |
| `document_version_id` | Định danh các phiên bản thuộc tài liệu.                                   |
| `version_status`      | Giữ trạng thái lịch sử của các phiên bản.                                 |
| `archived_by`         | Xác định quản trị viên thực hiện Archive.                                 |
| `archived_at`         | Thời điểm tài liệu được Archive.                                          |
| `archive_reason`      | Lý do lưu trữ nếu hệ thống yêu cầu.                                       |
| `updated_at`          | Thời điểm cập nhật trạng thái tài liệu.                                   |
| `access_policy`       | Chính sách truy cập được giữ lại để phục vụ audit hoặc khôi phục sau này. |
| `audit_event`         | Ghi nhận sự kiện Archive.                                                 |

### Ghi chú thiết kế

Cần phân biệt rất rõ:

```text
ARCHIVE
   ≠
DELETE
```

Ví dụ trước khi Archive:

```text
Document DOC-001
"Quy định nghỉ phép"

Status:
PUBLISHED

Versions:
├── v1 SUPERSEDED
├── v2 SUPERSEDED
└── v3 ACTIVE
```

Sau khi Admin Archive:

```text
Document DOC-001
"Quy định nghỉ phép"

Status:
ARCHIVED

Versions:
├── v1 SUPERSEDED
├── v2 SUPERSEDED
└── v3 ACTIVE (historical state)
```

Tuy nhiên vì:

```text
Document.status = ARCHIVED
```

nên v3 **không còn được retrieval sử dụng cho câu hỏi hiện hành**.

Có thể hiểu điều kiện retrieval:

```text
Document.status = PUBLISHED
AND
DocumentVersion.status = ACTIVE
AND
Employee có quyền READ
```

Khi Document chuyển:

```text
PUBLISHED
    ↓
ARCHIVED
```

thì điều kiện đầu tiên không còn thỏa mãn:

```text
Document.status != PUBLISHED
```

và tài liệu tự động bị loại khỏi Knowledge Base hiện hành.

---

### Vì sao không đổi Version `ACTIVE → SUPERSEDED` khi Archive?

Hai khái niệm khác nhau.

`SUPERSEDED` nghĩa là:

> Phiên bản này đã được **một phiên bản mới hơn của cùng tài liệu thay thế**.

Ví dụ:

```text
v3 ACTIVE
   ↓
Publish v4
   ↓
v3 SUPERSEDED
v4 ACTIVE
```

Trong khi Archive nghĩa là:

> **Toàn bộ tài liệu không còn được sử dụng hiện hành**.

Không nhất thiết có một version mới thay thế.

Ví dụ:

```text
DOC-001
v3 ACTIVE
    ↓
Archive Document
    ↓
DOC-001 = ARCHIVED
```

Không có v4, vì vậy nếu đổi v3 thành `SUPERSEDED` sẽ sai nghĩa nghiệp vụ.

---

### Retrieval sau Archive

Trước:

```text
Employee question
       ↓
ACL Filter
       ↓
Document = PUBLISHED
       ↓
Version = ACTIVE
       ↓
DOC-001 v3
       ↓
Retrieval
```

Sau Archive:

```text
Employee question
       ↓
ACL Filter
       ↓
Document = PUBLISHED ?
       ↓
       NO
       ↓
DOC-001 bị loại
```

Do đó tài liệu không được đi tiếp tới:

```text
Dense Search
BM25
RRF
Reranker
Evidence Gate
LLM
```

Đặc biệt không nên thiết kế:

```text
Retrieve cả ARCHIVED
       ↓
đến cuối mới filter
```

vì dữ liệu đã ngừng hiệu lực không nên trở thành candidate evidence ngay từ đầu.

---

### Archive và Delete

Tôi khuyên MVP áp dụng:

```text
DRAFT / upload nhầm
       ↓
có thể cho phép xóa theo policy

PUBLISHED
       ↓
không hard-delete thông thường
       ↓
ARCHIVE
```

Ví dụ:

```text
PUBLISHED
    ↓
ARCHIVED
    ↓
Giữ:
- Document
- Versions
- Source files
- Metadata
- Audit
- History
```

Điều này phù hợp hơn với hệ thống tri thức doanh nghiệp vì sau này bạn còn cần trả lời:

```text
Tài liệu nào đã từng được áp dụng?
Phiên bản nào có hiệu lực năm 2025?
Ai Archive tài liệu?
Tại sao tài liệu không còn sử dụng?
```

---

### Archive khi có version đang xử lý

Ví dụ:

```text
DOC-001

v3 ACTIVE

v4 PROCESSING
```

Admin chọn Archive.

Không nên bỏ qua v4 một cách âm thầm.

Hệ thống nên cảnh báo:

```text
Tài liệu đang có phiên bản v4
trong quá trình xử lý.

Archive sẽ làm toàn bộ tài liệu
ngừng được sử dụng.
```

Tùy policy có thể:

```text
Option A:
Không cho Archive cho tới khi xử lý v4 xong/hủy.

Option B:
Cho Archive và cancel processing v4.

Option C:
Cho Archive nhưng v4 tiếp tục xử lý,
sau đó vẫn không được publish.
```

Với MVP, tôi khuyên **Option A** vì đơn giản và ít tạo trạng thái khó kiểm soát.

---

### Archive khi có version chờ review

Ví dụ:

```text
v3 ACTIVE
v4 READY_FOR_REVIEW
```

Admin Archive Document.

Hệ thống nên cảnh báo:

```text
Tài liệu có một phiên bản đang chờ kiểm duyệt.
```

Không nên để:

```text
DOC = ARCHIVED

nhưng sau đó Admin vô tình:
Publish v4
→ DOC lại trở thành PUBLISHED
```

mà không có nghiệp vụ rõ ràng.

Vì vậy:

```text
Document = ARCHIVED
```

phải chặn:

```text
Publish version
Create new version
```

trừ khi tài liệu được khôi phục trước.

---

### State transition

State machine của `Document` có thể đơn giản:

```text
DRAFT
  │
  │ Publish
  ↓
PUBLISHED
  │
  │ Archive
  ↓
ARCHIVED
```

Sau này nếu cần khôi phục:

```text
ARCHIVED
   │
   │ Restore
   ↓
PUBLISHED
```

Nhưng tôi khuyên **Restore Document** là Use Case riêng, không gộp vào Archive.

---

### Quan hệ với Duplicate / Conflict

Archive cũng rất quan trọng cho conflict resolution sau này.

Ví dụ có hai tài liệu:

```text
DOC-001
Quy định nghỉ phép cũ

DOC-017
Quy định nghỉ phép mới
```

Sau review, doanh nghiệp xác nhận:

```text
DOC-017 thay thế DOC-001
```

Nếu chúng **không phải cùng logical Document** vì nghiệp vụ của doanh nghiệp đã tạo hai văn bản độc lập, có thể:

```text
DOC-001 → ARCHIVED
DOC-017 → PUBLISHED
```

và lưu quan hệ:

```text
DOC-017
   └── SUPERSEDES_DOCUMENT → DOC-001
```

Trong trường hợp chúng thực chất là cùng một tài liệu có version:

```text
DOC-001

v3 → SUPERSEDED
v4 → ACTIVE
```

thì không cần Archive cả Document.

Vì vậy cần phân biệt:

```text
Cùng Document
→ Version Management

Document mới thay thế một Document khác
→ Archive old Document + relationship
```

---

Use Case này về bản chất:

```text
Admin
  ↓
Xem chi tiết tài liệu
  ↓
Chọn Archive
  ↓
System kiểm tra quyền
  ↓
Kiểm tra workflow đang chạy
  ↓
Cảnh báo ảnh hưởng
  ↓
Admin xác nhận
  ↓
Document → ARCHIVED
  ↓
Loại khỏi Knowledge Base hiện hành
  ↓
Giữ file + versions + history
  ↓
Audit
```

Nguyên tắc quan trọng nhất:

```text
ARCHIVED
=
Không còn sử dụng hiện hành

KHÔNG PHẢI

Không còn tồn tại
```
### Use case yêu cầu xử lý lại tài liệu

| Thuộc tính                  | Mô tả                                                                                                                                                                                                                                                                                                                                                                                                        |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Tên Use Case**            | Yêu cầu xử lý lại tài liệu                                                                                                                                                                                                                                                                                                                                                                                   |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                                                                                                                                                                                                                                |
| **Mục tiêu**                | Cho phép quản trị viên yêu cầu hệ thống thực hiện lại quá trình xử lý đối với một phiên bản tài liệu khi lần xử lý trước thất bại, có lỗi hoặc kết quả xử lý không đạt yêu cầu, mà không cần tạo một phiên bản tài liệu mới nếu nội dung file nguồn không thay đổi.                                                                                                                                          |
| **Điều kiện kích hoạt**     | Quản trị viên phát hiện phiên bản tài liệu xử lý thất bại hoặc kết quả xử lý không đạt yêu cầu và chọn chức năng **Yêu cầu xử lý lại**.                                                                                                                                                                                                                                                                      |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản đang hoạt động.<br>3. Quản trị viên có quyền quản lý tài liệu tương ứng.<br>4. `DocumentVersion` cần xử lý lại tồn tại.<br>5. File nguồn của phiên bản vẫn còn khả dụng.<br>6. Phiên bản đang ở trạng thái cho phép xử lý lại.<br>7. Không có một Processing Job khác đang hoạt động cho cùng phiên bản, trừ khi hệ thống hỗ trợ cơ chế thay thế job rõ ràng. |
| **Đầu vào**                 | `document_id`, `document_version_id`; có thể kèm lý do yêu cầu xử lý lại hoặc cấu hình xử lý được phép thay đổi nếu hệ thống hỗ trợ.                                                                                                                                                                                                                                                                         |
| **Trạng thái — Thành công** | Một Processing Job mới được tạo cho đúng `DocumentVersion`; hệ thống thực hiện lại quá trình xử lý từ file nguồn; phiên bản chưa được đưa vào Knowledge Base chính thức cho tới khi xử lý thành công và hoàn tất các bước kiểm duyệt cần thiết.                                                                                                                                                              |
| **Trạng thái — Thất bại**   | Không tạo job xử lý mới hoặc job mới kết thúc ở trạng thái `FAILED`; dữ liệu phiên bản và phiên bản `ACTIVE` hiện tại không bị thay đổi ngoài ý muốn.                                                                                                                                                                                                                                                        |
| **Use Cases liên quan**     | Xem chi tiết tài liệu, Theo dõi trạng thái xử lý, Kiểm duyệt tài liệu, Tạo phiên bản tài liệu mới                                                                                                                                                                                                                                                                                                            |

### Main Flow

| Bước | Actor         | Hành động                                                                               |
| ---: | ------------- | --------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Mở trang **Xem chi tiết tài liệu** hoặc thông tin phiên bản cần xử lý lại.              |
|    2 | System        | Hiển thị trạng thái xử lý hiện tại và thông tin lỗi/cảnh báo nếu có.                    |
|    3 | Quản trị viên | Chọn chức năng **Yêu cầu xử lý lại**.                                                   |
|    4 | System        | Kiểm tra phiên đăng nhập và quyền của quản trị viên.                                    |
|    5 | System        | Kiểm tra `Document` và `DocumentVersion` còn tồn tại.                                   |
|    6 | System        | Kiểm tra file nguồn của phiên bản vẫn khả dụng và hợp lệ.                               |
|    7 | System        | Kiểm tra trạng thái hiện tại có cho phép xử lý lại hay không.                           |
|    8 | System        | Kiểm tra không có Processing Job khác đang chạy cho cùng phiên bản.                     |
|    9 | System        | Hiển thị thông tin ảnh hưởng của việc xử lý lại và yêu cầu quản trị viên xác nhận.      |
|   10 | Quản trị viên | Xác nhận yêu cầu xử lý lại.                                                             |
|   11 | System        | Tạo một Processing Job mới gắn với `document_version_id` hiện tại.                      |
|   12 | System        | Đặt trạng thái job mới thành `PENDING`.                                                 |
|   13 | System        | Ghi nhận người yêu cầu, thời điểm và lý do xử lý lại nếu có.                            |
|   14 | System        | Đưa job vào hàng đợi xử lý.                                                             |
|   15 | System        | Thực hiện lại quá trình xử lý tài liệu từ file nguồn.                                   |
|   16 | System        | Cập nhật trạng thái Processing Job thành `RUNNING`.                                     |
|   17 | System        | Khi xử lý hoàn tất thành công, cập nhật Processing Job thành `SUCCEEDED`.               |
|   18 | System        | Cập nhật phiên bản sang trạng thái phù hợp để kiểm duyệt lại, ví dụ `READY_FOR_REVIEW`. |
|   19 | System        | Ghi Audit Event cho thao tác xử lý lại.                                                 |
|   20 | System        | Thông báo kết quả hoặc trạng thái xử lý hiện tại cho quản trị viên.                     |

### Luồng xử lý kỹ thuật ở mức nghiệp vụ

| Giai đoạn                  | Mục đích                                                                    |
| -------------------------- | --------------------------------------------------------------------------- |
| **Tiếp nhận yêu cầu**      | Xác định đúng tài liệu, phiên bản và lý do cần xử lý lại.                   |
| **Tạo Processing Job mới** | Tạo một lần xử lý độc lập thay vì ghi đè lịch sử job cũ.                    |
| **Đọc lại file nguồn**     | Sử dụng lại file thuộc đúng `DocumentVersion`.                              |
| **Xử lý lại nội dung**     | Thực hiện lại các bước cần thiết của ingestion pipeline.                    |
| **Kiểm tra kết quả**       | Xác định quá trình xử lý mới thành công hay thất bại.                       |
| **Chuyển sang kiểm duyệt** | Nếu thành công, phiên bản được đưa trở lại trạng thái cần Admin kiểm duyệt. |
| **Lưu lịch sử**            | Giữ cả job cũ và job mới phục vụ audit và phân tích lỗi.                    |

### Luồng thay thế/ luồng ngoại lệ

| Điều kiện                                                                   | Luồng xử lý                                                                                                                                                  |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Quản trị viên không có quyền xử lý lại tài liệu                             | Hệ thống từ chối yêu cầu và không tạo Processing Job mới.                                                                                                    |
| Tài liệu hoặc phiên bản không tồn tại                                       | Hệ thống thông báo tài liệu/phiên bản không còn khả dụng.                                                                                                    |
| File nguồn không còn tồn tại                                                | Hệ thống không thể xử lý lại và yêu cầu quản trị viên kiểm tra file hoặc tạo phiên bản mới nếu cần.                                                          |
| File nguồn bị hỏng                                                          | Hệ thống từ chối xử lý lại và thông báo lỗi; nếu cần thay file phải sử dụng **Tạo phiên bản tài liệu mới**.                                                  |
| Có một Processing Job khác đang `RUNNING` cho cùng phiên bản                | Hệ thống không tạo job chạy song song và thông báo phiên bản đang được xử lý.                                                                                |
| Processing Job hiện tại đang `PENDING`                                      | Hệ thống không tạo thêm job trùng nếu job hiện tại vẫn còn hợp lệ.                                                                                           |
| Phiên bản đã `ACTIVE` nhưng Admin muốn xử lý lại do nghi ngờ lỗi extraction | Hệ thống phải áp dụng chính sách thận trọng; phiên bản hiện tại không được tự động thay đổi dữ liệu phục vụ retrieval trước khi kết quả mới được kiểm duyệt. |
| Phiên bản đã `REJECTED`                                                     | Hệ thống có thể cho phép xử lý lại nếu lý do từ chối là lỗi kỹ thuật; nếu lỗi nằm ở nội dung file, phải tạo phiên bản mới.                                   |
| Phiên bản `SUPERSEDED`                                                      | Hệ thống có thể hạn chế xử lý lại vì phiên bản không còn hiện hành, trừ nhu cầu audit hoặc phục hồi dữ liệu lịch sử.                                         |
| Document đã `ARCHIVED`                                                      | Hệ thống không cho phép xử lý lại theo luồng thông thường hoặc yêu cầu khôi phục Document trước, tùy chính sách.                                             |
| Quá trình xử lý lại thất bại                                                | Job mới chuyển sang `FAILED`; hệ thống lưu lỗi và cho phép Admin xem nguyên nhân.                                                                            |
| Quá trình xử lý lại thành công nhưng kết quả vẫn không đạt yêu cầu          | Phiên bản chuyển sang `READY_FOR_REVIEW`; Admin có thể tiếp tục yêu cầu xử lý lại hoặc từ chối tùy nguyên nhân.                                              |
| Hai Admin cùng yêu cầu xử lý lại                                            | Hệ thống phải kiểm soát concurrency để không tạo nhiều job trùng cho cùng phiên bản cùng thời điểm.                                                          |
| Dịch vụ hàng đợi hoặc worker không khả dụng                                 | Hệ thống không coi xử lý lại là hoàn tất; job có thể giữ `PENDING` hoặc request thất bại theo thiết kế.                                                      |
| Lỗi hệ thống khi tạo job                                                    | Hệ thống không thay đổi phiên bản và trả lỗi có kiểm soát.                                                                                                   |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                                                              |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Chỉ quản trị viên có quyền phù hợp mới được yêu cầu xử lý lại tài liệu.                                                                                                              |
| Xử lý lại được thực hiện đối với một `DocumentVersion` cụ thể.                                                                                                                       |
| Xử lý lại không tạo `Document` mới.                                                                                                                                                  |
| Xử lý lại không tạo `DocumentVersion` mới nếu file và nội dung nghiệp vụ không thay đổi.                                                                                             |
| Nếu Admin cần thay file hoặc nội dung tài liệu, phải sử dụng Use Case **Tạo phiên bản tài liệu mới**.                                                                                |
| Mỗi lần xử lý lại phải tạo một Processing Job mới thay vì ghi đè job cũ.                                                                                                             |
| Processing Job cũ phải được giữ lại phục vụ audit, debug và phân tích chất lượng.                                                                                                    |
| Hệ thống không được chạy nhiều Processing Job đồng thời cho cùng một `DocumentVersion` nếu điều đó có thể tạo dữ liệu không nhất quán.                                               |
| Job mới phải tham chiếu đúng `document_version_id` và file nguồn của phiên bản.                                                                                                      |
| Chỉ khi xử lý thành công, phiên bản mới được phép chuyển sang `READY_FOR_REVIEW`.                                                                                                    |
| Processing Job `FAILED` không được làm phiên bản trở thành `READY_FOR_REVIEW`.                                                                                                       |
| Xử lý lại thành công không đồng nghĩa phiên bản được tự động `ACTIVE`.                                                                                                               |
| Sau xử lý lại, phiên bản phải được kiểm duyệt lại nếu dữ liệu dùng cho Knowledge Base đã được tái tạo.                                                                               |
| Phiên bản đang `ACTIVE` không được tự động thay thế dữ liệu retrieval hiện hành bằng kết quả xử lý mới chưa được kiểm duyệt nếu việc đó có nguy cơ làm thay đổi evidence chính thức. |
| Việc xử lý lại không được làm thay đổi `version_number`.                                                                                                                             |
| File nguồn không được sửa trực tiếp trong Use Case xử lý lại.                                                                                                                        |
| Hệ thống phải ghi nhận người yêu cầu, thời điểm, Processing Job mới và kết quả xử lý.                                                                                                |
| Lịch sử các lần xử lý phải có khả năng truy vết.                                                                                                                                     |
| Nếu tài liệu đã `ARCHIVED`, xử lý lại phải tuân theo policy riêng của tài liệu Archive.                                                                                              |
| Xử lý lại phải đảm bảo kết quả cũ không bị xóa trước khi kết quả mới đủ điều kiện thay thế.                                                                                          |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                              |
| ---------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể yêu cầu xử lý lại một phiên bản bị lỗi.                                      |
| Người không có quyền không thể tạo Processing Job mới.                                                     |
| Hệ thống xác định đúng `DocumentVersion` cần xử lý lại.                                                    |
| Mỗi lần xử lý lại tạo một Processing Job mới.                                                              |
| Job xử lý trước đó vẫn được giữ lại trong lịch sử.                                                         |
| Xử lý lại không tạo một `DocumentVersion` mới nếu file không thay đổi.                                     |
| `version_number` không thay đổi sau khi xử lý lại.                                                         |
| Hệ thống sử dụng đúng file nguồn của phiên bản để xử lý lại.                                               |
| Khi file nguồn không tồn tại, hệ thống không tạo job xử lý không hợp lệ.                                   |
| Khi một job đang chạy, hệ thống không tạo thêm job chạy song song trái policy cho cùng phiên bản.          |
| Job mới bắt đầu ở trạng thái `PENDING` và chuyển sang `RUNNING` khi được worker tiếp nhận.                 |
| Khi xử lý thành công, job chuyển sang `SUCCEEDED`.                                                         |
| Khi xử lý thất bại, job chuyển sang `FAILED`.                                                              |
| Phiên bản chỉ chuyển sang `READY_FOR_REVIEW` khi quá trình xử lý thành công.                               |
| Xử lý thành công không tự động chuyển phiên bản thành `ACTIVE`.                                            |
| Phiên bản sau khi xử lý lại có thể được Admin kiểm duyệt lại trước khi sử dụng chính thức.                 |
| Nếu phiên bản đang `ACTIVE`, quá trình xử lý lại không được làm Employee nhận dữ liệu mới chưa kiểm duyệt. |
| Hệ thống ghi nhận được Admin yêu cầu xử lý lại và thời điểm yêu cầu.                                       |
| Hệ thống ghi nhận được lý do xử lý lại nếu trường này được yêu cầu.                                        |
| Khi job mới thất bại, phiên bản chính thức hiện tại không bị thay đổi ngoài ý muốn.                        |
| Không có tình trạng nhiều job cùng ghi đè dữ liệu xử lý của cùng một phiên bản mà không có kiểm soát.      |

### Dữ liệu liên quan

| Dữ liệu                      | Mục đích                                                        |
| ---------------------------- | --------------------------------------------------------------- |
| `document_id`                | Định danh Document chứa phiên bản cần xử lý lại.                |
| `document_version_id`        | Định danh chính xác phiên bản cần xử lý lại.                    |
| `version_number`             | Số phiên bản; không thay đổi khi reprocess.                     |
| `version_status`             | Xác định trạng thái nghiệp vụ của phiên bản trước và sau xử lý. |
| `processing_job_id`          | Định danh lần xử lý mới.                                        |
| `processing_status`          | Trạng thái job như `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`. |
| `previous_processing_job_id` | Liên kết tới job trước nếu cần truy vết các lần xử lý.          |
| `file_name`                  | Tên file nguồn được sử dụng lại.                                |
| `file_hash`                  | Xác định tính toàn vẹn của file nguồn.                          |
| `storage_location`           | Vị trí file nguồn cần xử lý.                                    |
| `retry_reason`               | Lý do Admin yêu cầu xử lý lại.                                  |
| `requested_by`               | Quản trị viên yêu cầu xử lý lại.                                |
| `requested_at`               | Thời điểm yêu cầu.                                              |
| `started_at`                 | Thời điểm job bắt đầu chạy.                                     |
| `completed_at`               | Thời điểm job kết thúc.                                         |
| `processing_error`           | Thông tin lỗi nếu job thất bại.                                 |
| `processing_warnings`        | Cảnh báo phát sinh trong quá trình xử lý.                       |
| `retry_count`                | Số lần xử lý lại nếu hệ thống cần theo dõi.                     |

### Ghi chú thiết kế

Điểm quan trọng nhất là phân biệt:

```text
XỬ LÝ LẠI
    ≠
TẠO PHIÊN BẢN MỚI
```

Ví dụ:

```text
Document DOC-001
"Quy định nghỉ phép"

Version v3
File:
quy_dinh_nghi_phep_2026.pdf
```

Lần xử lý đầu:

```text
Processing Job #1
      ↓
OCR / Extraction
      ↓
FAILED
```

Admin chọn:

```text
Yêu cầu xử lý lại
```

Hệ thống tạo:

```text
Document DOC-001
        │
        └── Version v3
               │
               ├── Processing Job #1
               │       └── FAILED
               │
               └── Processing Job #2
                       └── RUNNING
```

Không phải:

```text
v3 FAILED
   ↓
Reprocess
   ↓
Tạo v4
```

vì nội dung tài liệu không thay đổi.

---

Nếu Job #2 thành công:

```text
DocumentVersion v3
        │
        └── Processing Job #2
               ↓
           SUCCEEDED
               ↓
       READY_FOR_REVIEW
```

Admin tiếp tục:

```text
Kiểm duyệt
     ↓
Đạt yêu cầu
     ↓
Phê duyệt / Xuất bản
```

---

### Khi nào dùng Reprocess?

Ví dụ 1:

```text
File nguồn đúng

Nhưng OCR:
"15.000.000"
     ↓
"150.000.000"

→ Reprocess
```

Ví dụ 2:

```text
Extraction service timeout

→ FAILED
→ Reprocess
```

Ví dụ 3:

```text
Embedding service lỗi

→ FAILED
→ Reprocess
```

Ví dụ 4:

```text
Indexing chưa hoàn thành do Qdrant/Postgres lỗi

→ Reprocess phần xử lý cần thiết
```

Trong các trường hợp này:

```text
Source File không đổi
DocumentVersion không đổi
```

nên không cần version mới.

---

### Khi nào KHÔNG dùng Reprocess?

Nếu file nguồn thay đổi:

```text
File cũ:
Nghỉ phép = 12 ngày

File mới:
Nghỉ phép = 14 ngày
```

thì:

```text
Không dùng:
Yêu cầu xử lý lại

Phải dùng:
Tạo phiên bản tài liệu mới
```

Kết quả:

```text
DOC-001
│
├── v3 ACTIVE
│
└── v4 DRAFT
      ↓
    Processing
```

Có thể nhớ bằng quy tắc:

```text
File / Content không đổi
        +
Pipeline lỗi
        ↓
REPROCESS
```

```text
File / Content thay đổi
        ↓
NEW VERSION
```

---

### Không nên ghi đè Processing Job cũ

Thiết kế không tốt:

```text
processing_status = FAILED

Admin Retry

processing_status = RUNNING

→ mất lịch sử FAILED
```

Thiết kế tốt hơn:

```text
DocumentVersion v3
        │
        ├── Job 001
        │    status = FAILED
        │    error  = OCR_TIMEOUT
        │
        ├── Job 002
        │    status = FAILED
        │    error  = EMBEDDING_ERROR
        │
        └── Job 003
             status = SUCCEEDED
```

Nhờ đó Admin có thể biết:

```text
Tài liệu đã xử lý bao nhiêu lần?
Lỗi gì?
Lần nào thành công?
Mất bao lâu?
```

---

### Reprocess với phiên bản đang ACTIVE

Đây là trường hợp cần thận trọng.

Ví dụ:

```text
v3 = ACTIVE
```

sau đó phát hiện chunking hiện tại có lỗi và Admin muốn reprocess.

Không nên:

```text
Admin Reprocess
      ↓
Xóa ngay chunks/vector cũ
      ↓
Build lại
```

vì trong khoảng đó Employee có thể:

```text
không tìm thấy tài liệu
```

hoặc tệ hơn:

```text
retrieve dữ liệu mới chưa kiểm duyệt
```

Thiết kế an toàn hơn:

```text
v3 ACTIVE
   │
   │ Existing index snapshot
   │ vẫn hoạt động
   │
   └── Reprocess Job
          ↓
      Build candidate result
          ↓
      READY_FOR_REVIEW
          ↓
      Admin kiểm duyệt
          ↓
      Promote result mới
          ↓
      Retire result cũ
```

Tức là có thể giữ:

```text
ACTIVE SERVING DATA
```

và:

```text
CANDIDATE PROCESSING DATA
```

tách nhau cho đến khi kết quả mới được chấp nhận.

Đây là chi tiết kiến trúc nên triển khai sau trong Sequence/Processing Design; ở Use Case chỉ cần giữ rule:

> **Reprocess không được làm dữ liệu chưa kiểm duyệt thay thế dữ liệu đang phục vụ Employee.**

---

### Quan hệ với Processing Status

Bạn nên tiếp tục tách:

```text
DocumentVersion status
```

khỏi:

```text
ProcessingJob status
```

Ví dụ:

```text
DocumentVersion v4:
READY_FOR_REVIEW
```

có thể có lịch sử:

```text
Job 1 → FAILED
Job 2 → FAILED
Job 3 → SUCCEEDED
```

Trạng thái cuối của phiên bản:

```text
READY_FOR_REVIEW
```

không có nghĩa:

```text
mọi Processing Job đều thành công
```

mà có nghĩa lần xử lý hợp lệ gần nhất đã đủ để đưa phiên bản sang Review.

---

### State flow đề xuất

```text
DocumentVersion
    DRAFT
      │
      ↓
Processing Job #1
      │
      ├── FAILED
      │      ↓
      │   Reprocess
      │      ↓
      │ Processing Job #2
      │
      └── SUCCEEDED
             ↓
      READY_FOR_REVIEW
             ↓
          Review
```

Nếu Job #2 lại thất bại:

```text
Job #1 FAILED
Job #2 FAILED
     ↓
Admin Reprocess
     ↓
Job #3
```

Tất cả lịch sử vẫn được giữ.

---

### Liên hệ với duplicate/version detection

Nếu trong quá trình Admin chọn Reprocess, hệ thống phát hiện file nguồn thực tế đã bị thay đổi so với `file_hash` của `DocumentVersion`, thì không nên tiếp tục.

Ví dụ:

```text
Stored hash:
abc123

Current source hash:
xyz789
```

Điều này cho thấy:

```text
File source đã thay đổi
```

Hệ thống nên:

```text
Stop Reprocess
     ↓
Thông báo source không còn giống version ban đầu
     ↓
Yêu cầu tạo phiên bản mới
```

vì nếu vẫn xử lý lại:

```text
DocumentVersion v3
```

nhưng nội dung thực tế đã khác v3, hệ thống sẽ phá vỡ lịch sử version.

---

Use Case này về bản chất là:

```text
Admin
 ↓
Phát hiện lỗi xử lý
 ↓
Yêu cầu xử lý lại
 ↓
System kiểm tra Version + Source File
 ↓
Tạo Processing Job mới
 ↓
Giữ Processing Job cũ
 ↓
Chạy lại pipeline
 ↓
┌─────────────────┐
│                 │
FAILED          SUCCEEDED
│                 │
↓                 ↓
Theo dõi      READY_FOR_REVIEW
                  ↓
               Review
```

Nguyên tắc cần nhớ:

```text
REPROCESS
=
Xử lý lại cùng một phiên bản

NEW VERSION
=
Nội dung nghiệp vụ mới
```

### Use case quản lý người dùng

| Thuộc tính                  | Mô tả                                                                                                                                                                                                                                         |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**            | Quản lý người dùng                                                                                                                                                                                                                            |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                                                                 |
| **Mục tiêu**                | Cho phép quản trị viên xem và quản lý thông tin, trạng thái và thông tin tổ chức của người dùng trong Enterprise RAG Platform nhằm đảm bảo chỉ những người dùng hợp lệ mới có thể sử dụng hệ thống và được gán đúng vai trò, nhóm, phòng ban. |
| **Điều kiện kích hoạt**     | Quản trị viên truy cập chức năng **Quản lý người dùng**.                                                                                                                                                                                      |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản quản trị viên đang hoạt động.<br>3. Quản trị viên có quyền quản lý người dùng.                                                                                                                 |
| **Đầu vào**                 | Người dùng cần quản lý và các thông tin được phép cập nhật như họ tên, trạng thái tài khoản, vai trò, nhóm, phòng ban hoặc các thông tin quản trị khác.                                                                                       |
| **Trạng thái — Thành công** | Thông tin người dùng được cập nhật hợp lệ; các thay đổi liên quan đến trạng thái, vai trò, nhóm hoặc phòng ban được áp dụng theo chính sách phân quyền hiện tại; sự kiện thay đổi được ghi nhận phục vụ audit.                                |
| **Trạng thái — Thất bại**   | Thông tin người dùng không bị thay đổi; hệ thống thông báo nguyên nhân và không để dữ liệu ở trạng thái không nhất quán.                                                                                                                      |
| **Use Cases liên quan**     | Quản lý vai trò, Quản lý nhóm, Quản lý phòng ban, Thiết lập quyền truy cập tài liệu, Xem ma trận quyền, Kiểm tra quyền truy cập                                                                                                               |

### Main Flow

| Bước | Actor         | Hành động                                                                                |
| ---: | ------------- | ---------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Truy cập chức năng **Quản lý người dùng**.                                               |
|    2 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                              |
|    3 | System        | Kiểm tra quản trị viên có quyền quản lý người dùng hay không.                            |
|    4 | System        | Lấy danh sách người dùng thuộc phạm vi quản trị viên được phép quản lý.                  |
|    5 | System        | Hiển thị danh sách người dùng cùng các thông tin cơ bản.                                 |
|    6 | Quản trị viên | Tìm kiếm hoặc chọn người dùng cần quản lý.                                               |
|    7 | System        | Hiển thị thông tin chi tiết của người dùng được chọn.                                    |
|    8 | Quản trị viên | Chọn thao tác cần thực hiện đối với người dùng.                                          |
|    9 | Quản trị viên | Cập nhật các thông tin được phép như trạng thái tài khoản, vai trò, nhóm hoặc phòng ban. |
|   10 | System        | Kiểm tra tính hợp lệ của dữ liệu mới.                                                    |
|   11 | System        | Kiểm tra quản trị viên có quyền thực hiện thay đổi tương ứng hay không.                  |
|   12 | System        | Xác định ảnh hưởng của thay đổi tới quyền truy cập hiện tại của người dùng.              |
|   13 | Quản trị viên | Xác nhận thay đổi nếu thao tác có ảnh hưởng đến quyền hoặc trạng thái tài khoản.         |
|   14 | System        | Lưu thông tin người dùng mới.                                                            |
|   15 | System        | Cập nhật các quan hệ Role, Group hoặc Department tương ứng nếu có.                       |
|   16 | System        | Áp dụng lại quyền hiệu lực của người dùng theo dữ liệu mới.                              |
|   17 | System        | Ghi nhận người thực hiện, thời điểm và nội dung thay đổi vào Audit Log.                  |
|   18 | System        | Thông báo cập nhật thành công.                                                           |
|   19 | System        | Hiển thị lại thông tin người dùng mới nhất.                                              |

### Thông tin người dùng được quản lý

| Thông tin                       | Ý nghĩa                                                                                      |
| ------------------------------- | -------------------------------------------------------------------------------------------- |
| **Họ và tên**                   | Tên hiển thị của người dùng trong hệ thống.                                                  |
| **Email công ty**               | Email doanh nghiệp dùng để xác định tài khoản người dùng.                                    |
| **Trạng thái tài khoản**        | Xác định tài khoản đang `ACTIVE`, `LOCKED`, `DISABLED` hoặc trạng thái tương ứng.            |
| **Vai trò**                     | Các Role được gán cho người dùng như `EMPLOYEE`, `ADMIN` hoặc vai trò nghiệp vụ khác nếu có. |
| **Nhóm**                        | Các Group mà người dùng đang tham gia.                                                       |
| **Phòng ban**                   | Department hiện tại của người dùng.                                                          |
| **Thời điểm tạo tài khoản**     | Thời điểm người dùng được ghi nhận trong Enterprise RAG Platform.                            |
| **Thời điểm cập nhật**          | Thời điểm thông tin người dùng được cập nhật gần nhất.                                       |
| **Trạng thái sử dụng hệ thống** | Giúp Admin xác định tài khoản có còn được phép sử dụng hệ thống hay không.                   |

### Các thao tác quản lý người dùng

| Thao tác                          | Mô tả                                                                             |
| --------------------------------- | --------------------------------------------------------------------------------- |
| **Xem danh sách người dùng**      | Xem những người dùng hiện có trong hệ thống.                                      |
| **Xem thông tin người dùng**      | Xem thông tin tài khoản, Role, Group và Department hiện tại.                      |
| **Cập nhật thông tin người dùng** | Cập nhật các trường được phép quản lý.                                            |
| **Kích hoạt tài khoản**           | Chuyển tài khoản sang trạng thái cho phép sử dụng hệ thống nếu đáp ứng điều kiện. |
| **Vô hiệu hóa tài khoản**         | Ngăn người dùng tiếp tục sử dụng hệ thống mà không xóa dữ liệu lịch sử.           |
| **Gán hoặc thay đổi vai trò**     | Quản lý Role của người dùng theo quyền Admin được cấp.                            |
| **Gán hoặc thay đổi nhóm**        | Quản lý Group membership của người dùng.                                          |
| **Gán hoặc thay đổi phòng ban**   | Cập nhật Department của người dùng.                                               |

### Luồng thay thế / luồng ngoại lệ

| Điều kiện                                                               | Luồng xử lý                                                                                                                                  |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền quản lý người dùng                         | Hệ thống từ chối truy cập chức năng và không trả dữ liệu quản trị người dùng.                                                                |
| Người dùng cần quản lý không tồn tại                                    | Hệ thống thông báo không tìm thấy người dùng.                                                                                                |
| Thông tin cập nhật không hợp lệ                                         | Hệ thống không lưu dữ liệu và yêu cầu quản trị viên chỉnh sửa.                                                                               |
| Email công ty được quản lý bởi hệ thống danh tính doanh nghiệp          | Hệ thống không cho phép Admin thay đổi email trực tiếp tại Enterprise RAG hoặc chỉ cho phép thay đổi thông qua cơ chế đồng bộ được quy định. |
| Quản trị viên cố thay đổi mật khẩu công ty của người dùng               | Hệ thống không cho phép thực hiện vì mật khẩu thuộc hệ thống quản lý danh tính của công ty.                                                  |
| Quản trị viên gán một Role không tồn tại                                | Hệ thống từ chối thay đổi.                                                                                                                   |
| Quản trị viên gán người dùng vào Group không tồn tại                    | Hệ thống từ chối thay đổi.                                                                                                                   |
| Quản trị viên gán người dùng vào Department không tồn tại               | Hệ thống từ chối thay đổi.                                                                                                                   |
| Quản trị viên không có quyền gán Role quản trị                          | Hệ thống từ chối việc nâng quyền người dùng.                                                                                                 |
| Tài khoản đang `DISABLED` được kích hoạt lại                            | Hệ thống kiểm tra các điều kiện cần thiết trước khi chuyển về `ACTIVE`.                                                                      |
| Quản trị viên vô hiệu hóa một tài khoản đang đăng nhập                  | Hệ thống cập nhật trạng thái tài khoản; các request tiếp theo của người dùng bị từ chối theo chính sách xác thực.                            |
| User bị loại khỏi Group                                                 | Hệ thống tính lại các quyền mà User đang được kế thừa từ Group đó.                                                                           |
| User chuyển Department                                                  | Hệ thống tính lại các quyền được kế thừa từ Department.                                                                                      |
| User bị gỡ một Role                                                     | Hệ thống tính lại các quyền chức năng hoặc quyền liên quan đến Role đó.                                                                      |
| Người dùng vẫn có quyền từ nguồn khác sau khi bị gỡ khỏi một Group/Role | Hệ thống vẫn giữ effective permission nếu quyền đó còn được cấp từ nguồn hợp lệ khác.                                                        |
| Hai Admin đồng thời cập nhật cùng một người dùng                        | Hệ thống phát hiện xung đột và không âm thầm ghi đè dữ liệu mới hơn.                                                                         |
| Dịch vụ quản lý người dùng không khả dụng                               | Hệ thống trả lỗi có kiểm soát và không lưu thay đổi một phần.                                                                                |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                       |
| --------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền quản lý người dùng mới được truy cập Use Case này.                                                                 |
| Người dùng phải có một định danh duy nhất trong Enterprise RAG Platform.                                                                      |
| Một tài khoản công ty không được ánh xạ tới nhiều tài khoản Enterprise RAG khác nhau nếu chính sách xác định quan hệ một-một.                 |
| Email và mật khẩu do công ty cấp không được Admin xem dưới dạng plaintext.                                                                    |
| Enterprise RAG không được cho phép Admin thay đổi trực tiếp mật khẩu công ty nếu credential được quản lý bởi hệ thống danh tính doanh nghiệp. |
| Trạng thái tài khoản phải được quản lý độc lập với Role, Group và Department.                                                                 |
| Chỉ tài khoản ở trạng thái được phép, ví dụ `ACTIVE`, mới được sử dụng hệ thống.                                                              |
| Người dùng không được tự gán Role, Group hoặc Department cho chính mình thông qua chức năng người dùng thông thường.                          |
| Việc gán Role `ADMIN` phải yêu cầu quyền quản trị phù hợp.                                                                                    |
| Một người dùng có thể thuộc nhiều Group nếu nghiệp vụ hệ thống cho phép.                                                                      |
| Một người dùng có thể có một hoặc nhiều Role tùy mô hình phân quyền được lựa chọn.                                                            |
| Quan hệ của người dùng với Department phải tuân theo mô hình tổ chức của doanh nghiệp.                                                        |
| Thay đổi Role, Group hoặc Department có thể làm thay đổi quyền truy cập tài liệu của người dùng.                                              |
| Sau khi Role, Group hoặc Department thay đổi, hệ thống phải sử dụng dữ liệu quyền mới cho các request tiếp theo.                              |
| Hệ thống không được chỉ dựa vào thông tin quyền đã lưu lâu trong token nếu Role, Group hoặc Department hiện tại đã thay đổi.                  |
| Vô hiệu hóa người dùng phải làm người dùng không còn được phép truy cập các chức năng bảo vệ của hệ thống.                                    |
| Vô hiệu hóa người dùng không được xóa lịch sử câu hỏi, feedback, audit hoặc các dữ liệu nghiệp vụ cần lưu giữ.                                |
| Xóa người dùng vật lý không nên là thao tác mặc định đối với tài khoản đã từng hoạt động trong hệ thống.                                      |
| Nếu tài khoản không còn được sử dụng, nên chuyển trạng thái sang `DISABLED` thay vì hard-delete nếu cần bảo toàn audit.                       |
| Quyền hiệu lực của User phải được tính từ các nguồn quyền hiện tại như Role, Group, Department và quyền cấp trực tiếp nếu hệ thống hỗ trợ.    |
| Việc gỡ một quyền gián tiếp không có nghĩa người dùng chắc chắn mất quyền nếu vẫn nhận quyền tương tự từ một nguồn khác.                      |
| Các thay đổi liên quan đến người dùng, Role, Group, Department và trạng thái tài khoản phải có khả năng truy vết.                             |
| Hệ thống phải ghi nhận Admin thực hiện thay đổi, thời điểm thay đổi và loại thay đổi.                                                         |
| Admin không được thực hiện thay đổi vượt quá phạm vi quản trị được cấp cho chính Admin đó.                                                    |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                            |
| ------------------------------------------------------------------------------------------------------------------------ |
| Quản trị viên có quyền có thể truy cập chức năng **Quản lý người dùng**.                                                 |
| Người dùng không có quyền quản trị không thể truy cập chức năng quản lý người dùng.                                      |
| Hệ thống hiển thị đúng danh sách người dùng thuộc phạm vi quản trị viên được phép quản lý.                               |
| Quản trị viên có thể xem thông tin chi tiết của một người dùng.                                                          |
| Hệ thống hiển thị đúng trạng thái tài khoản hiện tại.                                                                    |
| Hệ thống hiển thị đúng Role hiện tại của người dùng.                                                                     |
| Hệ thống hiển thị đúng các Group mà người dùng đang tham gia.                                                            |
| Hệ thống hiển thị đúng Department của người dùng.                                                                        |
| Quản trị viên có quyền có thể kích hoạt hoặc vô hiệu hóa tài khoản theo policy.                                          |
| Tài khoản `DISABLED` không thể tiếp tục sử dụng các API hoặc tài nguyên yêu cầu xác thực.                                |
| Việc vô hiệu hóa người dùng không xóa dữ liệu lịch sử và Audit Log của người dùng.                                       |
| Quản trị viên không thể xem mật khẩu công ty của người dùng.                                                             |
| Quản trị viên không thể chỉnh sửa trực tiếp mật khẩu công ty trong Enterprise RAG nếu credential được quản lý tập trung. |
| Người dùng không thể tự gán Role `ADMIN`.                                                                                |
| Quản trị viên không có quyền nâng cấp Role không thể gán Role `ADMIN` cho người khác.                                    |
| Khi User được thêm vào Group, các quyền kế thừa từ Group được áp dụng đúng.                                              |
| Khi User bị loại khỏi Group, quyền chỉ được kế thừa từ Group đó không còn hiệu lực.                                      |
| Khi User chuyển Department, effective permission được tính lại theo Department mới.                                      |
| Khi Role của User thay đổi, quyền chức năng được áp dụng lại theo Role mới.                                              |
| Nếu User còn nhận cùng một quyền từ nguồn khác, hệ thống phải giữ effective permission tương ứng.                        |
| Các thay đổi trạng thái, Role, Group hoặc Department được ghi nhận trong Audit Log.                                      |
| Khi hai Admin cập nhật đồng thời gây xung đột, hệ thống không âm thầm ghi đè dữ liệu mới hơn.                            |
| Khi cập nhật thất bại, dữ liệu người dùng trước đó được giữ nguyên.                                                      |

### Dữ liệu liên quan

| Dữ liệu           | Mục đích                                                                    |
| ----------------- | --------------------------------------------------------------------------- |
| `user_id`         | Định danh duy nhất của người dùng trong Enterprise RAG Platform.            |
| `company_user_id` | Định danh tương ứng của người dùng trong hệ thống tài khoản công ty nếu có. |
| `full_name`       | Họ tên hiển thị của người dùng.                                             |
| `company_email`   | Email do công ty cấp, dùng để xác định danh tính người dùng.                |
| `account_status`  | Trạng thái tài khoản như `ACTIVE`, `LOCKED`, `DISABLED`.                    |
| `roles`           | Các Role hiện tại của người dùng.                                           |
| `groups`          | Các Group người dùng đang tham gia.                                         |
| `department_id`   | Phòng ban hiện tại của người dùng.                                          |
| `created_at`      | Thời điểm tài khoản được tạo hoặc ghi nhận trong hệ thống.                  |
| `updated_at`      | Thời điểm thông tin người dùng được cập nhật gần nhất.                      |
| `updated_by`      | Admin thực hiện cập nhật gần nhất.                                          |
| `last_login_at`   | Thời điểm đăng nhập gần nhất nếu hệ thống cần quản trị thông tin này.       |

### Ghi chú thiết kế

Với mô hình bạn đã xác định trước đó, nhân viên sử dụng:

```text
Email công ty
+
Mật khẩu công ty
```

để xác thực.

Do đó cần phân biệt:

```text
HỆ THỐNG TÀI KHOẢN CÔNG TY
──────────────────────────
Email
Password
Company User Identity
```

với:

```text
ENTERPRISE RAG
──────────────────────────
user_id
company_user_id
account_status
roles
groups
department
permissions
```

Enterprise RAG không nên cho Admin quản lý:

```text
Password công ty
```

mà chỉ quản lý:

```text
Thông tin người dùng trong RAG
+
Trạng thái sử dụng RAG
+
Role
+
Group
+
Department
+
Permission
```

Luồng khái quát:

```text
             Tài khoản công ty
                    │
                    │ identity
                    ↓
            Enterprise RAG User
                    │
        ┌───────────┼───────────┐
        ↓           ↓           ↓
      Role        Group     Department
        │           │           │
        └───────────┼───────────┘
                    ↓
           Effective Permission
                    ↓
            Truy cập tài liệu
```

### Phân biệt trạng thái tài khoản và quyền

Ví dụ:

```text
User A

account_status = ACTIVE
role = EMPLOYEE
department = HR
group = HR_MANAGER
```

`ACTIVE` chỉ có nghĩa:

> Tài khoản này được phép sử dụng hệ thống.

Nó **không có nghĩa**:

> Tài khoản này được đọc toàn bộ tài liệu.

Quyền tài liệu vẫn phải được tính riêng:

```text
User
 +
Role
 +
Group
 +
Department
 +
Direct Permission (nếu có)
        ↓
Effective Permission
        ↓
Document Access
```

Ví dụ:

```text
User A
│
├── Department HR
│      └── READ → HR Policies
│
├── Group HR_MANAGER
│      └── READ → Manager Reports
│
└── Direct Permission
       └── READ → DOC-100
```

Effective permission của User A là kết quả tổng hợp từ các nguồn được policy cho phép.

### Khi Admin vô hiệu hóa User

Ví dụ:

```text
User A
status = ACTIVE
```

Admin thực hiện:

```text
Vô hiệu hóa tài khoản
```

sau đó:

```text
User A
status = DISABLED
```

Request mới:

```text
User A
  ↓
Authentication / Authorization
  ↓
account_status == ACTIVE?
  ↓
NO
  ↓
DENY
```

User không còn được:

```text
Đặt câu hỏi
Xem tài liệu nguồn
Tải tài liệu
Sử dụng tài nguyên được bảo vệ
```

nhưng hệ thống vẫn giữ:

```text
Conversation history
Feedback
Reports
Audit events
Permission history
```

nếu chính sách lưu trữ yêu cầu.

### Khi Admin thay đổi Group

Ví dụ ban đầu:

```text
User A
   │
   └── Group HR
          └── READ DOC-001
```

Admin loại User A khỏi Group HR:

```text
User A
   X
Group HR
```

Hệ thống phải tính lại quyền.

Nếu User A không còn nguồn quyền nào khác:

```text
Effective READ DOC-001
        ↓
      FALSE
```

thì request tiếp theo:

```text
Search / RAG retrieval
        ↓
DOC-001 bị loại
```

Nhưng nếu User A vẫn có:

```text
Direct READ DOC-001
```

thì:

```text
Remove from HR Group
       ≠
Lose DOC-001 access
```

vì quyền trực tiếp vẫn tồn tại.

Đó là lý do hệ thống cần phân biệt:

```text
Permission Assignment
```

và:

```text
Effective Permission
```

### Quan hệ với các Use Case phân quyền

Use Case **Quản lý người dùng** không nên chứa toàn bộ logic phân quyền.

Ranh giới nên là:

```text
QUẢN LÝ NGƯỜI DÙNG
──────────────────
Thông tin User
Account Status
Role assignment
Group membership
Department membership
```

trong khi:

```text
THIẾT LẬP QUYỀN TRUY CẬP TÀI LIỆU
─────────────────────────────────
Ai?
      ↓
được làm gì?
      ↓
trên tài liệu nào?
```

Ví dụ:

```text
User A
    ↓
thuộc
    ↓
Department HR
```

là quản lý người dùng/phòng ban.

Còn:

```text
Department HR
     ↓
READ
     ↓
DOC-001
```

là quản lý quyền truy cập tài liệu.

Không nên trộn hai nghiệp vụ này.

### Luồng tổng thể của Use Case

```text
Admin
  ↓
Quản lý người dùng
  ↓
Chọn User
  ↓
Xem thông tin
  ↓
┌──────────────────────────────────────┐
│ Cập nhật thông tin                   │
│ Kích hoạt / vô hiệu hóa              │
│ Gán Role                             │
│ Gán Group                            │
│ Gán Department                       │
└──────────────────────────────────────┘
  ↓
Validate
  ↓
Lưu thay đổi
  ↓
Tính lại effective permission nếu cần
  ↓
Audit
  ↓
Áp dụng cho request tiếp theo
```

Nguyên tắc quan trọng:

```text
QUẢN LÝ USER
     ≠
QUẢN LÝ PASSWORD CÔNG TY
```

và:

```text
USER ACTIVE
     ≠
USER CÓ QUYỀN ĐỌC MỌI TÀI LIỆU
```

`ACTIVE` quyết định người dùng có được **sử dụng hệ thống**, còn việc đọc được tài liệu nào phải được quyết định bởi **Authorization / Access Policy**.

### Use case quản lý vai trò

| Thuộc tính                  | Mô tả                                                                                                                                                 |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**            | Quản lý vai trò                                                                                                                                       |
| **Actor chính**             | Quản trị viên                                                                                                                                         |
| **Mục tiêu**                | Cho phép quản trị viên tạo, xem, cập nhật và quản lý các vai trò trong hệ thống nhằm kiểm soát tập quyền chức năng mà người dùng được phép thực hiện. |
| **Điều kiện kích hoạt**     | Quản trị viên truy cập chức năng **Quản lý vai trò**.                                                                                                 |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản quản trị viên đang hoạt động.<br>3. Quản trị viên có quyền quản lý vai trò và phân quyền chức năng.    |
| **Đầu vào**                 | Tên vai trò, mô tả vai trò, danh sách quyền chức năng và các thuộc tính quản trị khác nếu có.                                                         |
| **Trạng thái — Thành công** | Vai trò được tạo mới hoặc cập nhật thành công; các thay đổi quyền của vai trò được áp dụng theo chính sách hệ thống và được ghi nhận phục vụ audit.   |
| **Trạng thái — Thất bại**   | Không tạo hoặc cập nhật vai trò; dữ liệu hiện tại được giữ nguyên và hệ thống thông báo nguyên nhân lỗi.                                              |
| **Use Cases liên quan**     | Quản lý người dùng, Quản lý nhóm, Quản lý phòng ban, Thiết lập quyền truy cập tài liệu, Xem ma trận quyền, Kiểm tra quyền truy cập                    |

### Main Flow

| Bước | Actor         | Hành động                                                                                |
| ---: | ------------- | ---------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Truy cập chức năng **Quản lý vai trò**.                                                  |
|    2 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                              |
|    3 | System        | Kiểm tra quyền quản lý vai trò của quản trị viên.                                        |
|    4 | System        | Hiển thị danh sách các vai trò hiện có trong hệ thống.                                   |
|    5 | Quản trị viên | Chọn một vai trò để xem/chỉnh sửa hoặc chọn tạo vai trò mới.                             |
|    6 | System        | Hiển thị thông tin của vai trò và các quyền chức năng hiện tại.                          |
|    7 | Quản trị viên | Nhập hoặc cập nhật tên vai trò, mô tả và tập quyền được gán cho vai trò.                 |
|    8 | System        | Kiểm tra tính hợp lệ của thông tin vai trò.                                              |
|    9 | System        | Kiểm tra tên hoặc định danh vai trò có bị trùng hay không.                               |
|   10 | System        | Kiểm tra quản trị viên có được phép cấp các quyền đã chọn hay không.                     |
|   11 | System        | Xác định các User đang sử dụng vai trò và ảnh hưởng của thay đổi nếu cần.                |
|   12 | Quản trị viên | Xác nhận thay đổi.                                                                       |
|   13 | System        | Tạo mới hoặc cập nhật vai trò.                                                           |
|   14 | System        | Cập nhật tập quyền chức năng liên kết với vai trò.                                       |
|   15 | System        | Áp dụng lại quyền hiệu lực cho những người dùng chịu ảnh hưởng theo chính sách hệ thống. |
|   16 | System        | Ghi nhận người thực hiện, thời điểm và nội dung thay đổi vào Audit Log.                  |
|   17 | System        | Thông báo thao tác thành công.                                                           |
|   18 | System        | Hiển thị lại thông tin vai trò mới nhất.                                                 |

### Thông tin vai trò được quản lý

| Thông tin                     | Ý nghĩa                                                                      |
| ----------------------------- | ---------------------------------------------------------------------------- |
| **Tên vai trò**               | Tên nghiệp vụ dùng để nhận biết vai trò, ví dụ `EMPLOYEE`, `ADMIN`.          |
| **Mô tả**                     | Giải thích phạm vi trách nhiệm hoặc mục đích của vai trò.                    |
| **Trạng thái**                | Xác định vai trò còn được sử dụng hay đã bị vô hiệu hóa nếu hệ thống hỗ trợ. |
| **Danh sách quyền chức năng** | Các hành động mà người dùng có vai trò được phép thực hiện.                  |
| **Số lượng người dùng**       | Số người dùng hiện đang được gán vai trò.                                    |
| **Thời điểm tạo**             | Thời điểm vai trò được tạo trong hệ thống.                                   |
| **Thời điểm cập nhật**        | Thời điểm vai trò được thay đổi gần nhất.                                    |

### Ví dụ quyền chức năng của Role

| Quyền                  | Mục đích                                                        |
| ---------------------- | --------------------------------------------------------------- |
| `ASK_KNOWLEDGE`        | Cho phép sử dụng chức năng hỏi đáp tri thức.                    |
| `VIEW_SOURCE`          | Cho phép mở tài liệu nguồn khi có quyền đọc tài liệu tương ứng. |
| `MANAGE_DOCUMENT`      | Cho phép quản lý tài liệu.                                      |
| `UPLOAD_DOCUMENT`      | Cho phép upload tài liệu.                                       |
| `REVIEW_DOCUMENT`      | Cho phép kiểm duyệt phiên bản tài liệu.                         |
| `PUBLISH_DOCUMENT`     | Cho phép phê duyệt/xuất bản tài liệu.                           |
| `MANAGE_USER`          | Cho phép quản lý người dùng.                                    |
| `MANAGE_ROLE`          | Cho phép quản lý vai trò.                                       |
| `MANAGE_GROUP`         | Cho phép quản lý nhóm.                                          |
| `MANAGE_DEPARTMENT`    | Cho phép quản lý phòng ban.                                     |
| `MANAGE_ACCESS_POLICY` | Cho phép thiết lập quyền truy cập tài liệu.                     |
| `VIEW_AUDIT_LOG`       | Cho phép xem Audit Log.                                         |

### Các thao tác quản lý vai trò

| Thao tác                  | Mô tả                                                              |
| ------------------------- | ------------------------------------------------------------------ |
| **Xem danh sách vai trò** | Xem các Role hiện đang tồn tại trong hệ thống.                     |
| **Xem chi tiết vai trò**  | Xem thông tin và tập quyền của một Role.                           |
| **Tạo vai trò**           | Tạo Role mới theo nhu cầu nghiệp vụ.                               |
| **Cập nhật vai trò**      | Thay đổi tên, mô tả hoặc tập quyền của Role.                       |
| **Vô hiệu hóa vai trò**   | Ngừng sử dụng Role mà vẫn giữ dữ liệu lịch sử nếu hệ thống hỗ trợ. |
| **Xóa vai trò**           | Chỉ thực hiện khi Role không còn được sử dụng và policy cho phép.  |

### Luồng thay thế / luồng ngoại lệ

| Điều kiện                                                           | Luồng xử lý                                                                          |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Quản trị viên không có quyền quản lý vai trò                        | Hệ thống từ chối truy cập chức năng.                                                 |
| Vai trò cần chỉnh sửa không tồn tại                                 | Hệ thống thông báo không tìm thấy vai trò.                                           |
| Tên vai trò bị trùng                                                | Hệ thống không tạo Role mới và yêu cầu chọn tên hoặc định danh khác.                 |
| Tên hoặc dữ liệu vai trò không hợp lệ                               | Hệ thống không lưu và yêu cầu quản trị viên chỉnh sửa.                               |
| Quản trị viên cố gán quyền mà bản thân không được phép quản lý      | Hệ thống từ chối thay đổi.                                                           |
| Vai trò đang được nhiều User sử dụng                                | Hệ thống hiển thị cảnh báo về phạm vi ảnh hưởng trước khi cập nhật quyền quan trọng. |
| Quản trị viên muốn xóa Role đang được User sử dụng                  | Hệ thống từ chối hoặc yêu cầu gỡ Role khỏi các User trước, tùy policy.               |
| Vai trò hệ thống không được phép xóa                                | Hệ thống chặn thao tác xóa.                                                          |
| Quản trị viên loại bỏ quyền quản trị quan trọng khỏi Role đang dùng | Hệ thống hiển thị cảnh báo về tác động trước khi xác nhận.                           |
| Thao tác có nguy cơ làm hệ thống không còn Admin hợp lệ             | Hệ thống từ chối thao tác theo policy bảo vệ quản trị.                               |
| Hai Admin cùng cập nhật một Role                                    | Hệ thống phát hiện conflict và không âm thầm ghi đè dữ liệu mới hơn.                 |
| Lưu thay đổi thất bại                                               | Hệ thống rollback và giữ nguyên cấu hình Role trước đó.                              |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                         |
| ------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền `MANAGE_ROLE` hoặc quyền tương đương mới được quản lý Role.                                          |
| Mỗi Role phải có định danh duy nhất trong hệ thống.                                                                             |
| Role được sử dụng chủ yếu để xác định **quyền chức năng** của người dùng.                                                       |
| Role không nên là nguồn duy nhất quyết định người dùng được đọc tài liệu nào.                                                   |
| Quyền đọc tài liệu cụ thể vẫn phải được xác định bởi Access Policy, Group, Department hoặc các Permission Assignment tương ứng. |
| Một User có thể có một hoặc nhiều Role nếu mô hình phân quyền của hệ thống cho phép.                                            |
| Employee không được tự gán hoặc thay đổi Role cho chính mình.                                                                   |
| Chỉ Admin có quyền phù hợp mới được gán Role có đặc quyền quản trị.                                                             |
| Hệ thống phải ngăn việc tạo nhiều Role có cùng định danh nghiệp vụ nếu policy yêu cầu duy nhất.                                 |
| Role hệ thống quan trọng như `ADMIN` hoặc `EMPLOYEE` có thể được bảo vệ khỏi việc xóa tùy policy.                               |
| Không được xóa một Role đang được sử dụng nếu việc xóa làm dữ liệu User hoặc Permission trở nên không nhất quán.                |
| Nếu cần ngừng sử dụng Role, nên ưu tiên `DISABLED` hoặc trạng thái tương đương thay vì hard-delete nếu cần bảo toàn audit.      |
| Khi quyền của Role thay đổi, effective permission của các User có Role đó phải được tính lại.                                   |
| Thay đổi quyền của Role phải có hiệu lực theo policy đối với các request sau.                                                   |
| Hệ thống không nên chỉ dựa vào quyền đã cache lâu trong token nếu cấu hình Role đã thay đổi.                                    |
| Admin không được cấp cho Role các quyền vượt ngoài phạm vi quyền mà Admin được phép quản lý.                                    |
| Hệ thống phải đảm bảo luôn còn ít nhất một đường quản trị hợp lệ, tránh trường hợp tự khóa toàn bộ Admin khỏi hệ thống.         |
| Tất cả thao tác tạo, cập nhật, vô hiệu hóa hoặc xóa Role phải được ghi Audit Log.                                               |
| Audit phải ghi được Role nào bị thay đổi, quyền nào được thêm/bớt, ai thực hiện và thời điểm thực hiện.                         |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                |
| -------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể truy cập chức năng **Quản lý vai trò**.                        |
| Người không có quyền không thể truy cập chức năng quản lý Role.                              |
| Hệ thống hiển thị đúng danh sách các Role hiện có.                                           |
| Quản trị viên có thể xem tập quyền hiện tại của từng Role.                                   |
| Quản trị viên có thể tạo Role mới với dữ liệu hợp lệ.                                        |
| Không thể tạo hai Role có cùng định danh khi policy yêu cầu duy nhất.                        |
| Quản trị viên có thể thêm hoặc loại bỏ quyền chức năng khỏi Role trong phạm vi được phép.    |
| Quản trị viên không thể gán một quyền không tồn tại.                                         |
| Quản trị viên không thể cấp quyền vượt ngoài phạm vi quản trị của mình.                      |
| Khi tập quyền của Role thay đổi, User có Role đó nhận đúng effective permission mới.         |
| Khi quyền bị loại khỏi Role, User không còn nhận quyền từ Role đó ở các request tiếp theo.   |
| Nếu User còn nhận cùng quyền từ nguồn khác, hệ thống vẫn phản ánh đúng effective permission. |
| Role hệ thống được bảo vệ không thể bị xóa trái policy.                                      |
| Role đang được User sử dụng không bị xóa nếu việc xóa gây trạng thái không nhất quán.        |
| Hệ thống không cho phép thao tác làm mất toàn bộ quyền quản trị cần thiết của tất cả Admin.  |
| Thay đổi Role được ghi vào Audit Log.                                                        |
| Audit Log ghi đúng quản trị viên, thời gian và nội dung thay đổi.                            |
| Khi cập nhật thất bại, cấu hình Role trước đó vẫn được giữ nguyên.                           |
| Khi hai Admin cập nhật đồng thời, hệ thống không âm thầm ghi đè thay đổi mới hơn.            |

### Dữ liệu liên quan

| Dữ liệu       | Mục đích                                                   |
| ------------- | ---------------------------------------------------------- |
| `role_id`     | Định danh duy nhất của vai trò.                            |
| `role_code`   | Mã vai trò dùng trong hệ thống, ví dụ `EMPLOYEE`, `ADMIN`. |
| `role_name`   | Tên hiển thị của vai trò.                                  |
| `description` | Mô tả mục đích và phạm vi của vai trò.                     |
| `role_status` | Trạng thái sử dụng của Role nếu hệ thống hỗ trợ.           |
| `permissions` | Danh sách quyền chức năng liên kết với Role.               |
| `created_by`  | Admin tạo Role.                                            |
| `created_at`  | Thời điểm Role được tạo.                                   |
| `updated_by`  | Admin cập nhật Role gần nhất.                              |
| `updated_at`  | Thời điểm Role được cập nhật gần nhất.                     |

### Ghi chú thiết kế

Điểm quan trọng nhất là phân biệt:

```text
ROLE
```

và:

```text
DOCUMENT ACCESS
```

Role trả lời câu hỏi:

```text
"Người dùng được phép làm chức năng gì trong hệ thống?"
```

Ví dụ:

```text
Role EMPLOYEE
│
├── ASK_KNOWLEDGE
├── VIEW_SOURCE
└── SUBMIT_FEEDBACK
```

Trong khi:

```text
Role ADMIN
│
├── MANAGE_DOCUMENT
├── REVIEW_DOCUMENT
├── PUBLISH_DOCUMENT
├── MANAGE_USER
├── MANAGE_ROLE
└── MANAGE_ACCESS_POLICY
```

Nhưng việc một `EMPLOYEE` có quyền đọc:

```text
DOC-001
```

hay không không nên chỉ được quyết định bằng:

```text
role = EMPLOYEE
```

mà cần:

```text
User
 +
Role
 +
Group
 +
Department
 +
Direct Permission / Access Policy
        ↓
Effective Permission
        ↓
Document Access
```

Ví dụ:

```text
User A
Role = EMPLOYEE
Department = HR
```

Role cho phép:

```text
ASK_KNOWLEDGE = YES
```

nhưng tài liệu:

```text
DOC-001
"Quy định tài chính nội bộ"
```

chỉ cho:

```text
Department = Finance
READ
```

thì User A vẫn:

```text
DENY DOC-001
```

Tức là:

```text
Role cho phép sử dụng chức năng hỏi đáp
```

không đồng nghĩa:

```text
Role cho phép truy cập mọi tri thức.
```

---

### Gán Role cho User

Có thể hình dung quan hệ:

```text
User
 │
 └── UserRole
       │
       └── Role
              │
              └── RolePermission
                       │
                       └── Permission
```

Ví dụ:

```text
User A
   ↓
EMPLOYEE
   ↓
ASK_KNOWLEDGE
VIEW_SOURCE
```

User B:

```text
User B
   ↓
ADMIN
   ↓
MANAGE_DOCUMENT
MANAGE_USER
MANAGE_ROLE
```

Nếu sau này một User có nhiều Role:

```text
User C
├── EMPLOYEE
└── DOCUMENT_REVIEWER
```

thì quyền chức năng có thể được tổng hợp:

```text
EMPLOYEE
├── ASK_KNOWLEDGE
└── VIEW_SOURCE

DOCUMENT_REVIEWER
└── REVIEW_DOCUMENT
```

Effective functional permissions:

```text
ASK_KNOWLEDGE
VIEW_SOURCE
REVIEW_DOCUMENT
```

---

### Khi Role bị thay đổi quyền

Ví dụ ban đầu:

```text
DOCUMENT_REVIEWER

Permissions:
- REVIEW_DOCUMENT
- PUBLISH_DOCUMENT
```

Admin sửa thành:

```text
DOCUMENT_REVIEWER

Permissions:
- REVIEW_DOCUMENT
```

thì tất cả User chỉ nhận `PUBLISH_DOCUMENT` từ Role này phải mất quyền publish ở các request tiếp theo.

Nhưng nếu User A còn có:

```text
Role = KNOWLEDGE_ADMIN
→ PUBLISH_DOCUMENT
```

thì User A vẫn có quyền Publish.

Vì vậy:

```text
Remove Permission From Role
          ≠
User chắc chắn mất Permission
```

Hệ thống phải tính:

```text
Effective Permissions
=
Union / Policy evaluation
của toàn bộ nguồn quyền hợp lệ
```

---

### Không nên hard-code

Không nên viết logic kiểu:

```text
if user.role == "admin":
    allow_everything()
```

vì sau này rất khó mở rộng.

Nên theo hướng:

```text
User
 ↓
Roles
 ↓
Permissions
 ↓
Authorization Check
```

Ví dụ:

```text
Can user publish document?

User
 ↓
Effective permissions
 ↓
contains PUBLISH_DOCUMENT?
 ↓
YES / NO
```

Sau đó vẫn kiểm tra thêm tài nguyên nếu nghiệp vụ yêu cầu.

---

### Quan hệ với Access Policy

Hai tầng có thể hiểu:

```text
TẦNG 1 — FUNCTION AUTHORIZATION

"User có được gọi chức năng này không?"

Role / Permission
```

và:

```text
TẦNG 2 — RESOURCE AUTHORIZATION

"User có được thao tác với Document này không?"

Access Policy
Group
Department
Direct Permission
Resource Scope
```

Ví dụ:

```text
User A
Role = ADMIN

MANAGE_DOCUMENT = YES
```

nhưng nếu hệ thống sau này hỗ trợ Admin theo phạm vi:

```text
Admin A
chỉ quản lý Department HR
```

thì:

```text
MANAGE_DOCUMENT = YES
```

vẫn chưa đủ để quản lý:

```text
Finance Documents
```

Cần:

```text
Functional Permission
        +
Resource Scope
        ↓
ALLOW / DENY
```

---

### Luồng tổng thể

```text
Admin
  ↓
Quản lý vai trò
  ↓
Chọn / tạo Role
  ↓
Cấu hình tập quyền
  ↓
Validate
  ↓
Kiểm tra phạm vi ảnh hưởng
  ↓
Xác nhận
  ↓
Lưu Role + Permissions
  ↓
Tính lại effective permissions
  ↓
Audit
  ↓
Áp dụng cho request tiếp theo
```

Nguyên tắc cần giữ:

```text
ROLE
=
Nhóm quyền chức năng
```

không phải:

```text
ROLE
=
Danh sách tất cả tài liệu User được đọc
```

Phần tài liệu cụ thể vẫn nên được quản lý ở **Thiết lập quyền truy cập tài liệu**.

### Use case quản lý nhóm

| Thuộc tính                  | Mô tả                                                                                                                                                                                                                |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**            | Quản lý nhóm                                                                                                                                                                                                         |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                                        |
| **Mục tiêu**                | Cho phép quản trị viên tạo, xem, cập nhật và quản lý các nhóm người dùng trong hệ thống nhằm hỗ trợ tổ chức người dùng và cấp quyền truy cập tài liệu theo nhóm thay vì phải cấu hình riêng cho từng người dùng.     |
| **Điều kiện kích hoạt**     | Quản trị viên truy cập chức năng **Quản lý nhóm**.                                                                                                                                                                   |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản quản trị viên đang hoạt động.<br>3. Quản trị viên có quyền quản lý nhóm.<br>4. Các người dùng được thêm vào nhóm phải tồn tại và có trạng thái hợp lệ trong hệ thống. |
| **Đầu vào**                 | Tên nhóm, mã nhóm, mô tả nhóm, danh sách thành viên và các thông tin quản trị khác nếu có.                                                                                                                           |
| **Trạng thái — Thành công** | Nhóm được tạo hoặc cập nhật thành công; membership của người dùng được cập nhật; các quyền mà người dùng kế thừa từ nhóm được tính lại theo chính sách hiện hành; thay đổi được ghi nhận phục vụ audit.              |
| **Trạng thái — Thất bại**   | Nhóm hoặc membership không bị thay đổi; hệ thống thông báo nguyên nhân lỗi và không để dữ liệu ở trạng thái không nhất quán.                                                                                         |
| **Use Cases liên quan**     | Quản lý người dùng, Quản lý vai trò, Quản lý phòng ban, Thiết lập quyền truy cập tài liệu, Cấp quyền, Thu hồi quyền, Xem ma trận quyền, Kiểm tra quyền truy cập                                                      |

### Main Flow

| Bước | Actor         | Hành động                                                                                                       |
| ---: | ------------- | --------------------------------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Truy cập chức năng **Quản lý nhóm**.                                                                            |
|    2 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                                                     |
|    3 | System        | Kiểm tra quyền quản lý nhóm của quản trị viên.                                                                  |
|    4 | System        | Hiển thị danh sách các nhóm hiện có trong hệ thống.                                                             |
|    5 | Quản trị viên | Chọn một nhóm để xem/chỉnh sửa hoặc chọn tạo nhóm mới.                                                          |
|    6 | System        | Hiển thị thông tin nhóm và danh sách thành viên hiện tại nếu nhóm đã tồn tại.                                   |
|    7 | Quản trị viên | Nhập hoặc cập nhật tên nhóm, mã nhóm, mô tả và các thông tin được phép thay đổi.                                |
|    8 | Quản trị viên | Thêm hoặc loại bỏ người dùng khỏi nhóm nếu cần.                                                                 |
|    9 | System        | Kiểm tra tính hợp lệ của thông tin nhóm.                                                                        |
|   10 | System        | Kiểm tra nhóm có bị trùng định danh với nhóm khác hay không.                                                    |
|   11 | System        | Kiểm tra các người dùng được thêm vào nhóm có tồn tại và hợp lệ hay không.                                      |
|   12 | System        | Xác định ảnh hưởng của việc thay đổi membership tới quyền truy cập của các người dùng liên quan.                |
|   13 | Quản trị viên | Xác nhận thay đổi.                                                                                              |
|   14 | System        | Tạo mới hoặc cập nhật thông tin nhóm.                                                                           |
|   15 | System        | Cập nhật danh sách thành viên của nhóm.                                                                         |
|   16 | System        | Tính lại effective permission của các người dùng chịu ảnh hưởng nếu nhóm đang được sử dụng trong Access Policy. |
|   17 | System        | Ghi nhận người thực hiện, thời điểm và nội dung thay đổi vào Audit Log.                                         |
|   18 | System        | Thông báo thao tác thành công.                                                                                  |
|   19 | System        | Hiển thị lại thông tin nhóm và danh sách thành viên mới nhất.                                                   |

### Thông tin nhóm được quản lý

| Thông tin               | Ý nghĩa                                                                         |
| ----------------------- | ------------------------------------------------------------------------------- |
| **Tên nhóm**            | Tên hiển thị của nhóm, ví dụ `HR_MANAGER`, `PROJECT_ALPHA`, `FINANCE_REVIEWER`. |
| **Mã nhóm**             | Định danh nghiệp vụ duy nhất của nhóm nếu hệ thống sử dụng.                     |
| **Mô tả**               | Giải thích mục đích hoặc phạm vi sử dụng của nhóm.                              |
| **Trạng thái nhóm**     | Xác định nhóm đang hoạt động hay đã bị vô hiệu hóa nếu hệ thống hỗ trợ.         |
| **Thành viên**          | Danh sách người dùng hiện thuộc nhóm.                                           |
| **Số lượng thành viên** | Tổng số người dùng đang tham gia nhóm.                                          |
| **Quyền liên quan**     | Các Access Policy hoặc Permission Assignment đang áp dụng cho nhóm nếu có.      |
| **Thời điểm tạo**       | Thời điểm nhóm được tạo.                                                        |
| **Thời điểm cập nhật**  | Thời điểm nhóm được thay đổi gần nhất.                                          |

### Các thao tác quản lý nhóm

| Thao tác               | Mô tả                                                                          |
| ---------------------- | ------------------------------------------------------------------------------ |
| **Xem danh sách nhóm** | Xem các nhóm đang tồn tại trong hệ thống.                                      |
| **Xem chi tiết nhóm**  | Xem thông tin nhóm, thành viên và các quyền liên quan.                         |
| **Tạo nhóm**           | Tạo một nhóm người dùng mới.                                                   |
| **Cập nhật nhóm**      | Thay đổi tên, mô tả hoặc các thông tin được phép.                              |
| **Thêm thành viên**    | Thêm một hoặc nhiều người dùng vào nhóm.                                       |
| **Loại thành viên**    | Loại một hoặc nhiều người dùng khỏi nhóm.                                      |
| **Vô hiệu hóa nhóm**   | Ngừng sử dụng nhóm mà vẫn giữ lịch sử nếu hệ thống hỗ trợ.                     |
| **Xóa nhóm**           | Chỉ thực hiện khi nhóm không còn được sử dụng và chính sách hệ thống cho phép. |

### Luồng thay thế / luồng ngoại lệ

| Điều kiện                                                   | Luồng xử lý                                                                                                                 |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền quản lý nhóm                   | Hệ thống từ chối truy cập chức năng.                                                                                        |
| Nhóm cần quản lý không tồn tại                              | Hệ thống thông báo không tìm thấy nhóm.                                                                                     |
| Tên hoặc mã nhóm đã tồn tại                                 | Hệ thống không tạo nhóm trùng và yêu cầu quản trị viên chỉnh sửa thông tin.                                                 |
| Thông tin nhóm không hợp lệ                                 | Hệ thống không lưu và yêu cầu quản trị viên chỉnh sửa.                                                                      |
| Người dùng cần thêm vào nhóm không tồn tại                  | Hệ thống không thêm người dùng đó vào nhóm.                                                                                 |
| Người dùng đã thuộc nhóm                                    | Hệ thống không tạo membership trùng và thông báo người dùng đã là thành viên.                                               |
| Quản trị viên loại một User không thuộc nhóm                | Hệ thống không thay đổi dữ liệu và thông báo membership không tồn tại.                                                      |
| User đang `DISABLED` được thêm vào nhóm                     | Hệ thống có thể cho phép lưu membership nhưng User vẫn không được sử dụng hệ thống khi tài khoản chưa `ACTIVE`, tùy policy. |
| Nhóm đang được sử dụng trong Access Policy                  | Hệ thống hiển thị cảnh báo rằng thay đổi membership có thể làm thay đổi quyền truy cập của thành viên.                      |
| Quản trị viên loại User khỏi nhóm đang cấp quyền `READ`     | Hệ thống tính lại effective permission của User sau khi membership bị loại bỏ.                                              |
| User vẫn nhận cùng quyền từ nguồn khác                      | Hệ thống vẫn giữ quyền hiệu lực tương ứng cho User.                                                                         |
| Quản trị viên muốn xóa nhóm đang được Access Policy sử dụng | Hệ thống từ chối hoặc yêu cầu xử lý các policy liên quan trước khi xóa.                                                     |
| Quản trị viên muốn xóa nhóm còn thành viên                  | Hệ thống cảnh báo hoặc yêu cầu gỡ các thành viên trước, tùy policy.                                                         |
| Hai Admin đồng thời cập nhật cùng một nhóm                  | Hệ thống phát hiện xung đột và không âm thầm ghi đè dữ liệu mới hơn.                                                        |
| Lưu thay đổi thất bại                                       | Hệ thống rollback và giữ nguyên thông tin nhóm/membership trước đó.                                                         |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                   |
| ----------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền quản lý nhóm mới được thực hiện Use Case này.                                                                  |
| Mỗi Group phải có định danh duy nhất trong hệ thống.                                                                                      |
| Một User có thể thuộc nhiều Group nếu nghiệp vụ cho phép.                                                                                 |
| Một Group có thể chứa nhiều User.                                                                                                         |
| Không được tạo membership trùng giữa cùng một User và cùng một Group.                                                                     |
| Group được sử dụng để gom các User có cùng nhu cầu truy cập hoặc cùng ngữ cảnh nghiệp vụ.                                                 |
| Group không đồng nghĩa với Role.                                                                                                          |
| Role chủ yếu xác định quyền chức năng, trong khi Group có thể được sử dụng làm đối tượng nhận quyền truy cập tài liệu.                    |
| Group không đồng nghĩa với Department.                                                                                                    |
| Department phản ánh cơ cấu tổ chức chính thức; Group có thể được tạo linh hoạt theo dự án, chức năng hoặc phạm vi cộng tác.               |
| User không được tự thêm mình vào Group nếu nghiệp vụ không cho phép self-membership.                                                      |
| Khi User được thêm vào Group, User có thể kế thừa các quyền mà Group đang được cấp.                                                       |
| Khi User bị loại khỏi Group, các quyền chỉ đến từ Group đó phải mất hiệu lực.                                                             |
| Việc loại User khỏi Group không đảm bảo User mất quyền nếu User vẫn nhận cùng quyền từ Role, Department, Group khác hoặc quyền trực tiếp. |
| Effective permission phải được tính từ toàn bộ các nguồn quyền hợp lệ hiện tại.                                                           |
| Khi membership thay đổi, hệ thống phải áp dụng dữ liệu mới cho các request tiếp theo theo chính sách authorization.                       |
| Hệ thống không được tiếp tục sử dụng membership cũ đã bị thu hồi trong quá trình retrieval.                                               |
| Một Group bị vô hiệu hóa không được tiếp tục cấp quyền hiệu lực nếu policy quy định Group inactive không tham gia authorization.          |
| Không được xóa Group đang được sử dụng trong Access Policy nếu thao tác làm dữ liệu phân quyền trở nên không nhất quán.                   |
| Nếu cần ngừng sử dụng Group nhưng vẫn giữ lịch sử, nên sử dụng trạng thái `DISABLED` thay vì hard-delete.                                 |
| Các thay đổi thành viên Group phải được ghi nhận phục vụ audit.                                                                           |
| Audit phải có khả năng xác định User nào được thêm/gỡ, Group nào bị thay đổi, ai thực hiện và thời điểm thực hiện.                        |
| Admin chỉ được quản lý Group trong phạm vi được cấp nếu hệ thống sau này hỗ trợ scoped administration.                                    |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                                    |
| -------------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể truy cập chức năng **Quản lý nhóm**.                                                               |
| Người dùng không có quyền quản lý nhóm không thể truy cập chức năng này.                                                         |
| Hệ thống hiển thị đúng danh sách các Group hiện có.                                                                              |
| Quản trị viên có thể xem thông tin và thành viên của một Group.                                                                  |
| Quản trị viên có thể tạo Group mới với dữ liệu hợp lệ.                                                                           |
| Không thể tạo hai Group có cùng định danh nếu policy yêu cầu duy nhất.                                                           |
| Quản trị viên có thể thêm User hợp lệ vào Group.                                                                                 |
| Không tạo hai membership trùng cho cùng một User và Group.                                                                       |
| Quản trị viên có thể loại User khỏi Group.                                                                                       |
| Khi User được thêm vào Group có quyền `READ` với một tài liệu, quyền hiệu lực của User được tính lại đúng.                       |
| Khi User bị loại khỏi Group, quyền chỉ được kế thừa từ Group đó không còn hiệu lực.                                              |
| Nếu User vẫn còn quyền `READ` từ một nguồn khác, hệ thống vẫn giữ effective permission tương ứng.                                |
| Khi membership thay đổi, các request tiếp theo sử dụng membership mới.                                                           |
| RAG retrieval không được sử dụng tài liệu mà User đã mất quyền sau khi bị loại khỏi Group nếu không còn nguồn quyền hợp lệ khác. |
| Group đang được dùng trong Access Policy không bị xóa trái policy.                                                               |
| Vô hiệu hóa hoặc xóa Group không làm mất Audit Log lịch sử.                                                                      |
| Các thao tác thêm và loại thành viên được ghi nhận trong Audit Log.                                                              |
| Audit Log ghi đúng Admin, User, Group, thao tác và thời điểm thay đổi.                                                           |
| Khi cập nhật thất bại, thông tin Group và membership trước đó vẫn được giữ nguyên.                                               |
| Khi hai Admin cập nhật đồng thời, hệ thống không âm thầm ghi đè thay đổi mới hơn.                                                |

### Dữ liệu liên quan

| Dữ liệu         | Mục đích                                      |
| --------------- | --------------------------------------------- |
| `group_id`      | Định danh duy nhất của Group.                 |
| `group_code`    | Mã nghiệp vụ của Group nếu hệ thống sử dụng.  |
| `group_name`    | Tên hiển thị của Group.                       |
| `description`   | Mô tả mục đích sử dụng của Group.             |
| `group_status`  | Trạng thái như `ACTIVE`, `DISABLED` nếu có.   |
| `user_id`       | Định danh User là thành viên nhóm.            |
| `user_group_id` | Định danh quan hệ giữa User và Group nếu cần. |
| `joined_at`     | Thời điểm User được thêm vào Group.           |
| `added_by`      | Admin đã thêm User vào Group.                 |
| `created_by`    | Admin tạo Group.                              |
| `created_at`    | Thời điểm Group được tạo.                     |
| `updated_by`    | Admin cập nhật Group gần nhất.                |
| `updated_at`    | Thời điểm cập nhật gần nhất.                  |

### Ghi chú thiết kế

Điểm quan trọng là phải phân biệt rõ:

```text
ROLE
GROUP
DEPARTMENT
```

Ba khái niệm này phục vụ các mục đích khác nhau.

#### Role

Trả lời:

```text
"User được phép thực hiện chức năng nào?"
```

Ví dụ:

```text
Role = EMPLOYEE

Permissions:
- ASK_KNOWLEDGE
- VIEW_SOURCE
- SUBMIT_FEEDBACK
```

#### Department

Trả lời:

```text
"User thuộc đơn vị tổ chức nào?"
```

Ví dụ:

```text
User A
    ↓
Department HR
```

#### Group

Trả lời:

```text
"User thuộc tập hợp người dùng nghiệp vụ nào?"
```

Ví dụ:

```text
Group:
PROJECT_ALPHA
```

có thể gồm:

```text
User A — HR
User B — Finance
User C — IT
```

mặc dù ba User thuộc ba Department khác nhau.

Nhóm có thể được dùng để cấp quyền chung:

```text
PROJECT_ALPHA
      ↓
    READ
      ↓
DOC-PROJECT-001
```

Khi đó tất cả thành viên của `PROJECT_ALPHA` có thể nhận quyền này.

---

### Ví dụ quản lý Group

Ban đầu:

```text
Group HR_MANAGER

Members:
├── User A
├── User B
└── User C
```

Access Policy:

```text
Group HR_MANAGER
       ↓
      READ
       ↓
DOC-001
"Chính sách quản lý nhân sự"
```

Do đó:

```text
User A → READ DOC-001
User B → READ DOC-001
User C → READ DOC-001
```

Admin thêm:

```text
User D
```

vào Group:

```text
HR_MANAGER
```

Sau khi cập nhật:

```text
Group HR_MANAGER
├── User A
├── User B
├── User C
└── User D
```

User D có thể nhận:

```text
READ DOC-001
```

từ Group.

Không cần Admin tạo:

```text
User D → READ DOC-001
```

riêng.

Đây chính là lợi ích của Group-based authorization.

---

### Khi loại User khỏi Group

Ví dụ:

```text
User A
    ↓
Group HR_MANAGER
    ↓
READ DOC-001
```

Admin thực hiện:

```text
Remove User A
from HR_MANAGER
```

Hệ thống tính lại quyền.

Nếu đây là nguồn duy nhất:

```text
User A
    X
READ DOC-001
```

request tiếp theo:

```text
User A hỏi câu hỏi
       ↓
Authorization
       ↓
DOC-001
READ?
       ↓
NO
       ↓
Không đưa DOC-001 vào retrieval
```

Nhưng nếu User A còn:

```text
Department HR
      ↓
READ DOC-001
```

thì:

```text
Remove User A from HR_MANAGER
             ↓
User A vẫn READ DOC-001
```

vì Department vẫn cấp quyền.

Do đó:

```text
Remove Group Membership
          ≠
Revoke Effective Permission
```

trong mọi trường hợp.

Phải tính:

```text
Effective Permission
        =
Role permissions
+
Group permissions
+
Department permissions
+
Direct permissions
+
Policy rules
```

theo mô hình authorization bạn chọn.

---

### Group không nên thay thế Department

Không nên thiết kế:

```text
Group HR
Group Finance
Group IT
```

để thay hoàn toàn cho:

```text
Department HR
Department Finance
Department IT
```

nếu doanh nghiệp thực sự có cấu trúc phòng ban.

Nên dùng:

```text
Department
=
cấu trúc tổ chức chính thức
```

và:

```text
Group
=
tập hợp linh hoạt
```

Ví dụ:

```text
Department
├── HR
├── IT
└── Finance
```

nhưng Group có thể là:

```text
PROJECT_VINHOME_A
├── User HR
├── User IT
└── User Finance
```

hoặc:

```text
CONTRACT_REVIEWERS
```

hoặc:

```text
FINANCIAL_REPORT_READERS
```

---

### Quan hệ dữ liệu

Ở mức domain/database có thể hình dung:

```text
User
 │
 └── UserGroup
       │
       └── Group
```

Quan hệ:

```text
User N ↔ N Group
```

Ví dụ:

```text
User A
├── HR_MANAGER
├── PROJECT_ALPHA
└── POLICY_REVIEWER
```

và:

```text
PROJECT_ALPHA
├── User A
├── User B
├── User C
└── User D
```

Không nên lưu kiểu:

```text
users.group_id
```

nếu hệ thống cần một User thuộc nhiều Group.

Hợp lý hơn là quan hệ trung gian:

```text
users
groups
user_groups
```

Ví dụ:

```text
user_groups

user_id    group_id
--------------------
U001       G001
U001       G005
U002       G001
U003       G005
```

---

### Quan hệ Group với quyền tài liệu

Sau này phần Access Policy có thể biểu diễn:

```text
Principal
   │
   ├── USER
   ├── ROLE
   ├── GROUP
   └── DEPARTMENT
```

Ví dụ:

```text
Permission Assignment

principal_type = GROUP
principal_id   = G001
resource       = DOC-001
permission     = READ
```

Nghĩa là:

```text
Group G001
   ↓
READ
   ↓
DOC-001
```

User thuộc G001 sẽ nhận quyền tương ứng khi hệ thống tính effective permission.

---

### Luồng tổng thể

```text
Admin
  ↓
Quản lý nhóm
  ↓
Chọn / tạo Group
  ↓
Cập nhật thông tin
  ↓
Thêm / loại thành viên
  ↓
Validate
  ↓
Xác định quyền bị ảnh hưởng
  ↓
Xác nhận
  ↓
Lưu Group + Membership
  ↓
Tính lại effective permission
  ↓
Audit
  ↓
Áp dụng cho request tiếp theo
```

Nguyên tắc quan trọng:

```text
GROUP
=
Tập hợp người dùng
```

không phải:

```text
GROUP
=
ROLE
```

và cũng không phải:

```text
GROUP
=
DEPARTMENT
```

Cách dùng hợp lý trong hệ thống của bạn là:

```text
Role
→ User được làm chức năng gì?

Department
→ User thuộc tổ chức nào?

Group
→ User thuộc tập hợp nghiệp vụ nào?

Access Policy
→ Principal nào được làm gì trên Document nào?
```

Giữ bốn khái niệm này tách biệt sẽ giúp phần Authorization và ACL của Enterprise RAG dễ mở rộng hơn rất nhiều.

### Use case quản lý phòng ban

| Thuộc tính                  | Mô tả                                                                                                                                                                                                          |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**            | Quản lý phòng ban                                                                                                                                                                                              |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                                  |
| **Mục tiêu**                | Cho phép quản trị viên tạo, xem, cập nhật và quản lý các phòng ban trong hệ thống, đồng thời quản lý quan hệ giữa người dùng và phòng ban để phục vụ tổ chức dữ liệu và phân quyền truy cập tài liệu.          |
| **Điều kiện kích hoạt**     | Quản trị viên truy cập chức năng **Quản lý phòng ban**.                                                                                                                                                        |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản quản trị viên đang hoạt động.<br>3. Quản trị viên có quyền quản lý phòng ban.<br>4. Các người dùng được phân vào phòng ban phải tồn tại trong hệ thống.         |
| **Đầu vào**                 | Tên phòng ban, mã phòng ban, mô tả, trạng thái, phòng ban cha nếu có và danh sách người dùng thuộc phòng ban.                                                                                                  |
| **Trạng thái — Thành công** | Phòng ban được tạo hoặc cập nhật thành công; quan hệ giữa người dùng và phòng ban được cập nhật; các quyền kế thừa từ phòng ban được tính lại theo chính sách hiện hành; thay đổi được ghi nhận phục vụ audit. |
| **Trạng thái — Thất bại**   | Thông tin phòng ban hoặc quan hệ người dùng–phòng ban không bị thay đổi; hệ thống thông báo nguyên nhân lỗi và không để dữ liệu ở trạng thái không nhất quán.                                                  |
| **Use Cases liên quan**     | Quản lý người dùng, Quản lý nhóm, Quản lý vai trò, Thiết lập quyền truy cập tài liệu, Xem ma trận quyền, Kiểm tra quyền truy cập                                                                               |

### Main Flow

| Bước | Actor         | Hành động                                                                                                        |
| ---: | ------------- | ---------------------------------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Truy cập chức năng **Quản lý phòng ban**.                                                                        |
|    2 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                                                      |
|    3 | System        | Kiểm tra quyền quản lý phòng ban của quản trị viên.                                                              |
|    4 | System        | Hiển thị danh sách hoặc cấu trúc các phòng ban hiện có.                                                          |
|    5 | Quản trị viên | Chọn một phòng ban để xem/chỉnh sửa hoặc chọn tạo phòng ban mới.                                                 |
|    6 | System        | Hiển thị thông tin phòng ban và danh sách người dùng hiện thuộc phòng ban nếu có.                                |
|    7 | Quản trị viên | Nhập hoặc cập nhật tên, mã, mô tả, trạng thái và thông tin tổ chức của phòng ban.                                |
|    8 | Quản trị viên | Thêm, chuyển hoặc loại người dùng khỏi phòng ban nếu cần.                                                        |
|    9 | System        | Kiểm tra tính hợp lệ của thông tin phòng ban.                                                                    |
|   10 | System        | Kiểm tra mã hoặc định danh phòng ban có bị trùng hay không.                                                      |
|   11 | System        | Kiểm tra các người dùng được gán vào phòng ban có tồn tại và hợp lệ hay không.                                   |
|   12 | System        | Kiểm tra quan hệ phòng ban cha–con nếu hệ thống hỗ trợ cấu trúc phân cấp.                                        |
|   13 | System        | Xác định ảnh hưởng của thay đổi đối với quyền truy cập của các người dùng liên quan.                             |
|   14 | Quản trị viên | Xác nhận thay đổi.                                                                                               |
|   15 | System        | Tạo mới hoặc cập nhật thông tin phòng ban.                                                                       |
|   16 | System        | Cập nhật quan hệ giữa người dùng và phòng ban.                                                                   |
|   17 | System        | Tính lại effective permission của các người dùng chịu ảnh hưởng nếu Department được sử dụng trong Access Policy. |
|   18 | System        | Ghi nhận người thực hiện, thời điểm và nội dung thay đổi vào Audit Log.                                          |
|   19 | System        | Thông báo thao tác thành công.                                                                                   |
|   20 | System        | Hiển thị lại thông tin phòng ban mới nhất.                                                                       |

### Thông tin phòng ban được quản lý

| Thông tin                | Ý nghĩa                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------ |
| **Tên phòng ban**        | Tên đơn vị tổ chức, ví dụ Phòng Nhân sự, Phòng Tài chính, Phòng Công nghệ thông tin. |
| **Mã phòng ban**         | Định danh nghiệp vụ duy nhất của phòng ban.                                          |
| **Mô tả**                | Thông tin mô tả chức năng hoặc phạm vi của phòng ban.                                |
| **Trạng thái**           | Xác định phòng ban đang `ACTIVE`, `DISABLED` hoặc trạng thái tương ứng.              |
| **Phòng ban cha**        | Xác định quan hệ phân cấp tổ chức nếu doanh nghiệp có cấu trúc nhiều cấp.            |
| **Danh sách thành viên** | Những người dùng hiện thuộc phòng ban.                                               |
| **Số lượng thành viên**  | Tổng số User hiện thuộc phòng ban.                                                   |
| **Quyền liên quan**      | Các Access Policy đang cấp quyền cho phòng ban nếu có.                               |
| **Thời điểm tạo**        | Thời điểm phòng ban được tạo trong hệ thống.                                         |
| **Thời điểm cập nhật**   | Thời điểm thông tin phòng ban được thay đổi gần nhất.                                |

### Các thao tác quản lý phòng ban

| Thao tác                                  | Mô tả                                                                          |
| ----------------------------------------- | ------------------------------------------------------------------------------ |
| **Xem danh sách phòng ban**               | Xem các phòng ban hiện có trong hệ thống.                                      |
| **Xem chi tiết phòng ban**                | Xem thông tin, thành viên và các quyền liên quan.                              |
| **Tạo phòng ban**                         | Tạo một đơn vị tổ chức mới.                                                    |
| **Cập nhật phòng ban**                    | Thay đổi tên, mô tả, trạng thái hoặc thông tin tổ chức.                        |
| **Gán người dùng vào phòng ban**          | Liên kết User với Department.                                                  |
| **Chuyển người dùng sang phòng ban khác** | Cập nhật Department hiện tại của User.                                         |
| **Loại người dùng khỏi phòng ban**        | Gỡ quan hệ User–Department nếu nghiệp vụ cho phép.                             |
| **Vô hiệu hóa phòng ban**                 | Ngừng sử dụng phòng ban mà vẫn giữ lịch sử.                                    |
| **Xóa phòng ban**                         | Chỉ thực hiện khi không còn dữ liệu phụ thuộc và chính sách hệ thống cho phép. |

### Luồng thay thế / luồng ngoại lệ

| Điều kiện                                                        | Luồng xử lý                                                                                                               |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền quản lý phòng ban                   | Hệ thống từ chối truy cập chức năng.                                                                                      |
| Phòng ban cần quản lý không tồn tại                              | Hệ thống thông báo không tìm thấy phòng ban.                                                                              |
| Mã phòng ban đã tồn tại                                          | Hệ thống không tạo phòng ban trùng và yêu cầu chỉnh sửa dữ liệu.                                                          |
| Tên hoặc dữ liệu phòng ban không hợp lệ                          | Hệ thống không lưu và yêu cầu quản trị viên chỉnh sửa.                                                                    |
| Người dùng cần gán vào phòng ban không tồn tại                   | Hệ thống từ chối gán.                                                                                                     |
| User đã thuộc phòng ban đó                                       | Hệ thống không tạo quan hệ trùng.                                                                                         |
| User được chuyển sang phòng ban khác                             | Hệ thống cập nhật Department hiện tại và tính lại các quyền kế thừa liên quan.                                            |
| User vẫn nhận cùng quyền từ Role, Group hoặc quyền trực tiếp     | Hệ thống giữ effective permission tương ứng dù Department thay đổi.                                                       |
| Phòng ban đang được sử dụng trong Access Policy                  | Hệ thống cảnh báo rằng việc thay đổi hoặc vô hiệu hóa phòng ban có thể ảnh hưởng tới quyền truy cập của nhiều người dùng. |
| Quản trị viên muốn xóa phòng ban còn người dùng                  | Hệ thống từ chối hoặc yêu cầu chuyển người dùng sang phòng ban khác trước.                                                |
| Quản trị viên muốn xóa phòng ban đang được Access Policy sử dụng | Hệ thống từ chối hoặc yêu cầu xử lý các policy liên quan trước.                                                           |
| Phòng ban có phòng ban con                                       | Hệ thống cảnh báo hoặc yêu cầu xử lý cấu trúc con trước khi xóa.                                                          |
| Quản trị viên tạo quan hệ phòng ban cha–con gây vòng lặp         | Hệ thống từ chối cấu hình.                                                                                                |
| Hai Admin đồng thời cập nhật một phòng ban                       | Hệ thống phát hiện xung đột và không âm thầm ghi đè dữ liệu mới hơn.                                                      |
| Lưu thay đổi thất bại                                            | Hệ thống rollback và giữ nguyên dữ liệu phòng ban trước đó.                                                               |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                  |
| ---------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền quản lý phòng ban mới được thực hiện Use Case này.                                                            |
| Mỗi Department phải có một định danh duy nhất trong hệ thống.                                                                            |
| Department đại diện cho cơ cấu tổ chức chính thức của doanh nghiệp.                                                                      |
| Department phải được phân biệt với Group; Group là tập hợp người dùng linh hoạt, còn Department phản ánh đơn vị tổ chức chính thức.      |
| Department phải được phân biệt với Role; Role xác định quyền chức năng, không xác định đơn vị tổ chức.                                   |
| Một User mặc định nên có một Department chính tại một thời điểm nếu mô hình tổ chức của doanh nghiệp quy định như vậy.                   |
| Nếu doanh nghiệp cho phép User thuộc nhiều Department, hệ thống phải định nghĩa rõ Department chính và Department phụ.                   |
| User không được tự thay đổi Department của mình nếu dữ liệu tổ chức do Admin hoặc doanh nghiệp quản lý.                                  |
| Khi User chuyển Department, các quyền chỉ kế thừa từ Department cũ phải mất hiệu lực.                                                    |
| Khi User được gán sang Department mới, các quyền được cấp cho Department mới có thể được áp dụng cho User.                               |
| Việc User rời Department không đảm bảo User mất toàn bộ quyền nếu vẫn có quyền tương đương từ Role, Group hoặc Direct Permission.        |
| Effective permission phải được tính từ toàn bộ các nguồn quyền hiện hành.                                                                |
| Nếu Department được sử dụng trong Access Policy, thay đổi membership phải được áp dụng cho các request tiếp theo.                        |
| Hệ thống không được tiếp tục sử dụng Department cũ để authorize User sau khi User đã được chuyển đơn vị.                                 |
| Phòng ban `DISABLED` không được tiếp tục cấp quyền hiệu lực nếu policy quy định Department không hoạt động không tham gia authorization. |
| Không được xóa Department đang có User, Department con hoặc Access Policy phụ thuộc nếu việc xóa làm dữ liệu trở nên không nhất quán.    |
| Nếu cần ngừng sử dụng Department nhưng vẫn bảo toàn lịch sử, nên sử dụng `DISABLED` thay vì hard-delete.                                 |
| Các thay đổi Department và User membership phải được Audit Log ghi nhận.                                                                 |
| Audit phải xác định được User nào chuyển từ Department nào sang Department nào, ai thực hiện và thời điểm thay đổi.                      |
| Admin chỉ được quản lý Department trong phạm vi được cấp nếu hệ thống sau này hỗ trợ scoped administration.                              |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể truy cập chức năng **Quản lý phòng ban**.                                                   |
| Người không có quyền không thể quản lý phòng ban.                                                                         |
| Hệ thống hiển thị đúng danh sách các Department hiện có.                                                                  |
| Quản trị viên có thể xem thông tin và danh sách thành viên của một Department.                                            |
| Quản trị viên có thể tạo Department mới với dữ liệu hợp lệ.                                                               |
| Không thể tạo hai Department có cùng mã định danh nếu policy yêu cầu duy nhất.                                            |
| Quản trị viên có thể cập nhật thông tin Department hợp lệ.                                                                |
| User có thể được gán vào đúng Department theo nghiệp vụ.                                                                  |
| Khi User chuyển Department, quan hệ với Department mới được cập nhật chính xác.                                           |
| Khi User rời Department cũ, quyền chỉ kế thừa từ Department cũ không còn hiệu lực.                                        |
| Khi User vào Department mới, quyền kế thừa từ Department mới được tính đúng.                                              |
| Nếu User còn cùng quyền từ nguồn khác, hệ thống vẫn giữ effective permission phù hợp.                                     |
| Các request sau khi User chuyển Department phải sử dụng Department mới.                                                   |
| RAG retrieval không được dùng tài liệu mà User đã mất quyền sau khi rời Department nếu không còn nguồn quyền hợp lệ khác. |
| Department đang được dùng trong Access Policy không bị xóa trái policy.                                                   |
| Department còn thành viên không bị xóa nếu policy yêu cầu chuyển thành viên trước.                                        |
| Quan hệ phòng ban cha–con không được tạo vòng lặp.                                                                        |
| Các thay đổi Department được ghi nhận trong Audit Log.                                                                    |
| Audit Log ghi đúng Admin, User, Department cũ, Department mới và thời điểm thay đổi.                                      |
| Khi cập nhật thất bại, dữ liệu trước đó được giữ nguyên.                                                                  |
| Khi hai Admin cập nhật đồng thời, hệ thống không âm thầm ghi đè thay đổi mới hơn.                                         |

### Dữ liệu liên quan

| Dữ liệu                | Mục đích                                                 |
| ---------------------- | -------------------------------------------------------- |
| `department_id`        | Định danh duy nhất của phòng ban.                        |
| `department_code`      | Mã nghiệp vụ của phòng ban.                              |
| `department_name`      | Tên hiển thị của phòng ban.                              |
| `description`          | Mô tả chức năng hoặc phạm vi của phòng ban.              |
| `department_status`    | Trạng thái như `ACTIVE`, `DISABLED`.                     |
| `parent_department_id` | Xác định phòng ban cha nếu có cấu trúc phân cấp.         |
| `user_id`              | Định danh User thuộc phòng ban.                          |
| `joined_at`            | Thời điểm User bắt đầu thuộc phòng ban nếu cần theo dõi. |
| `assigned_by`          | Admin thực hiện việc phân User vào Department.           |
| `created_by`           | Admin tạo Department.                                    |
| `created_at`           | Thời điểm Department được tạo.                           |
| `updated_by`           | Admin cập nhật Department gần nhất.                      |
| `updated_at`           | Thời điểm cập nhật gần nhất.                             |

### Ghi chú thiết kế

Cần phân biệt rõ ba khái niệm:

```text
ROLE
GROUP
DEPARTMENT
```

#### Role

Trả lời câu hỏi:

```text
"User được phép làm chức năng gì?"
```

Ví dụ:

```text
Role = EMPLOYEE

Permissions:
- ASK_KNOWLEDGE
- VIEW_SOURCE
```

#### Group

Trả lời câu hỏi:

```text
"User đang thuộc tập hợp nghiệp vụ nào?"
```

Ví dụ:

```text
Group = PROJECT_ALPHA

Members:
- User HR
- User IT
- User Finance
```

#### Department

Trả lời câu hỏi:

```text
"User thuộc đơn vị tổ chức nào?"
```

Ví dụ:

```text
User A
   ↓
Department HR
```

---

### Department và quyền truy cập tài liệu

Ví dụ có Access Policy:

```text
Department HR
      ↓
     READ
      ↓
DOC-001
"Quy định nhân sự"
```

Nếu:

```text
User A
Department = HR
```

thì User A có thể nhận:

```text
READ DOC-001
```

từ Department.

Luồng:

```text
User A
  ↓
Department HR
  ↓
Access Policy
  ↓
READ DOC-001
```

Nếu Admin chuyển User A:

```text
HR
 ↓
Finance
```

thì hệ thống phải tính lại quyền.

Nếu quyền `READ DOC-001` chỉ đến từ HR:

```text
User A
  X
Department HR
  ↓
Mất READ DOC-001
```

Request tiếp theo:

```text
User A đặt câu hỏi
        ↓
Resolve Principal Context
        ↓
Department = Finance
        ↓
Authorization
        ↓
DOC-001 READ?
        ↓
NO
        ↓
DOC-001 không được đưa vào retrieval
```

Nhưng nếu User A còn:

```text
Group HR_POLICY_READERS
        ↓
READ DOC-001
```

thì dù User A đã chuyển sang Finance:

```text
User A vẫn READ DOC-001
```

Do đó:

```text
CHUYỂN DEPARTMENT
       ≠
CHẮC CHẮN MẤT QUYỀN
```

Hệ thống phải tính **effective permission** từ toàn bộ nguồn quyền.

---

### Department và metadata tài liệu

Đây là điểm đặc biệt quan trọng.

Một tài liệu có thể có:

```text
document.department = HR
```

với ý nghĩa:

> Tài liệu này thuộc/được quản lý bởi phòng Nhân sự.

Đây có thể chỉ là **metadata nghiệp vụ**.

Nó không nhất thiết có nghĩa:

```text
Chỉ HR được READ tài liệu
```

Muốn giới hạn quyền, phải có Access Policy:

```text
Principal:
Department HR

Permission:
READ

Resource:
DOC-001
```

Do đó không nên suy luận trực tiếp:

```text
Document.department = HR
        ↓
auto READ for HR
```

trừ khi bạn **chủ động định nghĩa đây là business rule của hệ thống**.

Thiết kế sạch hơn:

```text
Metadata
────────────────
Document belongs to HR
```

và:

```text
Access Policy
────────────────
Department HR
READ
DOC-001
```

là hai khái niệm độc lập.

---

### Cấu trúc phòng ban phân cấp

Nếu doanh nghiệp có:

```text
Công ty
│
├── Khối Công nghệ
│   ├── Phòng AI
│   └── Phòng Data
│
└── Khối Vận hành
    ├── Phòng Nhân sự
    └── Phòng Tài chính
```

có thể biểu diễn:

```text
Department
   │
   └── parent_department_id
```

Ví dụ:

```text
Khối Công nghệ
    │
    ├── AI
    └── Data
```

Tuy nhiên cần xác định rõ quyền có kế thừa qua hierarchy hay không.

Ví dụ:

```text
Khối Công nghệ
      ↓
READ DOC-100
```

Có hai policy có thể chọn:

```text
Policy A:
AI và Data tự động kế thừa READ
```

hoặc:

```text
Policy B:
Không tự động kế thừa;
phải cấp rõ cho từng Department.
```

Với MVP, nếu chưa có yêu cầu mạnh về hierarchy, nên chọn **Policy B hoặc cấu trúc Department phẳng** để tránh authorization quá phức tạp.

---

### Quan hệ dữ liệu

Nếu mỗi User chỉ có một Department chính:

```text
User
 │
 └── department_id
       ↓
   Department
```

có thể đủ.

Nếu muốn lưu lịch sử chuyển phòng ban hoặc một User thuộc nhiều Department:

```text
users
departments
user_departments
```

sẽ linh hoạt hơn.

Ví dụ:

```text
user_departments

user_id   department_id   start_at     end_at
------------------------------------------------
U001      HR              2025-01-01   2026-06-30
U001      FINANCE         2026-07-01   NULL
```

Nhờ vậy hệ thống có thể biết:

```text
User A trước đây thuộc HR
```

và:

```text
Hiện tại thuộc Finance
```

mà không mất lịch sử tổ chức.

---

### Luồng tổng thể

```text
Admin
  ↓
Quản lý phòng ban
  ↓
Chọn / tạo Department
  ↓
Cập nhật thông tin
  ↓
Gán / chuyển User
  ↓
Validate
  ↓
Xác định quyền bị ảnh hưởng
  ↓
Admin xác nhận
  ↓
Lưu Department + Membership
  ↓
Tính lại Effective Permission
  ↓
Audit
  ↓
Áp dụng cho request tiếp theo
```

Nguyên tắc cần giữ:

```text
DEPARTMENT
=
Cơ cấu tổ chức
```

không phải:

```text
DEPARTMENT
=
ROLE
```

và cũng không phải:

```text
DEPARTMENT
=
GROUP
```

Mô hình tổng thể nên là:

```text
User
│
├── Role
│     └── Được làm chức năng gì?
│
├── Department
│     └── Thuộc đơn vị tổ chức nào?
│
├── Group
│     └── Thuộc tập hợp nghiệp vụ nào?
│
└── Access Policy
      └── Được làm gì trên tài nguyên nào?
```

Đây là ranh giới nên giữ xuyên suốt khi bạn thiết kế RBAC + ACL cho hệ thống RAG.

### Use case thiết lập quyền truy cập tài liệu

| Thuộc tính                  | Mô tả                                                                                                                                                                                                                                                                                                 |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**            | Thiết lập quyền truy cập tài liệu                                                                                                                                                                                                                                                                     |
| **Actor chính**             | Quản trị viên                                                                                                                                                                                                                                                                                         |
| **Mục tiêu**                | Cho phép quản trị viên xác định người dùng, vai trò, nhóm hoặc phòng ban nào được phép thực hiện các hành động cụ thể đối với một tài liệu hoặc phạm vi tài liệu, nhằm đảm bảo tài liệu chỉ được truy cập bởi đúng đối tượng được cấp quyền.                                                          |
| **Điều kiện kích hoạt**     | Quản trị viên chọn một tài liệu hoặc phạm vi tài liệu và mở chức năng **Thiết lập quyền truy cập**.                                                                                                                                                                                                   |
| **Điều kiện tiên quyết**    | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản quản trị viên đang hoạt động.<br>3. Quản trị viên có quyền quản lý chính sách truy cập tài liệu.<br>4. Tài liệu hoặc phạm vi tài liệu cần phân quyền tồn tại.<br>5. Đối tượng nhận quyền như User, Role, Group hoặc Department tồn tại trong hệ thống. |
| **Đầu vào**                 | Tài liệu hoặc phạm vi tài liệu; đối tượng nhận quyền; loại quyền cần thiết lập như `READ`, `DOWNLOAD`, `MANAGE`, `REVIEW` hoặc các quyền khác theo chính sách hệ thống.                                                                                                                               |
| **Trạng thái — Thành công** | Chính sách truy cập tài liệu được cập nhật thành công; quyền hiệu lực của các đối tượng liên quan được tính lại và áp dụng cho các request tiếp theo; thay đổi được ghi nhận phục vụ audit.                                                                                                           |
| **Trạng thái — Thất bại**   | Chính sách truy cập hiện tại không bị thay đổi; hệ thống thông báo nguyên nhân và không tạo cấu hình quyền không nhất quán.                                                                                                                                                                           |
| **Use Cases liên quan**     | Cấp quyền, Thu hồi quyền, Quản lý người dùng, Quản lý vai trò, Quản lý nhóm, Quản lý phòng ban, Xem ma trận quyền, Kiểm tra quyền truy cập, Xem chi tiết tài liệu                                                                                                                                     |

### Main Flow

| Bước | Actor         | Hành động                                                                                   |
| ---: | ------------- | ------------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Mở tài liệu hoặc khu vực quản lý quyền truy cập.                                            |
|    2 | Quản trị viên | Chọn chức năng **Thiết lập quyền truy cập tài liệu**.                                       |
|    3 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                                 |
|    4 | System        | Kiểm tra quản trị viên có quyền quản lý chính sách truy cập hay không.                      |
|    5 | System        | Xác định tài liệu hoặc phạm vi tài liệu cần phân quyền.                                     |
|    6 | System        | Hiển thị các chính sách và quyền hiện đang áp dụng.                                         |
|    7 | Quản trị viên | Chọn loại đối tượng cần thiết lập quyền: User, Role, Group hoặc Department.                 |
|    8 | Quản trị viên | Chọn đối tượng cụ thể cần cấp hoặc điều chỉnh quyền.                                        |
|    9 | Quản trị viên | Chọn quyền cần áp dụng cho đối tượng.                                                       |
|   10 | System        | Kiểm tra đối tượng và quyền được chọn có hợp lệ hay không.                                  |
|   11 | System        | Kiểm tra quản trị viên có quyền thay đổi cấu hình tương ứng hay không.                      |
|   12 | System        | Xác định các quyền hiện tại của đối tượng và nguồn quyền liên quan.                         |
|   13 | System        | Xác định ảnh hưởng dự kiến của thay đổi tới những người dùng liên quan.                     |
|   14 | System        | Hiển thị thông tin quyền sau thay đổi hoặc cảnh báo nếu thao tác có tác động lớn.           |
|   15 | Quản trị viên | Xác nhận thay đổi quyền.                                                                    |
|   16 | System        | Tạo mới, cập nhật hoặc vô hiệu hóa Permission Assignment tương ứng.                         |
|   17 | System        | Tính lại quyền hiệu lực của các User chịu ảnh hưởng.                                        |
|   18 | System        | Ghi nhận Admin thực hiện, thời điểm, tài nguyên, đối tượng và quyền thay đổi vào Audit Log. |
|   19 | System        | Thông báo cập nhật quyền thành công.                                                        |
|   20 | System        | Hiển thị lại chính sách truy cập hiện tại của tài liệu.                                     |

### Đối tượng có thể được cấp quyền

| Đối tượng      | Ý nghĩa                                                                                                    |
| -------------- | ---------------------------------------------------------------------------------------------------------- |
| **User**       | Cấp quyền trực tiếp cho một người dùng cụ thể.                                                             |
| **Role**       | Cấp quyền cho những User có vai trò tương ứng nếu mô hình phân quyền sử dụng Role cho resource permission. |
| **Group**      | Cấp quyền cho toàn bộ thành viên hiện tại của nhóm.                                                        |
| **Department** | Cấp quyền cho những người dùng thuộc phòng ban tương ứng.                                                  |

### Các loại quyền có thể quản lý

| Quyền               | Ý nghĩa                                                                                             |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| `READ`              | Cho phép người dùng đọc và sử dụng nội dung tài liệu trong phạm vi được phép.                       |
| `DOWNLOAD`          | Cho phép tải file nguồn của tài liệu.                                                               |
| `MANAGE`            | Cho phép thực hiện các thao tác quản lý tài liệu trong phạm vi chính sách cho phép.                 |
| `REVIEW`            | Cho phép kiểm duyệt phiên bản tài liệu.                                                             |
| `PUBLISH`           | Cho phép xuất bản tài liệu nếu workflow cho phép.                                                   |
| `ARCHIVE`           | Cho phép lưu trữ tài liệu.                                                                          |
| `MANAGE_PERMISSION` | Cho phép quản lý quyền truy cập của tài liệu nếu hệ thống hỗ trợ phân quyền quản trị theo resource. |

> Tập permission thực tế nên được chốt theo nghiệp vụ của hệ thống. Không nhất thiết MVP phải có toàn bộ các quyền trên.

### Các thao tác quản lý quyền

| Thao tác                    | Mô tả                                                                          |
| --------------------------- | ------------------------------------------------------------------------------ |
| **Xem quyền hiện tại**      | Xem các đối tượng đang được cấp quyền trên tài liệu.                           |
| **Cấp quyền**               | Thêm quyền mới cho một User, Role, Group hoặc Department.                      |
| **Thu hồi quyền**           | Loại bỏ một Permission Assignment đã được cấp trước đó.                        |
| **Thay đổi quyền**          | Điều chỉnh tập quyền của một đối tượng.                                        |
| **Xem nguồn quyền**         | Xác định User nhận quyền trực tiếp hay kế thừa từ Role, Group hoặc Department. |
| **Kiểm tra quyền hiệu lực** | Xác định quyền cuối cùng mà một User thực sự có trên tài liệu.                 |

### Luồng thay thế / luồng ngoại lệ

| Điều kiện                                                           | Luồng xử lý                                                                                                                            |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền quản lý Access Policy                  | Hệ thống từ chối thao tác và không hiển thị chức năng thay đổi quyền.                                                                  |
| Tài liệu không tồn tại                                              | Hệ thống thông báo tài liệu không còn khả dụng.                                                                                        |
| User, Role, Group hoặc Department được chọn không tồn tại           | Hệ thống không tạo Permission Assignment.                                                                                              |
| Quyền được chọn không hợp lệ                                        | Hệ thống từ chối cấu hình và yêu cầu Admin chọn permission hợp lệ.                                                                     |
| Quyền đã được cấp trực tiếp cho đối tượng                           | Hệ thống không tạo assignment trùng và thông báo quyền đã tồn tại.                                                                     |
| User đã có quyền thông qua Group hoặc Department                    | Hệ thống có thể hiển thị rằng User đã có effective permission từ nguồn khác trước khi Admin tạo quyền trực tiếp.                       |
| Admin thu hồi quyền trực tiếp nhưng User vẫn có quyền từ nguồn khác | Hệ thống thu hồi assignment trực tiếp nhưng effective permission của User vẫn được giữ từ nguồn còn lại.                               |
| Group có số lượng lớn thành viên                                    | Hệ thống hiển thị phạm vi ảnh hưởng trước khi Admin xác nhận nếu policy yêu cầu.                                                       |
| Department có nhiều người dùng                                      | Hệ thống cảnh báo thay đổi có thể ảnh hưởng tới toàn bộ thành viên của Department.                                                     |
| Admin cố cấp quyền vượt phạm vi quản trị của mình                   | Hệ thống từ chối thao tác.                                                                                                             |
| Admin cố tự cấp cho mình quyền mà policy không cho phép             | Hệ thống từ chối hoặc yêu cầu cấp quản trị cao hơn theo policy.                                                                        |
| Thay đổi có thể làm mất quyền truy cập quản trị cần thiết           | Hệ thống cảnh báo hoặc chặn thao tác nhằm tránh khóa toàn bộ quyền quản trị.                                                           |
| Tài liệu đã `ARCHIVED`                                              | Hệ thống có thể cho phép xem hoặc quản lý policy phục vụ audit nhưng quyền `READ` không làm tài liệu trở lại Knowledge Base hiện hành. |
| Tài liệu chưa `PUBLISHED`                                           | Có thể cấu hình quyền trước, nhưng việc có `READ` không làm tài liệu chưa Publish được Employee truy vấn.                              |
| Hai Admin đồng thời thay đổi cùng một policy                        | Hệ thống phát hiện xung đột và không âm thầm ghi đè thay đổi mới hơn.                                                                  |
| Lưu Access Policy thất bại                                          | Hệ thống rollback và giữ chính sách trước đó.                                                                                          |
| Không thể cập nhật dữ liệu authorization/cache                      | Hệ thống không được sử dụng dữ liệu quyền cũ quá thời hạn cho phép; phải fail-closed theo security policy.                             |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                                        |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền quản lý Access Policy mới được thiết lập quyền truy cập tài liệu.                                                                   |
| Quyền truy cập tài liệu phải được xác định riêng với quyền sử dụng chức năng của hệ thống.                                                                     |
| Việc User có Role `EMPLOYEE` không đồng nghĩa User được đọc mọi tài liệu.                                                                                      |
| Việc User có Role `ADMIN` cũng không nhất thiết đồng nghĩa có toàn quyền trên mọi Document nếu hệ thống hỗ trợ scoped administration.                          |
| Một Permission Assignment phải xác định ít nhất: principal, resource và permission.                                                                            |
| Principal có thể là User, Role, Group hoặc Department theo mô hình hệ thống.                                                                                   |
| Resource có thể là một Document hoặc phạm vi tài liệu nếu hệ thống hỗ trợ policy theo scope.                                                                   |
| Hệ thống phải xác định quyền hiệu lực từ tất cả nguồn quyền hợp lệ hiện tại.                                                                                   |
| Việc thu hồi một quyền trực tiếp không đảm bảo User mất quyền nếu còn nhận cùng quyền từ nguồn khác.                                                           |
| Khi User bị loại khỏi Group hoặc Department, quyền chỉ kế thừa từ nguồn đó phải mất hiệu lực.                                                                  |
| Bộ lọc authorization phải được áp dụng trước khi tài liệu trở thành candidate evidence của RAG.                                                                |
| Tài liệu User không có `READ` không được đưa vào retrieval.                                                                                                    |
| Unauthorized document không được truyền sang reranker, context builder hoặc LLM.                                                                               |
| Hệ thống không được tiết lộ tên, snippet, metadata nhạy cảm hoặc sự tồn tại của tài liệu cho User không có quyền nếu policy yêu cầu chống information leakage. |
| Quyền `DOWNLOAD` phải được kiểm tra độc lập với `READ` nếu nghiệp vụ tách hai quyền.                                                                           |
| Quyền phải được kiểm tra lại khi User truy cập trực tiếp resource qua URL hoặc API.                                                                            |
| Có `READ` không đủ để retrieval tài liệu nếu Document chưa `PUBLISHED`.                                                                                        |
| Có `READ` không đủ để retrieval một version không `ACTIVE` trong truy vấn hiện hành.                                                                           |
| Điều kiện sử dụng tài liệu cho truy vấn mặc định phải đồng thời thỏa điều kiện trạng thái và ACL.                                                              |
| Hệ thống phải áp dụng nguyên tắc fail-closed: nếu không xác định chắc chắn User có quyền thì từ chối truy cập.                                                 |
| Thay đổi Role, Group hoặc Department có ảnh hưởng tới authorization phải được phản ánh trong các request tiếp theo theo policy hệ thống.                       |
| Quyền truy cập không nên chỉ dựa trên thông tin stale được nhúng lâu trong JWT hoặc session.                                                                   |
| Tất cả hành động cấp, thay đổi và thu hồi quyền phải được ghi Audit Log.                                                                                       |
| Audit phải xác định được ai thực hiện, đối tượng nào, resource nào, permission nào, giá trị trước và sau, thời điểm thay đổi.                                  |
| Access Policy không được sử dụng để thay đổi trạng thái `PUBLISHED`, `ACTIVE`, `ARCHIVED` hoặc lifecycle của tài liệu.                                         |
| Metadata như `department = HR` không tự động đồng nghĩa `Department HR có READ` nếu business rule không định nghĩa như vậy.                                    |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                       |
| ------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể mở chức năng **Thiết lập quyền truy cập tài liệu**.                                   |
| Người không có quyền không thể thay đổi Access Policy.                                                              |
| Hệ thống hiển thị đúng các quyền hiện đang được cấu hình trên tài liệu.                                             |
| Admin có thể chọn đúng User, Role, Group hoặc Department để thiết lập quyền.                                        |
| Hệ thống không tạo Permission Assignment cho principal không tồn tại.                                               |
| Hệ thống không tạo permission không hợp lệ.                                                                         |
| Hệ thống không tạo bản ghi quyền trùng không cần thiết.                                                             |
| Khi User được cấp trực tiếp `READ`, User có quyền đọc tài liệu nếu các điều kiện trạng thái khác đều hợp lệ.        |
| Khi Group được cấp `READ`, thành viên hợp lệ của Group nhận quyền theo policy.                                      |
| Khi Department được cấp `READ`, người dùng thuộc Department nhận quyền theo policy.                                 |
| Khi User bị loại khỏi Group, quyền chỉ kế thừa từ Group đó không còn hiệu lực.                                      |
| Khi User chuyển Department, quyền kế thừa từ Department cũ và mới được tính lại chính xác.                          |
| Khi direct permission bị thu hồi nhưng User vẫn có quyền từ Group, hệ thống vẫn phản ánh đúng effective permission. |
| Khi User không còn bất kỳ nguồn `READ` hợp lệ nào, tài liệu không được đưa vào retrieval cho User đó.               |
| User không có `READ` không thể bypass quyền bằng cách biết `document_id`, URL hoặc API endpoint.                    |
| User không có `READ` không nhận được nội dung tài liệu trong RAG answer.                                            |
| Unauthorized chunk không được truyền đến LLM.                                                                       |
| Tài liệu chưa `PUBLISHED` không được retrieval dù User có `READ`.                                                   |
| Version không `ACTIVE` không được sử dụng mặc định dù User có `READ`.                                               |
| Tài liệu `ARCHIVED` không được sử dụng cho truy vấn hiện hành dù Permission Assignment vẫn còn.                     |
| Khi permission bị thu hồi, request tiếp theo phải sử dụng chính sách mới theo yêu cầu security của hệ thống.        |
| Mọi thay đổi quyền được ghi nhận trong Audit Log.                                                                   |
| Khi lưu policy thất bại, chính sách cũ vẫn được giữ nguyên.                                                         |
| Hai Admin thay đổi đồng thời không được gây mất dữ liệu hoặc ghi đè âm thầm.                                        |

### Dữ liệu liên quan

| Dữ liệu                    | Mục đích                                                                    |
| -------------------------- | --------------------------------------------------------------------------- |
| `access_policy_id`         | Định danh chính sách truy cập nếu hệ thống mô hình hóa policy riêng.        |
| `permission_assignment_id` | Định danh một cấu hình cấp quyền cụ thể.                                    |
| `principal_type`           | Loại đối tượng nhận quyền như `USER`, `ROLE`, `GROUP`, `DEPARTMENT`.        |
| `principal_id`             | Định danh đối tượng nhận quyền.                                             |
| `resource_type`            | Loại tài nguyên, ví dụ `DOCUMENT`.                                          |
| `resource_id`              | `document_id` hoặc resource tương ứng.                                      |
| `permission`               | Quyền được áp dụng như `READ`, `DOWNLOAD`, `MANAGE`.                        |
| `effect`                   | `ALLOW` hoặc `DENY` nếu mô hình policy hỗ trợ explicit deny.                |
| `status`                   | Trạng thái Permission Assignment nếu hệ thống hỗ trợ kích hoạt/vô hiệu hóa. |
| `created_by`               | Admin tạo permission.                                                       |
| `created_at`               | Thời điểm permission được tạo.                                              |
| `updated_by`               | Admin cập nhật permission gần nhất.                                         |
| `updated_at`               | Thời điểm permission được cập nhật.                                         |
| `revoked_by`               | Admin thu hồi quyền nếu có.                                                 |
| `revoked_at`               | Thời điểm quyền bị thu hồi.                                                 |

### Ghi chú thiết kế

Cần phân biệt hai tầng authorization.

#### Tầng 1 — Quyền chức năng

Trả lời câu hỏi:

```text
"User có được sử dụng chức năng này không?"
```

Ví dụ:

```text
User A
   ↓
Role EMPLOYEE
   ↓
ASK_KNOWLEDGE
```

Có nghĩa User A được phép sử dụng chức năng hỏi đáp.

Nhưng điều đó chưa xác định User được hỏi trên tài liệu nào.

---

#### Tầng 2 — Quyền tài nguyên

Trả lời:

```text
"User có được READ Document này không?"
```

Ví dụ:

```text
User A
   ↓
Group HR_POLICY_READERS
   ↓
READ
   ↓
DOC-001
```

Khi đó:

```text
Functional permission:
ASK_KNOWLEDGE = YES

Resource permission:
READ DOC-001 = YES
```

User mới có thể sử dụng DOC-001 trong RAG.

---

### Permission Assignment

Một quyền có thể hình dung:

```text
Principal
    +
Permission
    +
Resource
```

Ví dụ:

```text
GROUP HR_MANAGER
       +
      READ
       +
     DOC-001
```

Tương ứng:

```text
principal_type = GROUP
principal_id   = G001

permission     = READ

resource_type  = DOCUMENT
resource_id    = DOC-001
```

---

### Quyền từ nhiều nguồn

Ví dụ User A:

```text
User A
│
├── Direct Permission
│      └── READ DOC-001
│
├── Group HR
│      └── READ DOC-002
│
└── Department HR
       └── READ DOC-003
```

Kết quả:

```text
Effective permissions

DOC-001 → READ
DOC-002 → READ
DOC-003 → READ
```

Nếu Admin thu hồi:

```text
Direct READ DOC-001
```

nhưng Group HR cũng có:

```text
READ DOC-001
```

thì User vẫn được đọc DOC-001.

Vì vậy:

```text
REVOKE PERMISSION ASSIGNMENT
            ≠
USER CHẮC CHẮN MẤT QUYỀN
```

Hệ thống phải tính **effective permission**.

---

### Quan hệ với Department

Không nên dùng:

```text
Document.department = HR
```

để tự suy ra:

```text
HR → READ Document
```

trừ khi đây là business rule được định nghĩa rõ.

Thiết kế tách biệt:

```text
Document metadata

department = HR
```

nghĩa là:

> Tài liệu thuộc nghiệp vụ HR.

Còn:

```text
Access Policy

Department HR
      ↓
READ
      ↓
DOC-001
```

nghĩa là:

> Nhân viên HR được đọc DOC-001.

Hai việc khác nhau.

---

### Authorization trong RAG

Đây là phần đặc biệt quan trọng đối với hệ thống của bạn.

Không nên:

```text
User Question
      ↓
Search toàn Knowledge Base
      ↓
Top 20 chunks
      ↓
ACL filter
      ↓
LLM
```

vì hệ thống đã truy xuất candidate từ tài liệu User không có quyền.

Nên:

```text
User Question
      ↓
Xác định User hiện tại
      ↓
Resolve:
Role
Group
Department
Direct Permission
      ↓
Effective Permission
      ↓
Authorized Document IDs
      ↓
Retrieval chỉ trong tập được phép
      ↓
Dense + Sparse
      ↓
RRF / Rerank
      ↓
Evidence Gate
      ↓
LLM
```

Tức là:

```text
ACL BEFORE RETRIEVAL
```

hoặc ít nhất authorization phải được tích hợp vào truy vấn retrieval để unauthorized document không trở thành candidate.

Invariant nên là:

```text
Unauthorized retrieval rate = 0
```

và mạnh hơn:

```text
Unauthorized evidence sent to LLM = 0
```

---

### Điều kiện cuối cùng để một tài liệu được dùng trong RAG

Không chỉ:

```text
READ = TRUE
```

mà nên là:

```text
Document.status = PUBLISHED

AND

DocumentVersion.status = ACTIVE

AND

User effective permission contains READ
```

Có thể viết:

```text
CAN_USE_AS_KNOWLEDGE
=
PUBLISHED
AND ACTIVE
AND AUTHORIZED
```

Ví dụ:

```text
DOC-001
PUBLISHED

v3
ACTIVE

User A
READ = TRUE
```

→ được retrieval.

Nhưng:

```text
DOC-002
DRAFT

User A
READ = TRUE
```

→ vẫn không retrieval.

Hoặc:

```text
DOC-003
PUBLISHED

v4
READY_FOR_REVIEW

User A
READ = TRUE
```

→ v4 chưa được retrieval mặc định.

---

### Luồng tổng thể

```text
Admin
  ↓
Chọn tài liệu
  ↓
Thiết lập quyền truy cập
  ↓
Chọn Principal
(User / Role / Group / Department)
  ↓
Chọn Permission
  ↓
Kiểm tra policy hiện tại
  ↓
Xác định impact
  ↓
Admin xác nhận
  ↓
Lưu Permission Assignment
  ↓
Tính lại Effective Permission
  ↓
Audit
  ↓
Áp dụng cho request tiếp theo
```

Sau đó phía Employee:

```text
Employee đặt câu hỏi
        ↓
Resolve Principal Context
        ↓
Effective Permission
        ↓
Authorized Documents
        ↓
Retrieval
        ↓
Answer
```

Nguyên tắc quan trọng nhất:

```text
KHÔNG CÓ QUYỀN READ
        ↓
Document không được tham gia Retrieval
        ↓
Chunk không tới Reranker
        ↓
Evidence không tới LLM
```

Đây nên được coi là **security invariant P0** của Enterprise RAG Platform.

### Use case xem ma trận quyền

| Thuộc tính                        | Mô tả                                                                                                                                                                                                              |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Tên Use Case**                  | Xem ma trận quyền                                                                                                                                                                                                  |
| **Actor chính**                   | Quản trị viên                                                                                                                                                                                                      |
| **Mục tiêu**                      | Cho phép quản trị viên xem tổng quan các quyền truy cập đang được áp dụng giữa User, Role, Group, Department và tài liệu, từ đó xác định đối tượng nào có quyền gì trên tài liệu nào và quyền đó đến từ nguồn nào. |
| **Điều kiện kích hoạt**           | Quản trị viên truy cập chức năng **Xem ma trận quyền** trong khu vực quản lý người dùng và phân quyền.                                                                                                             |
| **Điều kiện tiên quyết**          | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản quản trị viên đang hoạt động.<br>3. Quản trị viên có quyền xem cấu hình phân quyền.<br>4. Dữ liệu User, Role, Group, Department và Access Policy đang khả dụng.     |
| **Đầu vào**                       | Không bắt buộc. Quản trị viên có thể chọn User, Role, Group, Department, Document hoặc loại Permission để lọc ma trận quyền.                                                                                       |
| **Trạng thái — Thành công**       | Hệ thống hiển thị ma trận quyền phù hợp với phạm vi quản trị viên được phép xem, bao gồm quyền được cấu hình, quyền hiệu lực và nguồn tạo ra quyền nếu có.                                                         |
| **Trạng thái — Không có dữ liệu** | Hệ thống hiển thị trạng thái không có cấu hình quyền phù hợp với điều kiện được chọn.                                                                                                                              |
| **Trạng thái — Thất bại**         | Hệ thống không hiển thị dữ liệu phân quyền nếu quản trị viên không có quyền hoặc dữ liệu không thể được xác định chính xác.                                                                                        |
| **Use Cases liên quan**           | Thiết lập quyền truy cập tài liệu, Cấp quyền, Thu hồi quyền, Kiểm tra quyền truy cập, Quản lý người dùng, Quản lý vai trò, Quản lý nhóm, Quản lý phòng ban                                                         |

### Main Flow

| Bước | Actor         | Hành động                                                                                  |
| ---: | ------------- | ------------------------------------------------------------------------------------------ |
|    1 | Quản trị viên | Truy cập chức năng **Xem ma trận quyền**.                                                  |
|    2 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                                |
|    3 | System        | Kiểm tra quản trị viên có quyền xem thông tin phân quyền hay không.                        |
|    4 | System        | Xác định phạm vi User, Role, Group, Department và Document mà quản trị viên được phép xem. |
|    5 | System        | Lấy các Access Policy và Permission Assignment đang có hiệu lực trong phạm vi đó.          |
|    6 | System        | Lấy thông tin quan hệ giữa User với Role, Group và Department.                             |
|    7 | System        | Xác định các nguồn quyền đang áp dụng cho từng đối tượng.                                  |
|    8 | System        | Tính hoặc lấy Effective Permission theo chính sách authorization hiện tại.                 |
|    9 | System        | Hiển thị ma trận quyền cho quản trị viên.                                                  |
|   10 | Quản trị viên | Chọn đối tượng hoặc tài liệu cần kiểm tra.                                                 |
|   11 | Quản trị viên | Có thể áp dụng bộ lọc theo User, Group, Department, Role, Document hoặc Permission.        |
|   12 | System        | Áp dụng điều kiện lọc trong phạm vi quản trị viên được phép xem.                           |
|   13 | System        | Hiển thị kết quả tương ứng.                                                                |
|   14 | Quản trị viên | Chọn một ô/quyền cụ thể để xem chi tiết nguồn quyền nếu cần.                               |
|   15 | System        | Hiển thị quyền là trực tiếp hay kế thừa và nguồn cấp quyền tương ứng.                      |

### Ví dụ ma trận quyền theo người dùng và tài liệu

| Người dùng | DOC-001 | DOC-002 | DOC-003 | DOC-004           |
| ---------- | ------- | ------- | ------- | ----------------- |
| User A     | `READ`  | `READ`  | —       | `READ + DOWNLOAD` |
| User B     | —       | `READ`  | `READ`  | —                 |
| User C     | `READ`  | —       | `READ`  | —                 |
| User D     | —       | —       | —       | —                 |

Trong đó:

```text
—
=
Không có quyền hiệu lực tương ứng
```

Nhưng ma trận không nên chỉ hiển thị:

```text
READ
```

mà khi Admin mở chi tiết cần biết:

```text
READ
↓
Đến từ đâu?
```

Ví dụ:

```text
User A → DOC-001 → READ

Source:
Group HR_MANAGER
```

hoặc:

```text
User A → DOC-002 → READ

Source:
Department HR
```

hoặc:

```text
User A → DOC-004 → READ

Sources:
- Direct Permission
- Group PROJECT_ALPHA
```

### Các chiều xem ma trận quyền

| Góc nhìn                   | Mục đích                                                                            |
| -------------------------- | ----------------------------------------------------------------------------------- |
| **User × Document**        | Xác định một User có quyền gì trên từng Document.                                   |
| **Group × Document**       | Xem quyền được cấp cho các Group.                                                   |
| **Department × Document**  | Xem quyền tài liệu theo phòng ban.                                                  |
| **Role × Document**        | Xem quyền resource được cấp thông qua Role nếu mô hình hệ thống hỗ trợ.             |
| **Document × Principal**   | Xem tất cả User/Group/Department/Role đang có quyền trên một tài liệu.              |
| **Permission × Principal** | Xem những đối tượng đang có một loại quyền cụ thể như `READ`, `DOWNLOAD`, `MANAGE`. |

### Thông tin hiển thị

| Thông tin                | Ý nghĩa                                                           |
| ------------------------ | ----------------------------------------------------------------- |
| **Principal**            | Đối tượng liên quan tới quyền: User, Role, Group hoặc Department. |
| **Document**             | Tài liệu được áp dụng quyền.                                      |
| **Permission**           | Quyền như `READ`, `DOWNLOAD`, `MANAGE`, `REVIEW`, `PUBLISH`...    |
| **Effective Permission** | Quyền thực tế của User sau khi tổng hợp các nguồn quyền hợp lệ.   |
| **Permission Source**    | Nguồn tạo ra quyền như Direct, Role, Group hoặc Department.       |
| **Assignment Status**    | Trạng thái của Permission Assignment nếu có.                      |
| **Document Status**      | Trạng thái tài liệu như `PUBLISHED`, `DRAFT`, `ARCHIVED`.         |
| **Version Status**       | Trạng thái phiên bản hiện tại như `ACTIVE`, `READY_FOR_REVIEW`.   |

### Luồng thay thế / luồng ngoại lệ

| Điều kiện                                                     | Luồng xử lý                                                                                                                       |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền xem ma trận quyền                | Hệ thống từ chối truy cập và không hiển thị dữ liệu phân quyền.                                                                   |
| Không có Permission Assignment nào                            | Hệ thống hiển thị ma trận trống hoặc thông báo chưa có cấu hình quyền.                                                            |
| Không tìm thấy dữ liệu phù hợp với bộ lọc                     | Hệ thống hiển thị trạng thái không có kết quả.                                                                                    |
| User không tồn tại                                            | Hệ thống không hiển thị User đó trong ma trận hiện tại.                                                                           |
| Document không tồn tại                                        | Hệ thống không đưa tài liệu đó vào kết quả hiện tại.                                                                              |
| Group hoặc Department đã bị vô hiệu hóa                       | Hệ thống phải hiển thị đúng trạng thái và không coi nguồn không còn hiệu lực là Effective Permission nếu policy quy định như vậy. |
| Direct Permission đã bị thu hồi nhưng User còn quyền từ Group | Ma trận phải hiển thị User vẫn có Effective Permission và chỉ rõ nguồn quyền còn lại.                                             |
| User thuộc nhiều Group cùng cấp một quyền                     | Hệ thống có thể hiển thị một Effective Permission nhưng phải cho phép xem tất cả nguồn tạo ra quyền đó.                           |
| User chuyển Department                                        | Hệ thống sử dụng Department hiện tại để tính Effective Permission.                                                                |
| Tài liệu `ARCHIVED` vẫn còn Permission Assignment             | Hệ thống có thể hiển thị assignment phục vụ quản trị nhưng phải chỉ rõ tài liệu không còn được sử dụng hiện hành.                 |
| Tài liệu chưa `PUBLISHED` nhưng User có `READ`                | Ma trận có thể hiển thị Permission Assignment nhưng phải phân biệt với khả năng sử dụng tài liệu trong Knowledge Base.            |
| Dữ liệu authorization không thể tính đầy đủ                   | Hệ thống không được suy đoán ALLOW; phải hiển thị trạng thái chưa xác định hoặc lỗi phù hợp.                                      |
| Dữ liệu có số lượng lớn                                       | Hệ thống hỗ trợ tìm kiếm, lọc, phân trang hoặc cơ chế tải phù hợp.                                                                |
| Dịch vụ phân quyền gặp lỗi                                    | Hệ thống trả lỗi có kiểm soát và không hiển thị quyền không xác định như quyền hợp lệ.                                            |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                               |
| ------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền xem cấu hình phân quyền mới được sử dụng chức năng này.                                                    |
| Ma trận quyền phải tuân theo phạm vi quản trị của Admin hiện tại.                                                                     |
| Hệ thống phải phân biệt **Permission Assignment** và **Effective Permission**.                                                        |
| Permission Assignment thể hiện một nguồn cấp quyền cụ thể.                                                                            |
| Effective Permission thể hiện quyền cuối cùng mà User thực sự có sau khi đánh giá tất cả nguồn quyền.                                 |
| Một User có thể nhận cùng một Permission từ nhiều nguồn khác nhau.                                                                    |
| Ma trận không được kết luận User mất quyền chỉ vì một Permission Assignment bị thu hồi nếu còn nguồn quyền hợp lệ khác.               |
| Hệ thống phải có khả năng xác định nguồn quyền như Direct, Role, Group hoặc Department.                                               |
| Nếu Group membership thay đổi, ma trận phải phản ánh Effective Permission mới.                                                        |
| Nếu Department của User thay đổi, ma trận phải phản ánh quyền theo Department hiện tại.                                               |
| Nếu Role của User thay đổi, các quyền liên quan phải được tính lại.                                                                   |
| Một tài liệu có Permission `READ` chưa chắc được phép sử dụng trong RAG nếu tài liệu chưa `PUBLISHED`.                                |
| Một phiên bản có Permission phù hợp chưa chắc được sử dụng nếu phiên bản không `ACTIVE`.                                              |
| Ma trận quyền không được thay đổi dữ liệu phân quyền; đây là Use Case chỉ đọc.                                                        |
| Các thao tác cấp hoặc thu hồi quyền phải được thực hiện qua Use Case tương ứng.                                                       |
| Hệ thống không được hiển thị tài liệu hoặc principal ngoài phạm vi mà Admin có quyền quản trị nếu scoped administration được áp dụng. |
| Khi không xác định được Effective Permission một cách chắc chắn, hệ thống phải áp dụng nguyên tắc fail-closed.                        |
| Ma trận phải phản ánh dữ liệu authorization hiện tại, không dựa hoàn toàn vào thông tin stale trong token/session.                    |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                   |
| --------------------------------------------------------------------------------------------------------------- |
| Quản trị viên có quyền có thể truy cập chức năng **Xem ma trận quyền**.                                         |
| Người không có quyền không thể xem ma trận quyền.                                                               |
| Hệ thống hiển thị đúng các User, Group, Role, Department và Document thuộc phạm vi quản trị.                    |
| Hệ thống hiển thị đúng Permission Assignment hiện tại.                                                          |
| Hệ thống hiển thị đúng Effective Permission của User.                                                           |
| Admin có thể xác định nguồn tạo ra một quyền cụ thể.                                                            |
| Khi User có quyền trực tiếp, hệ thống hiển thị nguồn `DIRECT`.                                                  |
| Khi User nhận quyền từ Group, hệ thống hiển thị Group tương ứng.                                                |
| Khi User nhận quyền từ Department, hệ thống hiển thị Department tương ứng.                                      |
| Khi User nhận quyền từ nhiều nguồn, hệ thống có thể hiển thị tất cả nguồn liên quan.                            |
| Khi một nguồn quyền bị thu hồi nhưng còn nguồn khác, Effective Permission vẫn được hiển thị chính xác.          |
| Khi không còn bất kỳ nguồn quyền hợp lệ nào, Effective Permission tương ứng không còn được hiển thị là `ALLOW`. |
| Khi User bị loại khỏi Group, ma trận phản ánh lại quyền sau thay đổi.                                           |
| Khi User chuyển Department, ma trận phản ánh lại quyền mới.                                                     |
| Khi Role của User thay đổi, quyền liên quan được phản ánh lại.                                                  |
| Tài liệu `ARCHIVED` được phân biệt rõ với tài liệu đang hoạt động.                                              |
| Tài liệu chưa `PUBLISHED` được phân biệt rõ với tài liệu có thể sử dụng trong Knowledge Base.                   |
| Admin có thể lọc ma trận theo User.                                                                             |
| Admin có thể lọc ma trận theo Group hoặc Department.                                                            |
| Admin có thể lọc ma trận theo Document.                                                                         |
| Admin có thể lọc theo loại Permission.                                                                          |
| Khi không có kết quả phù hợp, hệ thống hiển thị trạng thái không có dữ liệu thay vì báo lỗi.                    |
| Việc xem ma trận không làm thay đổi Access Policy hoặc Permission Assignment.                                   |

### Dữ liệu liên quan

| Dữ liệu                    | Mục đích                                                 |
| -------------------------- | -------------------------------------------------------- |
| `user_id`                  | Định danh User cần xác định quyền.                       |
| `role_id`                  | Định danh Role của User hoặc principal Role.             |
| `group_id`                 | Định danh Group liên quan.                               |
| `department_id`            | Định danh Department liên quan.                          |
| `document_id`              | Định danh tài liệu được kiểm tra quyền.                  |
| `principal_type`           | Loại principal: `USER`, `ROLE`, `GROUP`, `DEPARTMENT`.   |
| `principal_id`             | Định danh principal.                                     |
| `permission`               | Loại quyền được cấu hình.                                |
| `permission_assignment_id` | Định danh Permission Assignment cụ thể.                  |
| `permission_source`        | Nguồn quyền như `DIRECT`, `ROLE`, `GROUP`, `DEPARTMENT`. |
| `effective_permission`     | Quyền cuối cùng sau khi hệ thống đánh giá policy.        |
| `assignment_status`        | Trạng thái của Permission Assignment.                    |
| `document_status`          | Trạng thái hiện tại của Document.                        |
| `version_status`           | Trạng thái của phiên bản hiện tại.                       |

### Ghi chú thiết kế

Điểm quan trọng nhất của Use Case này là phân biệt:

```text
PERMISSION ASSIGNMENT
```

với:

```text
EFFECTIVE PERMISSION
```

#### Permission Assignment

Là một cấu hình quyền cụ thể.

Ví dụ:

```text
Group HR
   ↓
READ
   ↓
DOC-001
```

tương ứng:

```text
principal_type = GROUP
principal_id   = HR
permission     = READ
resource       = DOC-001
```

Đây chỉ là **một nguồn quyền**.

---

#### Effective Permission

Là câu trả lời cuối cùng:

```text
"User A thực sự có READ DOC-001 hay không?"
```

Ví dụ:

```text
User A
│
├── Group HR
│      └── READ DOC-001
│
├── Group PROJECT_A
│      └── READ DOC-001
│
└── Direct Permission
       └── READ DOC-001
```

Ma trận có thể hiển thị:

```text
User A
DOC-001
READ = YES

Sources:
✓ Group HR
✓ Group PROJECT_A
✓ Direct
```

Nếu Admin thu hồi:

```text
Direct READ
```

thì:

```text
Sources:
✗ Direct
✓ Group HR
✓ Group PROJECT_A

Effective READ:
YES
```

Do đó ma trận không được hiển thị đơn giản rằng:

```text
Direct permission removed
→ NO ACCESS
```

vì kết luận đó có thể sai.

---

### Ví dụ giao diện ma trận

```text
USER × DOCUMENT
──────────────────────────────────────────────────────────

              DOC-001       DOC-002       DOC-003
User A        READ           READ           —
User B        READ           —              READ
User C        —              READ           READ
```

Admin click:

```text
User A × DOC-001
```

hệ thống mở:

```text
Effective Permission
────────────────────────────

READ: YES

Sources:
✓ Department HR
✓ Group POLICY_READER

DOWNLOAD: NO

MANAGE: NO
```

Đây là thông tin hữu ích hơn nhiều so với chỉ:

```text
User A = READ
```

---

### Một User có nhiều nguồn quyền

Ví dụ:

```text
                     User A
                       │
          ┌────────────┼────────────┐
          │            │            │
          ↓            ↓            ↓
     Role EMPLOYEE   Group HR    Department HR
          │            │            │
          ↓            ↓            ↓
ASK_KNOWLEDGE      READ DOC-01   READ DOC-02
```

Ngoài ra:

```text
User A
  ↓
Direct Permission
  ↓
READ DOC-03
```

Ma trận cuối:

```text
DOC-01 → READ
DOC-02 → READ
DOC-03 → READ
```

nhưng mỗi quyền có nguồn khác nhau.

---

### Ma trận quyền không giống Access Policy

Access Policy là:

```text
Group HR
READ
DOC-001
```

Ma trận quyền là góc nhìn tổng hợp:

```text
Những User nào thực sự có READ DOC-001?
```

Ví dụ:

```text
Access Policies:

Group HR          → READ DOC-001
Group MANAGEMENT  → READ DOC-001
User U015         → READ DOC-001
```

Ma trận Effective Permission có thể trở thành:

```text
DOC-001

User A → READ
User B → READ
User C → READ
User D → READ
User U015 → READ
```

Do đó:

```text
ACCESS POLICY
=
Cấu hình quyền
```

còn:

```text
PERMISSION MATRIX
=
Góc nhìn tổng hợp kết quả của cấu hình quyền
```

---

### Ma trận quyền và trạng thái tài liệu

Một điểm rất dễ hiểu sai:

Giả sử:

```text
User A
READ DOC-001 = YES
```

nhưng:

```text
DOC-001.status = DRAFT
```

thì User A **có Permission Assignment**, nhưng chưa được sử dụng tài liệu đó trong RAG hiện hành.

Tương tự:

```text
User A
READ DOC-002 = YES

DOC-002 = ARCHIVED
```

User vẫn có thể còn assignment trong database phục vụ lịch sử, nhưng:

```text
CAN_USE_IN_CURRENT_RAG = NO
```

Vì điều kiện cuối phải là:

```text
PUBLISHED
AND
ACTIVE VERSION
AND
READ
```

Do đó nếu UI cho phép, nên phân biệt:

```text
Permission:
READ ✓

Knowledge availability:
Not available — Document is ARCHIVED
```

thay vì chỉ hiện:

```text
READ ✓
```

rồi khiến Admin tưởng User đang query được tài liệu.

---

### Quan hệ với Use Case Kiểm tra quyền truy cập

Hai Use Case này gần nhau nhưng khác nhau.

**Xem ma trận quyền** trả lời:

```text
"Tổng thể hệ thống đang phân quyền như thế nào?"
```

Ví dụ:

```text
User × Document
Department × Document
Group × Document
```

Trong khi **Kiểm tra quyền truy cập** trả lời một câu hỏi cụ thể:

```text
"User A có READ DOC-001 không?"
```

và tốt hơn nữa:

```text
"Tại sao?"
```

Ví dụ kết quả:

```text
User:
U001

Document:
DOC-001

Decision:
ALLOW

Permission:
READ

Reason:
User thuộc Group HR_MANAGER
và Group HR_MANAGER có READ DOC-001.
```

Do đó:

```text
Xem ma trận quyền
=
Overview
```

```text
Kiểm tra quyền truy cập
=
Explain one authorization decision
```

Nên giữ cả hai nếu bạn muốn phần Administration đủ mạnh.

---

### Luồng tổng thể

```text
Admin
  ↓
Xem ma trận quyền
  ↓
Chọn góc nhìn
  ↓
User / Group / Department / Document
  ↓
System lấy Access Policies
  ↓
Resolve Membership
  ↓
Resolve Permission Sources
  ↓
Tính Effective Permission
  ↓
Hiển thị Matrix
  ↓
Admin Filter / Drill-down
  ↓
Xem nguồn quyền
```

Nguyên tắc quan trọng nhất:

```text
MA TRẬN QUYỀN
≠
DANH SÁCH CÁC PERMISSION ASSIGNMENT
```

Ma trận tốt phải cho Admin biết:

```text
AI?
        +
Có quyền gì?
        +
Trên tài liệu nào?
        +
Quyền đến từ đâu?
        +
Quyền cuối cùng có thực sự hiệu lực không?
```

Đặc biệt với Enterprise RAG, câu hỏi cuối cùng phải có khả năng dẫn tới:

```text
User A
   ↓
READ DOC-001?
   ↓
YES
   ↓
DOC-001 có PUBLISHED?
   ↓
YES
   ↓
Active Version?
   ↓
YES
   ↓
Có thể tham gia Retrieval
```

Như vậy **Permission Matrix** không chỉ phục vụ giao diện Admin mà còn trở thành một công cụ rất hữu ích để kiểm tra xem hệ thống ACL của RAG đang hoạt động đúng hay không.

### Use case xem trạng thái xử lý tài liệu

| Thuộc tính                        | Mô tả                                                                                                                                                                                                                                                                                                 |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**                  | Xem trạng thái xử lý tài liệu                                                                                                                                                                                                                                                                         |
| **Actor chính**                   | Quản trị viên                                                                                                                                                                                                                                                                                         |
| **Mục tiêu**                      | Cho phép quản trị viên theo dõi trạng thái xử lý của một tài liệu hoặc một phiên bản tài liệu sau khi upload, tạo phiên bản mới hoặc yêu cầu xử lý lại, từ đó biết tài liệu đang chờ xử lý, đang xử lý, đã xử lý thành công hay xử lý thất bại.                                                       |
| **Điều kiện kích hoạt**           | Quản trị viên truy cập chức năng quản lý tài liệu và chọn xem trạng thái xử lý của một tài liệu hoặc phiên bản tài liệu.                                                                                                                                                                              |
| **Điều kiện tiên quyết**          | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản quản trị viên đang hoạt động.<br>3. Quản trị viên có quyền xem hoặc quản lý tài liệu tương ứng.<br>4. Tài liệu và `DocumentVersion` tồn tại trong hệ thống.<br>5. Tài liệu đã có ít nhất một Processing Job hoặc thông tin trạng thái xử lý tương ứng. |
| **Đầu vào**                       | `document_id`, `document_version_id`; có thể kèm bộ lọc theo trạng thái xử lý, thời gian, loại lỗi hoặc người upload.                                                                                                                                                                                 |
| **Trạng thái — Thành công**       | Hệ thống hiển thị trạng thái xử lý hiện tại, tiến trình và thông tin liên quan của phiên bản tài liệu; nếu có nhiều lần xử lý, hệ thống có thể hiển thị lịch sử các Processing Job.                                                                                                                   |
| **Trạng thái — Không có dữ liệu** | Hệ thống thông báo phiên bản chưa có quá trình xử lý hoặc chưa có dữ liệu trạng thái phù hợp.                                                                                                                                                                                                         |
| **Trạng thái — Thất bại**         | Hệ thống không hiển thị dữ liệu xử lý nếu quản trị viên không có quyền hoặc xảy ra lỗi khi truy xuất thông tin.                                                                                                                                                                                       |
| **Use Cases liên quan**           | Upload tài liệu, Xem chi tiết tài liệu, Tạo phiên bản tài liệu mới, Yêu cầu xử lý lại tài liệu, Kiểm duyệt tài liệu, Xem tài liệu xử lý lỗi                                                                                                                                                           |

### Main Flow

| Bước | Actor         | Hành động                                                                                                                    |
| ---: | ------------- | ---------------------------------------------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Truy cập chức năng **Quản lý tài liệu**.                                                                                     |
|    2 | Quản trị viên | Chọn tài liệu hoặc phiên bản cần theo dõi.                                                                                   |
|    3 | Quản trị viên | Chọn chức năng **Xem trạng thái xử lý**.                                                                                     |
|    4 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                                                                  |
|    5 | System        | Kiểm tra quyền xem tài liệu của quản trị viên.                                                                               |
|    6 | System        | Xác định `DocumentVersion` cần kiểm tra.                                                                                     |
|    7 | System        | Lấy Processing Job hiện tại hoặc Processing Job gần nhất của phiên bản.                                                      |
|    8 | System        | Xác định trạng thái hiện tại của Processing Job.                                                                             |
|    9 | System        | Lấy các thông tin liên quan như thời điểm tạo job, thời điểm bắt đầu, thời điểm hoàn tất, số lần thử và cảnh báo/lỗi nếu có. |
|   10 | System        | Hiển thị trạng thái xử lý hiện tại cho quản trị viên.                                                                        |
|   11 | Quản trị viên | Xem trạng thái và thông tin chi tiết của quá trình xử lý.                                                                    |
|   12 | Quản trị viên | Có thể xem lịch sử các lần xử lý trước nếu hệ thống hỗ trợ.                                                                  |
|   13 | Quản trị viên | Nếu quá trình xử lý thất bại, có thể chuyển sang Use Case **Yêu cầu xử lý lại tài liệu**.                                    |
|   14 | Quản trị viên | Nếu xử lý thành công và phiên bản đã `READY_FOR_REVIEW`, có thể chuyển sang Use Case **Kiểm duyệt tài liệu**.                |

### Các trạng thái xử lý chính

| Trạng thái  | Ý nghĩa                                                     |
| ----------- | ----------------------------------------------------------- |
| `PENDING`   | Yêu cầu xử lý đã được tạo nhưng chưa được worker tiếp nhận. |
| `RUNNING`   | Hệ thống đang xử lý tài liệu.                               |
| `SUCCEEDED` | Quá trình xử lý đã hoàn tất thành công.                     |
| `FAILED`    | Quá trình xử lý không hoàn tất do xảy ra lỗi.               |
| `CANCELLED` | Quá trình xử lý đã bị hủy nếu hệ thống hỗ trợ.              |

### Thông tin trạng thái có thể hiển thị

| Thông tin              | Ý nghĩa                                                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **Tên tài liệu**       | Tài liệu đang được theo dõi.                                                                                        |
| **Phiên bản**          | Phiên bản cụ thể đang được xử lý.                                                                                   |
| **Trạng thái xử lý**   | `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`...                                                                      |
| **Thời điểm tạo job**  | Thời điểm yêu cầu xử lý được tạo.                                                                                   |
| **Thời điểm bắt đầu**  | Thời điểm worker bắt đầu xử lý.                                                                                     |
| **Thời điểm hoàn tất** | Thời điểm job kết thúc.                                                                                             |
| **Thời gian xử lý**    | Khoảng thời gian job đã chạy hoặc đã hoàn thành.                                                                    |
| **Số lần xử lý**       | Số Processing Job hoặc số lần retry của phiên bản.                                                                  |
| **Cảnh báo**           | Các warning phát sinh nhưng không làm job thất bại.                                                                 |
| **Lỗi xử lý**          | Nguyên nhân thất bại nếu job có trạng thái `FAILED`.                                                                |
| **Bước hiện tại**      | Bước đang thực hiện như extraction, chunking, embedding, indexing nếu hệ thống hỗ trợ hiển thị tiến trình chi tiết. |
| **Người yêu cầu**      | Admin đã upload, tạo version hoặc yêu cầu reprocess.                                                                |

### Luồng thay thế / luồng ngoại lệ

| Điều kiện                                                             | Luồng xử lý                                                                                                                                    |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Quản trị viên không có quyền xem tài liệu                             | Hệ thống từ chối truy cập và không hiển thị thông tin xử lý.                                                                                   |
| Tài liệu không tồn tại                                                | Hệ thống thông báo tài liệu không còn khả dụng.                                                                                                |
| Phiên bản không tồn tại                                               | Hệ thống thông báo không tìm thấy phiên bản tương ứng.                                                                                         |
| Phiên bản chưa có Processing Job                                      | Hệ thống thông báo chưa có yêu cầu xử lý cho phiên bản.                                                                                        |
| Processing Job đang `PENDING`                                         | Hệ thống hiển thị rằng job đang chờ được xử lý.                                                                                                |
| Processing Job đang `RUNNING`                                         | Hệ thống hiển thị trạng thái đang xử lý và thông tin tiến trình nếu có.                                                                        |
| Processing Job `SUCCEEDED`                                            | Hệ thống thông báo xử lý thành công và trạng thái tiếp theo của phiên bản.                                                                     |
| Processing Job `FAILED`                                               | Hệ thống hiển thị lỗi phù hợp và cho phép quản trị viên thực hiện **Yêu cầu xử lý lại tài liệu** nếu có quyền.                                 |
| Processing Job bị `CANCELLED`                                         | Hệ thống hiển thị thời điểm và nguyên nhân hủy nếu có.                                                                                         |
| Có nhiều Processing Job cho cùng một phiên bản                        | Hệ thống hiển thị job hiện tại/gần nhất và cho phép xem lịch sử các job trước.                                                                 |
| Job mất heartbeat hoặc có dấu hiệu bị treo                            | Hệ thống hiển thị trạng thái bất thường theo cơ chế giám sát, không tự coi job là thành công.                                                  |
| Processing Job đã `SUCCEEDED` nhưng phiên bản chưa `READY_FOR_REVIEW` | Hệ thống hiển thị trạng thái không đồng bộ hoặc chờ bước hậu xử lý; không cho phép coi phiên bản đã sẵn sàng kiểm duyệt nếu điều kiện chưa đủ. |
| Dữ liệu trạng thái không đồng nhất                                    | Hệ thống không suy đoán trạng thái; hiển thị cảnh báo vận hành để Admin xử lý.                                                                 |
| Dịch vụ quản lý Processing Job không khả dụng                         | Hệ thống trả lỗi có kiểm soát và không hiển thị trạng thái cũ như trạng thái chắc chắn hiện tại.                                               |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                       |
| --------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền xem hoặc quản lý tài liệu mới được xem trạng thái xử lý của tài liệu đó.                                           |
| Trạng thái xử lý phải được quản lý ở cấp `ProcessingJob`, không được dùng chung với trạng thái của `Document` hoặc `DocumentVersion`.         |
| Một `DocumentVersion` có thể có nhiều Processing Job theo thời gian.                                                                          |
| Mỗi lần xử lý lại phải tạo một Processing Job mới thay vì ghi đè lịch sử job cũ.                                                              |
| Hệ thống phải xác định rõ Processing Job hiện tại hoặc Processing Job gần nhất của phiên bản.                                                 |
| Processing Job `PENDING` hoặc `RUNNING` không được coi là xử lý thành công.                                                                   |
| Chỉ Processing Job `SUCCEEDED` mới được coi là đã hoàn tất xử lý kỹ thuật.                                                                    |
| Processing Job `FAILED` không được làm phiên bản chuyển sang `READY_FOR_REVIEW`.                                                              |
| Processing Job `SUCCEEDED` không đồng nghĩa phiên bản đã `ACTIVE`.                                                                            |
| Sau khi xử lý thành công, phiên bản vẫn phải đi qua workflow kiểm duyệt trước khi được sử dụng chính thức nếu chính sách yêu cầu.             |
| Tài liệu đang xử lý không được tự động sử dụng làm nguồn trả lời Employee.                                                                    |
| Tài liệu xử lý thất bại không được tham gia Knowledge Base hiện hành.                                                                         |
| Phiên bản `ACTIVE` hiện tại không được bị ảnh hưởng chỉ vì một phiên bản candidate mới đang xử lý.                                            |
| Nếu một phiên bản `ACTIVE` được reprocess, kết quả xử lý mới chưa được kiểm duyệt không được tự động thay thế dữ liệu retrieval đang phục vụ. |
| Lỗi Processing Job phải được lưu ở mức đủ để Admin hiểu nguyên nhân nhưng không được làm lộ secret, credential hoặc stack trace nhạy cảm.     |
| Hệ thống phải giữ lịch sử thời điểm bắt đầu, kết thúc và kết quả của từng Processing Job.                                                     |
| Trạng thái hiển thị phải phản ánh dữ liệu hiện tại, không được coi cache cũ là trạng thái chắc chắn nếu đã hết hiệu lực.                      |
| Việc xem trạng thái là read-only và không được tự động tạo job mới.                                                                           |
| Yêu cầu chạy lại phải được thực hiện thông qua Use Case **Yêu cầu xử lý lại tài liệu**.                                                       |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                |
| ------------------------------------------------------------------------------------------------------------ |
| Quản trị viên có quyền có thể xem trạng thái xử lý của tài liệu.                                             |
| Người không có quyền không thể xem thông tin Processing Job của tài liệu.                                    |
| Hệ thống hiển thị đúng phiên bản đang được kiểm tra.                                                         |
| Hệ thống hiển thị đúng Processing Job hiện tại hoặc gần nhất.                                                |
| Job `PENDING` được hiển thị là đang chờ xử lý.                                                               |
| Job `RUNNING` được hiển thị là đang xử lý.                                                                   |
| Job `SUCCEEDED` được hiển thị là xử lý thành công.                                                           |
| Job `FAILED` được hiển thị là xử lý thất bại.                                                                |
| Khi job thất bại, Admin có thể xem thông tin lỗi phù hợp.                                                    |
| Khi job thất bại, Admin có thể chuyển sang **Yêu cầu xử lý lại tài liệu** nếu có quyền.                      |
| Khi xử lý thành công và phiên bản đủ điều kiện, Admin có thể nhận biết rằng phiên bản đã `READY_FOR_REVIEW`. |
| Processing Job `SUCCEEDED` không tự động làm Document hoặc Version trở thành `ACTIVE`.                       |
| Một phiên bản có nhiều lần xử lý phải giữ được lịch sử các Processing Job.                                   |
| Xử lý lại không làm mất thông tin job thất bại trước đó.                                                     |
| Hệ thống hiển thị đúng người yêu cầu và thời điểm tạo job nếu dữ liệu tồn tại.                               |
| Hệ thống hiển thị đúng thời điểm bắt đầu và hoàn thành job.                                                  |
| Hệ thống không hiển thị secret hoặc credential trong thông tin lỗi.                                          |
| Việc xem trạng thái không làm thay đổi trạng thái Processing Job.                                            |
| Khi dữ liệu trạng thái không xác định được, hệ thống không hiển thị sai rằng job đã thành công.              |

### Dữ liệu liên quan

| Dữ liệu                      | Mục đích                                                              |
| ---------------------------- | --------------------------------------------------------------------- |
| `document_id`                | Định danh tài liệu logic.                                             |
| `document_version_id`        | Định danh phiên bản đang được xử lý.                                  |
| `version_number`             | Số phiên bản để Admin dễ xác định.                                    |
| `processing_job_id`          | Định danh một lần xử lý cụ thể.                                       |
| `processing_status`          | Trạng thái `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`...             |
| `current_stage`              | Bước hiện tại của pipeline nếu hệ thống theo dõi chi tiết.            |
| `progress`                   | Tiến độ xử lý nếu hệ thống có khả năng xác định đáng tin cậy.         |
| `retry_count`                | Số lần thử lại hoặc số lần reprocess.                                 |
| `requested_by`               | Người tạo yêu cầu xử lý.                                              |
| `requested_at`               | Thời điểm yêu cầu xử lý được tạo.                                     |
| `started_at`                 | Thời điểm job bắt đầu.                                                |
| `completed_at`               | Thời điểm job kết thúc.                                               |
| `heartbeat_at`               | Thời điểm worker báo trạng thái gần nhất nếu hệ thống dùng heartbeat. |
| `processing_error`           | Thông tin lỗi khi job thất bại.                                       |
| `processing_warnings`        | Các cảnh báo của quá trình xử lý.                                     |
| `previous_processing_job_id` | Liên kết job trước nếu cần theo dõi chuỗi retry.                      |

### Ghi chú thiết kế

Cần phân biệt rõ ba loại trạng thái:

```text
Document
```

phản ánh **vòng đời nghiệp vụ của tài liệu**:

```text
DRAFT
PUBLISHED
ARCHIVED
```

---

```text
DocumentVersion
```

phản ánh **vòng đời của phiên bản**:

```text
DRAFT
READY_FOR_REVIEW
ACTIVE
REJECTED
SUPERSEDED
```

---

```text
ProcessingJob
```

phản ánh **quá trình xử lý kỹ thuật**:

```text
PENDING
RUNNING
SUCCEEDED
FAILED
```

Không nên gom thành:

```text
Document.status = PROCESSING
```

rồi sử dụng một field `status` cho toàn bộ hệ thống.

Ví dụ:

```text
Document DOC-001
Status: PUBLISHED

v3
Version Status: ACTIVE

v4
Version Status: DRAFT

Processing Job của v4
Status: RUNNING
```

Có nghĩa:

* DOC-001 hiện vẫn là tài liệu đã xuất bản.
* v3 vẫn đang là phiên bản chính thức.
* v4 là candidate version.
* v4 hiện đang được hệ thống xử lý.

Employee vẫn phải dùng:

```text
v3 ACTIVE
```

không dùng v4.

---

### Trạng thái sau Upload

Ví dụ Admin upload một tài liệu mới:

```text
Document DOC-010
        ↓
Version v1
        ↓
Processing Job #1
```

Ban đầu:

```text
Document:
DRAFT

Version:
DRAFT

Processing:
PENDING
```

Worker nhận job:

```text
Processing:
RUNNING
```

Sau khi thành công:

```text
Processing:
SUCCEEDED

Version:
READY_FOR_REVIEW
```

Sau đó mới:

```text
Admin Review
     ↓
Publish
```

và:

```text
Document:
PUBLISHED

Version:
ACTIVE
```

---

### Trường hợp xử lý thất bại

Ví dụ:

```text
v1
Processing Job #1
        ↓
      FAILED
```

Admin xem trạng thái:

```text
Status:
FAILED

Reason:
OCR_PROCESSING_ERROR
```

Sau đó:

```text
Admin
 ↓
Yêu cầu xử lý lại
 ↓
Processing Job #2
```

Lịch sử trở thành:

```text
DocumentVersion v1
│
├── Job #1
│    └── FAILED
│
└── Job #2
     └── RUNNING
```

Nếu Job #2 thành công:

```text
Job #2
SUCCEEDED
```

nhưng Job #1 vẫn được giữ:

```text
Job #1
FAILED
```

không nên ghi đè.

---

### Có nên hiển thị từng bước pipeline?

Có thể, nhưng đây là thông tin bổ sung.

Ví dụ:

```text
Processing
────────────────────────

✓ File Validation
✓ Extraction
✓ Structure Parsing
✓ Chunking
→ Embedding
○ Indexing
```

Tuy nhiên không nên biến:

```text
OCR
Chunking
Embedding
Indexing
```

thành các Use Case.

Chúng chỉ là **processing stages** của Processing Job.

Ở mức dữ liệu có thể dùng:

```text
current_stage = EMBEDDING
```

nhưng trạng thái tổng thể vẫn là:

```text
processing_status = RUNNING
```

---

### Progress %

Cần cẩn thận nếu UI hiển thị:

```text
Processing 72%
```

Nếu hệ thống không thực sự biết tổng lượng công việc còn lại, con số này dễ gây hiểu nhầm.

Với MVP, tôi nghiêng về:

```text
PENDING

RUNNING
Current stage: CHUNKING

SUCCEEDED

FAILED
```

thay vì cố tạo:

```text
37%
63%
91%
```

không đáng tin cậy.

---

### Quan hệ với Use Case Yêu cầu xử lý lại

Hai Use Case khác nhau:

```text
XEM TRẠNG THÁI XỬ LÝ
=
Read-only
```

Admin chỉ kiểm tra:

```text
Job đang thế nào?
```

Trong khi:

```text
YÊU CẦU XỬ LÝ LẠI
=
Command
```

Admin yêu cầu hệ thống:

```text
Tạo một Processing Job mới
```

Do đó flow hợp lý:

```text
Xem trạng thái
      ↓
    FAILED
      ↓
Admin chọn Reprocess
      ↓
Yêu cầu xử lý lại
```

không nên để việc mở trang trạng thái tự động retry.

---

### Quan hệ với kiểm duyệt

Nếu:

```text
Processing = SUCCEEDED
```

thì chưa đồng nghĩa:

```text
Version = ACTIVE
```

Luồng đúng:

```text
SUCCEEDED
     ↓
READY_FOR_REVIEW
     ↓
Kiểm duyệt
     ↓
Phê duyệt & xuất bản
     ↓
ACTIVE
```

Do đó UI có thể hiển thị:

```text
Processing Status:
SUCCEEDED

Version Status:
READY_FOR_REVIEW

Next Action:
Kiểm duyệt tài liệu
```

Đây sẽ dễ hiểu hơn rất nhiều so với chỉ:

```text
Status: SUCCESS
```

---

### Luồng tổng thể

```text
Admin
  ↓
Chọn Document
  ↓
Chọn Version
  ↓
Xem trạng thái xử lý
  ↓
System lấy Processing Job
  ↓
┌──────────┬───────────┬────────────┐
│          │           │            │
PENDING   RUNNING    SUCCEEDED     FAILED
│          │           │            │
↓          ↓           ↓            ↓
Chờ      Theo dõi   Review       Reprocess
```

Nguyên tắc quan trọng nhất:

```text
PROCESSING STATUS
≠
DOCUMENT STATUS
≠
VERSION STATUS
```

Ba trạng thái này phải được tách riêng ngay từ Domain Model và Database Schema. Nếu gom chúng vào một field `status`, các Use Case như **Upload, Reprocess, Review, Publish, Versioning và Archive** sau này sẽ rất dễ xung đột trạng thái.

### Use case xem tài liệu xử lý lỗi

| Thuộc tính                        | Mô tả                                                                                                                                                                                          |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Tên Use Case**                  | Xem tài liệu xử lý lỗi                                                                                                                                                                         |
| **Actor chính**                   | Quản trị viên                                                                                                                                                                                  |
| **Mục tiêu**                      | Cho phép quản trị viên xem danh sách các tài liệu hoặc phiên bản tài liệu có quá trình xử lý thất bại để xác định nguyên nhân, đánh giá mức độ ảnh hưởng và thực hiện hành động xử lý phù hợp. |
| **Điều kiện kích hoạt**           | Quản trị viên truy cập chức năng **Xem tài liệu xử lý lỗi** trong khu vực quản lý hoặc giám sát tài liệu.                                                                                      |
| **Điều kiện tiên quyết**          | 1. Quản trị viên đã đăng nhập.<br>2. Tài khoản quản trị viên đang hoạt động.<br>3. Quản trị viên có quyền xem trạng thái xử lý tài liệu.<br>4. Hệ thống quản lý Processing Job đang khả dụng.  |
| **Đầu vào**                       | Không bắt buộc. Quản trị viên có thể sử dụng bộ lọc theo thời gian, loại tài liệu, phòng ban, loại lỗi, phiên bản hoặc số lần retry.                                                           |
| **Trạng thái — Thành công**       | Hệ thống hiển thị danh sách các `DocumentVersion` có Processing Job thất bại cùng thông tin lỗi cần thiết để quản trị viên đánh giá và xử lý.                                                  |
| **Trạng thái — Không có dữ liệu** | Hệ thống thông báo hiện không có tài liệu xử lý lỗi phù hợp với phạm vi hoặc bộ lọc đang áp dụng.                                                                                              |
| **Trạng thái — Thất bại**         | Hệ thống không hiển thị dữ liệu nếu quản trị viên không có quyền hoặc không thể truy xuất trạng thái Processing Job một cách đáng tin cậy.                                                     |
| **Use Cases liên quan**           | Xem trạng thái xử lý tài liệu, Xem chi tiết tài liệu, Yêu cầu xử lý lại tài liệu, Tạo phiên bản tài liệu mới                                                                                   |

### Main Flow

| Bước | Actor         | Hành động                                                                                                                     |
| ---: | ------------- | ----------------------------------------------------------------------------------------------------------------------------- |
|    1 | Quản trị viên | Truy cập chức năng **Xem tài liệu xử lý lỗi**.                                                                                |
|    2 | System        | Kiểm tra phiên đăng nhập của quản trị viên.                                                                                   |
|    3 | System        | Kiểm tra quyền xem trạng thái xử lý tài liệu của quản trị viên.                                                               |
|    4 | System        | Xác định phạm vi tài liệu mà quản trị viên được phép xem.                                                                     |
|    5 | System        | Tìm các Processing Job có trạng thái `FAILED` trong phạm vi tương ứng.                                                        |
|    6 | System        | Liên kết mỗi Processing Job lỗi với đúng `DocumentVersion` và `Document`.                                                     |
|    7 | System        | Lấy thông tin lỗi, thời điểm xử lý, số lần thử và thông tin quản trị liên quan.                                               |
|    8 | System        | Sắp xếp danh sách theo tiêu chí mặc định, ví dụ thời điểm lỗi gần nhất.                                                       |
|    9 | System        | Hiển thị danh sách tài liệu xử lý lỗi.                                                                                        |
|   10 | Quản trị viên | Xem danh sách các tài liệu/phiên bản bị lỗi.                                                                                  |
|   11 | Quản trị viên | Có thể tìm kiếm, lọc hoặc sắp xếp danh sách.                                                                                  |
|   12 | Quản trị viên | Chọn một tài liệu lỗi để xem thông tin chi tiết.                                                                              |
|   13 | System        | Hiển thị trạng thái, lỗi và lịch sử Processing Job của phiên bản được chọn.                                                   |
|   14 | Quản trị viên | Xác định hành động tiếp theo như **Yêu cầu xử lý lại tài liệu** hoặc **Tạo phiên bản mới** nếu file nguồn/nội dung có vấn đề. |

### Thông tin hiển thị trong danh sách

| Thông tin               | Ý nghĩa                                                                                    |
| ----------------------- | ------------------------------------------------------------------------------------------ |
| **Tên tài liệu**        | Tên nghiệp vụ của tài liệu bị lỗi.                                                         |
| **Phiên bản**           | Phiên bản cụ thể có Processing Job thất bại.                                               |
| **Tên file**            | File nguồn của phiên bản.                                                                  |
| **Trạng thái xử lý**    | Thường là `FAILED`.                                                                        |
| **Bước xảy ra lỗi**     | Giai đoạn như extraction, OCR, chunking, embedding hoặc indexing nếu hệ thống có ghi nhận. |
| **Loại lỗi**            | Nhóm lỗi để Admin nhanh chóng phân loại nguyên nhân.                                       |
| **Thông báo lỗi**       | Mô tả lỗi ở mức an toàn và có ích cho quản trị viên.                                       |
| **Số lần xử lý**        | Số Processing Job hoặc số lần retry của phiên bản.                                         |
| **Thời điểm lỗi**       | Thời điểm job gần nhất kết thúc thất bại.                                                  |
| **Người yêu cầu xử lý** | Người upload hoặc yêu cầu reprocess gần nhất.                                              |
| **Phòng ban**           | Đơn vị liên quan đến tài liệu nếu có.                                                      |

### Ví dụ phân loại lỗi

| Nhóm lỗi               | Ví dụ                                                     |
| ---------------------- | --------------------------------------------------------- |
| **FILE_ERROR**         | File hỏng, không đọc được, cấu trúc file không hợp lệ.    |
| **UNSUPPORTED_FORMAT** | Định dạng file chưa được hệ thống hỗ trợ.                 |
| **OCR_ERROR**          | OCR thất bại hoặc không xử lý được trang scan.            |
| **EXTRACTION_ERROR**   | Không thể trích xuất nội dung từ tài liệu.                |
| **PARSING_ERROR**      | Lỗi trong quá trình chuyển nội dung sang cấu trúc nội bộ. |
| **CHUNKING_ERROR**     | Không thể tạo chunk hợp lệ.                               |
| **EMBEDDING_ERROR**    | Dịch vụ embedding thất bại hoặc trả lỗi.                  |
| **INDEXING_ERROR**     | Không thể ghi dữ liệu vào search/vector index.            |
| **STORAGE_ERROR**      | Không thể đọc/ghi file hoặc dữ liệu xử lý.                |
| **TIMEOUT**            | Processing Job vượt quá giới hạn thời gian xử lý.         |
| **SYSTEM_ERROR**       | Lỗi hệ thống không thuộc các nhóm nghiệp vụ trên.         |

### Luồng thay thế / luồng ngoại lệ

| Điều kiện                                                        | Luồng xử lý                                                                                                                          |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Quản trị viên không có quyền xem tài liệu lỗi                    | Hệ thống từ chối truy cập và không trả thông tin Processing Job.                                                                     |
| Không có Processing Job nào `FAILED`                             | Hệ thống hiển thị trạng thái không có tài liệu lỗi.                                                                                  |
| Không có dữ liệu phù hợp với bộ lọc                              | Hệ thống hiển thị danh sách trống và cho phép thay đổi điều kiện lọc.                                                                |
| Document đã bị `ARCHIVED` nhưng có Processing Job lỗi lịch sử    | Hệ thống có thể hiển thị trong lịch sử nếu Admin có quyền, nhưng phải thể hiện rõ Document đang `ARCHIVED`.                          |
| Phiên bản có Job cũ `FAILED` nhưng Job mới nhất đã `SUCCEEDED`   | Hệ thống không nên coi phiên bản hiện tại là đang lỗi; lỗi cũ chỉ xuất hiện trong lịch sử xử lý hoặc khi Admin chọn xem lịch sử lỗi. |
| Một phiên bản có nhiều Processing Job `FAILED`                   | Hệ thống hiển thị lần lỗi gần nhất và cho phép xem toàn bộ lịch sử.                                                                  |
| File nguồn không còn khả dụng                                    | Hệ thống hiển thị lỗi liên quan và không cho Reprocess nếu không còn source file hợp lệ.                                             |
| Lỗi do file nguồn sai hoặc nội dung file cần thay đổi            | Hệ thống hướng Admin sang **Tạo phiên bản tài liệu mới**, không dùng Reprocess để thay nội dung.                                     |
| Lỗi chỉ thuộc pipeline xử lý trong khi file nguồn vẫn hợp lệ     | Admin có thể thực hiện **Yêu cầu xử lý lại tài liệu**.                                                                               |
| Job mất heartbeat hoặc bị treo nhưng chưa được đánh dấu `FAILED` | Hệ thống không tự liệt kê là FAILED trừ khi cơ chế giám sát đã xác định job thất bại theo policy.                                    |
| Thông tin lỗi chứa dữ liệu kỹ thuật nhạy cảm                     | Hệ thống chỉ hiển thị thông tin đã được làm sạch, không lộ credential, secret hoặc stack trace nhạy cảm.                             |
| Dữ liệu Processing Job không đồng nhất                           | Hệ thống hiển thị cảnh báo và không tự kết luận sai trạng thái.                                                                      |
| Dịch vụ quản lý job không khả dụng                               | Hệ thống trả lỗi có kiểm soát thay vì hiển thị danh sách lỗi cũ như dữ liệu hiện tại.                                                |

### Quy tắc nghiệp vụ

| Quy tắc                                                                                                                                              |
| ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chỉ quản trị viên có quyền xem hoặc quản lý tài liệu mới được xem danh sách tài liệu xử lý lỗi trong phạm vi được cấp.                               |
| Một tài liệu chỉ nên được coi là **đang xử lý lỗi** khi Processing Job hiện tại/gần nhất có hiệu lực ở trạng thái `FAILED`.                          |
| Job `FAILED` trong lịch sử không đồng nghĩa phiên bản hiện tại vẫn lỗi nếu một Job mới hơn đã `SUCCEEDED`.                                           |
| Processing Job lỗi phải liên kết với đúng `DocumentVersion`.                                                                                         |
| Một `DocumentVersion` có thể có nhiều Processing Job theo thời gian.                                                                                 |
| Lịch sử job thất bại không được ghi đè hoặc xóa khi Admin yêu cầu xử lý lại.                                                                         |
| Processing Job `FAILED` không được làm phiên bản chuyển sang `READY_FOR_REVIEW`.                                                                     |
| Phiên bản đang xử lý lỗi không được trở thành `ACTIVE` hoặc được sử dụng làm nguồn tri thức chính thức.                                              |
| Nếu phiên bản candidate lỗi trong khi Document có phiên bản `ACTIVE` cũ, phiên bản `ACTIVE` cũ vẫn tiếp tục được sử dụng.                            |
| Reprocess chỉ phù hợp khi file nguồn và nội dung của `DocumentVersion` không thay đổi.                                                               |
| Nếu cần sửa hoặc thay file nguồn, phải sử dụng Use Case **Tạo phiên bản tài liệu mới**.                                                              |
| Hệ thống phải lưu loại lỗi, thời điểm lỗi và thông tin cần thiết để hỗ trợ Admin xác định nguyên nhân.                                               |
| Thông tin lỗi hiển thị cho Admin không được chứa password, access token, API key hoặc secret.                                                        |
| Stack trace kỹ thuật chi tiết nếu cần phải nằm trong hệ thống observability/log phù hợp, không nhất thiết hiển thị toàn bộ trên giao diện nghiệp vụ. |
| Việc xem danh sách tài liệu lỗi là read-only và không tự động retry job.                                                                             |
| Retry phải được thực hiện thông qua Use Case **Yêu cầu xử lý lại tài liệu**.                                                                         |
| Danh sách tài liệu lỗi phải phản ánh dữ liệu hiện tại, không chỉ dựa vào cache cũ.                                                                   |
| Các hành động quản trị phát sinh từ danh sách phải được kiểm tra quyền lại tại thời điểm thực hiện.                                                  |

### Các điều kiện nghiệm thu

| Các điều kiện                                                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------ |
| Quản trị viên có quyền có thể truy cập chức năng **Xem tài liệu xử lý lỗi**.                                                         |
| Người không có quyền không thể xem thông tin lỗi xử lý của tài liệu.                                                                 |
| Hệ thống chỉ hiển thị tài liệu thuộc phạm vi Admin được phép quản lý.                                                                |
| Phiên bản có Processing Job hiện tại `FAILED` xuất hiện trong danh sách lỗi.                                                         |
| Phiên bản có Job cũ `FAILED` nhưng Job mới `SUCCEEDED` không bị hiển thị sai là đang lỗi.                                            |
| Mỗi kết quả lỗi liên kết đúng với `Document` và `DocumentVersion`.                                                                   |
| Hệ thống hiển thị đúng trạng thái `FAILED`.                                                                                          |
| Hệ thống hiển thị đúng thời điểm lỗi nếu dữ liệu tồn tại.                                                                            |
| Hệ thống hiển thị đúng loại lỗi hoặc nhóm lỗi nếu có.                                                                                |
| Hệ thống hiển thị thông báo lỗi ở mức phù hợp cho Admin.                                                                             |
| Hệ thống không hiển thị password, token, secret hoặc credential trong thông tin lỗi.                                                 |
| Admin có thể mở chi tiết tài liệu/phiên bản từ danh sách lỗi.                                                                        |
| Admin có thể xem lịch sử các Processing Job nếu phiên bản đã được xử lý nhiều lần.                                                   |
| Khi file nguồn vẫn hợp lệ, Admin có thể chuyển sang **Yêu cầu xử lý lại tài liệu**.                                                  |
| Khi file nguồn cần thay đổi, Admin được hướng sang **Tạo phiên bản tài liệu mới**.                                                   |
| Việc xem danh sách lỗi không tự động tạo Processing Job mới.                                                                         |
| Khi không có tài liệu lỗi, hệ thống hiển thị trạng thái không có dữ liệu thay vì báo lỗi.                                            |
| Khi áp dụng bộ lọc, hệ thống trả đúng các tài liệu lỗi phù hợp.                                                                      |
| Sau khi Reprocess thành công, phiên bản không còn xuất hiện trong danh sách lỗi hiện tại nếu Processing Job mới nhất đã `SUCCEEDED`. |

### Dữ liệu liên quan

| Dữ liệu               | Mục đích                                                      |
| --------------------- | ------------------------------------------------------------- |
| `document_id`         | Định danh Document chứa phiên bản lỗi.                        |
| `document_version_id` | Định danh chính xác phiên bản xử lý lỗi.                      |
| `version_number`      | Xác định số phiên bản.                                        |
| `processing_job_id`   | Định danh Processing Job bị lỗi.                              |
| `processing_status`   | Trạng thái của Job, thông thường là `FAILED`.                 |
| `current_stage`       | Bước xử lý xảy ra lỗi nếu có.                                 |
| `error_code`          | Mã lỗi phục vụ phân loại.                                     |
| `error_type`          | Nhóm lỗi như `OCR_ERROR`, `INDEXING_ERROR`...                 |
| `error_message`       | Thông báo lỗi ở mức an toàn cho quản trị viên.                |
| `retry_count`         | Số lần thử hoặc xử lý lại.                                    |
| `requested_by`        | Người tạo yêu cầu xử lý.                                      |
| `requested_at`        | Thời điểm job được tạo.                                       |
| `started_at`          | Thời điểm job bắt đầu.                                        |
| `failed_at`           | Thời điểm job được xác định thất bại.                         |
| `heartbeat_at`        | Heartbeat gần nhất nếu hệ thống sử dụng worker heartbeat.     |
| `file_name`           | Tên file nguồn của phiên bản.                                 |
| `file_hash`           | Hỗ trợ kiểm tra file nguồn có còn đúng với version hay không. |
| `storage_location`    | Vị trí lưu file nguồn.                                        |
| `document_status`     | Trạng thái hiện tại của Document.                             |
| `version_status`      | Trạng thái hiện tại của DocumentVersion.                      |

### Ghi chú thiết kế

Cần phân biệt:

```text
XEM TRẠNG THÁI XỬ LÝ
```

với:

```text
XEM TÀI LIỆU XỬ LÝ LỖI
```

Use Case **Xem trạng thái xử lý tài liệu** tập trung vào:

```text
"Một tài liệu cụ thể hiện đang xử lý thế nào?"
```

Ví dụ:

```text
DOC-001 / v3

Processing:
RUNNING
```

Trong khi **Xem tài liệu xử lý lỗi** tập trung vào:

```text
"Trong toàn bộ phạm vi tôi quản lý,
những tài liệu nào hiện đang lỗi?"
```

Ví dụ:

```text
TÀI LIỆU XỬ LÝ LỖI
──────────────────────────────────────────────────
Document       Version   Stage        Error
──────────────────────────────────────────────────
DOC-001        v3        OCR          OCR_ERROR
DOC-015        v1        Embedding    TIMEOUT
DOC-021        v4        Indexing     INDEXING_ERROR
```

Do đó đây là một **dashboard/list use case**, còn `Xem trạng thái xử lý` thường là drill-down của từng tài liệu.

---

### Xác định tài liệu nào thực sự đang lỗi

Ví dụ:

```text
DocumentVersion v3
│
├── Job #1 → FAILED
└── Job #2 → SUCCEEDED
```

Phiên bản v3 hiện tại:

```text
KHÔNG còn được coi là đang xử lý lỗi
```

vì lần xử lý hợp lệ mới nhất đã thành công.

Job #1 vẫn tồn tại trong:

```text
Processing History
```

nhưng không nên khiến v3 xuất hiện trong:

```text
Current Failed Documents
```

Có thể dùng logic khái quát:

```text
Latest effective Processing Job
             ↓
          FAILED?
          /    \
        YES     NO
        ↓        ↓
   Hiển thị    Không hiển thị
   trong danh
   sách lỗi
```

Điểm này rất quan trọng nếu sau này Admin retry nhiều lần.

---

### Ví dụ một phiên bản lỗi

```text
Document DOC-010
"Quy định tài chính"

Version:
v2

Version Status:
DRAFT

Processing Job #17:
FAILED

Stage:
OCR

Error:
OCR_PROCESSING_ERROR
```

Admin mở chi tiết và phát hiện:

```text
Source file vẫn đúng
PDF scan chất lượng thấp
OCR engine bị lỗi
```

Hành động phù hợp:

```text
Yêu cầu xử lý lại
```

Luồng:

```text
FAILED
  ↓
Admin Reprocess
  ↓
Job #18
  ↓
RUNNING
  ↓
SUCCEEDED
  ↓
READY_FOR_REVIEW
```

Sau khi Job #18 thành công, tài liệu không còn nằm trong danh sách lỗi hiện tại.

---

### Nếu file nguồn sai

Ví dụ:

```text
DOC-010 v2

File:
quy_dinh_tai_chinh.pdf

Admin kiểm tra:
Upload nhầm file.
```

Không nên:

```text
Reprocess
```

vì reprocess cùng file sai vẫn tạo cùng nội dung sai.

Phải:

```text
Tạo phiên bản mới
     ↓
Upload file đúng
```

Có thể nhớ:

```text
PIPELINE ERROR
+
SOURCE FILE ĐÚNG
        ↓
REPROCESS
```

```text
SOURCE FILE / CONTENT SAI
        ↓
NEW VERSION
```

---

### Không nên hiển thị raw stack trace

Ví dụ backend có lỗi:

```text
ConnectionError:
postgres://admin:password@...
```

hoặc:

```text
OPENAI_API_KEY=...
```

không được đưa nguyên văn lên UI.

UI Admin nên nhận:

```text
Stage:
Embedding

Error Code:
EMBEDDING_PROVIDER_UNAVAILABLE

Message:
Không thể hoàn tất bước tạo embedding.
Vui lòng thử xử lý lại sau.
```

Chi tiết kỹ thuật sâu:

```text
stack trace
request payload
provider response
internal host
secret
```

nên nằm trong observability/log có quyền truy cập riêng.

---

### Quan hệ giữa ba Use Case

Có thể thiết kế navigation:

```text
Xem tài liệu xử lý lỗi
          ↓
Chọn DOC-001 v3
          ↓
Xem trạng thái xử lý
          ↓
FAILED
          ↓
Xem lỗi
          ↓
┌──────────────────────┐
│                      │
↓                      ↓
Pipeline lỗi        File/nội dung sai
│                      │
↓                      ↓
Yêu cầu xử lý lại   Tạo phiên bản mới
```

Đây là ranh giới khá sạch:

```text
Xem tài liệu xử lý lỗi
=
Tìm đối tượng có vấn đề
```

```text
Xem trạng thái xử lý
=
Hiểu trạng thái và lỗi cụ thể
```

```text
Yêu cầu xử lý lại
=
Ra lệnh chạy lại pipeline
```

---

### Luồng tổng thể

```text
Admin
  ↓
Xem tài liệu xử lý lỗi
  ↓
System lấy các Processing Job lỗi hiện tại
  ↓
Map về DocumentVersion
  ↓
Hiển thị danh sách
  ↓
Admin lọc / tìm kiếm
  ↓
Chọn phiên bản lỗi
  ↓
Xem nguyên nhân
  ↓
┌────────────────────────────┐
│                            │
Pipeline lỗi            Source/content sai
│                            │
↓                            ↓
Reprocess                New Version
```

Nguyên tắc quan trọng nhất:

```text
FAILED PROCESSING JOB
≠
FAILED DOCUMENT
```

Chính xác hơn phải hiểu:

```text
DocumentVersion
có lần xử lý hiện tại bị FAILED
```

vì `Document` có thể vẫn đang:

```text
PUBLISHED
```

và còn một version cũ:

```text
ACTIVE
```

đang phục vụ Employee bình thường.

Ví dụ:

```text
DOC-001 = PUBLISHED

v3 = ACTIVE
     Processing = SUCCEEDED

v4 = DRAFT
     Processing = FAILED
```

Khi đó **v4 là phiên bản xử lý lỗi**, nhưng **DOC-001 không phải toàn bộ tài liệu bị hỏng** và Employee vẫn có thể tiếp tục truy vấn v3.
