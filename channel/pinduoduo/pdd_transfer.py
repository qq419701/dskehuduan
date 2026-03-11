                "remark": (item.get("remarkName") or item.get("remark") or
                           item.get("memo") or item.get("tag") or
                           item.get("comment") or item.get("note") or
                           item.get("csRemark") or item.get("label") or ""),

logger.info(f"[transfer] 客服原始数据... Remark: {item.get('remarkName') or item.get('remark') or item.get('memo') or item.get('tag') or item.get('comment') or item.get('note') or item.get('csRemark') or item.get('label') or ''}")
