#!/usr/bin/env python3
"""
根据 code_index.json 和源文件状态，准确重建 progress.json
确保 batch_id 与类的对应关系正确
"""
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple

# ========== 配置（必须与主脚本一致） ==========
SOURCE_DIR = r"D:\FBIPV82-javasource\nccloud"
OUTPUT_DIR = Path("./code_index")
BATCH_SIZE = 20

@dataclass
class JavaClassInfo:
    file_path: str
    class_name: str
    package: str
    business_summary: str = ""


def parse_java_file(file_path: str) -> JavaClassInfo:
    """解析单个Java文件"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except:
        return None
    
    # 提取包名
    package_match = re.search(r'package\s+([\w.]+);', content)
    package = package_match.group(1) if package_match else "default"
    
    # 提取类名
    class_match = re.search(r'(?:public\s+|abstract\s+|final\s+)?(?:class|interface|enum)\s+(\w+)', content)
    class_name = class_match.group(1) if class_match else Path(file_path).stem
    
    return JavaClassInfo(
        file_path=file_path,
        class_name=class_name,
        package=package
    )


def scan_all_files(source_dir: str) -> Dict[str, JavaClassInfo]:
    """扫描所有Java文件"""
    class_map = {}
    source_path = Path(source_dir)
    
    if not source_path.exists():
        print(f"[错误] 源目录不存在: {source_dir}")
        return class_map
    
    java_files = list(source_path.rglob("*.java"))
    print(f"[扫描] 找到 {len(java_files)} 个Java文件")
    
    for file_path in java_files:
        info = parse_java_file(str(file_path))
        if info:
            full_name = f"{info.package}.{info.class_name}"
            class_map[full_name] = info
    
    return class_map


def create_batches(class_map: Dict[str, JavaClassInfo]) -> List[Tuple[int, List[str]]]:
    """
    创建批次，与主脚本逻辑完全一致
    返回: [(batch_id, [full_name1, full_name2, ...]), ...]
    """
    # 按包分组
    package_groups = defaultdict(list)
    for full_name in class_map.keys():
        pkg = class_map[full_name].package
        package_groups[pkg].append(full_name)
    
    # 创建批次（与主脚本逻辑一致）
    batches = []
    batch_id = 0
    
    # 注意：主脚本没有排序，这里也不排序以保持一致
    # 但如果需要确定性，可以添加排序
    for pkg in sorted(package_groups.keys()):
        classes = sorted(package_groups[pkg])  # 包内排序保证稳定
        for i in range(0, len(classes), BATCH_SIZE):
            batch = classes[i:i + BATCH_SIZE]
            batches.append((batch_id, batch))
            batch_id += 1
    
    return batches


def load_analyzed_classes() -> Set[str]:
    """从 code_index.json 加载已分析的类"""
    code_index_path = OUTPUT_DIR / "code_index.json"
    if not code_index_path.exists():
        print(f"[错误] 找不到 {code_index_path}")
        return set()
    
    print(f"[读取] {code_index_path}")
    with open(code_index_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    analyzed = set()
    for full_name, info in data.get('class_index', {}).items():
        summary = info.get('business_summary', '')
        if summary and len(summary) > 10:
            analyzed.add(full_name)
    
    print(f"[统计] 已分析类数: {len(analyzed)}")
    return analyzed


def rebuild_progress():
    """重建 progress.json"""
    print("=" * 60)
    print("重建 progress.json")
    print("=" * 60)
    
    # 1. 扫描源文件
    print("\n[步骤1] 扫描Java源文件...")
    class_map = scan_all_files(SOURCE_DIR)
    if not class_map:
        print("[错误] 未找到Java文件")
        return
    print(f"[结果] 扫描到 {len(class_map)} 个类")
    
    # 2. 创建批次（与主脚本一致）
    print(f"\n[步骤2] 创建批次 (batch_size={BATCH_SIZE})...")
    batches = create_batches(class_map)
    print(f"[结果] 共 {len(batches)} 个批次")
    
    # 3. 加载已分析的类
    print("\n[步骤3] 从 code_index.json 加载已分析类...")
    analyzed_classes = load_analyzed_classes()
    
    # 4. 确定哪些批次已完成
    print("\n[步骤4] 确定已完成批次...")
    completed_batches = []
    completed_classes = []
    
    for batch_id, batch_classes in batches:
        # 检查该批次是否所有类都已分析
        all_analyzed = all(cls in analyzed_classes for cls in batch_classes)
        if all_analyzed:
            completed_batches.append(batch_id)
            completed_classes.extend(batch_classes)
    
    print(f"[结果] 已完成批次: {len(completed_batches)}/{len(batches)}")
    print(f"[结果] 已完成类数: {len(completed_classes)}/{len(class_map)}")
    
    if len(completed_batches) > 0:
        print(f"[示例] 前10个完成批次: {completed_batches[:10]}")
    
    # 5. 保存 progress.json
    print("\n[步骤5] 保存 progress.json...")
    progress_data = {
        "batches": completed_batches,
        "classes": completed_classes,
        "updated_at": __import__('time').strftime("%Y-%m-%d %H:%M:%S"),
        "metadata": {
            "source_dir": SOURCE_DIR,
            "batch_size": BATCH_SIZE,
            "total_batches": len(batches),
            "total_classes": len(class_map),
            "completed_batches": len(completed_batches),
            "completed_classes": len(completed_classes)
        }
    }
    
    progress_path = OUTPUT_DIR / "progress.json"
    
    # 备份原文件
    if progress_path.exists():
        backup_path = OUTPUT_DIR / "progress.json.backup"
        progress_path.rename(backup_path)
        print(f"[备份] 原文件 -> {backup_path}")
    
    # 保存新文件
    with open(progress_path, 'w', encoding='utf-8') as f:
        json.dump(progress_data, f, ensure_ascii=False, indent=2)
    
    print(f"[保存] {progress_path}")
    print("=" * 60)
    print("完成！")
    print(f"\n断点续传说明:")
    print(f"- 已完成批次会跳过API调用")
    print(f"- 未完成批次会重新分析")
    print(f"- 直接运行主脚本即可继续")
    print("=" * 60)


if __name__ == "__main__":
    rebuild_progress()
