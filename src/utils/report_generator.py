import os
from fpdf import FPDF

class ICTDailyReport(FPDF):
    def header(self):
        # Sử dụng font đã cấu hình ở dưới (đảm bảo hỗ trợ tiếng Việt)
        self.set_font("VietnameseFont", "B", 16)
        self.cell(0, 10, "BÁO CÁO GIAO DỊCH LÝ THUYẾT ICT V2", ln=True, align="C")
        self.set_font("VietnameseFont", "I", 10)
        self.cell(0, 10, "Hệ thống phân tích Đa khung thời gian (Daily -> H1 -> M5)", ln=True, align="C")
        self.line(10, 28, 200, 28)
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("VietnameseFont", "I", 8)
        self.cell(0, 10, f"Trang {self.page_no()}/{{nb}}", align="C")

def generate_pdf_report(output_path: str, text_data: dict, image_paths: list):
    pdf = ICTDailyReport()
    pdf.alias_nb_pages()
    
    # Đăng ký font tiếng Việt (Thay đường dẫn bằng file font thực tế của bạn)
    # Bạn có thể lấy file font từ C:\Windows\Fonts\arial.ttf sang thư mục code
    font_path = "arial.ttf" 
    if os.path.exists(font_path):
        pdf.add_font("VietnameseFont", "", font_path, uni=True)
        pdf.add_font("VietnameseFont", "B", font_path, uni=True) # Dùng tạm arial cho cả Bold
        pdf.add_font("VietnameseFont", "I", font_path, uni=True)
    else:
        # Fallback nếu không có file font (sẽ bị lỗi hiển thị dấu tiếng Việt)
        pdf.add_font("VietnameseFont", "", "Helvetica")
        print("⚠️ Cảnh báo: Không tìm thấy file font Arial.ttf, tiếng Việt có thể bị lỗi hiển thị.")

    pdf.add_page()
    pdf.set_font("VietnameseFont", "", 11)

    # 1. Chèn phần thông tin Text / Metadata Phân Tích
    pdf.set_font("VietnameseFont", "B", 12)
    pdf.cell(0, 10, "1. Kết quả Phân tích từ AI Agent:", ln=True)
    pdf.set_font("VietnameseFont", "", 11)
    
    for key, value in text_data.items():
        pdf.multi_cell(0, 8, f"• **{key}**: {value}")
    
    pdf.ln(10)

    # 2. Chèn trực tiếp các ảnh RAW
    pdf.set_font("VietnameseFont", "B", 12)
    pdf.cell(0, 10, "2. Biểu đồ kỹ thuật đính kèm (Multi-Timeframe):", ln=True)
    pdf.ln(5)

    for img_path in image_paths:
        if os.path.exists(img_path):
            # Lấy tên file làm tiêu đề ảnh
            img_name = os.path.basename(img_path)
            pdf.set_font("VietnameseFont", "I", 10)
            pdf.cell(0, 8, f"Đồ thị: {img_name}", ln=True)
            
            # Chèn ảnh raw trực tiếp, tự động scale chiều rộng 180mm cho vừa trang A4
            pdf.image(img_path, w=180)
            pdf.ln(10)
        else:
            print(f"❌ Không tìm thấy file ảnh: {img_path}")

    # Xuất file PDF hoàn chỉnh
    pdf.output(output_path)
    print(f"✅ Đã xuất báo cáo PDF thành công: {output_path}")

# ==========================================
# VÍ DỤ SỬ DỤNG TRONG BOT CỦA BẠN
# ==========================================
if __name__ == "__main__":
    # Giả lập dữ liệu text thu được từ pipeline 3 stage
    sample_text_data = {
        "Daily Bias": "BULLISH",
        "Draw on Liquidity": "Vùng BSL tại mức giá 1.09500",
        "H1 Trend": "Bullish Swing tiếp diễn",
        "Key POI H1": "Cú quét SSL + FVG H1 tăng trưởng",
        "M5 Action": "BUY lệnh tại vùng FVG M5 thành công"
    }

    # Giả lập danh sách đường dẫn ảnh raw được lưu trong các class Util
    # (Đường dẫn này bạn lấy từ output của DailyBiasUtil, H1StructureUtil, M5EntryUtil)
    sample_image_files = [
        "data/charts/daily_bias.png",
        "data/charts/h1_structure.png",
        "data/charts/m5_entry.png"
    ]

    # Tạo các file ảnh giả lập nếu chưa có để test code không bị lỗi
    os.makedirs("data/charts", exist_ok=True)
    for path in sample_image_files:
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(b"GiaLapDuLieuAnhRaw") 

    # Tiến hành gom và xuất file PDF
    generate_pdf_report("data/reports/Daily_Trading_Report_20260616.pdf", sample_text_data, sample_image_files)