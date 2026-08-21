import re

# 读取文件内容
with open('test.md', 'r', encoding='utf-8') as f:
    content = f.read()

# 应用正则表达式替换
pattern = r'^(\s*)(\d+)\.(\d+)\s+'
replacement = r'\1\3. '
new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

# 保存修改后的内容
with open('test_fixed.md', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Markdown列表格式已修复！")