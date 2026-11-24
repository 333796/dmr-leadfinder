from __future__ import annotations
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests
import streamlit as st
from leadfinder.app import process_companies
from leadfinder.config import load_config
from leadfinder.sources.base import MissingAPIKeyError, QuotaExceededError
from leadfinder.sources.csv_source import CSVSource
st.set_page_config(page_title="Leadfinder — лиды без сайта", page_icon="🎯", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: Manrope, sans-serif; }
.stApp { background: radial-gradient(ellipse at 12% 0%, #1d2c37 0, #0b1117 45%, #080c10 100%); color: #f4f0e8; }
.block-container { padding-top: 2rem; max-width: 1400px; }
[data-testid="stMetric"] { background: #131e26; border: 1px solid #2c3d48; border-radius: 16px; padding: 16px 20px; }
[data-testid="stFileUploader"] { border: 1px dashed #ff7046; border-radius: 16px; padding: 12px; }
.stButton button, .stDownloadButton button { border-radius: 30px; font-weight: 700; }
</style>
""", unsafe_allow_html=True)
st.markdown("## 🎯 Leadfinder <span style='color:#ff7046'>/</span> Стерлитамак", unsafe_allow_html=True)
st.caption("Локальный помощник менеджера: публичные контакты бизнеса, без массовых рассылок. Проверяйте карточки перед обращением.")
st.info("Источник 2ГИС выбран по умолчанию. Измените категории слева и нажмите «Найти компании без сайта». Поиск запускается только по вашему нажатию, чтобы не расходовать квоту автоматически.")
with st.sidebar:
    st.header("Настройки поиска")
    source_name = st.selectbox("Источник", ["2GIS API", "CSV-экспорт", "Яндекс Карты API", "Google Places API"], index=0)
    city = st.text_input("Город", value="Стерлитамак")
    categories_text = st.text_area("Категории (по одной на строку)", "кофейня\nстоматология\nавтосервис\nсалон красоты")
    min_rating = st.number_input("Минимальный рейтинг", min_value=0.0, max_value=5.0, value=3.0, step=0.1)
    has_phone = st.checkbox("Только компании с телефоном", value=False)
    limit = st.number_input("Лимит на категорию", min_value=1, max_value=5000, value=100, step=50)
    st.divider()
    st.caption("API-ключи хранятся локально в .env. Поиск идёт через официальный API и останавливается при ошибке доступа/квоты.")
source_map = {"Яндекс Карты API": "yandex", "2GIS API": "2gis", "Google Places API": "google", "CSV-экспорт": "csv"}
source = source_map[source_name]
if source == "csv":
    uploaded = st.file_uploader("Загрузите CSV из публичного бизнес-каталога (необязательно)", type=["csv"])
    st.caption("Если файла пока нет, оставьте поле пустым: приложение попробует прочитать встроенный шаблон data/sterlitamak_template.csv. Шаблон пустой — его нужно заполнить данными каталога. Колонки: name, address, phone, website, category, url; дополнительно можно заполнить rating, reviews_count, phone_extra, vk, instagram, telegram.")
else:
    uploaded = None
    st.info("Будут использованы ключи из .env. Для API соблюдаются пауза минимум 0,15 с между запросами и ограничения провайдера.")
if "leads" not in st.session_state:
    st.session_state.leads = []
    st.session_state.found = 0
if st.button("Найти компании без сайта", type="primary", use_container_width=True):
    categories = [line.strip() for line in categories_text.splitlines() if line.strip()]
    if not city.strip() or not categories:
        st.error("Введите город и хотя бы одну категорию.")
    else:
        try:
            if source == "csv":
                if uploaded is not None:
                    raw_text = uploaded.getvalue().decode("utf-8-sig")
                    source_obj = CSVSource("uploaded.csv")
                    reader = csv.DictReader(io.StringIO(raw_text))
                    if not {"name", "website"}.issubset(reader.fieldnames or []):
                        st.error("В CSV нужны столбцы name и website с разделителем-запятой.")
                        st.stop()
                    rows = list(reader)
                else:
                    bundled_csv = Path("data/sterlitamak_template.csv")
                    if not bundled_csv.exists():
                        st.error("Загрузите CSV-выгрузку каталога. Встроенный шаблон не найден.")
                        st.stop()
                    source_obj = CSVSource(bundled_csv)
                    with bundled_csv.open("r", encoding="utf-8-sig", newline="") as stream:
                        rows = list(csv.DictReader(stream))
                    if not rows:
                        st.error("Встроенный шаблон CSV пустой. Сначала нужна выгрузка из каталога или API-ключ.")
                        st.stop()
                companies = []
                counts = dict.fromkeys((c.casefold() for c in categories), 0)
                for row in rows:
                    category = (row.get("category") or categories[0]).strip()
                    key = category.casefold()
                    if key not in counts or counts[key] >= limit:
                        continue
                    if row.get("city") and row["city"].strip().casefold() != city.strip().casefold():
                        continue
                    companies.append(source_obj.normalize_company(row, category, city.strip()))
                    counts[key] += 1
            else:
                config = load_config("config.yaml")
                config = config.model_copy(update={"source": source, "city": city.strip(), "categories": categories, "max_results_per_category": int(limit), "min_rating": min_rating if min_rating > 0 else None, "has_phone": has_phone})
                from leadfinder.__main__ import _build_source
                api = _build_source(config)
                companies = []
                progress = st.progress(0, text="Поиск в каталоге…")
                for idx, category in enumerate(categories, 1):
                    companies.extend(api.fetch(category, city.strip(), int(limit)))
                    progress.progress(idx / len(categories), text=f"Обработана категория: {category}")
                progress.empty()
                if source == "2gis" and companies and not any(c.phone for c in companies):
                    st.warning("2ГИС вернул названия и адреса, но не телефоны. По документации 2ГИС поле contact_groups может требовать отдельного разрешения/тарифа. Включите доступ к контактным полям в кабинете 2ГИС. Пока можно открыть карточки компаний из списка ниже.")
            result = process_companies(companies, min_rating=min_rating if min_rating > 0 else None, has_phone=has_phone)
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for lead in result["leads"]:
                lead.collected_at = stamp
            st.session_state.leads = result["leads"]
            st.session_state.found = result["found"]
            st.success(f"Готово: найдено {result['found']} компаний, без сайта и по фильтрам — {result['passed']}.")
        except MissingAPIKeyError as exc:
            st.error(str(exc))
        except QuotaExceededError as exc:
            st.error(f"Поиск остановлен: {exc}")
        except requests.RequestException as exc:
            status = f" (HTTP {exc.response.status_code})" if exc.response is not None else ""
            st.error(f"Не удалось получить ответ каталога{status}. Проверьте соединение и настройки доступа.")
        except Exception as exc:
            st.error(f"Не удалось выполнить поиск: {exc}")
leads = st.session_state.leads
if leads:
    st.divider()
    st.subheader("Компании без указанного сайта")
    st.caption("Контакты доступны только если источник разрешил их выдачу. Открывайте карточку компании, чтобы проверить данные и связаться вручную.")
    for idx, lead in enumerate(leads):
        with st.container(border=True):
            title_col, score_col = st.columns([5, 1])
            title_col.markdown(f"### {lead.name or 'Без названия'}")
            title_col.caption(f"{lead.category} · {lead.city}")
            score_col.metric("Score", lead.score)
            st.write(lead.address or "Адрес не указан")
            actions = st.columns([1, 1, 1, 3])
            if lead.phone:
                actions[0].link_button("Позвонить", f"tel:{lead.phone}", use_container_width=True)
            else:
                actions[0].button("Телефон недоступен", key=f"no-phone-{idx}", disabled=True, use_container_width=True)
            if lead.source_url:
                actions[1].link_button("Карточка в каталоге", lead.source_url, use_container_width=True)
            if lead.website:
                actions[2].link_button("Сайт", lead.website, use_container_width=True)
            else:
                actions[2].button("Сайта нет в каталоге", key=f"no-site-{idx}", disabled=True, use_container_width=True)
            contacts = []
            if lead.vk: contacts.append(f"VK: {lead.vk}")
            if lead.instagram: contacts.append(f"Instagram: {lead.instagram}")
            if lead.telegram: contacts.append(f"Telegram: {lead.telegram}")
            actions[3].caption(" · ".join(contacts) if contacts else "Связь: позвонить по телефону или написать через каталог, если там доступен контакт.")
    m1, m2, m3 = st.columns(3)
    m1.metric("Найдено организаций", st.session_state.found)
    m2.metric("Лидов без сайта", len(leads))
    m3.metric("Средний score", round(sum(x.score for x in leads) / len(leads)))
    table_rows = []
    for lead in leads:
        row = lead.model_dump(exclude={"raw"})
        row["phone_extra"] = "; ".join(row["phone_extra"])
        table_rows.append(row)
    display_order = ["score", "name", "category", "city", "address", "phone", "phone_extra", "vk", "instagram", "telegram", "rating", "reviews_count", "source", "source_url", "legal_name", "comment", "collected_at"]
    frame = pd.DataFrame(table_rows).reindex(columns=display_order)
    st.dataframe(frame, use_container_width=True, hide_index=True, column_config={"score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d")})
    csv_bytes = frame.to_csv(index=False).encode("utf-8-sig")
    json_bytes = json.dumps([lead.model_dump(mode="json") for lead in leads], ensure_ascii=False, indent=2).encode("utf-8")
    xlsx_buffer = io.BytesIO()
    with pd.ExcelWriter(xlsx_buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Leads")
    left, middle, right = st.columns(3)
    left.download_button("Скачать CSV для Excel", csv_bytes, "sterlitamak_leads.csv", "text/csv", use_container_width=True)
    middle.download_button("Скачать XLSX", xlsx_buffer.getvalue(), "sterlitamak_leads.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    right.download_button("Скачать JSON", json_bytes, "sterlitamak_leads.json", "application/json", use_container_width=True)
else:
    st.markdown("### Начните с каталожной выгрузки или выберите API")
    st.write("Сайт считается отсутствующим только если каталог не опубликовал ссылку. Это не гарантирует, что у компании вообще нет сайта.")
st.caption("Данные предназначены только для ручной работы менеджера. Не собираются личные телефоны и ФИО. Рекомендуется удалять выгрузки в течение 90 дней.")
