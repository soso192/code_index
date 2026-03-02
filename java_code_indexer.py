#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Java代码批量分析与索引生成工具
优化策略：按包/目录批量聚合，最小化Minimax API调用次数
"""

import os
import json
import hashlib
import re
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict
import anthropic
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


@dataclass
class MethodInfo:
    """方法详细信息"""
    name: str
    signature: str
    description: str = ""
    
@dataclass
class JavaClassInfo:
    """Java类信息数据结构"""
    file_path: str
    class_name: str
    package: str
    imports: List[str]
    dependencies: List[str]
    methods: List[str]
    business_summary: str = ""  # 详细业务摘要
    related_classes: List[str] = None
    method_details: List[MethodInfo] = None  # 详细方法解释
    core_responsibility: str = ""  # 核心职责
    business_flow: str = ""  # 业务流程
    
    def __post_init__(self):
        if self.related_classes is None:
            self.related_classes = []
        if self.method_details is None:
            self.method_details = []


class JavaFileScanner:
    """Java文件扫描器 - 提取基础信息"""
    
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.class_map: Dict[str, JavaClassInfo] = {}  # 全限定名 -> 类信息
        self.package_groups: Dict[str, List[str]] = defaultdict(list)  # 包名 -> 文件路径列表
        
    def scan_all_files(self) -> Dict[str, JavaClassInfo]:
        """扫描所有Java文件并提取基础元数据"""
        java_files = list(self.root_dir.rglob("*.java"))
        print(f"[扫描] 发现 {len(java_files)} 个Java文件")
        
        for file_path in java_files:
            try:
                info = self._parse_java_file(file_path)
                if info:
                    self.class_map[f"{info.package}.{info.class_name}"] = info
                    self.package_groups[info.package].append(str(file_path))
            except Exception as e:
                print(f"[警告] 解析失败 {file_path}: {e}")
                
        print(f"[扫描] 成功解析 {len(self.class_map)} 个类")
        return self.class_map
    
    def _parse_java_file(self, file_path: Path) -> Optional[JavaClassInfo]:
        """解析单个Java文件的基础信息"""
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
        except:
            return None
            
        # 提取包名
        package_match = re.search(r'package\s+([\w.]+);', content)
        package = package_match.group(1) if package_match else "default"
        
        # 提取类名
        class_match = re.search(r'(?:public\s+)?(?:class|interface|enum)\s+(\w+)', content)
        if not class_match:
            return None
        class_name = class_match.group(1)
        
        # 提取imports
        imports = re.findall(r'import\s+([\w.*]+);', content)
        
        # 提取方法签名（简化版）
        methods = re.findall(
            r'(?:public|private|protected)\s+(?:static\s+)?(?:[\w<>,\[\]]+\s+)?(\w+)\s*\([^)]*\)\s*\{',
            content
        )
        
        # 从imports和代码中识别依赖
        dependencies = []
        for imp in imports:
            if not imp.startswith('java.') and not imp.startswith('javax.'):
                if imp.endswith('.*'):
                    dependencies.append(imp[:-2])  # 包级依赖
                else:
                    dependencies.append(imp)  # 具体类依赖
                    
        return JavaClassInfo(
            file_path=str(file_path),
            class_name=class_name,
            package=package,
            imports=imports,
            dependencies=dependencies,
            methods=methods[:10]  # 只保留前10个方法
        )


class BatchAnalyzer:
    """批量分析器 - 聚合多个类一次性调用API"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        # 支持Minimax的Anthropic兼容模式
        # base_url 默认为 None (Anthropic官方) 或 https://api.minimaxi.com/anthropic
        self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self.stats = {
            "total_calls": 0,
            "total_tokens": 0,
            "failed_calls": 0
        }
        self.lock = threading.Lock()
        
    def analyze_batch(self, classes: List[JavaClassInfo], batch_id: int) -> List[JavaClassInfo]:
        """批量分析一组相关的类"""
        if not classes:
            return []
            
        # 构建批量分析的prompt
        prompt = self._build_batch_prompt(classes)
        
        try:
            response = self._call_api(prompt, batch_id)
            analyzed = self._parse_batch_response(response, classes)
            
            with self.lock:
                self.stats["total_calls"] += 1
                
            return analyzed
        except Exception as e:
            print(f"[错误] 批次 {batch_id} API调用失败: {e}")
            with self.lock:
                self.stats["failed_calls"] += 1
            return classes  # 返回原始数据
    
    def _build_batch_prompt(self, classes: List[JavaClassInfo]) -> str:
        """构建详细的批量分析prompt"""
        prompt_parts = [
            "你是一个Java代码分析专家，请深度分析以下Java类的业务逻辑、核心职责和方法。",
            "",
            "对于每个类，请提供以下详细信息：",
            "1. business_summary: 详细业务摘要（200-500字），包括：",
            "   - 该类的核心职责是什么",
            "   - 在业务架构中的位置和作用",
            "   - 与其他系统/模块的交互关系",
            "   - 主要处理的业务场景",
            "",
            "2. core_responsibility: 一句话概括核心职责（50字以内）",
            "",
            "3. method_details: 每个主要方法的详细说明，包括：",
            "   - name: 方法名",
            "   - signature: 完整方法签名",
            "   - description: 方法的业务功能描述（50-100字），说明该方法在业务流程中的作用、输入输出含义、调用场景",
            "",
            "4. related_classes: 该类直接依赖或关联的其他类列表（从提供的类名中选择）",
            "",
            "5. business_flow: 描述该类参与的主要业务流程（100-200字）",
            "",
            "=== 待分析的类列表 ===",
            ""
        ]
        
        class_names = [f"{c.package}.{c.class_name}" for c in classes]
        
        for i, cls in enumerate(classes, 1):
            rel_path = Path(cls.file_path).name
            deps_str = ", ".join(cls.dependencies[:8]) if cls.dependencies else "无"
            methods_str = "\n        ".join([f"- {m}" for m in cls.methods[:15]]) if cls.methods else "无"
            
            prompt_parts.append(f"[{i}] {cls.package}.{cls.class_name}")
            prompt_parts.append(f"    文件路径: {rel_path}")
            prompt_parts.append(f"    导入依赖: {deps_str}")
            prompt_parts.append(f"    方法列表:")
            prompt_parts.append(f"        {methods_str}")
            prompt_parts.append("")
            
        prompt_parts.append("=== 可用类名索引（用于关联关系） ===")
        prompt_parts.append(", ".join(class_names))
        prompt_parts.append("")
        prompt_parts.append("请严格按照以下JSON格式返回（只返回JSON，不要有其他文字）：")
        prompt_parts.append(json.dumps({
            "analyses": [
                {
                    "class_index": 1,
                    "business_summary": "详细业务摘要，200-500字，描述核心职责、业务场景、系统交互等",
                    "core_responsibility": "一句话核心职责",
                    "method_details": [
                        {
                            "name": "方法名",
                            "signature": "完整方法签名",
                            "description": "方法业务功能描述，50-100字"
                        }
                    ],
                    "related_classes": ["包名.类名1", "包名.类名2"],
                    "business_flow": "该类参与的主要业务流程描述，100-200字"
                }
            ]
        }, ensure_ascii=False, indent=2))
        
        return "\n".join(prompt_parts)
    
    def _call_api(self, prompt: str, batch_id: int) -> str:
        """使用Anthropic SDK调用MiniMax-M2.5 API"""
        message = self.client.messages.create(
            model="MiniMax-M2.5",
            max_tokens=14000,
            system="你是Java代码分析专家，擅长从代码中提取业务逻辑和类关系。分析要简洁准确。",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )
        
        # 提取响应内容
        content_text = ""
        for block in message.content:
            if block.type == "text":
                content_text += block.text
        
        # 记录token使用情况
        with self.lock:
            self.stats["total_calls"] += 1
            self.stats["total_tokens"] += message.usage.input_tokens + message.usage.output_tokens
            
        return content_text
    
    def _parse_batch_response(self, response: str, original_classes: List[JavaClassInfo]) -> List[JavaClassInfo]:
        """解析API返回的详细批量分析结果 - 增强容错"""
        try:
            # 去除Markdown代码块标记
            cleaned_response = response.strip()
            if cleaned_response.startswith("```json"):
                cleaned_response = cleaned_response[7:].lstrip()
            elif cleaned_response.startswith("```"):
                cleaned_response = cleaned_response[3:].lstrip()
            if cleaned_response.rstrip().endswith("```"):
                cleaned_response = cleaned_response.rstrip()[:-3].rstrip()
            cleaned_response = cleaned_response.strip()
            
            # 方法1: 尝试直接解析
            data = None
            try:
                data = json.loads(cleaned_response)
            except json.JSONDecodeError:
                pass
            
            # 方法2: 如果失败，尝试修复常见错误后解析
            if not data:
                # 修复双引号转义问题
                fixed_response = cleaned_response.replace('""class_index""', '"class_index"')
                fixed_response = fixed_response.replace('""business_summary""', '"business_summary"')
                try:
                    data = json.loads(fixed_response)
                except:
                    pass
            
            # 方法3: 使用decoder扫描找到有效的JSON对象
            if not data:
                decoder = json.JSONDecoder()
                idx = 0
                while idx < len(cleaned_response):
                    try:
                        char = cleaned_response[idx]
                        if char == '{':
                            obj, end = decoder.raw_decode(cleaned_response, idx)
                            if "analyses" in obj:
                                data = obj
                                break
                            # 如果是拼接的多个类分析对象
                            if "class_index" in obj and "business_summary" in obj:
                                analyses_list = [obj]
                                idx += end
                                while idx < len(cleaned_response):
                                    try:
                                        next_char = cleaned_response[idx]
                                        if next_char == '{':
                                            next_obj, next_end = decoder.raw_decode(cleaned_response, idx)
                                            if "class_index" in next_obj:
                                                analyses_list.append(next_obj)
                                                idx += next_end
                                                continue
                                        idx += 1
                                    except:
                                        idx += 1
                                data = {"analyses": analyses_list}
                                break
                            idx += end
                        else:
                            idx += 1
                    except:
                        idx += 1
            
            # 方法4: 使用正则提取单个类分析对象
            if not data:
                analyses_list = []
                # 匹配每个类分析对象
                class_pattern = r'\{\s*"class_index"\s*:\s*(\d+)[^}]*"business_summary"\s*:\s*"([^"]*)"'
                for match in re.finditer(class_pattern, cleaned_response, re.DOTALL):
                    idx = int(match.group(1))
                    summary = match.group(2)
                    if 0 < idx <= len(original_classes):
                        cls = original_classes[idx - 1]
                        cls.business_summary = summary[:500]  # 截断避免过长
                        analyses_list.append({"class_index": idx, "found": True})
                
                if analyses_list:
                    print(f"[解析] 正则提取到 {len(analyses_list)} 个类的摘要")
                    return original_classes
            
            # 处理标准格式
            if data and "analyses" in data:
                analyses = data.get("analyses", [])
                parsed_count = 0
                
                for analysis in analyses:
                    idx = analysis.get("class_index", 0) - 1
                    if 0 <= idx < len(original_classes):
                        cls = original_classes[idx]
                        cls.business_summary = analysis.get("business_summary", "")
                        cls.core_responsibility = analysis.get("core_responsibility", "")
                        cls.business_flow = analysis.get("business_flow", "")
                        cls.related_classes = analysis.get("related_classes", [])
                        
                        # 解析方法详情
                        method_details_data = analysis.get("method_details", [])
                        cls.method_details = []
                        for md in method_details_data:
                            if isinstance(md, dict):
                                cls.method_details.append(MethodInfo(
                                    name=md.get("name", ""),
                                    signature=md.get("signature", ""),
                                    description=md.get("description", "")
                                ))
                        parsed_count += 1
                
                if parsed_count == 0:
                    print(f"[警告] 找到analyses但未能解析任何类，批次大小: {len(original_classes)}")
            else:
                # 保存失败响应用于调试
                debug_file = Path(f"debug_response_{int(time.time())}.txt")
                debug_file.write_text(response, encoding='utf-8')
                print(f"[警告] 响应中未找到analyses字段，已保存到: {debug_file}")
                        
        except Exception as e:
            print(f"[警告] 解析响应时出错: {e}, 响应前300字: {response[:300]}...")
            
        return original_classes


class CodeIndexer:
    """代码索引生成器"""
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def build_index(self, class_map: Dict[str, JavaClassInfo]) -> Dict:
        """构建多级索引结构"""
        
        # 1. 类级索引
        class_index = {}
        for full_name, info in class_map.items():
            # 转换方法详情为字典列表
            methods_detail_list = []
            for md in info.method_details:
                methods_detail_list.append({
                    "name": md.name,
                    "signature": md.signature,
                    "description": md.description
                })
            
            class_index[full_name] = {
                "file_path": info.file_path,
                "package": info.package,
                "business_summary": info.business_summary,
                "core_responsibility": info.core_responsibility,
                "business_flow": info.business_flow,
                "related_classes": info.related_classes,
                "method_details": methods_detail_list,
                "methods_count": len(info.methods),
                "dependencies": info.dependencies
            }
        
        # 2. 包级索引
        package_index = defaultdict(lambda: {"classes": [], "summary": "", "dependencies": []})
        for full_name, info in class_map.items():
            pkg = info.package
            package_index[pkg]["classes"].append(full_name)
            package_index[pkg]["dependencies"].extend(info.dependencies)
            
        # 3. 依赖关系图
        dependency_graph = defaultdict(list)
        for full_name, info in class_map.items():
            for dep in info.related_classes:
                if dep in class_map:  # 只记录项目内的依赖
                    dependency_graph[full_name].append(dep)
        
        # 4. 标签索引（从业务摘要中提取关键词）
        tag_index = defaultdict(list)
        for full_name, info in class_map.items():
            if info.business_summary:
                # 简单关键词提取
                words = re.findall(r'[\u4e00-\u9fa5]{2,}|[A-Z][a-z]+', info.business_summary)
                for word in words[:3]:
                    tag_index[word].append(full_name)
        
        index_data = {
            "metadata": {
                "total_classes": len(class_map),
                "total_packages": len(package_index),
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")
            },
            "class_index": class_index,
            "package_index": dict(package_index),
            "dependency_graph": dict(dependency_graph),
            "tag_index": dict(tag_index)
        }
        
        return index_data
    
    def save_index(self, index_data: Dict, filename: str = "code_index.json"):
        """保存索引文件"""
        output_path = self.output_dir / filename
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
        print(f"[索引] 已保存到: {output_path}")
        
    def generate_summary_report(self, index_data: Dict, class_map: Dict[str, JavaClassInfo]):
        """生成可读性摘要报告"""
        report_path = self.output_dir / "code_summary.md"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"# 代码库总览\n\n")
            f.write(f"- **总类数**: {index_data['metadata']['total_classes']}\n")
            f.write(f"- **总包数**: {index_data['metadata']['total_packages']}\n")
            f.write(f"- **生成时间**: {index_data['metadata']['generated_at']}\n\n")
            
            f.write("## 包结构概览\n\n")
            for pkg, data in sorted(index_data['package_index'].items()):
                f.write(f"### {pkg}\n")
                f.write(f"- 类数量: {len(data['classes'])}\n")
                f.write(f"- 包含类: {', '.join(data['classes'][:5])}")
                if len(data['classes']) > 5:
                    f.write(f" 等共{len(data['classes'])}个类")
                f.write("\n\n")
                
            f.write("## 核心业务类（含详细分析）\n\n")
            # 按业务摘要长度排序，优先展示有详细分析的类
            sorted_classes = sorted(
                class_map.items(),
                key=lambda x: len(x[1].business_summary),
                reverse=True
            )[:100]  # 前100个
            
            for full_name, info in sorted_classes:
                if info.business_summary:
                    f.write(f"### {full_name}\n\n")
                    f.write(f"**核心职责**: {info.core_responsibility}\n\n")
                    f.write(f"**业务摘要**: {info.business_summary}\n\n")
                    if info.business_flow:
                        f.write(f"**业务流程**: {info.business_flow}\n\n")
                    
                    # 方法详情
                    if info.method_details:
                        f.write("**方法详解**:\n")
                        for md in info.method_details[:10]:  # 最多展示10个方法
                            f.write(f"- `{md.name}`: {md.description}\n")
                        if len(info.method_details) > 10:
                            f.write(f"- ... 等共 {len(info.method_details)} 个方法\n")
                        f.write("\n")
                    
                    if info.related_classes:
                        f.write(f"**关联类**: {', '.join(info.related_classes[:10])}\n\n")
                    f.write(f"**文件路径**: `{info.file_path}`\n\n")
                    f.write("---\n\n")
                    
        print(f"[报告] 已生成摘要报告: {report_path}")


class ProgressManager:
    """进度管理器 - 支持断点续传"""
    
    def __init__(self, progress_file: str):
        self.progress_file = Path(progress_file)
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        self.completed_batches: Set[int] = set()
        self.completed_classes: Set[str] = set()
        self.load()
        
    def load(self):
        """加载进度"""
        if self.progress_file.exists():
            try:
                data = json.loads(self.progress_file.read_text(encoding='utf-8'))
                self.completed_batches = set(data.get("batches", []))
                self.completed_classes = set(data.get("classes", []))
                print(f"[进度] 已加载: {len(self.completed_batches)} 批次, {len(self.completed_classes)} 个类")
            except:
                pass
                
    def save(self):
        """保存进度"""
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "batches": list(self.completed_batches),
            "classes": list(self.completed_classes),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self.progress_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        
    def is_batch_completed(self, batch_id: int) -> bool:
        return batch_id in self.completed_batches
        
    def mark_batch_completed(self, batch_id: int, classes: List[str]):
        self.completed_batches.add(batch_id)
        self.completed_classes.update(classes)
        self.save()


def main():
    """主程序"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Java代码批量分析与索引工具')
    parser.add_argument('--source', '-s', required=True, help='Java源代码根目录')
    parser.add_argument('--output', '-o', default='./code_index', help='输出目录')
    parser.add_argument('--api-key', '-k', help='API Key (Anthropic或Minimax，或从环境变量读取)')
    parser.add_argument('--base-url', '-u', help='API基础URL (Minimax使用 https://api.minimaxi.com/anthropic)')
    parser.add_argument('--batch-size', '-b', type=int, default=50, help='每批处理的类数（建议30-100，越大越快）')
    parser.add_argument('--workers', '-w', type=int, default=5, help='并发线程数（建议3-10，越大越快但注意API限流）')
    parser.add_argument('--no-sleep', action='store_true', help='移除请求间隔，全速运行（可能被API限流）')
    parser.add_argument('--resume', '-r', action='store_true', help='断点续传模式')
    parser.add_argument('--reset', action='store_true', help='重置进度，强制重新分析所有文件')
    
    args = parser.parse_args()
    
    # 处理重置
    progress_file = Path(args.output) / "progress.json"
    if args.reset and progress_file.exists():
        progress_file.unlink()
        print("[进度] 已重置，将重新分析所有文件")
    
    # 1. 扫描所有Java文件
    print("=" * 60)
    print("步骤1: 扫描Java文件")
    print("=" * 60)
    scanner = JavaFileScanner(args.source)
    class_map = scanner.scan_all_files()
    
    if not class_map:
        print("[错误] 未找到Java文件")
        return
    
    # 2. 按包分组，创建批次
    print("\n" + "=" * 60)
    print("步骤2: 创建分析批次")
    print("=" * 60)
    
    # 初始化索引器（用于增量保存）
    indexer = CodeIndexer(args.output)
    
    # 加载已有索引（断点续传时恢复业务数据）
    existing_index_path = Path(args.output) / "code_index.json"
    loaded_count = 0
    pending_classes = []  # 待处理的类
    
    if existing_index_path.exists() and not args.reset:
        try:
            with open(existing_index_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            # 将已有业务数据合并到class_map，并筛选出未完成的类
            for full_name, cls_info in existing_data.get('class_index', {}).items():
                if full_name in class_map:
                    summary = cls_info.get('business_summary', '')
                    class_map[full_name].business_summary = summary
                    class_map[full_name].core_responsibility = cls_info.get('core_responsibility', '')
                    class_map[full_name].business_flow = cls_info.get('business_flow', '')
                    class_map[full_name].related_classes = cls_info.get('related_classes', [])
                    # 加载方法详情
                    method_details = cls_info.get('method_details', [])
                    class_map[full_name].method_details = [
                        MethodInfo(name=md.get('name', ''), 
                                   signature=md.get('signature', ''), 
                                   description=md.get('description', ''))
                        for md in method_details
                    ]
                    if summary and len(summary) > 10:
                        loaded_count += 1
                    else:
                        # 没有有效摘要，加入待处理列表
                        pending_classes.append(class_map[full_name])
            print(f"[续传] 已加载 {loaded_count} 个类的业务数据")
            print(f"[续传] 待处理类数: {len(pending_classes)}")
        except Exception as e:
            print(f"[警告] 加载已有索引失败: {e}")
            pending_classes = list(class_map.values())  # 全部重新处理
    else:
        pending_classes = list(class_map.values())  # 全部处理
    
    # 对未完成的类重新分批
    if pending_classes:
        package_groups = defaultdict(list)
        for info in pending_classes:
            package_groups[info.package].append(info)
        
        batches = []
        batch_id = 0
        for pkg, classes in package_groups.items():
            # 每个包内的类按类名排序后分批
            classes_sorted = sorted(classes, key=lambda c: c.class_name)
            for i in range(0, len(classes_sorted), args.batch_size):
                batch = classes_sorted[i:i + args.batch_size]
                batches.append((batch_id, batch))
                batch_id += 1
        
        print(f"[批次] 共创建 {len(batches)} 个分析批次（待处理类）")
    else:
        batches = []
        print("[完成] 所有类都已分析，无需处理")
        
    # 如果没有待处理批次，直接生成最终报告
    if not batches:
        print("\n" + "=" * 60)
        print("步骤3: 生成最终索引文件")
        print("=" * 60)
        final_index_data = indexer.build_index(class_map)
        indexer.save_index(final_index_data)
        indexer.generate_summary_report(final_index_data, class_map)
        print("\n完成！")
        return
    
    # 4. 批量分析（并发处理）
    print("\n" + "=" * 60)
    print("步骤3: 批量分析（并发调用API）")
    print(f"         批次大小: {args.batch_size}  并发数: {args.workers}")
    print(f"         待处理类: {sum(len(b) for _, b in batches)}  批次: {len(batches)}")
    print("=" * 60)
    
    # 从参数或环境变量获取配置
    api_key = args.api_key or os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('MINIMAX_API_KEY')
    base_url = args.base_url or os.environ.get('ANTHROPIC_BASE_URL')
    
    if not api_key:
        print('[错误] 请提供API Key: --api-key 或设置环境变量 ANTHROPIC_API_KEY / MINIMAX_API_KEY')
        return
        
    analyzer = BatchAnalyzer(api_key=api_key, base_url=base_url)

    # 3. 初始化进度管理（仅用于记录，不再用于跳过）
    progress = ProgressManager(Path(args.output) / "progress.json")
    
    index_data = indexer.build_index(class_map)  # 构建索引（包含已加载的业务数据）

    # 用于线程安全的锁
    index_lock = threading.Lock()
    file_lock = threading.Lock()  # 文件写入专用锁
    save_counter = [0]  # 使用列表存储计数器，避免闭包问题
    save_every = 10  # 每10个批次保存一次

    def save_incremental(force=False):
        """增量保存当前索引 - 每N批次或强制保存"""
        with index_lock:
            save_counter[0] += 1
            should_save = force or (save_counter[0] % save_every == 0)
            if should_save:
                with file_lock:
                    indexer.save_index(index_data)
                print(f"  -> 已保存 ({len(progress.completed_classes)}/{len(class_map)} 类, {len(progress.completed_batches)}/{len(batches)} 批)")
            else:
                print(f"  -> 已更新内存索引 ({len(progress.completed_classes)}/{len(class_map)} 类)")

    
    def process_batch(batch_id: int, batch_classes: List[JavaClassInfo]) -> int:
        """处理单个批次，返回成功处理的类数"""
        if progress.is_batch_completed(batch_id):
            return 0  # 跳过已完成的
            
        print(f"[批次 {batch_id:4d}] 分析 {len(batch_classes):2d} 个类...", flush=True)
        result = analyzer.analyze_batch(batch_classes, batch_id)
        
        success_count = 0
        # 更新全局class_map和索引
        with index_lock:
            for cls in result:
                full_name = f"{cls.package}.{cls.class_name}"
                class_map[full_name] = cls
                # 更新索引中的详细字段
                if full_name in index_data['class_index']:
                    index_data['class_index'][full_name]['business_summary'] = cls.business_summary
                    index_data['class_index'][full_name]['core_responsibility'] = cls.core_responsibility
                    index_data['class_index'][full_name]['business_flow'] = cls.business_flow
                    index_data['class_index'][full_name]['related_classes'] = cls.related_classes
                    # 转换方法详情
                    methods_detail_list = []
                    for md in cls.method_details:
                        methods_detail_list.append({
                            "name": md.name,
                            "signature": md.signature,
                            "description": md.description
                        })
                    index_data['class_index'][full_name]['method_details'] = methods_detail_list
                    if cls.business_summary:
                        success_count += 1
        
        # 标记完成
        class_names = [f"{c.package}.{c.class_name}" for c in batch_classes]
        progress.mark_batch_completed(batch_id, class_names)
        
        # 立即保存索引（断点续传）- 每10批次或强制
        save_incremental(force=False)
        
        return success_count
    
    # 并发处理所有批次
    completed = 0
    failed = 0
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # 提交所有任务
        future_to_batch = {
            executor.submit(process_batch, batch_id, batch_classes): (batch_id, batch_classes)
            for batch_id, batch_classes in batches
        }
        
        # 处理完成的任务
        for future in as_completed(future_to_batch):
            batch_id, batch_classes = future_to_batch[future]
            try:
                success_count = future.result()
                if success_count > 0:
                    completed += success_count
                else:
                    failed += len(batch_classes)
            except Exception as e:
                print(f"[批次 {batch_id}] 异常: {e}")
                failed += len(batch_classes)
            
            # 可选：添加短暂延迟避免限流
            if not args.no_sleep:
                time.sleep(0.1)
    
    print(f"\n[统计] API调用: {analyzer.stats['total_calls']} 次")
    print(f"[统计] Token使用: {analyzer.stats['total_tokens']}")
    print(f"[统计] 失败调用: {analyzer.stats['failed_calls']} 次")
    print(f"[统计] 成功分析: {completed} 类, 失败: {failed} 类")
    
    # 5. 生成最终索引和报告
    print("\n" + "=" * 60)
    print("步骤4: 生成最终索引文件")
    print("=" * 60)
    
    # 重新构建完整索引（确保所有关系正确）
    final_index_data = indexer.build_index(class_map)
    indexer.save_index(final_index_data)
    indexer.generate_summary_report(final_index_data, class_map)
    
    print("\n" + "=" * 60)
    print("完成!")
    print(f"索引文件: {Path(args.output) / 'code_index.json'}")
    print(f"摘要报告: {Path(args.output) / 'code_summary.md'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
