import gradio as gr
import requests
import json
import os

def format_size(size_bytes):
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes} Bytes"

def get_image_size(image_filepath):
    if not image_filepath or not os.path.exists(image_filepath):
        return ""
    file_size_bytes = os.path.getsize(image_filepath)
    return format_size(file_size_bytes)

def test_analyze(image_filepath, method):
    if not image_filepath:
        yield {"error": "Chưa chọn ảnh"}, []
        return

    url = "http://localhost:8000/analyze"
    with open(image_filepath, "rb") as f:
        files = {"file": (image_filepath, f, "image/jpeg")}
        params = {"method": method}
        response = requests.post(url, files=files, params=params)
    
    res_json = response.json()
    
    # Render table data
    table_data = []
    
    if res_json.get("success") and "data" in res_json and "dishes" in res_json["data"]:
        for dish in res_json["data"]["dishes"]:
            total_nut = dish.get("total_estimated_nutritions") or {}
            
            # Add main dish total row
            table_data.append([
                f"🍽️ {dish.get('vi_name') or dish.get('name')} (Tổng)",
                f"{dish.get('total_estimated_weight_g', 0)}",
                f"{total_nut.get('calories', 0)}",
                f"{total_nut.get('protein', 0)}",
                f"{total_nut.get('carbs', 0)}",
                f"{total_nut.get('fat', 0)}"
            ])
            
            # Add ingredient rows
            for ing in dish.get("ingredients", []):
                nut = ing.get("estimated_nutritions") or {}
                table_data.append([
                    f"   └─ {ing.get('vi_name') or ing.get('name')}",
                    f"{ing.get('estimated_weight_g', 0)}",
                    f"{nut.get('calories', 0)}",
                    f"{nut.get('protein', 0)}",
                    f"{nut.get('carbs', 0)}",
                    f"{nut.get('fat', 0)}"
                ])

    # Sử dụng yield thay vì return để chuyển response sang dạng Stream (SSE).
    # Điều này FIX triệt để lỗi "Too much data for declared Content-Length" của Gradio/Starlette do khác biệt kích thước Unicode byte!
    yield res_json, table_data

def save_results(json_data):
    if not json_data or "error" in json_data:
        return None
    
    # Đường dẫn lưu kết quả tuyệt đối
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    save_dir = os.path.join(project_root, "data", "results")
    os.makedirs(save_dir, exist_ok=True)
    
    import time
    timestamp = int(time.time())
    filename = os.path.join(save_dir, f"analysis_{timestamp}.json")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4, ensure_ascii=False)
    
    return filename

# Tạo giao diện tự động với gr.Blocks để tùy biến sự kiện realtime
with gr.Blocks(title="NutriTrack API Tester") as demo:
    gr.Markdown("# NutriTrack API Tester")
    gr.Markdown("Tải ảnh thức ăn lên để phân tích. Dung lượng sẽ được tính toán ngay lập tức!")
    
    with gr.Row():
        with gr.Column():
            img_input = gr.Image(type="filepath", label="Upload Food Image")
            method_input = gr.Radio(["tools", "manual"], value="tools", label="Method")
            size_output = gr.Textbox(label="Dung lượng ảnh gốc", interactive=False)
            analyze_btn = gr.Button("🔍 Analyze", variant="primary")
            
            gr.Markdown("---")
            save_btn = gr.Button("💾 Save Results to JSON")
            file_download = gr.File(label="Tải về file kết quả")
            
        with gr.Column():
            json_output = gr.JSON(label="API Response - Raw JSON")
            df_output = gr.Dataframe(
                headers=["Tên món/Nguyên liệu", "Khối lượng (g)", "Calories (kcal)", "Protein (g)", "Carbs (g)", "Fat (g)"],
                label="Bảng phân tích dinh dưỡng"
            )

    # Sự kiện 1: Vừa chọn ảnh (change) là tính kích thước truyền qua Textbox luôn
    img_input.change(fn=get_image_size, inputs=img_input, outputs=size_output)

    # Sự kiện 2: Bấm nút Analyze thì mới gửi request lên API Server
    analyze_btn.click(
        fn=test_analyze, 
        inputs=[img_input, method_input], 
        outputs=[json_output, df_output]
    )

    # Sự kiện 3: Lưu kết quả
    save_btn.click(
        fn=save_results,
        inputs=[json_output],
        outputs=[file_download]
    )

demo.launch() # Mặc định chạy ở localhost:7860
