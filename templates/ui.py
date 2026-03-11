import gradio as gr
import requests
import json
import os

API_BASE_URL = "http://localhost:8000"

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


def _render_nutrition_table(res_json: dict) -> list:
    """Extract nutrition table data from unified API response."""
    table_data = []
    if res_json.get("success") and "data" in res_json and "dishes" in res_json["data"]:
        for dish in res_json["data"]["dishes"]:
            total_nut = dish.get("total_estimated_nutritions") or {}
            table_data.append([
                f"🍽️ {dish.get('vi_name') or dish.get('name')} (Tổng)",
                f"{dish.get('total_estimated_weight_g', 0)}",
                f"{total_nut.get('calories', 0)}",
                f"{total_nut.get('protein', 0)}",
                f"{total_nut.get('carbs', 0)}",
                f"{total_nut.get('fat', 0)}"
            ])
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
    return table_data


def test_analyze_food(image_filepath, method):
    if not image_filepath:
        yield {"error": "Chưa chọn ảnh"}, []
        return

    url = f"{API_BASE_URL}/analyze-food"
    with open(image_filepath, "rb") as f:
        files = {"file": (os.path.basename(image_filepath), f, "image/jpeg")}
        params = {"method": method}
        response = requests.post(url, files=files, params=params)

    res_json = response.json()
    table_data = _render_nutrition_table(res_json)
    yield res_json, table_data


def test_analyze_label(image_filepath):
    if not image_filepath:
        yield {"error": "Chưa chọn ảnh"}, []
        return

    url = f"{API_BASE_URL}/analyze-label"
    with open(image_filepath, "rb") as f:
        files = {"file": (os.path.basename(image_filepath), f, "image/jpeg")}
        response = requests.post(url, files=files)

    res_json = response.json()
    table_data = _render_nutrition_table(res_json)

    # If no label detected, show informative message in table
    if res_json.get("success") and not res_json.get("label_detected"):
        table_data = [["⚠️ Không phát hiện nhãn dinh dưỡng trong ảnh", "", "", "", "", ""]]

    yield res_json, table_data


def save_results(json_data):
    if not json_data or "error" in json_data:
        return None

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    save_dir = os.path.join(project_root, "data", "results")
    os.makedirs(save_dir, exist_ok=True)

    import time
    timestamp = int(time.time())
    filename = os.path.join(save_dir, f"analysis_{timestamp}.json")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4, ensure_ascii=False)

    return filename


NUTRITION_TABLE_HEADERS = ["Tên món/Nguyên liệu", "Khối lượng (g)", "Calories (kcal)", "Protein (g)", "Carbs (g)", "Fat (g)"]

# Tạo giao diện với gr.Blocks + Tabs để phân biệt Food Analysis và Label Analysis
with gr.Blocks(title="NutriTrack API Tester") as demo:
    gr.Markdown("# NutriTrack API Tester")
    gr.Markdown("Tải ảnh thức ăn hoặc ảnh nhãn dinh dưỡng lên để phân tích.")

    with gr.Tabs():
        # ─── Tab 1: Food Analysis ────────────────────────────────────────
        with gr.TabItem("🍽️ Phân tích thức ăn"):
            with gr.Row():
                with gr.Column():
                    food_img_input = gr.Image(type="filepath", label="Upload Food Image")
                    food_method_input = gr.Radio(["tools", "manual"], value="tools", label="Method")
                    food_size_output = gr.Textbox(label="Dung lượng ảnh gốc", interactive=False)
                    food_analyze_btn = gr.Button("🔍 Analyze Food", variant="primary")

                    gr.Markdown("---")
                    food_save_btn = gr.Button("💾 Save Results to JSON")
                    food_file_download = gr.File(label="Tải về file kết quả")

                with gr.Column():
                    food_json_output = gr.JSON(label="API Response - Raw JSON")
                    food_df_output = gr.Dataframe(
                        headers=NUTRITION_TABLE_HEADERS,
                        label="Bảng phân tích dinh dưỡng"
                    )

            food_img_input.change(fn=get_image_size, inputs=food_img_input, outputs=food_size_output)
            food_analyze_btn.click(
                fn=test_analyze_food,
                inputs=[food_img_input, food_method_input],
                outputs=[food_json_output, food_df_output]
            )
            food_save_btn.click(
                fn=save_results,
                inputs=[food_json_output],
                outputs=[food_file_download]
            )

        # ─── Tab 2: Label Analysis ───────────────────────────────────────
        with gr.TabItem("🏷️ Phân tích nhãn dinh dưỡng"):
            with gr.Row():
                with gr.Column():
                    label_img_input = gr.Image(type="filepath", label="Upload Label Image")
                    label_size_output = gr.Textbox(label="Dung lượng ảnh gốc", interactive=False)
                    label_analyze_btn = gr.Button("🔍 Analyze Label", variant="primary")

                    gr.Markdown("---")
                    label_save_btn = gr.Button("💾 Save Results to JSON")
                    label_file_download = gr.File(label="Tải về file kết quả")

                with gr.Column():
                    label_json_output = gr.JSON(label="API Response - Raw JSON")
                    label_df_output = gr.Dataframe(
                        headers=NUTRITION_TABLE_HEADERS,
                        label="Bảng phân tích dinh dưỡng từ nhãn"
                    )

            label_img_input.change(fn=get_image_size, inputs=label_img_input, outputs=label_size_output)
            label_analyze_btn.click(
                fn=test_analyze_label,
                inputs=[label_img_input],
                outputs=[label_json_output, label_df_output]
            )
            label_save_btn.click(
                fn=save_results,
                inputs=[label_json_output],
                outputs=[label_file_download]
            )

demo.launch()  # Mặc định chạy ở localhost:7860
