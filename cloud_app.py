"""Cloud entry point. Configure APP_PASSWORD and catalog keys in Streamlit Secrets."""
import hmac
import runpy
from pathlib import Path

import streamlit as st
import sys
sys.path.insert(0, str(Path(__file__).with_name('leadfinder.zip')))


def main():
    st.set_page_config(page_title="Leadfinder", page_icon="🎯", layout="wide")
    try:
        password = st.secrets.get("APP_PASSWORD", "")
    except FileNotFoundError:
        password = ""
    if not password:
        st.error("Приложение готовится к запуску. Пароль доступа ещё не настроен.")
        st.stop()
    if not st.session_state.get("authenticated"):
        st.title("Leadfinder")
        st.caption("Поиск компаний без сайта")
        with st.form("login"):
            entered = st.text_input("Пароль доступа", type="password")
            submitted = st.form_submit_button("Открыть приложение")
        if submitted:
            if hmac.compare_digest(entered.encode(), password.encode()):
                st.session_state.authenticated = True
                st.rerun()
            st.error("Неверный пароль.")
        st.stop()
    runpy.run_path(str(Path(__file__).with_name("miniapp.py")), run_name="__main__")


if __name__ == "__main__":
    main()
