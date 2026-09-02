#!/usr/bin/env python3
"""
状态查询处理器 - 使用缓存管理器
"""

import json
import time
from typing import Dict, Any, Optional, Callable

class StatusQueryHandler:
    """状态查询处理器 - 使用缓存管理器"""
    
    def __init__(self, node):
        self.node = node
        self.logger = node.get_logger()
    
    def _get_lane_status_from_cache(self, lane_num: str) -> Dict[str, Any]:
        """从缓存管理器获取巷道状态"""
        try:
            # 检查缓存管理器是否存在
            if not hasattr(self.node, 'lane_cache_manager'):
                self.logger.warning("lane_cache_manager 未找到")
                return self._get_error_response(lane_num, "缓存管理器未初始化")
            
            # 使用缓存管理器
            cache_manager = self.node.lane_cache_manager
            
            # ✅ 修正巷道名称格式转换
            lane_prefix = ""
            if lane_num.startswith("CJWAK200"):
                lane_prefix = lane_num[8:]  # 正确提取 Z20
                self.logger.info(f"✅ 从缓存提取巷道前缀: {lane_num} -> {lane_prefix}")
            else:
                lane_prefix = lane_num
            
            self.logger.info(f"🔍 从缓存查询巷道状态: {lane_num} -> {lane_prefix}")
            
            # ✅ 检查巷道是否存在
            if lane_prefix not in cache_manager.lane_caches:
                self.logger.warning(f"巷道 {lane_prefix} 不存在于缓存中")
                return self._get_error_response(lane_num, f"巷道 {lane_prefix} 不存在于缓存中")
            
            # 获取巷道货架状态
            shelves_data = cache_manager.get_lane_shelves_status(lane_prefix)
            
            # 构建返回格式
            shelves = []
            for item in shelves_data:
                shelves.append({
                    "shelfcode": item.get("shelfcode", "01"),
                    "shelfstatus": item.get("shelfstatus", "EMPTY")
                })
            
            # 确保有4个货架
            existing_codes = {s["shelfcode"] for s in shelves}
            for i in range(1, 5):
                shelfcode = f"{i:02d}"
                if shelfcode not in existing_codes:
                    shelves.append({
                        "shelfcode": shelfcode,
                        "shelfstatus": "EMPTY"
                    })
            
            # 按货架号排序
            shelves.sort(key=lambda x: x["shelfcode"])
            
            result = {
                "timestamp": int(time.time() * 1000),
                "lanePrefix": lane_num,
                "shelves": shelves
            }
            
            # 记录查询统计
            full_count = sum(1 for s in shelves if s["shelfstatus"] == "FULL")
            self.logger.info(f"✅ 巷道 {lane_prefix} 缓存查询结果: FULL={full_count}/4")
            
            # 调试：显示每个货架状态
            for shelf in shelves:
                self.logger.debug(f"  货架 {shelf['shelfcode']}: {shelf['shelfstatus']}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"从缓存获取巷道状态失败: {e}")
            return self._get_error_response(lane_num, str(e))
    
    def get_lane_status(self, lane_num: str) -> Dict[str, Any]:
        """根据巷道名称获取该巷道下所有货架状态"""
        try:
            # 验证巷道名称
            allowed_lanes = ["CJWAK200Z01", "CJWAK200Z02", "CJWAK200Z03", "CJWAK200Z04"]
            if lane_num not in allowed_lanes:
                return {
                    "timestamp": int(time.time() * 1000),
                    "error": f"无效的巷道名称，只支持{allowed_lanes}",
                    "code": 400
                }
            
            # ✅ 修正巷道前缀提取逻辑
            lane_prefix = self.extract_lane_prefix(lane_num)
            self.logger.info(f"✅ 提取巷道前缀: {lane_num} -> {lane_prefix}")
            
            if lane_num.startswith("CJWAK200"):
                # "CJWAK200" 长度为8，所以从第8个字符开始
                lane_prefix = lane_num[8:]  # 正确提取 Z20
                self.logger.info(f"✅ 提取巷道前缀: {lane_num} -> {lane_prefix}")
            else:
                lane_prefix = lane_num
            
            self.logger.info(f"🔍 查询巷道状态: {lane_num} (前缀: {lane_prefix})")
            
            # 检查各个状态管理器的存在性
            self.logger.info(f"检查状态管理器:")
            self.logger.info(f"  - lane_cache_manager: {'存在' if hasattr(self.node, 'lane_cache_manager') else '不存在'}")
            self.logger.info(f"  - parking_state_manager: {'存在' if hasattr(self.node, 'parking_state_manager') else '不存在'}")
            self.logger.info(f"  - lane_state_manager: {'存在' if hasattr(self.node, 'lane_state_manager') else '不存在'}")
            
            # 优先尝试从缓存管理器获取
            if hasattr(self.node, 'lane_cache_manager'):
                cache_manager = self.node.lane_cache_manager
                self.logger.info(f"使用缓存管理器查询巷道 {lane_prefix}")
                
                # ✅ 检查巷道是否存在于缓存中
                if lane_prefix not in cache_manager.lane_caches:
                    self.logger.warning(f"巷道 {lane_prefix} 不存在于缓存管理器中")
                    # 列出所有存在的巷道
                    existing_lanes = list(cache_manager.lane_caches.keys())
                    self.logger.info(f"缓存管理器中存在的巷道: {existing_lanes}")
                else:
                    self.logger.info(f"✅ 巷道 {lane_prefix} 存在于缓存管理器中")
                
                # 获取巷道状态
                lane_status = cache_manager.get_lane_status(lane_prefix)
                if lane_status:
                    self.logger.info(f"缓存管理器返回状态: {lane_status.get('lane_status')}")
                    
                    # 获取货架状态
                    shelves_data = cache_manager.get_lane_shelves_status(lane_prefix)
                    shelves = []
                    
                    for item in shelves_data:
                        shelves.append({
                            "shelfcode": item.get("shelfcode", "01"),
                            "shelfstatus": item.get("shelfstatus", "EMPTY")
                        })
                    
                    # 确保有4个货架并按货架号排序
                    shelves.sort(key=lambda x: x["shelfcode"])
                    
                    # 记录详细状态
                    full_count = sum(1 for s in shelves if s["shelfstatus"] == "FULL")
                    self.logger.info(f"巷道 {lane_prefix} 缓存查询结果: FULL={full_count}/4")
                    
                    # 调试：显示每个货架状态
                    for shelf in shelves:
                        self.logger.debug(f"  货架 {shelf['shelfcode']}: {shelf['shelfstatus']}")
                    
                    result = {
                        "timestamp": int(time.time() * 1000),
                        "lanePrefix": lane_num,
                        "shelves": shelves
                    }
                    
                    self.logger.info(f"返回查询结果: {result}")
                    return result
                else:
                    self.logger.warning(f"缓存管理器没有返回状态数据")
                    
                    # ✅ 尝试直接获取货架状态作为备选
                    try:
                        shelves_data = cache_manager.get_lane_shelves_status(lane_prefix)
                        if shelves_data:
                            shelves = []
                            for item in shelves_data:
                                shelves.append({
                                    "shelfcode": item.get("shelfcode", "01"),
                                    "shelfstatus": item.get("shelfstatus", "EMPTY")
                                })
                            
                            shelves.sort(key=lambda x: x["shelfcode"])
                            
                            full_count = sum(1 for s in shelves if s["shelfstatus"] == "FULL")
                            self.logger.info(f"备选查询巷道 {lane_prefix} 结果: FULL={full_count}/4")
                            
                            result = {
                                "timestamp": int(time.time() * 1000),
                                "lanePrefix": lane_num,
                                "shelves": shelves
                            }
                            
                            self.logger.info(f"返回备选查询结果: {result}")
                            return result
                    except Exception as e:
                        self.logger.error(f"备选查询失败: {e}")
            
            # 如果缓存管理器不可用或没有数据，回退到原有状态管理器
            self.logger.warning("缓存管理器不可用或没有数据，使用原有状态管理器")
            
            if hasattr(self.node, 'parking_state_manager'):
                parking_manager = self.node.parking_state_manager
                self.logger.info(f"使用原有状态管理器查询巷道 {lane_prefix}")
                
                # 获取该巷道的所有仓位
                lane_slots = []
                for slot_name, slot in parking_manager.slots.items():
                    # ✅ 修正筛选逻辑
                    if f"{lane_prefix}-" in slot_name or slot_name.endswith(f"-{lane_prefix}"):
                        lane_slots.append(slot)
                
                self.logger.info(f"找到 {len(lane_slots)} 个仓位")
                
                # 如果没有找到，尝试其他匹配方式
                if len(lane_slots) == 0:
                    self.logger.warning(f"未找到巷道 {lane_prefix} 的仓位，尝试宽松匹配")
                    # 检查所有仓位名称
                    for slot_name, slot in parking_manager.slots.items():
                        self.logger.debug(f"检查仓位: {slot_name}")
                        if lane_prefix in slot_name:
                            lane_slots.append(slot)
                    self.logger.info(f"宽松匹配找到 {len(lane_slots)} 个仓位")
                
                # 构建货架状态
                shelves = []
                for i in range(1, 5):
                    shelfcode = f"{i:02d}"
                    shelfstatus = "EMPTY"
                    
                    # 查找对应仓位的状态
                    for slot in lane_slots:
                        parts = slot.name.split('-')
                        if len(parts) == 3 and parts[2] == shelfcode:
                            # 检查状态
                            self.logger.debug(f"检查仓位 {slot.name}:")
                            self.logger.debug(f"  channel_0_status={slot.channel_0_status}")
                            self.logger.debug(f"  channel_1_status={slot.channel_1_status}")
                            self.logger.debug(f"  final_status={slot.final_status}")
                            self.logger.debug(f"  is_stable={slot.is_stable}")
                            
                            if slot.final_status is True:
                                shelfstatus = "FULL"
                                self.logger.debug(f"  → 使用final_status=True → FULL")
                            elif slot.channel_1_status is True:
                                shelfstatus = "FULL"
                                self.logger.debug(f"  → 使用channel_1_status=True → FULL")
                            elif slot.channel_0_status is False:
                                shelfstatus = "EMPTY"
                                self.logger.debug(f"  → 使用channel_0_status=False → EMPTY")
                            else:
                                shelfstatus = "EMPTY"
                                self.logger.debug(f"  → 所有状态都不确定 → EMPTY")
                            break
                    
                    shelves.append({
                        "shelfcode": shelfcode,
                        "shelfstatus": shelfstatus
                    })
                
                # 按货架号排序
                shelves.sort(key=lambda x: x["shelfcode"])
                
                # 统计FULL数量
                full_count = sum(1 for s in shelves if s["shelfstatus"] == "FULL")
                self.logger.info(f"巷道 {lane_prefix} 查询结果: FULL={full_count}/4")
                
                result = {
                    "timestamp": int(time.time() * 1000),
                    "lanePrefix": lane_num,
                    "shelves": shelves
                }
                
                self.logger.info(f"返回查询结果: {result}")
                return result
            
            # 如果都没有，返回默认值
            self.logger.warning("所有状态管理器都不可用，返回默认值")
            return self._get_default_response(lane_num)
                
        except Exception as e:
            self.logger.error(f"获取巷道状态失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return self._get_default_response(lane_num, str(e))
    
    def _get_error_response(self, lane_num: str, error_msg: str) -> Dict[str, Any]:
        """获取错误响应"""
        return {
            "timestamp": int(time.time() * 1000),
            "lanePrefix": lane_num,
            "error": error_msg,
            "code": 500,
            "shelves": [
                {"shelfcode": "01", "shelfstatus": "EMPTY"},
                {"shelfcode": "02", "shelfstatus": "EMPTY"},
                {"shelfcode": "03", "shelfstatus": "EMPTY"},
                {"shelfcode": "04", "shelfstatus": "EMPTY"}
            ]
        }
        
    def extract_lane_prefix(self, lane_num: str) -> str:
        """提取巷道前缀，支持多种格式"""
        # 移除所有可能的非字母数字字符
        clean_lane = ''.join(c for c in lane_num if c.isalnum())
        
        # 查找 "Z" 开头的部分
        import re
        match = re.search(r'(Z\d{2})', clean_lane)
        if match:
            return match.group(1)  # Z20, Z21 等
        
        # 如果找不到 Z 开头，尝试其他模式
        if clean_lane.startswith("CJWAK200"):
            return clean_lane[8:]  # 提取 Z20
        
        # 默认返回原值
        return lane_num