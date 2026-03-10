import json, os, requests

config_file = os.path.expanduser('~') + r'\.aikefu-client\config.json'
cfg = json.load(open(config_file, encoding='utf-8'))

token = cfg.get('client_token', '')
server = cfg.get('server_url', 'http://8.145.43.255:1010')

r = requests.get(server + '/api/client/shops', headers={'X-Client-Token': token}, timeout=10)
shops = r.json().get('shops', [])
print('同步到店铺:')
for s in shops:
    print('  - [' + str(s['id']) + '] ' + s['name'] + ' (' + s['platform'] + ')')

cfg['active_shops'] = shops
cfg['task_runner'] = {'enabled': True, 'poll_interval': 2, 'heartbeat_interval': 30}
json.dump(cfg, open(config_file, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('修复完成，已激活全部', len(shops), '家店铺')
