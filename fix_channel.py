content = open('channel/pinduoduo/pdd_channel.py', encoding='utf-8').read()
old = '        if reply and not needs_human and self.sender:'
new = '        # process_by=plugin 时也发送立即回复话术\n        if reply and self.sender and (not needs_human or process_by == \"plugin\"):'
if old in content:
    open('channel/pinduoduo/pdd_channel.py', 'w', encoding='utf-8').write(content.replace(old, new))
    print('OK')
else:
    print('NOT FOUND: ' + repr(content[content.find('if reply'):content.find('if reply')+60]))
