<p align="center">
  <img src="assets/icon_on_light.png" width="112" alt="LazyK logo">
</p>

<h1 align="center">LazyK</h1>
<p align="center"><b>Đọc truyện tranh mọi thứ tiếng, theo cách lười nhất.</b><br>
<i>Read comics in any language, the lazy way.</i></p>

---

LazyK là công cụ cho **Windows** giúp bạn đọc manga, manhwa, manhua, truyện tranh tiếng Anh **ngay trên trình duyệt** mà không cần chờ bản dịch. Bạn cứ cuộn trang như bình thường, LazyK sẽ:

1. chụp phần trang truyện đang hiện trên màn hình,
2. đọc chữ trong các bóng thoại bằng AI (Google Gemini hoặc Cloudflare Workers AI),
3. dịch cả trang sang **tiếng Việt**,
4. **tẩy chữ gốc và viết chữ dịch** vào đúng bóng thoại, như một bản scan đã được dịch sẵn.

> 🇬🇧 **English summary:** LazyK is a Windows overlay that captures the comic page in your browser, reads the speech bubbles with Gemini / Cloudflare AI, translates the whole page (to Vietnamese by default) and paints the translation over the original bubbles. You need Python 3.11+ (or the prebuilt `.exe`) and a free Gemini API key.

## ✨ Tính năng

- **Tự dịch khi bạn dừng cuộn** (chế độ Auto), hoặc chỉ dịch khi bấm phím tắt.
- Hỗ trợ **tiếng Nhật, Hàn, Trung, Anh**; đọc được chữ dọc của manga.
- **Tẩy bóng thoại theo đúng hình**; bóng thoại đen hoặc xám vẫn giữ màu gốc.
- Chữ dịch được **xếp vừa bóng thoại**, dòng giữa dài, dòng trên dưới ngắn, không có dòng một chữ.
- **Tự đổi model hoặc server khi bị báo bận / hết lượt** (Gemini ↔ Cloudflare).
- **3 chế độ**: AI đọc và dịch · Local OCR + AI dịch · Local OCR + **Google Translate** (miễn phí hoàn toàn, không cần API key).
- Trang đã dịch được **nhớ lại**: cuộn quay lại là hiện ngay, không tốn lượt API.
- **Thanh công cụ nhỏ luôn nổi trên cùng**, chọn được font chữ có sẵn trong Windows.
- Lớp dịch **hiện được trong ảnh chụp màn hình** (Print Screen, Snipping Tool).

## 📋 Yêu cầu

| | |
|---|---|
| Hệ điều hành | Windows 10 (bản 2004 trở lên) hoặc Windows 11 |
| Python | 3.11 trở lên *(không cần nếu dùng bản `.exe` ở mục Releases)* |
| API key | Google Gemini (**miễn phí**) và/hoặc Cloudflare Workers AI |
| Mạng | Cần có để cài thư viện và gọi AI |

Không cần card đồ hoạ mạnh: mặc định mọi xử lý AI đều chạy trên máy chủ của Google / Cloudflare. Nếu bật **Local OCR**, việc đọc chữ chạy trên máy bạn (CPU, hoặc card đồ hoạ qua DirectML nếu có).

## 🚀 Cài đặt

### Cách 1: Dùng bản `.exe` (dễ nhất)

1. Vào mục **[Releases](https://github.com/Maditor/LazyK/releases)**, tải file `LazyK-windows.zip` mới nhất.
2. Giải nén ra một thư mục bất kỳ, ví dụ `D:\LazyK`.
3. Mở **`LazyK.exe`**.

> Windows có thể cảnh báo *"Windows protected your PC"* vì ứng dụng chưa có chữ ký số. Bấm **More info → Run anyway**.

### Cách 2: Chạy từ mã nguồn

1. Cài **Python 3.11+** bằng **một trong hai cách**:

   **a) Bằng lệnh (nhanh nhất).** Mở **Command Prompt** (bấm `Win`, gõ `cmd`, Enter) rồi dán lệnh:
   ```bat
   winget install -e --id Python.Python.3.11 --override "/passive PrependPath=1 Include_launcher=1 Include_tcltk=1"
   ```
   Lệnh này tải và cài Python 3.11, **tự thêm vào PATH**, kèm *py launcher* và *tcl/tk* mà LazyK cần. Nếu Windows hỏi quyền, bấm **Yes**.

   > Máy báo `'winget' is not recognized`? Cài **App Installer** từ Microsoft Store (Windows 10 bản cũ), hoặc dùng cách b.

   **b) Bằng trình cài đặt.** Tải từ [python.org](https://www.python.org/downloads/windows/), mở file cài, **tick ô "Add python.exe to PATH"** rồi bấm *Install Now* (các mục khác để mặc định).

   **Kiểm tra:** **đóng CMD cũ, mở CMD mới** rồi gõ:
   ```bat
   py --version
   ```
   Hiện `Python 3.11.x` (hoặc mới hơn) là được.

   > Nếu gõ `python` mà Microsoft Store tự mở ra: vào *Settings → Apps → Advanced app settings → App execution aliases*, tắt hai mục *python.exe* và *python3.exe*.

2. Tải mã nguồn, chọn một trong hai cách:
   - Bấm nút **Code → Download ZIP** trên trang GitHub rồi giải nén.
   - Hoặc dùng Git (cài Git bằng `winget install -e --id Git.Git` nếu chưa có), mở CMD mới rồi gõ:
     ```bat
     cd /d %USERPROFILE%\Desktop
     git clone https://github.com/Maditor/LazyK.git
     ```
3. Mở thư mục `LazyK`, chạy **`setup.bat`** (bấm đúp). Nó tự tạo môi trường Python riêng và cài thư viện, mất khoảng 1–3 phút.
   Muốn chạy bằng lệnh thì:
   ```bat
   cd /d %USERPROFILE%\Desktop\LazyK
   setup.bat
   ```
4. Chạy **`run.bat`** mỗi khi muốn dùng.

## 🔑 Lấy API key

### Google Gemini (khuyên dùng, miễn phí)
1. Vào **[Google AI Studio → API keys](https://aistudio.google.com/api-keys)**, đăng nhập tài khoản Google.
2. Bấm **Create API key**, sao chép key (dạng `AIza...`).

### Cloudflare Workers AI (tuỳ chọn, làm dự phòng)
1. Đăng nhập **[Cloudflare Dashboard](https://dash.cloudflare.com/)** và sao chép **Account ID** (ở trang Overview hoặc trên thanh địa chỉ).
2. Vào **[API Tokens](https://dash.cloudflare.com/profile/api-tokens)** → **Create Token** → mẫu **Workers AI**, rồi sao chép token.

### Nhập key vào LazyK
Lần chạy đầu, cửa sổ **API & Models** tự mở ra (sau này mở lại bằng nút ⚙ → *API keys & models…*):
1. Chọn tab **Google Gemini**, dán key.
2. Bấm **Test connection**; thấy ✓ xanh là được.
3. Bấm **Save**.

Nếu nhập cả hai server và bật *Switch server when one runs out*, khi Gemini hết lượt LazyK sẽ tự chuyển sang Cloudflare (và ngược lại).

> 🔒 Key chỉ được lưu trong file `settings.json` cạnh ứng dụng, trên máy của bạn. **Đừng chia sẻ hoặc đăng file này lên mạng.**

## 📖 Cách dùng

1. Mở trang truyện trên **Chrome, Edge, Firefox, Brave, Opera, Vivaldi hoặc Cốc Cốc**.
2. **Cuộn trang như bình thường.** Khi bạn dừng lại khoảng 0,7 giây, LazyK tự chụp, đọc, dịch và hiện bản dịch.
3. Cuộn tiếp thì bản dịch cũ tự ẩn; dừng lại thì trang mới được dịch.

Chấm tròn trên thanh công cụ cho biết LazyK đang làm gì:
🟢 đang bật · 🔵 đang đọc chữ · 🟣 đang dịch · ⚪ tạm dừng · 🔴 có lỗi (rê chuột vào để xem chi tiết).

### Thanh công cụ

```
⋮⋮ 💬 ● On · Auto | Gemini · 3.5 Flash Lite ▾ | ↻  ❚❚  👁  ⛶ | ⚙  ‹  ✕
```

| Nút | Chức năng |
|---|---|
| `⋮⋮` / logo | Kéo để di chuyển thanh (vị trí được nhớ lại) |
| **Gemini · …▾** | Chọn server AI và model; bật/tắt tự đổi model / server. Cột *Mode* chọn ai đọc và ai dịch (nút hiện **Gemini · …**, **Local + Gemini** hoặc **Local + Google**) |
| **↻** | Dịch ngay trang đang xem |
| **❚❚** | Tạm dừng / chạy lại |
| **👁** | Ẩn / hiện bản dịch |
| **⛶** | Kéo một khung quanh trang truyện (chuyển sang màu cam khi đang dùng khung) |
| **⚙** | Cài đặt |
| **‹** | Thu gọn thanh (vẫn giữ ↻ ❚❚ 👁 ⛶) |
| **✕** | Thoát LazyK |

### Phím tắt

| Phím | Chức năng |
|---|---|
| `Alt + T` | Dịch ngay |
| `Esc` | Ẩn bản dịch |
| `Alt + Shift + T` | Tạm dừng / chạy lại |
| `Alt + Shift + A` | Đổi chế độ Auto ↔ Hotkey |
| `Alt + Shift + R` | Kéo khung chọn vùng |
| `Ctrl + Alt + Q` | Thoát |

### Cài đặt (nút ⚙)

Menu cài đặt **luôn mở trong lúc bạn chỉnh**; bấm lại ⚙, nhấn `Esc` hoặc bấm ra ngoài để đóng.

| Mục | Ý nghĩa |
|---|---|
| **Mode** | *Auto*: tự dịch khi dừng cuộn · *Hotkey only*: chỉ dịch khi bấm `Alt + T` |
| **Reading order** | *Manga*: đọc phải → trái · *Webtoon*: đọc trái → phải |
| **Source language** | Ngôn ngữ gốc: Tự nhận / Nhật / Hàn / Trung / Anh |
| **Capture** | Chụp *cả trang trình duyệt* hay chỉ *khung bạn đã kéo* |
| **Text** | Font chữ, **cỡ chữ tối thiểu** (chữ dịch không bao giờ nhỏ hơn cỡ này), hiện bản dịch trong ảnh chụp màn hình |

### Kéo khung chọn vùng (⛶)
Hữu ích khi trang đọc truyện có menu, bình luận hoặc nền rối bên cạnh. Bấm **⛶**, màn hình tối lại, **kéo một khung ôm sát trang truyện** rồi thả chuột. Từ đó LazyK chỉ đọc trong khung này, kể cả sau khi mở lại. Muốn bỏ khung: ⚙ → *Capture* → *Browser page*.

### Chọn chế độ: ai đọc chữ, ai dịch

Bấm nút server trên thanh công cụ, cột **Mode** có 3 lựa chọn:

| Chế độ | Đọc chữ | Dịch | Khi nào dùng |
|---|---|---|---|
| **AI · reads and translates** (mặc định) | Gemini / Cloudflare | Gemini / Cloudflare | Dịch hay nhất, hiểu mạch truyện, bỏ qua tiếng động (SFX) |
| **Local OCR + AI translation** | Máy bạn | Gemini / Cloudflare | Vẫn dịch hay, đỡ tốn lượt AI nhiều vì AI chỉ nhận chữ |
| **Local OCR + Google Translate** | Máy bạn | Google Translate | Nhanh nhất, **không cần API key**, không lo hết lượt; bản dịch kém tự nhiên hơn |

- Ở chế độ Google: nếu Google tạm chặn (lỗi 429) và bạn có nhập key AI, trang đó được AI dịch thay. Bấm **Test Google Translate** trong menu để kiểm tra.
- Google dịch từng bóng thoại riêng, không biết mạch truyện, nên xưng hô và câu kéo qua nhiều bóng sẽ kém hơn AI.

### Local OCR (đọc chữ ngay trên máy)

Mục **Local OCR models…** trong menu mở cửa sổ quản lý model:

| Model | Dung lượng | Dùng cho |
|---|---|---|
| PP-OCRv6 (PaddleOCR) | có sẵn | Tiếng Nhật (cả chữ dọc), Trung, Anh |
| PP-OCRv5 Korean | 13 MB | Tiếng Hàn (manhwa, webtoon): **cần tải** |
| manga-ocr | 460 MB | Tuỳ chọn: đọc chữ vẽ tay trong manga Nhật chính xác hơn, chậm hơn |

- Model tải về được lưu ở `%LOCALAPPDATA%\LazyK\models`, build lại hay cài lại LazyK vẫn còn.
- **Use the graphics card**: chạy trên card đồ hoạ qua DirectML (NVIDIA, AMD, Intel đều được). Không có thì tự chạy bằng CPU.
- **Source language = Any**: LazyK thử model đã đúng ở trang trước; nếu đọc không chắc thì thử thêm model kia (Nhật/Trung/Anh ↔ Hàn). Đọc truyện Hàn thì nên tải model Korean; chọn hẳn *Source language* sẽ nhanh hơn.
- Trang đầu tiên chậm hơn vài giây vì phải nạp model; các trang sau nhanh.
- Tốc độ tham khảo (trang khoảng 10 bóng thoại): CPU khoảng 1–3 giây cho PP-OCR, thêm 0,2–0,5 giây mỗi bóng nếu dùng manga-ocr; card đồ hoạ nhanh hơn nhiều. Phần dịch bằng AI tính riêng.
- Local OCR không phân biệt được tiếng động (SFX) với lời thoại như AI, nên chữ SFX vẽ to có thể cũng được dịch.

## 💡 Mẹo để dịch đẹp hơn

- **Phóng to trang truyện** trong trình duyệt (`Ctrl` + `+`) để AI đọc chữ chính xác hơn và chữ dịch to, dễ đọc hơn.
- Chọn đúng **Reading order**: *Manga* cho truyện Nhật, *Webtoon* cho truyện Hàn/cuộn dọc.
- Đặt đúng **Source language** thay vì *Any* nếu truyện chỉ có một thứ tiếng.
- Thấy chữ dịch bị tràn ra ngoài bóng thoại? Giảm **cỡ chữ tối thiểu** trong ⚙ → *Text* một chút.
- Model có chữ **"lite"** nhanh và nhiều lượt miễn phí hơn; model **không "lite"** (ví dụ `gemini-3.5-flash`) hiểu ngữ cảnh và xưng hô tốt hơn.
- Dùng một font truyện tranh hỗ trợ tiếng Việt (⚙ → *Text* → *Font…*) để trông giống bản dịch thật.

## 🛠️ Xử lý sự cố

<details>
<summary><b>Không thấy bản dịch hiện ra</b></summary>

- Kiểm tra chấm trên thanh công cụ: nếu đỏ, rê chuột vào để xem lỗi.
- Chế độ *Hotkey only* thì phải bấm `Alt + T`.
- Chế độ *Auto* chỉ phản ứng khi cuộn trong trình duyệt được hỗ trợ (danh sách `auto_apps` trong `settings.json`).
- Bấm ⚙ → *API keys & models…* → **Test connection** để kiểm tra key.
</details>

<details>
<summary><b>Báo "Rate limited", "busy" hoặc hết lượt</b></summary>

Tài khoản miễn phí có giới hạn số lượt theo phút / ngày. Bật **Auto-switch model** và **Auto-switch server** trong menu server để LazyK tự đổi sang model / server khác, hoặc chờ vài phút rồi thử lại.
</details>

<details>
<summary><b>Bản dịch bị lệch khỏi bóng thoại</b></summary>

- Không đổi mức phóng to của Windows (Display scale) trong lúc LazyK đang chạy.
- Thử kéo khung ⛶ ôm sát trang truyện.
- Mở `settings.json`, đặt `"debug_save": true`, chạy lại; ảnh chụp và vị trí AI trả về sẽ được lưu trong `logs\debug\` để kiểm tra.
</details>

<details>
<summary><b>setup.bat báo lỗi không tìm thấy Python</b></summary>

- Mở CMD **mới** và gõ `py --version`. Nếu báo lỗi, cài lại Python theo mục *Cài đặt → Cách 2* (lệnh `winget` đã tự thêm PATH).
- Nếu cài bằng file từ python.org, nhớ tick **"Add python.exe to PATH"**.
- Sau khi cài xong, đóng mọi cửa sổ CMD rồi chạy lại `setup.bat`.
</details>

<details>
<summary><b>setup.bat báo "Fatal error in launcher: Unable to create process"</b></summary>

Thư mục `.venv` được chép hoặc di chuyển từ chỗ khác sang, nên vẫn trỏ về đường dẫn cũ. Bản `setup.bat` mới tự phát hiện và tạo lại `.venv`. Nếu vẫn lỗi, xoá thư mục `.venv` rồi chạy lại:

```bat
rmdir /s /q .venv
setup.bat
```
Đừng chép `.venv` sang máy hoặc thư mục khác. Mỗi nơi chỉ cần chạy `setup.bat` một lần.
</details>

<details>
<summary><b>Xem log ở đâu?</b></summary>

`logs\lazyk.log` trong thư mục của LazyK.
</details>

## 📦 Tự đóng gói file `.exe`

Sau khi chạy `setup.bat`, chạy **`build_exe.bat`**. Script làm 4 bước:
1. Tự tắt LazyK nếu đang chạy (để file cũ không bị khoá), rồi cài PyInstaller.
2. Đóng gói vào `dist\LazyK\`.
3. Giữ lại `settings.json` của bản build trước (API key, vị trí thanh công cụ…). Nếu chưa có bản build trước thì chép `settings.json` từ thư mục mã nguồn.
4. Tạo lối tắt **LazyK** ngoài Desktop.

⚠️ Chỉ chạy `LazyK.exe` trong `dist\LazyK`, **không** chạy file trong thư mục `build` (đó chỉ là file nháp, sẽ báo *Failed to load Python DLL*; script tự xoá nó). Đừng tách `LazyK.exe` ra khỏi thư mục `_internal` đi kèm.

🔒 `dist\LazyK` có `settings.json` chứa API key của bạn, nên **đừng nén nguyên thư mục này gửi người khác**. Để chia sẻ, dùng `build_installer.bat` bên dưới: file cài đặt tự bỏ `settings.json` và thư mục log ra.

### Tạo file cài đặt (Setup.exe)

Sau khi `build_exe.bat` chạy xong, chạy **`build_installer.bat`**. Nếu máy chưa có Inno Setup, script sẽ tự cài bằng `winget`. Muốn ghi số phiên bản thì thêm vào sau lệnh, ví dụ `build_installer.bat 1.2.0`.

Kết quả là một file duy nhất `Output\LazyK-Setup-<phiên bản>.exe`. Người nhận chỉ cần chạy file này:
- Không cần quyền Administrator, không cần Python: mọi thư viện đã nằm sẵn trong bản build.
- LazyK được cài vào `%LOCALAPPDATA%\Programs\LazyK`, có lối tắt ở Start Menu (và ngoài Desktop nếu chọn).
- Gỡ bằng *Settings → Apps* như ứng dụng bình thường. Khi gỡ, `settings.json` (chứa API key) và thư mục log cũng bị xoá.

## 🔐 Quyền riêng tư

- LazyK chỉ gửi **ảnh vùng trang truyện** và **chữ cần dịch** tới dịch vụ AI bạn chọn (Google Gemini hoặc Cloudflare). Không có máy chủ trung gian nào khác.
- API key và cài đặt nằm trong `settings.json` trên máy bạn.

## 🧑‍💻 Dành cho nhà phát triển

Cấu trúc mã nguồn, cách hoạt động và toàn bộ tuỳ chọn trong `settings.json`: xem **[docs/DEVELOPER.md](docs/DEVELOPER.md)**.

## 📄 Giấy phép

Xem file [LICENSE](LICENSE).
