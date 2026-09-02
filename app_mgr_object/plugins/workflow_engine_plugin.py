#!/usr/bin/env python3
"""
workflow_engine_plugin — 工作流引擎插件

基于 YAML 工作流定义（config/workflows/*.yaml）执行状态机编排：
  - 解析 states[] 定义，构建状态转移图
  - create_instance(wf_name, ctx) 创建工作流实例
  - trigger(instance_id, event) 注入事件驱动状态转移
  - 每个 state 的 action 通过 _action_handlers 字典分发
  - 支持 timeout / retry / final / on_enter / on_exit / on_error

工作流 YAML 格式（参见 config/workflows/agv_transport_atomic.yaml）：
  name, version, description, initial_state, max_concurrent
  states:
    - id, description, action, retry, timeout, final
      transitions: [{ event, target }]
      on_enter: [{ action }]
      on_exit: [{ action }]
  on_error: [{ action }]
"""
import time
import threading
import yaml
from typing import Dict, Any, Optional, List, Callable
from pathlib import Path

from .base_plugin import BasePlugin


class WorkflowInstance:
    """单个工作流执行实例。"""

    def __init__(self, instance_id: str, wf_name: str,
                 current_state: str, context: Dict[str, Any]):
        self.instance_id = instance_id
        self.wf_name = wf_name
        self.current_state = current_state
        self.context = context
        self.history: List[Dict[str, Any]] = []
        self.created_at = time.time()
        self.updated_at = time.time()
        self.finished = False
        self.error: Optional[str] = None

    def transition_to(self, new_state: str, event: str) -> None:
        self.history.append({
            'from': self.current_state,
            'to': new_state,
            'event': event,
            'ts': time.time(),
        })
        self.current_state = new_state
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'instance_id': self.instance_id,
            'workflow': self.wf_name,
            'current_state': self.current_state,
            'finished': self.finished,
            'error': self.error,
            'context_keys': list(self.context.keys()),
            'history_len': len(self.history),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class WorkflowEnginePlugin(BasePlugin):
    """工作流引擎插件。"""

    PLUGIN_NAME = "workflow_engine"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)
        # workflow_name -> parsed definition dict
        self._workflow_defs: Dict[str, Dict[str, Any]] = {}
        # instance_id -> WorkflowInstance
        self._instances: Dict[str, WorkflowInstance] = {}
        self._lock = threading.Lock()
        self._instance_counter = 0
        # action_name -> handler callable(instance, context)
        self._action_handlers: Dict[str, Callable] = {}
        self._max_concurrent = 10
        # timeout 监控线程
        self._timeout_thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()

    # ════════════════════════════════════════════════════
    #  生命周期
    # ════════════════════════════════════════════════════

    def _configure_impl(self) -> bool:
        # 1. 从 config 加载工作流定义文件路径
        wf_files = self.config.get('workflow_files', [])
        wf_dir = self.config.get('workflow_dir', '')

        # 2. 从 config.workflows 直接内联定义
        inline_defs = self.config.get('workflows', {})
        if isinstance(inline_defs, dict):
            for name, defn in inline_defs.items():
                self._register_workflow(name, defn)

        # 3. 从文件加载
        for f in wf_files:
            self._load_workflow_file(f)
        if wf_dir:
            for p in sorted(Path(wf_dir).glob('*.yaml')):
                self._load_workflow_file(str(p))

        # 4. 并发上限
        self._max_concurrent = int(self.config.get('max_concurrent', 10))

        # 5. 注册内置 action handlers
        self._register_default_actions()

        self.logger.info(
            f"workflow_engine 配置完成: {len(self._workflow_defs)} 个工作流, "
            f"max_concurrent={self._max_concurrent}")
        return True

    def _activate_impl(self) -> bool:
        # 启动 timeout 监控线程
        self._stop_flag.clear()
        self._timeout_thread = threading.Thread(
            target=self._timeout_monitor_loop, daemon=True)
        self._timeout_thread.start()
        self.logger.info("workflow_engine 激活: timeout 监控已启动")
        return True

    def _deactivate_impl(self) -> bool:
        self._stop_flag.set()
        if self._timeout_thread:
            self._timeout_thread.join(timeout=3)
        # 标记所有未完成实例为错误
        with self._lock:
            for inst in self._instances.values():
                if not inst.finished:
                    inst.error = "engine deactivated"
                    inst.finished = True
        self.logger.info("workflow_engine 停用")
        return True

    def _cleanup_impl(self) -> bool:
        with self._lock:
            self._workflow_defs.clear()
            self._instances.clear()
            self._action_handlers.clear()
        return True

    # ════════════════════════════════════════════════════
    #  工作流定义加载
    # ════════════════════════════════════════════════════

    def _load_workflow_file(self, filepath: str) -> None:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                defn = yaml.safe_load(f)
            if not isinstance(defn, dict):
                self.logger.warning(f"工作流文件 {filepath} 格式无效")
                return
            name = defn.get('name', Path(filepath).stem)
            self._register_workflow(name, defn)
            self.logger.debug(f"已加载工作流定义: {name} (v{defn.get('version','?')})")
        except Exception as ex:
            self.logger.error(f"加载工作流文件 {filepath} 失败: {ex}")

    def _register_workflow(self, name: str, defn: Dict[str, Any]) -> None:
        # 校验最小必要字段
        if 'states' not in defn:
            self.logger.warning(f"工作流 {name} 缺少 states 定义，跳过")
            return
        if 'initial_state' not in defn:
            self.logger.warning(f"工作流 {name} 缺少 initial_state，跳过")
            return
        # 构建状态索引: state_id -> state_def
        states = {}
        for s in defn.get('states', []):
            sid = s.get('id')
            if sid:
                states[sid] = s
        defn['_states_index'] = states
        self._workflow_defs[name] = defn

    # ════════════════════════════════════════════════════
    #  Action handlers
    # ════════════════════════════════════════════════════

    def _register_default_actions(self) -> None:
        """注册内置 action handler（空实现，仅记录日志）。"""
        defaults = {
            'invoke_gen_task': self._action_noop,
            'wait_for_completion': self._action_noop,
            'compensate_query': self._action_noop,
            'release_resources': self._action_noop,
            'publish_completed_event': self._action_noop,
            'publish_failed_event': self._action_noop,
            'publish_manual_event': self._action_noop,
            'log_manual_entry': self._action_noop,
            'log_error': self._action_noop,
        }
        for name, handler in defaults.items():
            self._action_handlers[name] = handler

    def _action_noop(self, instance: WorkflowInstance,
                     context: Dict[str, Any]) -> Any:
        """默认空操作。"""
        return None

    def register_action(self, action_name: str,
                        handler: Callable[[WorkflowInstance, Dict], Any]) -> None:
        """注册自定义 action handler。"""
        self._action_handlers[action_name] = handler

    def _execute_action(self, action_name: str,
                        instance: WorkflowInstance,
                        context: Dict[str, Any]) -> Any:
        handler = self._action_handlers.get(action_name)
        if handler is None:
            self.logger.warning(
                f"工作流 {instance.wf_name} 实例 {instance.instance_id}: "
                f"action '{action_name}' 无注册 handler，跳过")
            return None
        try:
            return handler(instance, context)
        except Exception as ex:
            self.logger.error(
                f"工作流 action '{action_name}' 执行异常: {ex}")
            instance.error = str(ex)
            return None

    # ════════════════════════════════════════════════════
    #  实例管理 & 状态转移
    # ════════════════════════════════════════════════════

    def create_instance(self, wf_name: str,
                        context: Optional[Dict[str, Any]] = None
                        ) -> Optional[WorkflowInstance]:
        """创建工作流实例并执行 initial_state 的 on_enter/action。"""
        defn = self._workflow_defs.get(wf_name)
        if defn is None:
            self.logger.error(f"工作流 {wf_name} 未定义")
            return None

        with self._lock:
            active = sum(1 for i in self._instances.values() if not i.finished)
            if active >= self._max_concurrent:
                self.logger.warning(
                    f"工作流 {wf_name} 创建失败: 已达并发上限 {self._max_concurrent}")
                return None
            self._instance_counter += 1
            inst_id = f"{wf_name}_{int(time.time())}_{self._instance_counter}"
            initial = defn.get('initial_state', '')
            inst = WorkflowInstance(inst_id, wf_name, initial, context or {})
            self._instances[inst_id] = inst

        # 执行 initial_state 的 on_enter + action
        self._enter_state(inst, initial)
        return inst

    def trigger(self, instance_id: str, event: str) -> bool:
        """向工作流实例注入事件，驱动状态转移。

        Returns:
            True 如果转移成功或实例已终态; False 如果实例不存在或转移失败
        """
        with self._lock:
            inst = self._instances.get(instance_id)
        if inst is None:
            self.logger.warning(f"工作流实例 {instance_id} 不存在")
            return False
        if inst.finished:
            self.logger.debug(f"工作流实例 {instance_id} 已终态，忽略事件 {event}")
            return True

        defn = self._workflow_defs.get(inst.wf_name)
        if defn is None:
            return False
        states_idx = defn.get('_states_index', {})
        cur_state_def = states_idx.get(inst.current_state, {})
        transitions = cur_state_def.get('transitions', [])

        # 查找匹配 event 的 transition
        target = None
        for t in transitions:
            if t.get('event') == event:
                target = t.get('target')
                break

        if target is None:
            self.logger.debug(
                f"工作流 {inst.wf_name} 实例 {instance_id}: "
                f"状态 {inst.current_state} 无事件 {event} 的转移，忽略")
            return False

        # 退出当前 state (on_exit)
        self._exit_state(inst, inst.current_state)

        # 转移
        inst.transition_to(target, event)
        self.logger.info(
            f"工作流转移: {inst.wf_name}#{instance_id} "
            f"{cur_state_def.get('id','?')} --[{event}]--> {target}")

        # 进入新 state
        self._enter_state(inst, target)
        return True

    def _enter_state(self, inst: WorkflowInstance, state_id: str) -> None:
        """进入新状态: 执行 on_enter actions + state action。"""
        defn = self._workflow_defs.get(inst.wf_name)
        if defn is None:
            return
        states_idx = defn.get('_states_index', {})
        state_def = states_idx.get(state_id)
        if state_def is None:
            self.logger.error(
                f"工作流 {inst.wf_name} 状态 {state_id} 未定义")
            inst.error = f"undefined state {state_id}"
            inst.finished = True
            return

        # 记录进入时间（用于 timeout 监控）
        inst.context[f'_enter_ts_{state_id}'] = time.time()

        # on_enter actions
        for step in state_def.get('on_enter', []):
            action_name = step.get('action') if isinstance(step, dict) else step
            if action_name:
                self._execute_action(action_name, inst, inst.context)

        # state action
        action_name = state_def.get('action')
        if action_name:
            self._execute_action(action_name, inst, inst.context)

        # 若为 final 状态，标记完成
        if state_def.get('final'):
            # on_exit actions
            for step in state_def.get('on_exit', []):
                a = step.get('action') if isinstance(step, dict) else step
                if a:
                    self._execute_action(a, inst, inst.context)
            inst.finished = True
            self.logger.info(
                f"工作流 {inst.wf_name}#{inst.instance_id} 进入终态 {state_id}")

    def _exit_state(self, inst: WorkflowInstance, state_id: str) -> None:
        """退出当前状态: 执行 on_exit actions。"""
        defn = self._workflow_defs.get(inst.wf_name)
        if defn is None:
            return
        states_idx = defn.get('_states_index', {})
        state_def = states_idx.get(state_id, {})
        for step in state_def.get('on_exit', []):
            a = step.get('action') if isinstance(step, dict) else step
            if a:
                self._execute_action(a, inst, inst.context)

    # ════════════════════════════════════════════════════
    #  Timeout 监控
    # ════════════════════════════════════════════════════

    def _timeout_monitor_loop(self) -> None:
        """周期性检查实例是否超时，超时则注入 timeout 事件。"""
        while not self._stop_flag.is_set():
            try:
                now = time.time()
                with self._lock:
                    candidates = []
                    for inst in self._instances.values():
                        if inst.finished:
                            continue
                        defn = self._workflow_defs.get(inst.wf_name)
                        if not defn:
                            continue
                        states_idx = defn.get('_states_index', {})
                        sd = states_idx.get(inst.current_state, {})
                        timeout = sd.get('timeout')
                        if not timeout or timeout <= 0:
                            continue
                        enter_ts = inst.context.get(
                            f'_enter_ts_{inst.current_state}', now)
                        if now - enter_ts >= timeout:
                            candidates.append(inst.instance_id)

                for iid in candidates:
                    self.trigger(iid, 'timeout')

            except Exception as ex:
                self.logger.error(f"工作流 timeout 监控异常: {ex}")

            # 每 5 秒检查一次
            self._stop_flag.wait(5.0)

    # ════════════════════════════════════════════════════
    #  查询接口
    # ════════════════════════════════════════════════════

    def get_instance(self, instance_id: str) -> Optional[WorkflowInstance]:
        with self._lock:
            return self._instances.get(instance_id)

    def list_instances(self, include_finished: bool = False) -> List[Dict]:
        with self._lock:
            return [inst.to_dict() for inst in self._instances.values()
                    if include_finished or not inst.finished]

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        with self._lock:
            active = sum(1 for i in self._instances.values() if not i.finished)
        base.update({
            'workflow_count': len(self._workflow_defs),
            'active_instances': active,
            'total_instances': len(self._instances),
            'action_handlers': len(self._action_handlers),
        })
        return base
