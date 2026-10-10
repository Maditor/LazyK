<p align="center">
  <img src="assets/icon_on_light.png" width="112" alt="LazyK logo">
</p>

<h1 align="center">LazyK</h1>
<p align="center"><b>Đọc truyện tranh và chơi visual novel mọi thứ tiếng, theo cách lười nhất.</b><br>
<i>Read comics and play visual novels in any language, the lazy way.</i></p>

---

LazyK là công cụ cho **Windows** giúp bạn đọc manga, manhwa, manhua, truyện tranh tiếng Anh **ngay trên trình duyệt** mà không cần chờ bản dịch. Bạn cứ cuộn trang như bình thường, LazyK sẽ:

1. chụp phần trang truyện đang hiện trên màn hình,
2. đọc chữ trong các bóng thoại bằng AI (Google Gemini hoặc Cloudflare Workers AI),
3. dịch cả trang sang **tiếng Việt**,
4. **tẩy chữ gốc và viết chữ dịch** vào đúng bóng thoại, như một bản scan đã được dịch sẵn.

Không chỉ truyện tranh: LazyK còn dịch **visual novel và game có hộp thoại** ngay trên màn hình (xem [Chế độ Visual novel](#chế-độ-visual-novel)), và có thể **đọc to bản dịch** bằng giọng nói (xem [Text to speech](#text-to-speech)).

> 🇬🇧 **English summary:** LazyK is a Windows overlay that captures the comic page in your browser, reads the speech bubbles with Gemini / Cloudflare AI, translates the whole page (to Vietnamese by default) and paints the translation over the original bubbles. It also translates **visual novels / games with a dialogue box** line by line, can **read the translation aloud** (a local Piper voice or Edge online voices, adjustable speed and volume) and keeps a temporary **record of the session's translations**. By default it reads the page on your PC and translates with Google Translate, so no API key is needed; a free Gemini key unlocks the AI modes. You need Python 3.11+ (or the prebuilt `.exe`).

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
- **Chế độ Visual novel**: dịch từng dòng thoại của game trong một khung nhỏ do bạn chọn, tự quét khi chữ đổi (tuỳ chọn), bản dịch phủ lên hộp thoại với màu của chính hộp thoại.
- **Đọc to bản dịch** (tuỳ chọn, mặc định tắt): dịch xong là đọc luôn bằng giọng chạy trên máy (Piper) hoặc giọng online của Microsoft Edge, chỉnh được **tốc độ** và **âm lượng**, cuộn trang là dừng.
- **Bản ghi dịch tạm**: phần đã dịch của phiên làm việc được ghi vào `record-lazyk.txt` để xem lại, tự xoá khi thoát LazyK.

## 📋 Yêu cầu

| | |
|---|---|
| Hệ điều hành | Windows 10 (bản 2004 trở lên) hoặc Windows 11 |
| Python | 3.11 trở lên *(không cần nếu dùng bản `.exe` ở mục Releases)* |
| API key | **Không cần** để bắt đầu (mặc định: Local OCR + Google Translate). Muốn AI dịch hay hơn thì thêm Google Gemini (**miễn phí**) và/hoặc Cloudflare Workers AI |
| Mạng | Cần có để cài thư viện và gọi AI (và để dùng giọng đọc nếu bật *Text to speech*) |

Không cần card đồ hoạ mạnh: mặc định LazyK đọc chữ ngay trên máy bạn (**Local OCR**, chạy trên CPU hoặc card đồ hoạ qua DirectML nếu có) rồi dịch bằng **Google Translate**, nên mở lên là dùng được ngay, không phải nhập key. Chọn chế độ AI thì việc đọc và dịch chạy trên máy chủ của Google / Cloudflare.

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

## 🔑 Lấy API key (tuỳ chọn)

Chỉ cần khi bạn chọn chế độ có AI (nút server → *AI · reads and translates* hoặc *Local OCR + AI translation*). Chế độ mặc định *Local OCR + Google Translate* không cần key.

### Google Gemini (khuyên dùng, miễn phí)
1. Vào **[Google AI Studio → API keys](https://aistudio.google.com/api-keys)**, đăng nhập tài khoản Google.
2. Bấm **Create API key**, sao chép key (dạng `AIza...`).

### Cloudflare Workers AI (tuỳ chọn, làm dự phòng)
1. Đăng nhập **[Cloudflare Dashboard](https://dash.cloudflare.com/)** và sao chép **Account ID** (ở trang Overview hoặc trên thanh địa chỉ).
2. Vào **[API Tokens](https://dash.cloudflare.com/profile/api-tokens)** → **Create Token** → mẫu **Workers AI**, rồi sao chép token.

### Nhập key vào LazyK
Khi bạn chọn chế độ có AI mà chưa có key, cửa sổ **API & Models** tự mở ra (mở lại lúc nào cũng được bằng nút ⚙ → *API keys & models*):
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
| **Gemini · …▾** | Menu gọn một cột: chọn ai đọc và ai dịch (nút hiện **Gemini · …**, **Local + Gemini** hoặc **Local + Google**). **OCR device** chọn CPU hay card đồ hoạ; **AI server**, **Model**, **Auto-switch** là các menu con |
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
| `Alt + T` | Dịch ngay (đổi được ở ⚙ → Hotkeys → Translate key) |
| `Esc` | Ẩn bản dịch |
| `Alt + Shift + T` | Tạm dừng / chạy lại |
| `Alt + Shift + A` | Đổi chế độ Auto ↔ Hotkey |
| `Alt + Shift + R` | Kéo khung chọn vùng |
| `Alt + Shift + V` | Visual novel: bật / tắt tự quét khi chữ đổi (đổi được ở ⚙ → Hotkeys → Auto-scan key) |
| `Ctrl + Alt + Q` | Thoát |

### Preset (cài đặt có sẵn)

Ô **preset** trên thanh công cụ (mặc định ghi **Default**) giữ cả một bộ cài đặt dưới một cái tên; bấm chọn là đổi hết trong một lần. Tiện khi bạn đọc nhiều loại: ví dụ *Manga JP*, *Webtoon KR*, *Game VN*.

* **Default** luôn có sẵn, không đổi tên và không xoá được.
* **Tự lưu:** preset đang dùng tự giữ mọi thay đổi bạn chỉnh (font, ngôn ngữ, chế độ…), không cần bấm lưu. Chọn preset khác rồi quay lại thì mọi thứ vẫn như lần cuối bạn để.
* **Create new preset:** lấy đúng cài đặt đang dùng làm preset mới, mở hộp nhỏ để đặt tên (**Save** / **Cancel**). Preset mới trở thành preset đang dùng; preset cũ giữ nguyên.
* **Rename** / **Delete** cho preset đang dùng (trừ Default). Xoá preset đang dùng thì quay về Default.

Một preset lưu: thứ tự đọc (Manga / Webtoon / Visual novel), chế độ Auto / Hotkey, khung chụp và khung hộp thoại VN, ngôn ngữ gốc và đích, ai đọc / ai dịch, server AI, thiết bị đọc chữ, font, cỡ chữ, *Auto text size*, màu chữ và màu ô, độ trong suốt / mờ, *Text box* (cả vị trí và kích thước ô), *Hide the box under the mouse*, và *Text to speech* (bật/tắt, tốc độ, âm lượng). Preset **không** lưu API key và phím tắt.

### Cài đặt (nút ⚙)

Menu cài đặt **luôn mở trong lúc bạn chỉnh**; bấm lại ⚙, nhấn `Esc` hoặc bấm ra ngoài để đóng. Mục nào có dấu `›` thì mở thêm một menu con bên cạnh.

| Mục | Ý nghĩa |
|---|---|
| **Reading order** | *Manga*: đọc phải → trái · *Webtoon*: đọc trái → phải · *Visual novel · text box*: dịch game visual novel (xem bên dưới) |
| **Scanning** | Manga / Webtoon: *Auto* (tự dịch khi dừng cuộn) hay *Hotkey only*; chụp *cả trang trình duyệt* hay *khung bạn đã kéo*; *Draw a new frame*. Visual novel: *Auto-scan when text changes* và *Text box frame*. LazyK nhận ra trang đang cuộn bằng cả con lăn chuột lẫn cách nhìn trang dịch lên/xuống, nên touchpad, kéo thanh cuộn hay phím mũi tên đều được (tắt cách nhìn trang: `"scroll_watch": false` trong `settings.json`) |
| **Language** | Hai cột: **From** (ngôn ngữ gốc: tự nhận / Nhật / Hàn / Trung / Anh) và **To** (ngôn ngữ đích: Việt, Anh, Nhật, Hàn, Trung giản thể / phồn thể, Thái, Indonesia, Tây Ban Nha, Pháp, Đức, Bồ Đào Nha, Nga). Giọng đọc *Text to speech* tự đổi theo ngôn ngữ đích |
| **Look** | Chia 3 nhóm. **Text**: **Font**, **Minimum size** (chữ dịch không bao giờ nhỏ hơn cỡ này), *Auto text size* (bật: ô rộng thì chữ to dần, tối đa 1,6 lần · tắt: chữ luôn đúng *Minimum size*, cỡ chữ ổn định, hợp với Visual novel), **Text color**. **Box**: **Box color**, *Box color from the page* (lấy màu nền của bóng thoại / hộp thoại), *Box opacity* và *Box blur* (chỉ Visual novel). **Display**: *Text box* (chỉ Visual novel: bản dịch hiện trong một ô riêng thay vì đè lên hộp thoại, xem [Text box](#text-box)), *Hide the box under the mouse*, *Show in screenshots*. Cuối cùng là *Reset look*. Bảng chọn màu có ô mã hex, màu mẫu và nút **Pick from screen** để lấy màu bất kỳ trên màn hình bằng ống hút; màu đổi ngay trên bản dịch, *Cancel* trả lại màu cũ |
| **Text to speech** | Đọc to bản dịch: bật / tắt, **Speed**, **Volume**, *Test voice* (xem [Text to speech](#text-to-speech)) |
| **More** | Phím tắt (**Translate key** gán phím bất kỳ hoặc nút phụ của chuột; **Auto-scan key**; **Show / hide toolbar key**), **Keep / Open translation record** (xem [Bản ghi dịch tạm](#bản-ghi-dịch-tạm)), *Show in taskbar*, *Developer mode*, **API keys & models** |

Chọn **ai đọc, ai dịch** (AI / Local OCR / Google), server, model và thiết bị đọc chữ (CPU / card đồ hoạ) nằm ở **nút server** trên thanh công cụ, không nằm trong ⚙.

### Chế độ Visual novel

⚙ → **Reading order → Visual novel · text box**. Lần đầu tool bảo bạn kéo khung (⛶) **quanh hộp thoại của game**
(kéo sát hộp thoại, không kéo cả màn hình: ảnh càng nhỏ càng nhanh). Khung này được nhớ riêng, không đè khung manga.

* **Quét tay:** bấm phím dịch (mặc định `Alt + T`, hoặc phím / nút chuột Anh đã gán ở *Translate key*).
* **Tự quét khi chữ đổi:** bật ở ⚙ → *Scanning* → *Auto-scan when text changes* hoặc phím `Alt + Shift + V`. Mặc định **tắt**.
  Tool chỉ nhìn khung nhỏ vài lần mỗi giây và chỉ khi cửa sổ game đang ở trước; chữ đổi thì bản dịch cũ ẩn ngay,
  đợi chữ chạy xong (hiệu ứng typewriter) rồi mới quét một lần. Tắt đi là tool hoàn toàn không nhìn màn hình nữa.
* Bản dịch phủ lên hộp thoại với **màu của chính hộp thoại** (tắt ở ⚙ → Look → *Box color from the page*).
  Rê chuột vào để ẩn tạm và xem chữ gốc. Dòng đã dịch rồi lấy từ cache nên hiện gần như tức thì.
* Game phải chạy **cửa sổ hoặc không viền** (borderless). Fullscreen độc quyền thì overlay không hiện lên trên được.
* Khi Auto-scan đang bật, bản dịch **không xuất hiện trong ảnh chụp màn hình** (nếu không nó tự làm chữ đổi và quét lặp).
* Trong chế độ này cuộn chuột / Space / PageDown **không** kích hoạt quét (VN dùng chúng để đọc tiếp).
* **Nhanh nhất:** chọn *Local OCR + Google Translate* và để tốc độ chữ của game ở mức nhanh / tức thì (hiệu ứng chạy chữ là phần chờ lâu nhất). Log có dòng `VN: translation shown …s after the text stopped changing` để đo.
* Chỉnh sâu trong `settings.json`: `vn_poll_ms` (100), `vn_stable_ms` (200, chế độ AI đọc ảnh tối thiểu 350: tăng nếu game chạy chữ có đoạn ngắt),
  `vn_change_pct` (0.3: tăng nếu có icon "bấm để tiếp" to và nhấp nháy làm tool tưởng chữ đổi).

### Text box

Chỉ dành cho **Visual novel**: bật ở ⚙ → **Look** → *Text box* (ở Manga / Webtoon mục này bị khoá 🔒, vì bản dịch cần nằm đúng trên từng bóng thoại). Bản dịch không còn đè lên hộp thoại của game nữa mà hiện trong **một ô riêng**:

* **Kéo** chỗ nào trong ô để di chuyển, **kéo góc dưới bên phải** để đổi kích thước. Vị trí và kích thước được nhớ (lưu cả trong preset).
* Lần đầu bật, ô nằm ở giữa phía dưới màn hình và ghi *Translations appear here*. Có bản dịch là chữ đó biến mất.
* Chữ dùng font, *Text color* và *Box color* trong ⚙ → Look. *Box opacity* và *Box blur* chỉ làm trong / mờ **khung** (thấy game phía sau như kính mờ), **chữ luôn rõ 100 %**. Chữ tự nhỏ lại cho vừa ô. *Auto text size* bật thì ô rộng chữ to hơn, tối đa 1,6 lần.
* Bấm vào ô **không** làm game hay trình duyệt mất focus. Ô cũng **không bị OCR đọc lại** dù đặt đè lên vùng quét (giống toolbar, ô không xuất hiện trong ảnh chụp màn hình).
* Tắt *Text box* là bản dịch lại phủ lên hộp thoại như cũ. Đổi sang Manga / Webtoon thì ô tự ẩn, quay lại Visual novel thì ô hiện lại đúng chỗ cũ.

### Text to speech

Bật ở ⚙ → **Text to speech** → *Read the translation aloud* (mặc định **tắt**). Sau khi dịch xong, LazyK đọc các bóng thoại theo thứ tự đọc. Có hai giọng:

| Giọng | Ưu điểm | Nhược điểm |
|---|---|---|
| **Local voice** (Piper, chạy trên máy) — **mặc định** | Bắt đầu đọc gần như ngay lập tức (thường 0,03–0,2 giây), lần nào cũng như nhau, không cần mạng, không gửi chữ đi đâu | Giọng kém tự nhiên hơn giọng online. Mỗi ngôn ngữ tải một lần khoảng 60–75 MB |
| **Online voice** (Microsoft Edge) | Giọng tự nhiên hơn, có cho mọi ngôn ngữ đích | Dịch vụ miễn phí trả tiếng chậm (thường 2–9 giây) và hay chập chờn. Mỗi bản dịch được tải trọn vẹn rồi mới đọc, nên bắt đầu muộn nhưng không bị ngắt giữa câu |

**Ngôn ngữ có giọng local** (giọng Piper "medium" từ [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)):

| Ngôn ngữ đích | Giọng | Dung lượng |
|---|---|---|
| Tiếng Việt | `vi_VN-vais1000` | 63 MB |
| English | `en_US-lessac` | 63 MB |
| 한국어 | `ko_KR-kss` | ~65 MB |
| Bahasa Indonesia | `id_ID-news_tts` | ~65 MB |
| Español | `es_ES-davefx` | ~65 MB |
| Français | `fr_FR-siwis` | ~65 MB |
| Deutsch | `de_DE-thorsten` | 63 MB |
| Português | `pt_BR-faber` | ~65 MB |
| Русский | `ru_RU-irina` | ~65 MB |

Tiếng **Nhật, Trung và Thái** chưa có giọng local (Piper cần thêm thư viện tách từ riêng cho các tiếng này), nên dù chọn *Local voice* LazyK vẫn tự dùng giọng online.

**Lần đầu dùng:** LazyK tự cài Piper (khoảng 20 MB, chỉ khi chạy bằng Python) và tự tải giọng của ngôn ngữ đích. Việc này diễn ra khi bạn bật *Read the translation aloud*, chọn *Local voice*, đổi ngôn ngữ đích hoặc mở app với *Local voice* đang bật. Toolbar hiện tiến trình (%). Trong lúc tải, LazyK tạm đọc bằng giọng online. Giọng được lưu ở `%LOCALAPPDATA%\LazyK\models` (cùng chỗ với model OCR local), tên file dạng `piper_vi.onnx`. Muốn tải lại thì xoá hai file `piper_<ngôn ngữ>.onnx` và `.onnx.json`.

| Mục trong ⚙ → Text to speech | Ý nghĩa |
|---|---|
| **Read the translation aloud** | Bật / tắt đọc to |
| **Local voice** / **Online voice** | Chọn giọng. Bên phải *Local voice* ghi trạng thái: *fast · offline* (đã có), *download … MB* (chưa tải) hoặc *online for this language* (ngôn ngữ chưa có giọng local). Chọn xong là đọc thử một câu |
| **Speed** | Tốc độ đọc 50–200 % (100 = bình thường) |
| **Volume** | Âm lượng 0–100 % so với âm lượng Windows (muốn to hơn thì tăng âm lượng hệ thống) |
| **Test voice** | Đọc một câu mẫu. Gõ số vào Speed / Volume rồi Enter cũng đọc câu mẫu luôn |

* **Dừng ngay** khi bạn cuộn trang, nhấn `Esc`, tạm dừng, ẩn bản dịch (👁) hoặc có bản dịch mới. Trang lấy lại từ cache (cuộn quay về) **không** đọc lại.
* **Visual novel:** mỗi dòng thoại mới được đọc một lần (kèm tên nhân vật nếu có).
* **Giọng online** tự chọn theo ngôn ngữ đích (⚙ → Language → To): tiếng Việt dùng `vi-VN-HoaiMyNeural` (nữ). Muốn giọng khác, sửa `tts_voice` trong `settings.json`, ví dụ `"vi-VN-NamMinhNeural"` (nam). Để `"auto"` thì tự chọn lại.
* **Cài đặt:** `setup.bat` cài `edge-tts`, `miniaudio` và `piper-tts`. Bản **exe** có sẵn Piper khi được build bằng `build_exe.bat` trên máy đã cài Piper. Mất mạng khi dùng giọng online thì chỉ hiện một thông báo ngắn, phần dịch vẫn chạy bình thường.
* **Thử giọng ngoài app:** `.venv\Scripts\python main.py --tts "Xin chào các bạn"`.

### Bản ghi dịch tạm

Mỗi lần quét và dịch xong, **phần đã dịch** (không có chữ gốc) được ghi nối vào file **`record-lazyk.txt`**, nằm cạnh `settings.json`, để bạn xem lại những gì vừa đọc. Mở bằng ⚙ → More → **Open translation record**.

```
=== #1 · 07:59:47 ===
1. Xin chào
2. Bạn khỏe không?

=== #2 · 08:00:12 ===
Một dòng thoại
```

* Mỗi lần quét là một khối có số thứ tự và giờ; bóng thoại được đánh số theo thứ tự đọc.
* Trang lấy lại từ cache và nội dung trùng với lần ghi trước **không** bị ghi lặp.
* Đây là **file tạm của phiên làm việc**: bị xoá khi bạn thoát LazyK (✕, tray, `Ctrl + Alt + Q`, đóng cửa sổ taskbar) và được làm trống mỗi lần mở lại. Muốn giữ một đoạn thì chép ra chỗ khác trước khi thoát.
* Tắt hẳn ở ⚙ → More → *Keep translation record* (khoá `record_enabled` trong `settings.json`).

### Kéo khung chọn vùng (⛶)
Hữu ích khi trang đọc truyện có menu, bình luận hoặc nền rối bên cạnh. Bấm **⛶**, màn hình tối lại, **kéo một khung ôm sát trang truyện** rồi thả chuột. Từ đó LazyK chỉ đọc trong khung này, kể cả sau khi mở lại. Muốn bỏ khung: ⚙ → *Capture* → *Browser page*.

### Chọn chế độ: ai đọc chữ, ai dịch

Bấm nút server trên thanh công cụ, cột **Mode** có 3 lựa chọn:

| Chế độ | Đọc chữ | Dịch | Khi nào dùng |
|---|---|---|---|
| **AI · reads and translates** | Gemini / Cloudflare | Gemini / Cloudflare | Dịch hay nhất, hiểu mạch truyện, bỏ qua tiếng động (SFX) |
| **Local OCR + AI translation** | Máy bạn | Gemini / Cloudflare | Vẫn dịch hay, đỡ tốn lượt AI nhiều vì AI chỉ nhận chữ |
| **Local OCR + Google Translate** (mặc định) | Máy bạn | Google Translate | Nhanh nhất, **không cần API key**, không lo hết lượt; bản dịch kém tự nhiên hơn |

- Ở chế độ Google: nếu Google tạm chặn (lỗi 429) và bạn có nhập key AI, trang đó được AI dịch thay. Bấm **Test Google Translate** trong menu để kiểm tra.
- Google dịch từng bóng thoại riêng, không biết mạch truyện, nên xưng hô và câu kéo qua nhiều bóng sẽ kém hơn AI.

### Local OCR (đọc chữ ngay trên máy)

Mục **Local OCR models** trong menu mở cửa sổ quản lý model:

| Model | Dung lượng | Dùng cho |
|---|---|---|
| PP-OCRv6 (PaddleOCR) | có sẵn | Tiếng Nhật (cả chữ dọc), Trung, Anh |
| PP-OCRv5 Korean | 13 MB | Tiếng Hàn (manhwa, webtoon): **cần tải** |
| manga-ocr | 460 MB | Tuỳ chọn: đọc chữ vẽ tay trong manga Nhật chính xác hơn, chậm hơn |

- Model tải về được lưu ở `%LOCALAPPDATA%\LazyK\models`, build lại hay cài lại LazyK vẫn còn.
- **OCR device** (menu của nút server → *OCR device*, đây là **chỗ duy nhất** để chọn thiết bị; cửa sổ *OCR models* chỉ ghi thiết bị đang dùng): chọn **CPU** hoặc một trong các **card đồ hoạ** LazyK tìm thấy (ví dụ *RTX 2050* và *AMD Radeon*). Card đồ hoạ chạy qua DirectML (NVIDIA, AMD, Intel đều được); không có DirectML thì chỉ còn CPU. Mặc định là **CPU**. Model OCR nhỏ nên **CPU đôi khi nhanh ngang hoặc hơn** card đồ hoạ (nhất là card tích hợp), hãy thử từng lựa chọn rồi xem thời gian `RapidOCR … X.XXs` trong `logs\lazyk.log`.
- **Language → From = Any**: LazyK thử model đã đúng ở trang trước; nếu đọc không chắc thì thử thêm model kia (Nhật/Trung/Anh ↔ Hàn). Đọc truyện Hàn thì nên tải model Korean; chọn hẳn ngôn ngữ gốc (⚙ → Language → From) sẽ nhanh hơn.
- Trang đầu tiên chậm hơn vài giây vì phải nạp model; các trang sau nhanh.
- Tốc độ tham khảo (trang khoảng 10 bóng thoại): CPU khoảng 1–3 giây cho PP-OCR, thêm 0,2–0,5 giây mỗi bóng nếu dùng manga-ocr; card đồ hoạ nhanh hơn nhiều. Phần dịch bằng AI tính riêng.
- Local OCR không phân biệt được tiếng động (SFX) với lời thoại như AI, nên chữ SFX vẽ to có thể cũng được dịch.

## 💡 Mẹo để dịch đẹp hơn

- **Phóng to trang truyện** trong trình duyệt (`Ctrl` + `+`) để AI đọc chữ chính xác hơn và chữ dịch to, dễ đọc hơn.
- Chọn đúng **Reading order**: *Manga* cho truyện Nhật, *Webtoon* cho truyện Hàn/cuộn dọc.
- Đặt đúng ngôn ngữ gốc (⚙ → Language → From) thay vì *Any* nếu truyện chỉ có một thứ tiếng.
- Thấy chữ dịch bị tràn ra ngoài bóng thoại? Giảm **cỡ chữ tối thiểu** trong ⚙ → *Text* một chút.
- Model có chữ **"lite"** nhanh và nhiều lượt miễn phí hơn; model **không "lite"** (ví dụ `gemini-3.5-flash`) hiểu ngữ cảnh và xưng hô tốt hơn.
- Dùng một font truyện tranh hỗ trợ tiếng Việt (⚙ → *Text* → *Font*) để trông giống bản dịch thật.

## 🛠️ Xử lý sự cố

<details>
<summary><b>Không thấy bản dịch hiện ra</b></summary>

- Kiểm tra chấm trên thanh công cụ: nếu đỏ, rê chuột vào để xem lỗi.
- Chế độ *Hotkey only* thì phải bấm `Alt + T`.
- Chế độ *Auto* chỉ phản ứng khi cuộn trong trình duyệt được hỗ trợ (danh sách `auto_apps` trong `settings.json`).
- Bấm ⚙ → *API keys & models* → **Test connection** để kiểm tra key.
</details>

<details>
<summary><b>Bật Text to speech mà không nghe thấy tiếng</b></summary>

- Giọng online cần Internet. Báo *"Text to speech failed (check the internet connection)"* nghĩa là không kết nối được dịch vụ giọng. Thử chuyển sang *Local voice*.
- Báo *"Local voice setup failed …"*: xem dòng `TTS: local voice setup failed` trong `logs\lazyk.log` (thường là mất mạng khi tải giọng). Chọn lại *Online voice* rồi *Local voice* để thử lại. Bản exe báo *"This build has no local voice"* thì build lại bằng `build_exe.bat` trên máy đã chạy `setup.bat`.
- Báo *"install edge-tts"*: chạy lại `setup.bat` để cài thư viện còn thiếu.
- Thử `.venv\Scripts\python main.py --tts "Xin chào"`. Nghe được ở đây mà trong app không có thì kiểm tra *Volume* (⚙ → Text to speech) và xem `logs\lazyk.log`, dòng `app.tts` ghi rõ câu bị lỗi.
- Giọng bắt đầu chậm vài giây ở lần đọc đầu tiên là bình thường; từ lần sau nhanh hơn.
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

`logs\lazyk.log` trong thư mục của LazyK. Mỗi lần mở LazyK, log được **làm mới** (giống bản ghi dịch tạm) nên không phình to theo thời gian. Log của **lần chạy trước** vẫn được giữ trong `logs\lazyk.previous.log` (chỉ một bản), để nếu app bị lỗi, mở lại rồi vẫn gửi được log. Một phiên dài cũng chỉ giữ tối đa khoảng 4 MB.
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
- Nếu bật **Text to speech** với *Online voice*, **phần chữ đã dịch** (không phải ảnh) được gửi tới dịch vụ giọng đọc của Microsoft Edge để tạo âm thanh. *Local voice* đọc ngay trên máy, không gửi gì.
- `record-lazyk.txt` chỉ nằm trên máy bạn và bị xoá khi thoát LazyK.

## 🧑‍💻 Dành cho nhà phát triển

Cấu trúc mã nguồn, cách hoạt động và toàn bộ tuỳ chọn trong `settings.json`: xem **[docs/DEVELOPER.md](docs/DEVELOPER.md)**.

## 📄 Giấy phép

Xem file [LICENSE](LICENSE).
