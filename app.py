import time
import os

import requests
import streamlit as st

# 标题
st.title("智扫通机器人智能客服")
st.divider()

API_BASE_URL = os.getenv("AGENT_API_BASE_URL", "http://127.0.0.1:8000")

if "message" not in st.session_state:
    st.session_state["message"] = []

for message in st.session_state["message"]:
    st.chat_message(message["role"]).write(message["content"])

# 用户输入提示词
prompt = st.chat_input()

if prompt:
    st.chat_message("user").write(prompt)
    st.session_state["message"].append({"role": "user", "content": prompt})

    response_messages: list[str] = []
    with st.spinner("智能客服思考中..."):
        try:
            payload = {"message": prompt}
            resp = requests.post(
                f"{API_BASE_URL}/v1/chat/stream",
                json=payload,
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()

            def api_stream():
                for chunk in resp.iter_content(chunk_size=1, decode_unicode=True):
                    if chunk:
                        yield chunk

            res_stream = api_stream()
        except Exception as e:
            err_msg = f"API调用失败：{e}"
            st.chat_message("assistant").write(err_msg)
            st.session_state["message"].append({"role": "assistant", "content": err_msg})
            st.stop()

        def capture(generator, cache_list):
            for chunk in generator:
                cache_list.append(chunk)
                for char in chunk:
                    time.sleep(0.01)
                    yield char

        st.chat_message("assistant").write_stream(capture(res_stream, response_messages))
        st.session_state["message"].append({"role": "assistant", "content": "".join(response_messages)})
        st.rerun()


