import subprocess
import time
import re
import sys
import json
import platform
from typing import List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

class DNSSpeedTest:
    def __init__(self):
        # 从配置文件加载DNS服务器列表
        config_path = Path(__file__).parent / 'dns_servers.json'
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.dns_servers = [(server['ip'], server['name']) for server in config['dns_servers']]
                self.test_domain = config.get('test_domain', 'www.baidu.com')
                self.count  = config.get('count',  100) 
                self.dns_servers  = self.dns_servers[:self.count]  
        except Exception as e:
            print(f'加载配置文件失败: {str(e)}')
            sys.exit(1)
        
        self.is_windows = platform.system().lower() == 'windows'

    def ping_dns(self, dns_server: Tuple[str, str]) -> Dict:
        """测试DNS服务器的响应时间"""
        ip, name = dns_server
        try:
            # 根据操作系统选择不同的ping命令参数
            if self.is_windows:
                cmd = ['ping', '-n', '3', '-w', '1000', ip]
            else:
                cmd = ['ping', '-c', '3', '-W', '1', ip]

            start_time = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='gbk', errors='ignore')
            
            # 解析ping结果
            if result.returncode == 0:
                if self.is_windows:
                    match = re.search(r'平均 = (\d+)ms', result.stdout)
                else:
                    match = re.search(r'min/avg/max.+= [\d.]+/([\d.]+)/', result.stdout)
                
                if match:
                    latency = float(match.group(1))
                    return {'ip': ip, 'name': name, 'latency': latency, 'status': 'ok'}
            
            return {'ip': ip, 'name': name, 'latency': float('inf'), 'status': 'failed'}
        except Exception as e:
            print(f'测试 {name} ({ip}) 时发生错误: {str(e)}')
            return {'ip': ip, 'name': name, 'latency': float('inf'), 'status': 'error'}

    def test_all_dns(self) -> List[Dict]:
        """测试所有DNS服务器的响应时间"""
        print('开始测试DNS服务器延迟...')
        results = []
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(self.ping_dns, server) for server in self.dns_servers]
            for future in futures:
                result = future.result()
                results.append(result)
                print(f'{result["name"]} ({result["ip"]}): '
                      f'{result["latency"]:.1f}ms ({result["status"]})')
                sys.stdout.flush()  # 实时刷新输出
        
        return sorted(results, key=lambda x: x['latency'])

    def get_network_adapters(self) -> List[str]:
        """获取所有已启用的网络适配器"""
        adapters = []
        try:
            cmd = ['netsh', 'interface', 'ipv4', 'show', 'interfaces']
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
            
            if not result.stdout:
                print('获取网络适配器信息失败：命令输出为空')
                return adapters

            lines = result.stdout.splitlines()
            
            # 查找已启用的接口
            for line in lines:
                if line and line.strip():
                    # 检查是否包含"已连接"或"connected"状态
                    if '已连接' in line:
                        adapter = line.split('已连接')[-1].strip()
                        if adapter:
                            adapters.append(adapter)
                    elif 'connected' in line:
                        adapter = line.split('connected')[-1].strip()
                        if adapter:
                            adapters.append(adapter)
        except Exception as e:
            print(f'获取网络适配器列表时发生错误: {str(e)}')
        
        return adapters

    def set_dns_windows(self, dns_servers: List[str]) -> bool: 
        """在Windows系统中设置DNS服务器""" 
        try: 
            # 获取网络适配器列表 
            adapters = self.get_network_adapters()
            
            if not adapters: 
                print('\n未找到已启用的网络适配器，可能的原因：') 
                print('1. 网络适配器未启用') 
                print('2. 网络连接已断开') 
                print('3. 需要管理员权限') 
                return False 
            
            # 显示可用的网络适配器列表
            print('\n可用的网络适配器列表：')
            for i, adapter in enumerate(adapters, 1):
                print(f'{i}. {adapter}')
            
            # 让用户选择网络适配器
            while True:
                try:
                    choice = input('\n请选择要设置DNS的网络适配器编号: ').strip()
                    index = int(choice) - 1
                    if 0 <= index < len(adapters):
                        adapter = adapters[index]
                        break
                    else:
                        print('无效的选择，请重新输入')
                except ValueError:
                    print('请输入有效的数字')
            
            print(f'\n正在设置网络适配器 {adapter} 的DNS服务器...') 
            
            # 设置主DNS 
            cmd = ['netsh', 'interface', 'ipv4', 'set', 'dns', 
                f'"{adapter}"', 'static', dns_servers[0]]  # 给适配器名称加双引号 
            print(f'执行命令: {" ".join(cmd)}') 
            subprocess.run(cmd,  check=True, capture_output=True, text=True, encoding='gbk', errors='ignore') 
            
            # 设置备用DNS 
            if len(dns_servers) > 1: 
                cmd = ['netsh', 'interface', 'ipv4', 'add', 'dns', 
                    f'"{adapter}"', dns_servers[1], 'index=2']  # 给适配器名称加双引号 
                print(f'执行命令: {" ".join(cmd)}') 
                subprocess.run(cmd,  check=True, capture_output=True, text=True, encoding='gbk', errors='ignore') 
            
            print(f'已成功设置网络适配器 {adapter} 的DNS服务器') 
            return True 
        except subprocess.CalledProcessError as e: 
            print(f'设置DNS时发生错误: {str(e)}') 
            return False 
        except Exception as e: 
            print(f'设置DNS时发生未知错误: {str(e)}') 
            return False 

    def run(self):
        """运行DNS测速和自动切换"""
        if not self.is_windows:
            print('当前仅支持Windows系统')
            return
        
        print('开始DNS测速工具...')
        print(f'测试域名: {self.test_domain}')
        print('='*50)
        
        # 测试所有DNS服务器
        results = self.test_all_dns()
        print('\n测试完成！')
        print('='*50)
        
        # 显示最快的DNS服务器
        print('\n延迟最低的DNS服务器:')
        for i, result in enumerate(results[:3], 1):
            if result['latency'] != float('inf'):
                print(f'{i}. {result["name"]} ({result["ip"]}): {result["latency"]:.1f}ms')
        
        # 选择最快的两个DNS服务器
        fastest_dns = [r['ip'] for r in results[:2] if r['latency'] != float('inf')]
        if len(fastest_dns) < 2:
            print('\n没有足够的可用DNS服务器')
            return
        
        # 询问是否要切换DNS
        print('\n是否要将DNS切换为延迟最低的服务器？(y/n)')
        choice = input().strip().lower()
        if choice == 'y':
            if self.set_dns_windows(fastest_dns):
                print(f'\nDNS已成功切换为:\n主DNS: {fastest_dns[0]}\n备用DNS: {fastest_dns[1]}')
            else:
                print('\nDNS切换失败，请检查是否有管理员权限')

if __name__ == '__main__':
    # 检查是否以管理员权限运行
    if platform.system().lower() == 'windows':
        try:
            is_admin = subprocess.run(['net', 'session'], capture_output=True).returncode == 0
            if not is_admin:
                print('请以管理员权限运行此程序')
                print('请使用 run_dns_test.vbs 启动程序')
                sys.exit(1)
        except:
            print('请以管理员权限运行此程序')
            print('请使用 run_dns_test.vbs 启动程序')
            sys.exit(1)
    
    dns_test = DNSSpeedTest()
    dns_test.run()
    
    # 等待用户按任意键退出
    print('\n按回车键退出程序...')
    input()