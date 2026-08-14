import sqlite3
import json
import os

DATABASE = 'templates.db'

def get_db_path():
    """获取数据库文件的绝对路径"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, DATABASE)

def init_db():
    """初始化数据库，创建模板表"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            data TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def add_template(name, type, data):
    """添加新模板"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO templates (name, type, data) VALUES (?, ?, ?)", (name, type, json.dumps(data)))
    conn.commit()
    template_id = cursor.lastrowid
    conn.close()
    return template_id

def get_templates():
    """获取所有模板"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, type, data FROM templates")
    templates = []
    for row in cursor.fetchall():
        templates.append({
            'id': row[0],
            'name': row[1],
            'type': row[2],
            'data': json.loads(row[3])
        })
    conn.close()
    return templates

def update_template(template_id, name, type, data):
    """更新指定ID的模板（覆盖）"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE templates SET name=?, type=?, data=? WHERE id=?", (name, type, json.dumps(data), template_id))
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    return rows_affected > 0

def delete_template(template_id):
    """删除指定ID的模板"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM templates WHERE id = ?", (template_id,))
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    return rows_affected > 0

# 确保数据库在模块导入时被初始化
init_db()
