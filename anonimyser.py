import re
import fitz
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
import streamlit as st
from io import BytesIO, StringIO

# === Маскировка ===
def remove_sensitive_data(text):
    patterns = [
        # ФИО в формате: Иванов Иван Иванович
        r'\b[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+\b',
        # Иванов И.И.
        r'\b[А-ЯЁ][а-яё]+ [А-ЯЁ]\.[А-ЯЁ]\.\b',
        # И.О. Иванов
        r'\b[А-ЯЁ]\.[А-ЯЁ]\. ?[А-ЯЁ][а-яё]+\b',
        # ИНН, ОГРН, КПП
        r'\bИНН ?\d{10,12}\b',
        r'\bОГРН ?\d{13}\b',
        r'\bКПП ?\d{9}\b',
        # Email
        r'\b[\w\.-]+@[\w\.-]+\.\w+\b',
        # Телефоны
        r'(?:(?:8|\+7)[\s\-]?)?\(?\d{3,4}\)?[\s\-]?\d{2,3}[\s\-]?\d{2}[\s\-]?\d{2,4}',
        # URL и домены
        r'https?://[^\s,]+',
        r'\b[\w\.-]+\.(ru|com|pdf|org|net)\b',
        # Адреса
        r'(?i)(юридический|почтовый)?\s*адрес\s*[:\-\u2013\u2014]?\s*[^\n\r]*',
        r'(?i)местонахождение\s*[:\-\u2013\u2014]?\s*[^\n\r]*',
        r'г\.\s?[А-ЯЁа-яё]+,\s?ул\.\s?[А-ЯЁа-яё\s]+,\s?д\.\d+[\w]?,?\s?(стр\.|корп\.|оф\.)?\d*',
        # Банковские реквизиты
        r'(?i)(расчетный счет|р/с|к/с|кор/с|корреспондентский счет)[^\n\r]*',
        # Наименования организаций
        # 1. Сокращённые правовые формы с вложенными кавычками
        r'(?i)\b(ООО|АО|ПАО|ОАО|ЗАО|ИП|ТСЖ|МУП|ГУП|НКО|МКА|СНТ|ПК|КФХ|ГМК)\s+[«"„“][^»”"]+[»”"](?:\s*[«"„“][^»”"]+[»”"])*',
        # 2. Полные правовые формы с вложенными кавычками
        r'(?i)(Общество с ограниченной ответственностью|публичное акционерное общество|непубличное акционерное общество|акционерное общество|индивидуальный предприниматель|Муниципальное унитарное предприятие|Государственное унитарное предприятие|Некоммерческая организация|Московская коллегия адвокатов|Адвокатская контора)\s+[«"„“][^»”"]+[»”"](?:\s*[«"„“][^»”"]+[»”"])*',
        # 3. Организации без кавычек, но с правовой формой в конце
        r'(?i)[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)+\s+(акционерное общество|публичное акционерное общество|непубличное акционерное общество|общество с ограниченной ответственностью)',
    ]

    replacements = {}
    for i, pattern in enumerate(patterns):
        def repl(match):
            key = f"[УДАЛЕНО_{i}_{len(replacements)}]"
            replacements[key] = match.group()
            return key
        text = re.sub(pattern, repl, text)
    return text, replacements

# === Восстановление ===
def restore_sensitive_data(text, replacements):
    for key, original in replacements.items():
        text = text.replace(key, original)
    return text

# === Установка шрифта ===
def set_font(paragraph):
    for run in paragraph.runs:
        run.font.name = 'Arial'
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'Arial')
        run.font.size = Pt(11)

# === Обработка DOCX ===
def sanitize_docx(file_bytes):
    file_bytes.seek(0)
    doc = Document(BytesIO(file_bytes.read()))
    full_replacements = {}
    for para in doc.paragraphs:
        new_text, replacements = remove_sensitive_data(para.text)
        para.text = new_text
        set_font(para)
        full_replacements.update(replacements)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                new_text, replacements = remove_sensitive_data(cell.text)
                cell.text = new_text
                for p in cell.paragraphs:
                    set_font(p)
                full_replacements.update(replacements)
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer, full_replacements

def restore_docx(file_bytes, replacements):
    file_bytes.seek(0)
    doc = Document(BytesIO(file_bytes.read()))
    for para in doc.paragraphs:
        para.text = restore_sensitive_data(para.text, replacements)
        set_font(para)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                cell.text = restore_sensitive_data(cell.text, replacements)
                for p in cell.paragraphs:
                    set_font(p)
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# === Обработка PDF ===
def sanitize_pdf(file_bytes):
    pdf_in = fitz.open(stream=file_bytes.read(), filetype='pdf')
    pdf_out = fitz.open()
    full_replacements = {}
    for page in pdf_in:
        text = page.get_text()
        new_text, replacements = remove_sensitive_data(text)
        full_replacements.update(replacements)
        new_page = pdf_out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_text((50, 50), new_text, fontsize=11, fontname="helv")
    buffer = BytesIO()
    pdf_out.save(buffer)
    buffer.seek(0)
    return buffer, full_replacements

# === Карта замен ===
def export_replacements(replacements):
    rep_text = "\n".join(f"{k} → {v}" for k, v in replacements.items())
    buffer = BytesIO()
    buffer.write(rep_text.encode("utf-8"))
    buffer.seek(0)
    return buffer

def import_replacements(text_file):
    content = text_file.read().decode("utf-8")
    replacements = {}
    for line in content.strip().splitlines():
        if "→" in line:
            key, val = line.split("→", 1)
            replacements[key.strip()] = val.strip()
    return replacements

# === Интерфейс Streamlit ===
st.set_page_config(page_title="AsiwiAnonymizer", page_icon="📄")
st.title("AsiwiAnonymizer — Обезличивание и восстановление .docx и .pdf")

tab1, tab2 = st.tabs(["🔒 Обезличить", "♻️ Восстановить"])

with tab1:
    uploaded_file = st.file_uploader("Загрузите файл .docx или .pdf", type=["docx", "pdf"])
    if uploaded_file and st.button("Обезличить"):
        filetype = uploaded_file.name.split(".")[-1].lower()
        if filetype == "docx":
            output, replacements = sanitize_docx(uploaded_file)
            filename = "обезличенный.docx"
        elif filetype == "pdf":
            output, replacements = sanitize_pdf(uploaded_file)
            filename = "обезличенный.pdf"
        else:
            st.error("Неподдерживаемый формат.")
            st.stop()

        st.download_button("📁 Скачать обезличенный файл", data=output, file_name=filename)
        if replacements:
            rep_file = export_replacements(replacements)
            st.download_button("🗂️ Скачать карту замен (.txt)", data=rep_file, file_name="карта_замен.txt")

with tab2:
    file_docx = st.file_uploader("Загрузите изменённый обезличенный .docx", type=["docx"], key="restore_docx")
    file_map = st.file_uploader("Загрузите соответствующую карту замен (.txt)", type=["txt"], key="restore_map")
    if file_docx and file_map and st.button("Восстановить"):
        replacements = import_replacements(file_map)
        restored_doc = restore_docx(file_docx, replacements)
        st.download_button("📄 Скачать восстановленный .docx", data=restored_doc, file_name="восстановленный.docx")
