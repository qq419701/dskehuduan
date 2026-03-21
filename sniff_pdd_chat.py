        def _on_websocket(ws) -> None:
            url = ws.url
            print(_info(f"WebSocket 已连接: {url}"))
            if "pinduoduo" not in url and "pdd" not in url.lower():
                return

            def _get_payload(frame) -> str:
                """兼容新旧版 Playwright：新版直接传 bytes，旧版传 dict"""
                if isinstance(frame, (bytes, bytearray)):
                    try:
                        return frame.decode("utf-8", errors="replace")
                    except Exception:
                        return ""
                if isinstance(frame, str):
                    return frame
                if isinstance(frame, dict):
                    return frame.get("payload", "")
                return str(frame)

            ws.on(
                "framesent",
                lambda frame: _handle_ws_frame(_get_payload(frame), "SEND"),
            )
            ws.on(
                "framereceived",
                lambda frame: _handle_ws_frame(_get_payload(frame), "RECV"),
            )