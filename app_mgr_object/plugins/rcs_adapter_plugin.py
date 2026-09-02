#!/usr/bin/env python3
"""
rcs_adapter_plugin — RCS 接口适配器

职责：
  - 封装 RCS-2000 V3.3 全部对外任务接口
  - 向上层插件（bay_status_fusion / status_poller / workflow_engine）暴露标准方法
  - 管理 RCS 服务器连接配置（base_url / timeout / max_retries）

依赖：
  - network (NetworkPlugin — 提供 HTTP 会话)
  - RCSHttpClient / RCSPayloadBuilder / RCSResponseParser (组件层)

暴露方法：
  - gen_task(task_context)                → 生成调度任务
  - cancel_task(task_code, force)         → 取消任务
  - continue_task(task_code)              → 继续执行任务
  - query_agv_status(robot_ids)           → 查询 AGV 状态
  - query_task_status(task_codes)         → 查询任务状态
  - query_pod_berth_and_mat(bay_ids)      → 查询终点仓位绑定
  - bind_ctnr_and_bin(bay_id, cargo_type, ind_bind) → 绑定/解绑
"""

from typing import Dict, Any, List, Optional
import time

from .base_plugin import BasePlugin
from app_mgr_object.components.rcs_client.rcs_http_client import RCSHttpClient, RCSClientError
from app_mgr_object.components.rcs_client.rcs_payload_builder import RCSPayloadBuilder
from app_mgr_object.components.rcs_client.rcs_response_parser import (
    RCSResponseParser,
    RCSTaskStatus,
    RCSRobotStatus,
    RCSResponseCode,
)


class RCSAdapterPlugin(BasePlugin):
    """RCS-2000 V3.3 HTTP 接口适配器插件

    封装了 RCSHttpClient 的全部接口，向上层插件提供统一的 RCS 通信能力。
    所有方法均为同步调用，由调用方决定是否放入线程池。
    """

    PLUGIN_NAME = "rcs_adapter"
    PLUGIN_VERSION = "1.0.0"

    def __init__(self, node, config: Dict[str, Any] = None):
        super().__init__(node, config)

        # RCS 连接配置
        self._base_url = self.config.get('rcs_base_url', 'http://192.168.1.100:8080')
        self._timeout = self.config.get('rcs_timeout', 10.0)
        self._max_retries = self.config.get('rcs_max_retries', 2)
        self._enabled = self.config.get('enabled', True)

        # 组件实例
        self._client: Optional[RCSHttpClient] = None
        self._payload_builder: Optional[RCSPayloadBuilder] = None
        self._response_parser: Optional[RCSResponseParser] = None

    # ═══════════════════════════════════════════════════════════════
    #  生命周期
    # ═══════════════════════════════════════════════════════════════

    def _configure_impl(self) -> bool:
        """配置：初始化 RCSHttpClient 和工具组件"""
        try:
            # 获取 NetworkPlugin 实例
            network = self._get_network_plugin()

            # 创建 RCS HTTP 客户端
            self._client = RCSHttpClient(
                network_plugin=network,
                base_url=self._base_url,
                timeout=self._timeout,
                max_retries=self._max_retries,
                logger=self.logger,
            )

            # 创建辅助组件
            self._payload_builder = RCSPayloadBuilder()
            self._response_parser = RCSResponseParser()

            # 将自身挂载到节点，供其他插件通过 self.node.rcs_adapter 访问
            self.node.rcs_adapter = self

            self.logger.info(
                f"RCSAdapter 配置完成: base_url={self._base_url}, "
                f"timeout={self._timeout}s, max_retries={self._max_retries}"
            )
            return True

        except Exception as e:
            self.logger.error(f"RCSAdapter 配置失败: {e}")
            return False

    def _activate_impl(self) -> bool:
        """激活：执行连通性检查"""
        if not self._enabled:
            self.logger.info("RCSAdapter 已禁用")
            return True

        # 可选：启动时检查 RCS 连通性
        try:
            self._check_connectivity()
        except Exception as e:
            self.logger.warning(f"RCS 连通性检查失败（非致命）: {e}")

        return True

    def _deactivate_impl(self) -> bool:
        return True

    def _cleanup_impl(self) -> bool:
        self._client = None
        self._payload_builder = None
        self._response_parser = None
        return True

    # ═══════════════════════════════════════════════════════════════
    #  任务接口 (2.x)
    # ═══════════════════════════════════════════════════════════════

    def gen_task(self, task_context: Dict[str, Any],
                 task_typ: str = "F13", priority: int = 64) -> Dict[str, Any]:
        """生成 AGV 调度任务

        对应 RCS 接口: 2.1.1 genAgvSchedulingTask

        Args:
            task_context: 任务上下文，包含 task_id / src_bay / dst_bay / robot_id
            task_typ: 任务类型，默认 "F13"（巷道到工作台）
            priority: 优先级 1~127

        Returns:
            RCS 响应体，含 taskNo（任务流水号）

        Raises:
            RCSClientError: 请求失败
        """
        self.logger.info(f"[RCS] gen_task 被调用: {task_context.get('task_id')}")
        payload = self._payload_builder.build_task_payload(
            task_context, task_typ=task_typ, priority=priority
        )
        self.logger.info(f"下发 RCS 任务: {task_context.get('task_id')}")
        return self._client.gen_agv_scheduling_task(payload)

    def cancel_task(self, task_code: str, force_cancel: bool = True) -> Dict[str, Any]:
        """取消任务

        对应 RCS 接口: 2.1.3 cancelTask

        Args:
            task_code: RCS 任务号
            force_cancel: True=软取消（叉车背货回库），False=硬取消（就地丢弃）

        Returns:
            RCS 响应体
        """
        force_flag = "1" if force_cancel else "0"
        self.logger.info(f"取消 RCS 任务: {task_code}, force={force_flag}")
        return self._client.cancel_task(task_code, force_cancel=force_flag)

    def continue_task(self, task_code: str) -> Dict[str, Any]:
        """继续执行已暂停的任务

        对应 RCS 接口: 2.1.2 continueTask
        """
        self.logger.info(f"继续 RCS 任务: {task_code}")
        return self._client.continue_task(task_code)

    # ═══════════════════════════════════════════════════════════════
    #  查询接口 (3.x)
    # ═══════════════════════════════════════════════════════════════

    def query_agv_status(self, robot_ids: List[int]) -> Dict[str, Any]:
        """查询 AGV 叉车实时状态"""
        self.logger.info(f"[RCS查询] 查询 AGV 状态: robot_ids={robot_ids}")
        start_time = time.time()
        try:
            resp = self._client.query_agv_status(robot_ids)
            elapsed = (time.time() - start_time) * 1000
            
            # 打印查询结果详情
            if resp.get('code') == '0':
                data = resp.get('data', [])
                status_summary = []
                for item in data:
                    rid = item.get('robotID', item.get('agvCode', 'unknown'))
                    status = item.get('agvStatus', 'unknown')
                    battery = item.get('battery', 'N/A')
                    status_summary.append(f"{rid}:{status}({battery}%)")
                self.logger.info(
                    f"[RCS查询] AGV 状态成功 ({elapsed:.1f}ms): {', '.join(status_summary)}"
                )
            else:
                self.logger.warning(
                    f"[RCS查询] AGV 状态返回非成功码: code={resp.get('code')}, msg={resp.get('msg')}"
                )
            return resp
        except Exception as e:
            self.logger.error(f"[RCS查询] AGV 状态查询异常: {e}")
            raise

    def query_task_status(self, task_codes: List[str]) -> Dict[str, Any]:
        """查询任务执行状态

        对应 RCS 接口: 3.1.9 queryTaskStatus

        Args:
            task_codes: RCS 任务号列表

        Returns:
            RCS 响应体。data 数组中每项含 taskCode / taskStatus
        """
        return self._client.query_task_status(task_codes)
    
    def query_task_status_unified(self, task_id: str, rcs_task_no: str = '') -> dict:
        """
        统一查询任务状态：优先 taskCode（业务任务号），taskNo 兼容回退。
        与 RCSPayloadBuilder 的 taskCode=task_id、agvCallback 回传 taskCode 的约定保持一致。
        """
        keys = []
        if task_id:
            keys.append(task_id)
        if rcs_task_no and rcs_task_no not in keys:
            keys.append(rcs_task_no)
        if not keys:
            return {'code': '-1', 'msg': '缺少查询键', 'data': []}

        last_resp = {'code': '-1', 'msg': '查询失败', 'data': []}
        for key in keys:
            try:
                resp = self._client.query_task_status([key])
                last_resp = resp
                if resp.get('code') == '0' and resp.get('data'):
                    self.logger.debug(f"query_task_status_unified: 键 {key} 命中")
                    return resp
            except Exception as e:
                self.logger.warning(f"query_task_status_unified: 键 {key} 查询异常: {e}")
        return last_resp

    def extract_task_status(self, resp: dict, task_id: str, rcs_task_no: str = '') -> str:
        """
        从 RCS 响应中容错提取任务状态码，未命中返回 ''。
        优先匹配 taskCode，单条数据时兼容取首项。
        """
        data_list = resp.get('data') or []
        if not isinstance(data_list, list):
            return ''
        valid_keys = {task_id, rcs_task_no}
        for item in data_list:
            code = str(item.get('taskCode', ''))
            if code in valid_keys:
                return str(item.get('taskStatus', ''))
        if len(data_list) == 1:
            return str(data_list[0].get('taskStatus', ''))
        return ''

    def query_pod_berth_and_mat(self, bay_ids: List[str]) -> Dict[str, Any]:
        """查询货架储位与物料批次关系

        对应 RCS 接口: 3.1.6 queryPodBerthAndMat

        用于判断终点仓位是否为空：ctnrCode 为空 → 仓位空闲。

        Args:
            bay_ids: 仓位编码列表，如 ["T2001", "T2002"]

        Returns:
            RCS 响应体。data 数组中每项含 stgBinCode / ctnrCode
        """
        return self._client.query_pod_berth_and_mat(bay_ids)

    # ═══════════════════════════════════════════════════════════════
    #  绑定接口 (3.x)
    # ═══════════════════════════════════════════════════════════════

    def bind_ctnr_and_bin(self,
                          bay_id: str,
                          cargo_type: int,
                          ind_bind: str = "1") -> Dict[str, Any]:
        """容器与仓位绑定/解绑

        对应 RCS 接口: 3.1.8 bindCtnrAndBin

        在起始仓位 AI 检测确认有货后，调用此接口绑定容器与仓位。
        绑定后该仓位才能被调度系统识别为"可调度"。

        Args:
            bay_id:     仓位编码（如 "A1001"）
            cargo_type: 货物类型编号（1~6）
            ind_bind:   "1"=绑定, "0"=解绑

        Returns:
            RCS 响应体
        """
        payload = self._payload_builder.build_bind_payload(
            bay_id, cargo_type, ind_bind
        )
        self.logger.debug(f"RCS 绑定请求: {bay_id} ind_bind={ind_bind}")
        return self._client.bind_ctnr_and_bin(
            ctnr_code=payload['ctnrCode'],
            ctnr_typ=payload['ctnrTyp'],
            stg_bin_code=payload['stgBinCode'],
            ind_bind=payload['indBind'],
        )

    # ═══════════════════════════════════════════════════════════════
    #  辅助方法
    # ═══════════════════════════════════════════════════════════════

    def _get_network_plugin(self):
        """获取 NetworkPlugin 实例"""
        network = getattr(self.node, 'network_plugin', None)
        if network is None:
            network = self.node.plugin_manager.get_plugin('network')
        if network is None:
            raise RuntimeError("NetworkPlugin 未加载，rcs_adapter 依赖 network 插件")
        return network

    def _check_connectivity(self):
        """检测 RCS 服务器连通性"""
        self.logger.info(f"[RCS连通性] 检测 RCS 服务器: {self._base_url}")
        try:
            resp = self._client.query_agv_status(self.config.get('test_robot_ids', []))
            if self._response_parser.is_success(resp):
                data = resp.get('data', [])
                self.logger.info(
                    f"[RCS连通性] 检测成功，共 {len(data)} 台 AGV 在线"
                )
                for item in data:
                    rid = item.get('robotID', 'unknown')
                    status = item.get('agvStatus', 'unknown')
                    self.logger.debug(f"  AGV {rid}: status={status}")
            else:
                self.logger.warning(
                    f"[RCS连通性] 检测失败: code={resp.get('code')}, msg={resp.get('msg')}"
                )
        except RCSClientError as e:
            self.logger.warning(f"[RCS连通性] 检测异常: {e}")

    # ═══════════════════════════════════════════════════════════════
    #  状态查询
    # ═══════════════════════════════════════════════════════════════

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            'rcs_base_url': self._base_url,
            'rcs_timeout': self._timeout,
            'rcs_max_retries': self._max_retries,
            'enabled': self._enabled,
        })
        return base