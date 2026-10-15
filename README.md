<p align="center">
  <img src="assets/icon_on_light.png" width="112" alt="LazyK logo">
</p>

<h1 align="center">LazyK</h1>
<p align="center"><b>Đọc truyện tranh và chơi visual novel mọi thứ tiếng, theo cách lười nhất.</b><br>
<i>Read comics and play visual novels in any language, the lazy way.</i></p>

---

LazyK chạy trên **Windows**. Bạn đọc manga, manhwa, webtoon trên trình duyệt hoặc chơi visual novel như bình thường; LazyK chụp phần đang hiện, đọc chữ, dịch (mặc định sang **tiếng Việt**) và **viết bản dịch đè lên đúng bóng thoại / hộp thoại**. Có thể đọc to bản dịch.

> 🇬🇧 **English summary:** a Windows overlay that reads the speech bubbles of the comic in your browser (or a visual novel's text box), translates them and paints the translation over the original. Default: on-PC OCR + Google Translate, no API key needed; a free Gemini key unlocks the AI modes. 64-bit recommended.

## ✨ Tính năng

- **Tự dịch** khi bạn dừng cuộn hoặc click sang trang; trang đã dịch hiện lại ngay khi quay về.
- Đọc **Nhật (cả chữ dọc), Hàn, Trung, Anh**; dịch sang 13 ngôn ngữ.
- **Tìm bóng thoại bằng AI**: tách bóng kép, bóng nét đứt / mây / gai / đen / xám; tẩy đúng hình bóng và xếp chữ vừa bóng. Chữ ngoài bóng chỉ che đúng chỗ chữ gốc; chữ trên nền (bảng đen, áp phích) được bỏ qua.
- **Visual novel**: tự quét khi câu thoại đổi, dịch phủ lên hộp thoại hoặc trong một ô riêng.
- Chọn riêng **đọc** (AI / trên máy) và **dịch** (AI / Google Translate miễn phí).
- Đọc to bản dịch, preset cho từng loại truyện, bản ghi dịch của phiên.

## 🚀 Cài đặt

**Bản `.exe`:** tải ở **[Releases](https://github.com/Maditor/LazyK/releases)**, giải nén, mở **`LazyK.exe`** (Windows cảnh báo thì bấm **More info → Run anyway**).

**Từ mã nguồn:** tải mã nguồn, bấm đúp **`setup.bat`** (tự cài Python 3.12, thư viện và model tìm bóng thoại ~170 MB; vài phút), sau đó mỗi lần dùng chạy **`run.bat`**.

Yêu cầu: Windows 10 (2004+) / 11, có mạng. Máy **32-bit** không đọc chữ trên máy được (dùng chế độ AI).

## 🔑 API key (tuỳ chọn)

Mặc định không cần key. Muốn AI đọc / dịch hay hơn, lấy key **Google Gemini** miễn phí ở [Google AI Studio](https://aistudio.google.com/api-keys) (hoặc **Cloudflare Workers AI** làm dự phòng), dán vào ⚙ → *API keys & models* → **Test connection** → **Save**.

> 🔒 Key nằm trong `settings.json` trên máy bạn. **Đừng chia sẻ file này.**

## 📖 Cách dùng

Mở truyện trên trình duyệt và đọc như bình thường. Dừng cuộn một chút (hoặc click sang trang) là bản dịch hiện ra; cuộn tiếp thì bản dịch tự ẩn. Rê chuột lên một bóng để xem chữ gốc bên dưới.

```
⋮⋮ 💬 ● On · Auto | Default ▾ | Local + Google ▾ | ↻  ❚❚  👁  ⛶ | ⚙  ‹  ✕
```

| Nút | Chức năng |
|---|---|
| `⋮⋮` | Kéo để di chuyển thanh |
| **Default ▾** | Preset (bộ cài đặt có tên, tự lưu khi chỉnh; không lưu key và phím tắt) |
| **Local + Google ▾** | Ai đọc chữ (**AI** / **Local**) và ai dịch (**AI** / **Google**); thiết bị và model đọc chữ |
| **↻ ❚❚ 👁 ⛶** | Dịch ngay · tạm dừng · ẩn/hiện bản dịch · kéo khung chỉ dịch trong vùng đó |
| **⚙ ‹ ✕** | Cài đặt · thu gọn · thoát |

Chấm tròn: 🟢 bật · 🔵 đọc chữ · 🟣 dịch · ⚪ tạm dừng · 🔴 lỗi (rê chuột để xem).

**Đọc trên máy (Local)** mặc định chạy bằng card đồ hoạ rời (nhanh hơn CPU nhiều); đổi ở *OCR device*. Tiếng Hàn cần tải thêm model (13 MB) ở *OCR models*; *manga-ocr* (460 MB) đọc chữ Nhật viết tay chính xác hơn. Model tìm bóng thoại cũng tải lại được ở đây nếu thiếu.

**Phím tắt** (đổi được ở ⚙ → More):

| Phím | |
|---|---|
| `Alt + T` | Dịch ngay |
| `Esc` | Ẩn bản dịch |
| `Ctrl + Alt + P` / `M` / `R` | Tạm dừng · đổi Auto ↔ Hotkey · kéo khung |
| `Ctrl + Alt + V` | Visual novel: bật / tắt tự quét |
| `Ctrl + Alt + H` / `Q` | Ẩn / hiện thanh · thoát |

**Cài đặt (⚙):** *Reading order* (Manga / Webtoon / Visual novel), *Scanning* (Auto / Hotkey, cả trang hay khung), *Language*, *Look* (font, cỡ chữ, màu), *Text to speech*.

## 🎮 Visual novel

1. ⚙ → **Reading order → Visual novel**, kéo khung (⛶) sát quanh hộp thoại của game.
2. Bấm `Alt + T`, hoặc bật tự quét (`Ctrl + Alt + V`) để tự dịch mỗi câu mới.

- Game phải chạy **cửa sổ** hoặc **borderless**.
- Tự quét không dịch vì cảnh sau hộp thoại chuyển động? Tăng độ đục hộp thoại trong game, hoặc bật ⚙ → Scanning → **Ignore moving background**.
- **Text box** (⚙ → Look): bản dịch hiện trong ô riêng, kéo để di chuyển; màu, opacity, blur của ô này chỉnh riêng.

## 🔊 Đọc to

⚙ → **Text to speech**. **Local voice** (Piper) đọc gần như ngay, không cần mạng (tự tải ~65 MB lần đầu); **Online voice** (Microsoft Edge) tự nhiên hơn, mọi ngôn ngữ, nhưng chậm hơn.

## 🛠️ Xử lý sự cố

- **Không thấy bản dịch:** rê chuột lên chấm đỏ xem lỗi; ở chế độ *Hotkey* phải bấm `Alt + T`; chế độ AI thì **Test connection**.
- **Hết lượt / "Rate limited":** chờ vài phút hoặc bật tự đổi model / server trong menu server.
- **`setup.bat` lỗi Python:** LazyK cần Python 3.10–3.12. Cài tay từ [python.org](https://www.python.org/downloads/release/python-3128/) (tick *Add to PATH*), xoá `.venv` rồi chạy lại.
- **"DLL load failed":** chạy lại `setup.bat` hoặc cài [VC++ Runtime](https://aka.ms/vs/17/release/vc_redist.x64.exe).
- **Phím tắt không ăn trong game:** chạy LazyK bằng *Run as administrator*.

Khi báo lỗi, gửi kèm **`logs\lazyk.log`**.

## 📦 Tự đóng gói

- **`build_exe.bat`**: tạo `dist\LazyK\LazyK.exe`, chép kèm model tìm bóng mà `setup.bat` đã tải. Thư mục này có `settings.json` chứa key, **đừng gửi nguyên thư mục**.
- **`build_installer.bat`**: tạo `Output\LazyK-Setup-<phiên bản>.exe` để chia sẻ (tự bỏ `settings.json` và log).

Model tìm bóng: [ogkalu/comic-text-and-bubble-detector](https://huggingface.co/ogkalu/comic-text-and-bubble-detector) (giấy phép Apache-2.0).

## 🔐 Quyền riêng tư

LazyK chỉ gửi **ảnh vùng cần dịch** và **chữ cần dịch** tới dịch vụ bạn chọn (Gemini, Cloudflare hoặc Google Translate), và chữ đã dịch tới Microsoft Edge nếu dùng giọng online. Đọc chữ trên máy và giọng Local chạy hoàn toàn trên máy.

---

Nhà phát triển: **[docs/DEVELOPER.md](docs/DEVELOPER.md)** · Giấy phép: [LICENSE](LICENSE)
