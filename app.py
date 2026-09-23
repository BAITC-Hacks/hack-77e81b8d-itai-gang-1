"""Run with: python -m streamlit run app.py"""

import hashlib
import json
import logging
import os

import streamlit as st
from pydantic import ValidationError

from backend_adapter import InputDocument, analyze, backend_available
from demo_data import demo_report
from ui_contract import AnalysisReport


st.set_page_config(page_title="ОргАнализ", page_icon="🔎", layout="wide")

LABELS = {
    "created": "Создано", "preserved": "Сохранено", "reorganized": "Преобразовано",
    "removed": "Удалено", "transferred": "Передана", "lost": "Потенциально потеряна",
    "duplicated": "Дублируется", "new": "Новая",
}

DEFAULT_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"


def secret_value(name):
    try:
        value = st.secrets.get(name, "")
    except Exception:
        return ""
    return str(value).strip() if value else ""


def configured_value(name, default=""):
    return os.getenv(name) or secret_value(name) or default


def apply_nim_settings(api_key, model, base_url):
    api_key = api_key.strip()
    model = model.strip()
    base_url = base_url.strip()

    if api_key:
        os.environ["NVIDIA_API_KEY"] = api_key
    elif not (os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")):
        secret_key = secret_value("NVIDIA_API_KEY") or secret_value("NIM_API_KEY")
        if secret_key:
            os.environ["NVIDIA_API_KEY"] = secret_key

    if model:
        os.environ["NIM_MODEL"] = model
    elif secret_value("NIM_MODEL") and not os.getenv("NIM_MODEL"):
        os.environ["NIM_MODEL"] = secret_value("NIM_MODEL")

    if base_url:
        os.environ["NIM_BASE_URL"] = base_url
    elif secret_value("NIM_BASE_URL") and not os.getenv("NIM_BASE_URL"):
        os.environ["NIM_BASE_URL"] = secret_value("NIM_BASE_URL")


def nim_configured():
    return bool((os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")) and os.getenv("NIM_MODEL"))


def input_key(before, after):
    digest = hashlib.sha256()
    for version, files in (("before", before), ("after", after)):
        digest.update(version.encode())
        for file in files:
            digest.update(json.dumps([file.name, file.size]).encode())
            digest.update(file.getvalue())
    return digest.hexdigest()


def show_sources(finding, source_map):
    for source_id in finding.source_ids:
        source = source_map[source_id]
        version = "До" if source.version == "before" else "После"
        with st.expander(f"{source_id} · {version} · {source.document} · {source.location}"):
            st.text(source.text)


def show_findings(findings, source_map, key):
    if not findings:
        st.info("В отчёте нет записей этого типа.")
        return
    rows = []
    for finding in findings:
        row = {"Вывод": finding.title}
        if hasattr(finding, "status"):
            row["Статус"] = LABELS[finding.status]
        if hasattr(finding, "before_units"):
            row["До"] = ", ".join(finding.before_units) or "—"
            row["После"] = ", ".join(finding.after_units) or "—"
        row["Обоснование"] = finding.explanation
        row["Источники"] = ", ".join(finding.source_ids)
        rows.append(row)
    st.dataframe(rows, hide_index=True, width="stretch")
    selected = st.selectbox("Проверить источники вывода", range(len(findings)),
                            format_func=lambda i: f"{i + 1}. {findings[i].title}", key=key)
    st.write(findings[selected].explanation)
    show_sources(findings[selected], source_map)


def text_report(report, origin):
    lines = ["ОргАнализ — отчёт", origin, "Выводы требуют проверки ответственным сотрудником.", ""]
    sections = [("Подразделения", report.departments), ("Функции", report.functions),
                ("Дублирование", report.duplicates), ("Конфликты", report.conflicts),
                ("Рекомендации", report.recommendations), ("Заключение", [report.conclusion])]
    for title, findings in sections:
        lines.append(title)
        for finding in findings:
            lines.extend([finding.title, finding.explanation])
            if hasattr(finding, "status"):
                lines.append("Статус: " + LABELS[finding.status])
            if hasattr(finding, "before_units"):
                lines.append("До: " + (", ".join(finding.before_units) or "—"))
                lines.append("После: " + (", ".join(finding.after_units) or "—"))
            lines.extend(["Источники: " + ", ".join(finding.source_ids), ""])
    lines.append("Фрагменты источников")
    for source in report.sources:
        version = "До" if source.version == "before" else "После"
        lines.extend([f"{source.id} | {version} | {source.document} | {source.location}", source.text, ""])
    return "\n".join(lines)


st.title("ОргАнализ")
st.write("Сравнение структуры и функций до и после реорганизации")
st.caption("Каждый вывод можно проверить по пунктам исходных документов.")

with st.sidebar:
    st.header("Рабочее пространство")
    mode = st.radio("Режим", ["Демонстрация", "Документы", "Готовый JSON"])
    st.divider()
    st.caption("1. Загрузите комплекты «до» и «после».\n\n"
               "2. Получите отчёт агента.\n\n3. Проверьте выводы по источникам.")
    st.info("Выводы ИИ носят рекомендательный характер и требуют проверки сотрудником.")
    st.divider()
    st.header("NIM API")
    st.caption("Ключ можно задать через env, Streamlit secrets или только на текущую сессию.")
    sidebar_api_key = st.text_input(
        "NVIDIA_API_KEY",
        type="password",
        placeholder="Оставьте пустым, если ключ уже задан",
    )
    sidebar_model = st.text_input("NIM_MODEL", value=configured_value("NIM_MODEL"))
    sidebar_base_url = st.text_input(
        "NIM_BASE_URL",
        value=configured_value("NIM_BASE_URL", DEFAULT_NIM_BASE_URL),
    )
    apply_nim_settings(sidebar_api_key, sidebar_model, sidebar_base_url)
    if nim_configured():
        st.success("NIM настроен")
    else:
        st.warning("Для анализа документов задайте NVIDIA_API_KEY и NIM_MODEL.")

report = None
origin = ""
if mode == "Демонстрация":
    st.warning("Учебные данные: это демонстрация интерфейса, а не анализ ваших документов.")
    report = demo_report()
    origin = "ДЕМО — вымышленные документы"
elif mode == "Готовый JSON":
    st.subheader("Результат команды")
    st.write("Загрузите JSON отчёта вместе с фрагментами источников.")
    uploaded = st.file_uploader("Отчёт агента", type=["json"])
    if uploaded:
        try:
            report = AnalysisReport.model_validate_json(uploaded.getvalue())
            origin = f"Импорт JSON: {uploaded.name}"
        except (ValidationError, ValueError) as exc:
            st.error("Отчёт не соответствует формату или содержит неизвестные ID источников.")
            with st.expander("Подробности для команды"):
                st.text(str(exc))
else:
    st.subheader("Документы для сравнения")
    left, right = st.columns(2)
    with left:
        before = st.file_uploader("До реорганизации", type=["docx", "pdf", "xlsx"],
                                  accept_multiple_files=True, key="before")
    with right:
        after = st.file_uploader("После реорганизации", type=["docx", "pdf", "xlsx"],
                                 accept_multiple_files=True, key="after")
    fingerprint = input_key(before, after)
    if st.session_state.get("input_key") != fingerprint:
        st.session_state.pop("analysis", None)
        st.session_state["input_key"] = fingerprint
    ready = backend_available()
    if not ready:
        st.info("Анализ документов будет доступен после подключения модуля команды. "
                "Сейчас можно посмотреть демонстрацию или открыть готовый JSON.")
    if ready and not nim_configured():
        st.warning("Backend подключён, но NIM не настроен. Укажите API key и model в боковой панели.")
    if st.button("Сравнить документы", type="primary", disabled=not (ready and before and after and nim_configured())):
        st.session_state.pop("analysis", None)
        try:
            with st.spinner("Агент сравнивает документы…"):
                result = analyze([InputDocument(f.name, f.getvalue()) for f in before],
                                 [InputDocument(f.name, f.getvalue()) for f in after])
            st.session_state["analysis"] = result.model_dump()
        except Exception:
            logging.exception("Document analysis failed")
            st.error("Не удалось получить корректный отчёт. Проверьте модуль анализа; подробности в терминале.")
    if "analysis" in st.session_state:
        report = AnalysisReport.model_validate(st.session_state["analysis"])
        origin = "Анализ загруженных документов"

if report is not None:
    source_map = {source.id: source for source in report.sources}
    st.divider()
    st.subheader("Результаты сравнения")
    st.caption(origin)
    metrics = st.columns(4)
    metrics[0].metric("Подразделения в отчёте", len(report.departments))
    metrics[1].metric("Потенциальные потери", sum(f.status == "lost" for f in report.functions))
    metrics[2].metric("Дублирование", len(report.duplicates))
    metrics[3].metric("Потенциальные конфликты", len(report.conflicts))
    tabs = st.tabs(["Подразделения", "Функции", "Дублирование", "Конфликты", "Заключение"])
    # Reset selection keys when another report is loaded.
    report_key = hashlib.sha256(report.model_dump_json().encode()).hexdigest()[:12]
    for tab, findings, name in zip(tabs[:4],
                                   [report.departments, report.functions, report.duplicates, report.conflicts],
                                   ["departments", "functions", "duplicates", "conflicts"]):
        with tab:
            show_findings(findings, source_map, f"{mode}_{report_key}_{name}")
    with tabs[4]:
        st.subheader(report.conclusion.title)
        st.write(report.conclusion.explanation)
        show_sources(report.conclusion, source_map)
        st.subheader("Рекомендации")
        show_findings(report.recommendations, source_map, f"{mode}_{report_key}_recommendations")
    st.divider()
    a, b = st.columns(2)
    prefix = "demo" if mode == "Демонстрация" else "analysis"
    with a:
        st.download_button("Скачать JSON", report.model_dump_json(indent=2),
                           file_name=f"{prefix}.json", mime="application/json")
    with b:
        st.download_button("Скачать заключение и источники", text_report(report, origin),
                           file_name=f"{prefix}.txt", mime="text/plain; charset=utf-8")
