import unittest
import os
import sys
import json
import shutil

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from CustomRoute import app

class A2AFileTestCase(unittest.TestCase):
    """A2A 文件管理系统单元测试"""

    def setUp(self):
        """测试前准备"""
        self.app = app.test_client()
        self.app.testing = True

        # A2A 目录路径
        self.a2a_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'A2AFile')

        # 确保 A2A 目录存在
        if not os.path.exists(self.a2a_dir):
            os.makedirs(self.a2a_dir)

        # 测试文件名
        self.test_file = 'exam1.md'

    def tearDown(self):
        """测试后清理"""
        # 清理测试文件
        test_file_path = os.path.join(self.a2a_dir, self.test_file)
        if os.path.exists(test_file_path):
            os.remove(test_file_path)

    def test_1_list_root(self):
        """测试获取根目录文件列表"""
        response = self.app.get('/api/a2a/list')
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['success'])
        self.assertIn('files', data)
        self.assertIn('current_path', data)

    def test_2_create_file(self):
        """测试创建文件"""
        response = self.app.post('/api/a2a/create',
            json={
                'path': self.test_file,
                'content': '# Test File\nInitial content.',
                'desc': '单元测试创建'
            })
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['success'])
        self.assertEqual(data['message'], '文件创建成功')

    def test_3_get_file(self):
        """测试获取文件内容"""
        # 先创建文件
        self.app.post('/api/a2a/create',
            json={
                'path': self.test_file,
                'content': '# Test File\nInitial content.'
            })

        # 获取文件
        response = self.app.get(f'/api/a2a/get?path={self.test_file}')
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['success'])
        self.assertIn('# Test File', data['content'])
        self.assertEqual(data['extension'], '.md')

    def test_4_update_file(self):
        """测试修改文件"""
        # 先创建文件
        self.app.post('/api/a2a/create',
            json={
                'path': self.test_file,
                'content': '# Test File\nInitial content.'
            })

        # 修改文件
        response = self.app.post('/api/a2a/update',
            json={
                'path': self.test_file,
                'content': '# Modified\nUpdated content.',
                'desc': '单元测试修改'
            })
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['success'])
        self.assertEqual(data['message'], '文件修改成功')

        # 验证修改后的内容
        response = self.app.get(f'/api/a2a/get?path={self.test_file}')
        data = json.loads(response.data)
        self.assertIn('Modified', data['content'])

    def test_5_history(self):
        """测试获取 Git 历史"""
        # 先创建并修改文件
        self.app.post('/api/a2a/create',
            json={
                'path': self.test_file,
                'content': '# Test File\nInitial content.'
            })
        self.app.post('/api/a2a/update',
            json={
                'path': self.test_file,
                'content': '# Modified\nUpdated content.'
            })

        # 获取历史
        response = self.app.get(f'/api/a2a/history?path={self.test_file}')
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['success'])
        self.assertIn('commits', data)
        self.assertGreaterEqual(len(data['commits']), 2)

    def test_6_delete_file(self):
        """测试删除文件"""
        # 先创建文件
        self.app.post('/api/a2a/create',
            json={
                'path': self.test_file,
                'content': '# Test File'
            })

        # 删除文件
        response = self.app.post('/api/a2a/delete',
            json={
                'path': self.test_file
            })
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['success'])
        self.assertEqual(data['message'], '文件删除成功')

        # 验证文件已删除
        response = self.app.get(f'/api/a2a/get?path={self.test_file}')
        data = json.loads(response.data)
        self.assertFalse(data['success'])

    def test_7_path_security(self):
        """测试路径安全检查"""
        # 尝试路径穿越
        response = self.app.get('/api/a2a/list?path=../../../')
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(data['success'])
        self.assertEqual(data['message'], '路径访问被拒绝')

    def test_8_invalid_extension(self):
        """测试不支持的文件扩展名"""
        response = self.app.post('/api/a2a/create',
            json={
                'path': 'test.txt',
                'content': 'some content'
            })
        data = json.loads(response.data)

        # 文件应该被创建，但不会出现在列表中
        self.assertEqual(response.status_code, 200)
        if data['success']:
            # 清理
            self.app.post('/api/a2a/delete', json={'path': 'test.txt'})


if __name__ == '__main__':
    unittest.main(verbosity=2)