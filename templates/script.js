// ─── NutriTrack Frontend Script ───

// ─── i18n Translations ───
const translations = {
    vi: {
        header_desc: "Chụp hoặc upload ảnh đồ ăn — AI phân tích dinh dưỡng chi tiết",
        upload_label: "Kéo thả ảnh vào đây hoặc chọn bên dưới",
        upload_sub: "Hỗ trợ JPG, PNG, WebP",
        btn_choose: "📁 Chọn ảnh",
        btn_capture: "📸 Chụp ảnh",
        btn_analyze: "🔍 Phân tích dinh dưỡng",
        loading_text: "🤖 AI đang phân tích ảnh...",
        loading_sub: "Quá trình này có thể mất 10-30 giây",
        err_file_type: "Vui lòng chọn file ảnh (JPG, PNG, WebP)",
        err_prefix: "Lỗi: ",
        res_header: (count) => `📊 Kết quả phân tích (${count} món)`,
        res_ai_est: "AI ước tính",
        th_ing: "Nguyên liệu",
        th_weight: "Khối lượng",
        lang_btn: "🇬🇧 EN"
    },
    en: {
        header_desc: "Snap or upload food photo — AI detailed nutrition analysis",
        upload_label: "Drag & drop image here or select below",
        upload_sub: "Supports JPG, PNG, WebP",
        btn_choose: "📁 Choose image",
        btn_capture: "📸 Capture image",
        btn_analyze: "🔍 Analyze nutrition",
        loading_text: "🤖 AI is analyzing the image...",
        loading_sub: "This process may take 10-30 seconds",
        err_file_type: "Please select an image file (JPG, PNG, WebP)",
        err_prefix: "Error: ",
        res_header: (count) => `📊 Analysis Results (${count} dishes)`,
        res_ai_est: "AI Estimated",
        th_ing: "Ingredient",
        th_weight: "Weight",
        lang_btn: "🇻🇳 VI"
    }
};

let currentLang = 'vi';
let lastAnalysisData = null;

function toggleLanguage() {
    currentLang = currentLang === 'vi' ? 'en' : 'vi';

    // Update static text elements
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (translations[currentLang][key]) {
            el.textContent = translations[currentLang][key];
        }
    });

    // Update toggle button text
    document.getElementById('langToggle').textContent = translations[currentLang].lang_btn;

    // Re-render results if available
    if (lastAnalysisData) {
        renderResults(lastAnalysisData);
    }
}

const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const cameraInput = document.getElementById('cameraInput');
const preview = document.getElementById('preview');
const previewImg = document.getElementById('previewImg');
const fileName = document.getElementById('fileName');
const loading = document.getElementById('loading');
const errorDiv = document.getElementById('error');
const resultsDiv = document.getElementById('results');

let selectedFile = null;

// ─── Drag & Drop ───
dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});
dropZone.addEventListener('click', () => fileInput.click());

// ─── File inputs ───
fileInput.addEventListener('change', (e) => { if (e.target.files[0]) handleFile(e.target.files[0]); });
cameraInput.addEventListener('change', (e) => { if (e.target.files[0]) handleFile(e.target.files[0]); });

function handleFile(file) {
    if (!file.type.startsWith('image/')) {
        showError(translations[currentLang].err_file_type);
        return;
    }
    selectedFile = file;
    const reader = new FileReader();
    reader.onload = (e) => {
        previewImg.src = e.target.result;
        fileName.textContent = file.name + ' (' + (file.size / 1024 / 1024).toFixed(1) + ' MB)';
        preview.style.display = 'block';
        errorDiv.style.display = 'none';
        resultsDiv.style.display = 'none';
    };
    reader.readAsDataURL(file);
}

// ─── Analyze ───
async function analyzeImage() {
    if (!selectedFile) return;

    loading.style.display = 'block';
    errorDiv.style.display = 'none';
    resultsDiv.style.display = 'none';
    document.getElementById('analyzeBtn').disabled = true;

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
        const res = await fetch('/analyze', { method: 'POST', body: formData });
        const data = await res.json();

        if (!res.ok) throw new Error(data.detail || 'Server error');
        if (!data.success) throw new Error(data.message || 'Analysis failed');
        lastAnalysisData = data.data;
        renderResults(data.data);
    } catch (err) {
        showError(translations[currentLang].err_prefix + err.message);
    } finally {
        loading.style.display = 'none';
        document.getElementById('analyzeBtn').disabled = false;
    }
}

function showError(msg) {
    errorDiv.textContent = msg;
    errorDiv.style.display = 'block';
}

// ─── Render Results ───
function renderResults(dishes) {
    const t_lang = translations[currentLang];
    let html = `<div class="results-header">${t_lang.res_header(dishes.length)}</div>`;

    for (const dish of dishes) {
        const t = dish.total_nutrition || {};
        const cal = (t.calories || 0).toFixed(0);
        const pro = (t.protein || 0).toFixed(1);
        const carb = (t.carbs || 0).toFixed(1);
        const fat = (t.fat || 0).toFixed(1);

        const displayName = currentLang === 'en' ? dish.name : (dish.vi_name || dish.name);
        const subName = currentLang === 'en' ? (dish.vi_name || '') : dish.name;

        html += `
        <div class="dish-card">
            <div class="dish-name">🍽️ ${displayName}</div>
            <div class="dish-name-vi">${subName} · ${t_lang.res_ai_est}: ${dish.qwen_estimated_calories || '?'} kcal</div>
            
            <div class="nutrition-bar">
                <div class="nut-item">
                    <div class="nut-value cal-color">${cal}</div>
                    <div class="nut-label">Calories</div>
                </div>
                <div class="nut-item">
                    <div class="nut-value pro-color">${pro}g</div>
                    <div class="nut-label">Protein</div>
                </div>
                <div class="nut-item">
                    <div class="nut-value carb-color">${carb}g</div>
                    <div class="nut-label">Carbs</div>
                </div>
                <div class="nut-item">
                    <div class="nut-value fat-color">${fat}g</div>
                    <div class="nut-label">Fat</div>
                </div>
            </div>

            <table class="ing-table">
                <thead>
                    <tr>
                        <th>${t_lang.th_ing}</th>
                        <th>${t_lang.th_weight}</th>
                        <th>Cal</th>
                        <th>P / C / F</th>
                    </tr>
                </thead>
                <tbody>
                    ${dish.ingredients.map(ing => {
            const n = ing.nutrition || {};
            const ingName = currentLang === 'en' ? ing.name : (ing.vi_name || ing.name);
            return `<tr>
                            <td>${ingName}</td>
                            <td>${(ing.weight_g || 0).toFixed(0)}g</td>
                            <td>${(n.calories || 0).toFixed(0)}</td>
                            <td>${(n.protein || 0).toFixed(1)} / ${(n.carbs || 0).toFixed(1)} / ${(n.fat || 0).toFixed(1)}</td>
                        </tr>`;
        }).join('')}
                </tbody>
            </table>
        </div>`;
    }

    resultsDiv.innerHTML = html;
    resultsDiv.style.display = 'block';
    resultsDiv.scrollIntoView({ behavior: 'smooth' });
}
