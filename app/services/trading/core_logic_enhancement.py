# -*- coding: utf-8 -*-
"""
核心逻辑增强模块
Core Logic Enhancement Module

为核心交易服务提供增强的逻辑处理功能
"""

from typing import Dict, Any

def generate_core_logic_explanation(
    analysis_summary: Dict[str, Any], 
    final_action: str, 
    final_confidence: float,
    weights: Dict[str, float]
) -> str:
    """生成核心逻辑说明 - 简化版本，去掉权重配置"""
    # 直接返回空字符串，因为详细推理已经包含在 generate_enhanced_detailed_reasoning 中
    return ""

def generate_enhanced_detailed_reasoning(analysis_summary: Dict[str, Any], detailed_analysis: Dict[str, Any]) -> str:
    """生成增强的详细推理 -"""
    reasoning_parts = []
    
    # Kronos AI 分析
    if 'kronos' in analysis_summary:
        kronos = analysis_summary['kronos']
        reasoning_parts.append(f"🤖 Kronos AI: {kronos['action']} (置信度: {kronos['confidence']:.1%})")
        if kronos.get('reasoning'):
            full_reasoning = kronos['reasoning']
            reasoning_parts.append(f"└─ Kronos预测: {full_reasoning}")
    
    # 技术分析 - 详细展示
    if 'technical' in analysis_summary:
        tech = analysis_summary['technical']
        reasoning_parts.append(f"📊 技术分析: {tech['action']} (置信度: {tech['confidence']:.1%})")
        reasoning_parts.append(f"├─ 趋势分析: {tech.get('trend', '中性')}")
        reasoning_parts.append(f"├─ 动量指标: {tech.get('momentum', '中性')}")
        reasoning_parts.append(f"├─ 成交量: {tech.get('volume', '正常')}")
        
        # 添加更多技术细节
        tech_details = detailed_analysis.get('technical', {})
        if isinstance(tech_details, dict):
            if tech_details.get('support_levels'):
                reasoning_parts.append(f"├─ 支撑位: {tech_details.get('support_levels', 'N/A')}")
            if tech_details.get('resistance_levels'):
                reasoning_parts.append(f"├─ 阻力位: {tech_details.get('resistance_levels', 'N/A')}")
            if tech_details.get('trend_strength'):
                reasoning_parts.append(f"└─ 趋势强度: {tech_details.get('trend_strength', 'N/A')}")
    
    # 量价分析 - 详细展示
    if 'volume_price' in analysis_summary:
        vol = analysis_summary['volume_price']
        reasoning_parts.append(f"📈 量价分析: {vol['action']} (置信度: {vol['confidence']:.1%})")
        reasoning_parts.append(f"├─ 价量背离: {vol.get('divergence', '无')}")
        reasoning_parts.append(f"├─ 趋势确认: {'强确认' if vol.get('volume_confirmation') else '弱确认'}")
        
        # 添加量价细节
        vol_details = detailed_analysis.get('volume_price', {})
        if isinstance(vol_details, dict):
            if vol_details.get('volume_trend'):
                reasoning_parts.append(f"└─ 成交量趋势: {vol_details.get('volume_trend', 'N/A')}")

    
    return "\n".join(reasoning_parts)

def get_enhanced_weights() -> Dict[str, float]:
    """获取增强的权重配置 - 以技术分析为主导"""
    return {
        'kronos': 0.20,      # 降低Kronos权重
        'technical': 0.55,   # 提高技术分析权重
        'volume_price': 0.20, # 保持量价分析权重
        'ml': 0.05           # 降低ML权重
    }

def get_dynamic_weights(confidence_scores: Dict[str, float]) -> Dict[str, float]:
    """根据各模块置信度动态调整权重"""
    base_weights = get_enhanced_weights()
    
    # 定义置信度阈值
    LOW_CONFIDENCE_THRESHOLD = 0.3
    HIGH_CONFIDENCE_THRESHOLD = 0.7
    
    # 计算可信模块和不可信模块
    reliable_modules = {}
    unreliable_modules = {}
    
    for module, confidence in confidence_scores.items():
        if module in base_weights:
            if confidence >= HIGH_CONFIDENCE_THRESHOLD:
                reliable_modules[module] = confidence
            elif confidence < LOW_CONFIDENCE_THRESHOLD:
                unreliable_modules[module] = confidence
    
    # 如果有不可信模块，重新分配权重
    if unreliable_modules:
        adjusted_weights = base_weights.copy()
        
        # 计算需要重新分配的权重
        total_penalty_weight = sum(base_weights[module] for module in unreliable_modules)
        
        # 将不可信模块的权重降低50%
        for module in unreliable_modules:
            adjusted_weights[module] = base_weights[module] * 0.5
        
        # 将减少的权重分配给可信模块
        redistributed_weight = total_penalty_weight * 0.5
        reliable_module_count = len([m for m in base_weights if m not in unreliable_modules])
        
        if reliable_module_count > 0:
            weight_boost = redistributed_weight / reliable_module_count
            for module in base_weights:
                if module not in unreliable_modules:
                    adjusted_weights[module] += weight_boost
        
        # 确保权重总和为1
        total_weight = sum(adjusted_weights.values())
        if total_weight > 0:
            for module in adjusted_weights:
                adjusted_weights[module] /= total_weight
        
        return adjusted_weights
    
    return base_weights

def calculate_enhanced_confidence(
    raw_confidence: float, 
    tech_confidence: float, 
    min_confidence: float = 0.3,
    max_confidence: float = 0.95
) -> float:
    """计算增强的置信度 - 以技术分析为准"""
    # 置信度增强逻辑 - 以技术分析为准，提高整体置信度
    if tech_confidence > 0.6:
        # 技术分析置信度高时，整体置信度获得加成
        confidence_boost = min(0.25, (tech_confidence - 0.6) * 0.5)
        final_confidence = min(max_confidence, raw_confidence + confidence_boost)
    else:
        final_confidence = raw_confidence
    
    # 确保置信度在合理范围内
    return max(min_confidence, min(max_confidence, final_confidence))

def apply_confidence_floor(confidence_scores: Dict[str, float]) -> Dict[str, float]:
    """应用置信度下限，确保每个模块的置信度不会过低"""
    MIN_CONFIDENCE = 0.25  # 最低置信度25%
    NEUTRAL_CONFIDENCE = 0.45  # 中性状态建议置信度45%
    
    adjusted_scores = {}
    
    for module, confidence in confidence_scores.items():
        if confidence < MIN_CONFIDENCE:
            # 极低置信度，提升到最低水平
            adjusted_scores[module] = MIN_CONFIDENCE
        elif confidence < 0.35 and module in ['technical', 'volume_price']:
            # 技术分析和量价分析如果过低，提升到中性水平
            adjusted_scores[module] = NEUTRAL_CONFIDENCE
        else:
            adjusted_scores[module] = confidence
    
    return adjusted_scores