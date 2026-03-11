def _parse_agents_from_data(data):
    agents = []
    for item in data:
        # Add debug log line here
        logger.info("[debug] 客服原始数据: uid_key=%s item=%s", uid_key, item)
        agents.append(item)
    return agents
