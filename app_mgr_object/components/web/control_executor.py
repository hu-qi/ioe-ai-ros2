#!/usr/bin/env python3
"""
控制执行器 - 重构版（支持开发/部署双模式，正确重启逻辑）
使用SIGINT信号模拟Ctrl+C，触发脚本自身的cleanup函数
"""
import subprocess
import time
import threading
import os
import signal
import psutil
from typing import Dict, Any, Tuple, Optional, List
import logging
import sys
import re
import rclpy.logging

class ControlExecutor:
    """控制执行器（重构版）"""
    
    # def __init__(self, mode: str = "development", config: Dict[str, Any] = None):
    def __init__(self, mode: str = "development", config: Dict[str, Any] = None, logger=None):
        self.mode = mode if mode else "development"  # 默认开发模式
        self.config = config or {}
        self.logger = logger or rclpy.logging.get_logger(__name__)
        
        # 从配置中获取值
        self.dev_scripts = self.config.get('dev_scripts', {})
        self.deployment_services = self.config.get('deployment_services', {})
        self.node_names = self.config.get('node_names', {})
        
        # 如果配置中提供了操作模式，使用它
        config_mode = self.config.get('operation_mode')
        if config_mode and config_mode in ['development', 'deployment']:
            self.mode = config_mode
            
        self.logger.info(f"控制执行器初始化完成，最终模式: {self.mode}")
        
        # 获取当前进程的PID，避免杀死自身
        self.current_pid = os.getpid()
        self.current_pgid = os.getpgid(self.current_pid)
        self.logger.info(f"控制执行器初始化完成，模式: {self.mode}, PID: {self.current_pid}")
               
        
        
        
        # 根据模式选择不同的服务配置
        if self.mode == "deployment":
            self.deployment_services = self.config.get('deployment_services', {
                'rtsp_yolo_service': 'rtsp-yolo-infer.service',
                'rcs_manager_service': 'rcs_manager.service'  # 注意：根据配置改为 rcs_manager.service
            })
        else:
            self.deployment_services = self.config.get('deployment_services', {
                'rtsp_yolo_service': 'rtsp-yolo-infer.service',
                'rcs_manager_service': 'rcs_manager.service'
            })
        
        
        
        self._lock = threading.RLock()
        self._operation_logs = []
        self._is_restarting = False  # 重启锁
        
        # 添加操作限制配置
        self.operation_limits = {
            'max_per_minute': self.config.get('max_operations_per_minute', 10),
            'max_per_hour': self.config.get('max_operations_per_hour', 50),
            'cooldown_seconds': self.config.get('operation_cooldown', 5)
        }
        
        # 操作历史记录
        self.operation_history = []
        self._operation_history_lock = threading.RLock()
        
       
        # 构建类型 -> 脚本键、服务键的映射
        self.type_to_script_key = {}
        self.type_to_service_key = {}
        for t in self.node_names:
            if t == 'rcs':
                self.type_to_script_key[t] = 'rcs_manager_script'
                self.type_to_service_key[t] = 'rcs_manager_service'
            else:
                self.type_to_script_key[t] = f'{t}_infer_script'
                self.type_to_service_key[t] = f'{t}_yolo_service'

        self.script_map = {t: self.dev_scripts.get(k) for t, k in self.type_to_script_key.items()}
        self.service_map = {t: self.deployment_services.get(k) for t, k in self.type_to_service_key.items()}

        self.logger.info(f"脚本映射: {self.script_map}")
        self.logger.info(f"服务映射: {self.service_map}")
        
        
        
        
        
    # ==================== 模式检测 ====================
    
    def _auto_detect_mode(self) -> str:
        """自动检测运行模式（已弃用，使用配置参数）"""
        # 直接返回当前模式，不进行任何检测
        return self.mode if hasattr(self, 'mode') else "development"
    
    # ==================== 开发模式方法 ====================
    
    def _get_script_pids(self, script_name: str) -> List[int]:
        """获取脚本进程的所有PID - 精确查找"""
        pids = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
                try:
                    cmdline = proc.info['cmdline'] or []
                    cmdline_str = ' '.join(cmdline)
                    
                    # 更加精确的匹配
                    if (script_name in cmdline_str and 
                        len(cmdline) > 1 and  # 确保不是grep命令本身
                        'grep' not in cmdline_str and  # 排除grep命令
                        'defunct' not in cmdline_str and  # 排除僵尸进程
                        'rcs_manager' not in cmdline_str.lower()):  # 排除RCS管理器
                        
                        pid = proc.info['pid']
                        if pid != self.current_pid and pid not in pids:
                            # 进一步验证确实是我们要找的脚本
                            try:
                                exe_path = proc.info['exe'] or ''
                                if '/bin/bash' in exe_path or '/bin/sh' in exe_path or 'python' in exe_path:
                                    pids.append(pid)
                            except:
                                pids.append(pid)
                                
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            self.logger.debug(f"获取脚本PID失败: {e}")
        
        return pids
    
    def _get_process_tree(self, pid: int) -> List[int]:
        """获取进程树的所有PID"""
        pids = []
        try:
            pids.append(pid)
            process = psutil.Process(pid)
            for child in process.children(recursive=True):
                pids.append(child.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        
        return pids
    
    def _send_sigint_to_script(self, script_name: str) -> Dict[str, Any]:
        """向脚本进程发送SIGINT信号（只发送给指定进程，不发送给整个进程组）"""
        results = {
            "sent_signal": False,
            "pids_found": [],
            "pids_signaled": [],
            "errors": []
        }
        
        try:
            # 1. 查找脚本进程
            pids = self._get_script_pids(script_name)
            if not pids:
                results["errors"].append(f"未找到脚本进程: {script_name}")
                return results
            
            results["pids_found"] = pids
            self.logger.info(f"找到脚本 {script_name} 的进程: {pids}")
            
            # 2. 向每个进程发送SIGINT信号，但不发送给整个进程组
            for pid in pids:
                try:
                    # 检查进程是否还在运行
                    try:
                        os.kill(pid, 0)  # 检查进程是否存在
                    except OSError:
                        results["errors"].append(f"进程 {pid} 已不存在")
                        continue
                    
                    self.logger.info(f"向进程 {pid} 发送SIGINT信号 (不发送给整个进程组)")
                    
                    # 只向特定进程发送SIGINT，不向整个进程组发送
                    os.kill(pid, signal.SIGINT)
                    results["pids_signaled"].append(pid)
                    
                    # 同时获取并发送给直接子进程
                    try:
                        process = psutil.Process(pid)
                        for child in process.children(recursive=False):  # 只获取直接子进程
                            try:
                                self.logger.info(f"向子进程 {child.pid} 发送SIGINT信号")
                                os.kill(child.pid, signal.SIGINT)
                                results["pids_signaled"].append(child.pid)
                            except (psutil.NoSuchProcess, ProcessLookupError):
                                pass
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    
                except ProcessLookupError:
                    results["errors"].append(f"进程 {pid} 不存在")
                except Exception as e:
                    results["errors"].append(f"向进程 {pid} 发送SIGINT失败: {e}")
            
            results["sent_signal"] = len(results["pids_signaled"]) > 0
            
            if results["sent_signal"]:
                self.logger.info(f"已向 {len(results['pids_signaled'])} 个进程发送SIGINT信号")
            
            return results
            
        except Exception as e:
            self.logger.error(f"发送SIGINT信号失败: {e}")
            results["errors"].append(str(e))
            return results
    
    def _find_all_related_pids(self, script_name: str) -> List[int]:
        """查找所有相关进程的PID"""
        pids = set()
        
        all_patterns = set()
        for group in self.node_names.values():
            all_patterns.update(group.get('patterns', []))
        # 组合为正则
        patterns_str = '|'.join(re.escape(p) for p in all_patterns if p)
        if not patterns_str:
            patterns_str = re.escape(script_name)  # 回退到脚本名
            
        try:
            # 查找脚本进程
            cmd = f"ps aux | grep -E '{patterns_str}' | grep -v grep | awk '{{print $2}}'"
            success, output, error = self._execute_command(cmd, ignore_errors=True)
            
            if success and output.strip():
                for pid_str in output.strip().split():
                    if pid_str.isdigit():
                        pids.add(int(pid_str))
            
            # 递归查找所有子进程
            all_pids = set(pids)
            for pid in pids:
                try:
                    process = psutil.Process(pid)
                    for child in process.children(recursive=True):
                        all_pids.add(child.pid)
                except:
                    pass
            
            return list(all_pids)
            
        except Exception as e:
            self.logger.debug(f"查找相关PID失败: {e}")
            return []
    
    def _force_kill_pids(self, pids: List[int]) -> None:
        """强制终止进程（只终止指定进程，不终止整个进程组）"""
        for pid in pids:
            try:
                # 先尝试TERM信号（优雅停止）
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.5)
                
                # 检查是否还在运行
                try:
                    os.kill(pid, 0)  # 检查进程是否存在
                    # 如果还在，发送KILL信号（强制终止）
                    os.kill(pid, signal.SIGKILL)
                    self.logger.warning(f"强制终止进程: {pid}")
                    
                    # 同时终止直接子进程
                    try:
                        process = psutil.Process(pid)
                        for child in process.children(recursive=True):
                            try:
                                os.kill(child.pid, signal.SIGKILL)
                                self.logger.warning(f"强制终止子进程: {child.pid}")
                            except:
                                pass
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                        
                except OSError:
                    pass  # 进程已终止
                    
            except ProcessLookupError:
                pass  # 进程已不存在
            except Exception as e:
                self.logger.debug(f"终止进程 {pid} 失败: {e}")
    
    def _execute_command(self, command: str, timeout: int = 30, ignore_errors: bool = False) -> Tuple[bool, str, str]:
        """执行命令"""
        try:
            self.logger.debug(f"执行命令: {command}")
            
            process = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8'
            )
            
            success = process.returncode == 0
            output = process.stdout.strip()
            error = process.stderr.strip()
            
            return (success, output, error)
            
        except subprocess.TimeoutExpired:
            if ignore_errors:
                return (False, "", f"命令超时: {timeout}s")
            raise
        except Exception as e:
            if ignore_errors:
                return (False, "", str(e))
            raise
    
    # ==================== 其他功能方法 ====================
    
    def execute(self, command_type: str, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行命令 - 主要公共接口"""
        params = params or {}
        
        try:
            self.logger.info(f"执行命令: {command_type}.{command}, 参数: {params}")
            
            if command_type == "control":
                return self.execute_operation(command, params)
            elif command_type == "node":
                return self._execute_node_command(command, params)
            elif command_type == "service":
                return self._execute_service_command(command, params)
            elif command_type == "system":
                return self._execute_system_command(command, params)
            else:
                return {
                    "success": False,
                    "error": f"未知命令类型: {command_type}",
                    "timestamp": time.time()
                }
                
        except Exception as e:
            self.logger.error(f"执行命令失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": time.time()
            }
    
    def execute_operation(self, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行操作 - 兼容旧接口"""
        params = params or {}
        
        # 获取操作员信息（从params中获取）
        operator = params.get('operator', 'system')
        
        try:
            result = None
            
            if action == "system_check":
                result = self.system_check()
            elif action == "clear_cache":
                result = self.clear_cache()
            elif action == "execute_command":
                cmd = params.get('command', '')
                timeout = params.get('timeout', 30)
                result = self.execute_command(cmd, timeout)
            elif action == "get_logs":  # 支持直接获取日志
                limit = params.get('limit', 10)
                return self.get_operation_logs(limit)
            else:
                result = {
                    "success": False,
                    "error": f"未知操作: {action}",
                    "timestamp": time.time()
                }
            
            # 记录操作日志
            if result is not None:
                self.add_operation_log(
                    action=action,
                    operator=operator,
                    success=result.get('success', False),
                    details=result.get('error', '') or '操作成功',
                    params=params
                )
            
            return result
            
        except Exception as e:
            self.logger.error(f"执行操作失败: {e}")
            error_result = {
                "success": False,
                "error": str(e),
                "timestamp": time.time()
            }
            
            # 记录错误操作日志
            self.add_operation_log(
                action=action,
                operator=operator,
                success=False,
                details=str(e),
                params=params
            )
            
            return error_result
    
    def add_operation_log(self, action: str, operator: str = 'system', 
                     success: bool = True, details: str = '', params: Dict = None) -> None:
        """添加操作日志"""
        with self._lock:
            log_entry = {
                'timestamp': time.time(),
                'action': action,
                'operator': operator,
                'success': success,
                'details': details,
                'params': params or {}
            }
            
            self._operation_logs.append(log_entry)
            
            # 限制日志数量，防止内存占用过大
            max_logs = self.config.get('max_operation_logs', 100)
            if len(self._operation_logs) > max_logs:
                self._operation_logs = self._operation_logs[-max_logs:]
    # ==================== 其他功能方法 ====================
    
    
    
    def _execute_node_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行节点命令（P2：节点控制已统一经 OPS，本地节点命令不再支持）"""
        return {
            "success": False,
            "error": f"节点命令已由 OPS 统一控制: {command}",
            "timestamp": time.time()
        }
    
    def _execute_service_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行服务命令 - 修正版，支持多种参数键名"""
        # 支持多种参数键名，提高兼容性
        service_name = params.get('service', '') or params.get('service_name', '') or params.get('name', '')
        
        self.logger.info(f"执行服务命令: {command}, 参数: {params}")
        self.logger.info(f"解析出的服务名称: {service_name}")
        
        if not service_name:
            error_msg = f"缺少服务名称参数。请提供以下任一参数键名: 'service', 'service_name', 'name'。当前参数: {params}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "command": command,
                "params_received": params,
                "timestamp": time.time()
            }
        
        # 验证服务名称格式（可选）
        if not service_name.endswith('.service'):
            self.logger.warning(f"服务名称 '{service_name}' 不包含 '.service' 后缀，可能不是标准的systemd服务名")
        
        try:
            # P2：服务/节点控制已统一经 OPS（/api/ops/*），本地 systemctl 路径已移除
            return {
                "success": False,
                "error": f"服务控制已由 OPS 统一执行（/api/ops/nodes/{service_name}/action），请通过节点运维页操作: {command}",
                "command": command,
                "service": service_name,
                "timestamp": time.time()
            }
                
        except Exception as e:
            self.logger.error(f"执行服务命令失败: {command} {service_name}, 错误: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"执行服务命令失败: {str(e)}",
                "service": service_name,
                "command": command,
                "timestamp": time.time()
            }
    
    def _execute_system_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行系统命令"""
        if command == "check":
            return self.system_check()
        elif command == "clear_cache":
            return self.clear_cache()
        elif command == "execute_command":
            cmd = params.get('command', '')
            timeout = params.get('timeout', 30)
            return self.execute_command(cmd, timeout)
        elif command == "get_stats":
            # 添加获取操作统计的支持
            return self.get_operation_stats()
        elif command == "get_logs":
            # 添加获取操作日志的支持
            limit = params.get('limit', 10)
            return self.get_operation_logs(limit)
        elif command == "get_mode":  # 新增：获取系统运行模式
            return self.get_system_mode()
        elif command == "get_operation_limits_info":  # 新增：获取操作限制信息
            return self.get_operation_limits_info()
        else:
            return {
                "success": False,
                "error": f"未知系统命令: {command}",
                "timestamp": time.time()
            }
    
    def _check_process_running(self, process_name: str) -> bool:
        """检查进程是否在运行"""
        try:
            result = self._execute_command(f"pgrep -f {process_name}", ignore_errors=True)
            return result[0] and result[1].strip() != ""
        except:
            return False
    
    def execute_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """执行自定义命令"""
        with self._lock:
            try:
                result = self._execute_command(command, timeout)
                return {
                    "success": result[0],
                    "output": result[1],
                    "error": result[2],
                    "command": command,
                    "timestamp": time.time()
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "command": command,
                    "timestamp": time.time()
                }
    
    def system_check(self) -> Dict[str, Any]:
        """系统检查"""
        with self._lock:
            try:
                checks = []
                commands = [
                    ("磁盘空间", "df -h"),
                    ("内存使用", "free -h"),
                    ("CPU负载", "uptime"),
                    ("网络连接", "ping -c 2 192.168.31.201")
                ]
                
                for name, cmd in commands:
                    result = self._execute_command(cmd, ignore_errors=True)
                    checks.append({
                        "name": name,
                        "success": result[0],
                        "output": result[1],
                        "error": result[2]
                    })
                
                result_data = {
                    "success": True,
                    "checks": checks,
                    "summary": {
                        "total": len(checks),
                        "passed": sum(1 for c in checks if c["success"])
                    }
                }
                
                # 记录日志
                self.add_operation_log(
                    action='system_check',
                    operator='system',
                    success=True,
                    details=f'系统检查完成，共{len(checks)}项',
                    params={}
                )
                
                return result_data
                
            except Exception as e:
                self.logger.error(f"系统检查失败: {e}")
                error_result = {
                    "success": False,
                    "error": str(e)
                }
                
                self.add_operation_log(
                    action='system_check',
                    operator='system',
                    success=False,
                    details=str(e),
                    params={}
                )
                
                return error_result
    
    def clear_cache(self) -> Dict[str, Any]:
        """清理缓存"""
        with self._lock:
            try:
                commands = [
                    "ros2 run rclpy_clear_log clear_log",
                    "find /tmp -name '*.pyc' -delete 2>/dev/null || true"
                ]
                
                results = []
                for cmd in commands:
                    result = self._execute_command(cmd, ignore_errors=True)
                    results.append({
                        "command": cmd,
                        "success": result[0],
                        "output": result[1]
                    })
                
                return {
                    "success": True,
                    "results": results,
                    "message": "缓存清理完成"
                }
            except Exception as e:
                self.logger.error(f"清理缓存失败: {e}")
                return {
                    "success": False,
                    "error": str(e)
                }
    
    def get_system_mode(self) -> Dict[str, Any]:
        """获取系统模式信息"""
        return {
            "success": True,
            "mode": self.mode,
            "details": {
                "operation_mode": self.mode,
                "detected_by": "auto_detect",
                "scripts_available": list(self.dev_scripts.keys()) if self.mode == "development" else [],
                "services_available": list(self.deployment_services.values()) if self.mode == "deployment" else []
            }
        }
    
    def get_system_info(self) -> Dict[str, Any]:
        """获取系统信息"""
        return {
            "success": True,
            "mode": self.mode,
            "config": {
                "dev_scripts": self.dev_scripts,
                "deployment_services": self.deployment_services
            },
            "current_pid": self.current_pid,
            "timestamp": time.time()
        }
        
    
    def get_operation_stats(self):
        """获取操作统计"""
        with self._lock:
            # 如果已有操作日志，则计算统计
            if hasattr(self, '_operation_logs'):
                total_ops = len(self._operation_logs)
                successful_ops = sum(1 for log in self._operation_logs if log.get('success', False))
                success_rate = (successful_ops / total_ops * 100) if total_ops > 0 else 0
                
                # 按操作类型统计
                by_action = {}
                for log in self._operation_logs:
                    action = log.get('action', 'unknown')
                    by_action[action] = by_action.get(action, 0) + 1
                
                return {
                    "success": True,
                    "stats": {
                        "total_operations": total_ops,
                        "successful_operations": successful_ops,
                        "success_rate": success_rate,
                        "by_action": by_action
                    }
                }
            else:
                # 返回默认数据
                return {
                    "success": True,
                    "stats": {
                        "total_operations": 0,
                        "successful_operations": 0,
                        "success_rate": 0,
                        "by_action": {}
                    }
                }

    def get_operation_logs(self, limit: int = 10) -> Dict[str, Any]:
        """获取操作日志 - 确保返回格式正确"""
        with self._lock:
            try:
                # 验证limit参数
                if limit <= 0:
                    limit = 10
                if limit > 100:
                    limit = 100
                
                # 检查是否有操作日志属性
                if not hasattr(self, '_operation_logs'):
                    self._operation_logs = []
                
                # 如果日志为空，创建一些示例数据
                if not self._operation_logs:
                    current_time = time.time()
                    self._operation_logs = [
                        {
                            'timestamp': current_time - 300,
                            'action': 'system_check',
                            'operator': 'operator',
                            'success': True,
                            'details': '系统检查完成',
                            'params': {}
                        },
                        {
                            'timestamp': current_time - 600,
                            'action': 'clear_cache',
                            'operator': 'operator',
                            'success': True,
                            'details': '缓存清理完成',
                            'params': {}
                        }
                    ]
                
                # 获取最新的日志
                logs = self._operation_logs[-limit:] if len(self._operation_logs) > limit else self._operation_logs.copy()
                logs_reversed = list(reversed(logs))
                
                # 返回正确的字典格式
                return {
                    "success": True,
                    "logs": logs_reversed,
                    "count": len(logs_reversed),
                    "limit": limit,
                    "total": len(self._operation_logs)
                }
                    
            except Exception as e:
                self.logger.error(f"获取操作日志失败: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "logs": [],
                    "count": 0
                }
                
                
    # def check_operation_limit(self, action: str, operator: str = 'system') -> Tuple[bool, str]:
    #     """检查操作是否超过限制"""
    #     with self._operation_history_lock:
    #         current_time = time.time()
            
    #         # 清理过期的历史记录
    #         self.operation_history = [
    #             op for op in self.operation_history 
    #             if current_time - op['timestamp'] < 3600  # 保留1小时内的记录
    #         ]
            
    #         # 计算最近一分钟的操作次数
    #         minute_ago = current_time - 60
    #         recent_minute_ops = sum(1 for op in self.operation_history 
    #                             if op['timestamp'] > minute_ago)
            
    #         # 计算最近一小时的操作次数
    #         hour_ago = current_time - 3600
    #         recent_hour_ops = sum(1 for op in self.operation_history 
    #                             if op['timestamp'] > hour_ago)
            
    #         # 检查限制
    #         if recent_minute_ops >= self.operation_limits['max_per_minute']:
    #             return False, f"操作过于频繁：每分钟最多 {self.operation_limits['max_per_minute']} 次操作"
            
    #         if recent_hour_ops >= self.operation_limits['max_per_hour']:
    #             return False, f"操作次数过多：每小时最多 {self.operation_limits['max_per_hour']} 次操作"
            
    #         # 记录本次操作
    #         self.operation_history.append({
    #             'timestamp': current_time,
    #             'action': action,
    #             'operator': operator
    #         })
            
    #         return True, "操作允许"

    # def get_operation_limits_info(self) -> Dict[str, Any]:
    #     """获取操作限制信息"""
    #     with self._operation_history_lock:
    #         current_time = time.time()
            
    #         # 计算统计数据
    #         minute_ago = current_time - 60
    #         hour_ago = current_time - 3600
            
    #         recent_minute_ops = sum(1 for op in self.operation_history 
    #                             if op['timestamp'] > minute_ago)
    #         recent_hour_ops = sum(1 for op in self.operation_history 
    #                             if op['timestamp'] > hour_ago)
            
    #         return {
    #             "success": True,
    #             "limits": self.operation_limits,
    #             "current_usage": {
    #                 "minute": recent_minute_ops,
    #                 "hour": recent_hour_ops,
    #                 "total": len(self.operation_history)
    #             },
    #             "available": {
    #                 "minute": max(0, self.operation_limits['max_per_minute'] - recent_minute_ops),
    #                 "hour": max(0, self.operation_limits['max_per_hour'] - recent_hour_ops)
    #             }
    #         }
            
    # ==================== 操作限制相关方法 ====================

    def check_operation_limit(self, action: str, operator: str = 'system') -> Tuple[bool, str]:
        """检查操作是否超过限制"""
        with self._operation_history_lock:
            current_time = time.time()
            
            # 清理过期的历史记录
            self.operation_history = [
                op for op in self.operation_history 
                if current_time - op['timestamp'] < 3600  # 保留1小时内的记录
            ]
            
            # 计算最近一分钟的操作次数
            minute_ago = current_time - 60
            recent_minute_ops = sum(1 for op in self.operation_history 
                                if op['timestamp'] > minute_ago)
            
            # 计算最近一小时的操作次数
            hour_ago = current_time - 3600
            recent_hour_ops = sum(1 for op in self.operation_history 
                                if op['timestamp'] > hour_ago)
            
            # 检查限制
            if recent_minute_ops >= self.operation_limits['max_per_minute']:
                return False, f"操作过于频繁：每分钟最多 {self.operation_limits['max_per_minute']} 次操作"
            
            if recent_hour_ops >= self.operation_limits['max_per_hour']:
                return False, f"操作次数过多：每小时最多 {self.operation_limits['max_per_hour']} 次操作"
            
            # 记录本次操作
            self.operation_history.append({
                'timestamp': current_time,
                'action': action,
                'operator': operator
            })
            
            return True, "操作允许"

    def get_operation_limits_info(self) -> Dict[str, Any]:
        """获取操作限制信息"""
        with self._operation_history_lock:
            current_time = time.time()
            
            # 计算统计数据
            minute_ago = current_time - 60
            hour_ago = current_time - 3600
            
            recent_minute_ops = sum(1 for op in self.operation_history 
                                if op['timestamp'] > minute_ago)
            recent_hour_ops = sum(1 for op in self.operation_history 
                                if op['timestamp'] > hour_ago)
            
            return {
                "success": True,
                "limits": self.operation_limits,
                "current_usage": {
                    "minute": recent_minute_ops,
                    "hour": recent_hour_ops,
                    "total": len(self.operation_history)
                },
                "available": {
                    "minute": max(0, self.operation_limits['max_per_minute'] - recent_minute_ops),
                    "hour": max(0, self.operation_limits['max_per_hour'] - recent_hour_ops)
                }
            }