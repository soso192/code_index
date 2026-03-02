# Java代码批量分析与索引生成工具

基于 Minimax API (Claude 兼容接口) 的智能 Java 代码分析工具，支持批量处理、并发调用、断点续传，自动生成详细的代码业务索引和摘要报告。

## 功能特性

- **批量聚合分析**：按包/目录分组，每批次可处理多个类，显著减少 API 调用次数
- **智能断点续传**：根据 `code_index.json` 中的分析状态自动识别未完成的类，重新分批处理
- **并发处理**：支持多线程并发调用 API，提升处理速度
- **健壮 JSON 解析**：多层容错机制，处理 Markdown 代码块、拼接 JSON、格式错误等异常情况
- **增量保存**：每完成一批次自动保存进度，避免数据丢失
- **详细业务分析**：生成类级别的业务摘要、核心职责、业务流程、方法详情、关联类关系

## 环境要求

- Python 3.8+
- `anthropic` Python SDK (>=0.39.0)

## 安装

```bash
pip install anthropic>=0.39.0
```

## 快速开始

### 1. 基本用法

```bash
python java_code_indexer.py \
  -s "D:\FBIPV82-javasource\nccloud" \
  -k "your-api-key" \
  -u "https://api.minimaxi.com/anthropic" \
  -b 20 \
  -w 50
```

### 2. 使用环境变量

```bash
export MINIMAX_API_KEY="your-api-key"
export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"

python java_code_indexer.py -s "D:\your\java\source" -b 20 -w 50
```

## 命令行参数

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--source` | `-s` | Java 源代码根目录 | 必填 |
| `--api-key` | `-k` | Minimax API Key | 从环境变量读取 |
| `--base-url` | `-u` | API Base URL | 从环境变量读取 |
| `--batch-size` | `-b` | 每批次的类数量 | 20 |
| `--workers` | `-w` | 并发线程数 | 10 |
| `--output` | `-o` | 输出目录 | `./code_index` |
| `--no-sleep` | - | 禁用请求间隔延迟 | False |
| `--reset` | - | 重置进度，重新分析所有类 | False |

## 工作原理

### 处理流程

1. **扫描阶段**：递归扫描源代码目录，解析所有 `.java` 文件，提取类名、包名、导入、方法签名等基础信息

2. **加载已有索引**：如果存在 `code_index.json`，加载已分析的业务数据，筛选出没有有效 `business_summary` 的类作为待处理列表

3. **智能分批**：对待处理的类按包分组，每个包内按类名排序后分批

4. **并发分析**：使用线程池并发调用 Minimax API，每批次发送多个类的代码进行批量分析

5. **增量保存**：每完成 10 个批次自动保存 `code_index.json`，同时更新 `progress.json` 记录进度

6. **生成报告**：处理完成后生成 `code_summary.md` 摘要报告

### 断点续传机制

脚本不再依赖 `progress.json` 的 `batch_id` 来跳过批次，而是通过检查 `code_index.json` 中每个类的 `business_summary` 字段长度来判断是否已完成分析。这种方式更加可靠，因为：

- 不受分批逻辑变化影响
- 能准确识别真正已分析的类
- 支持动态重新分批未完成的类

### 输出文件

| 文件 | 说明 |
|------|------|
| `code_index/code_index.json` | 完整的代码索引数据，包含每个类的详细分析结果 |
| `code_index/code_summary.md` | 人类可读的摘要报告，按包组织 |
| `code_index/progress.json` | 进度记录（仅作参考，断点续传主要依赖 `code_index.json`） |

### code_index.json 结构

```json
{
  "metadata": {
    "total_classes": 52308,
    "total_packages": 1200,
    "analyzed_count": 20785,
    "timestamp": "2025-03-02T10:30:00"
  },
  "class_index": {
    "com.example.MyClass": {
      "file_path": "src/com/example/MyClass.java",
      "class_name": "MyClass",
      "package": "com.example",
      "imports": [...],
      "dependencies": [...],
      "methods": [...],
      "business_summary": "业务摘要...",
      "core_responsibility": "核心职责...",
      "business_flow": "业务流程...",
      "related_classes": [...],
      "method_details": [
        {
          "name": "methodName",
          "signature": "public void methodName(String arg)",
          "description": "方法描述..."
        }
      ]
    }
  },
  "package_index": {...},
  "dependency_graph": {...}
}
```

## 辅助工具

### rebuild_progress.py

用于根据 `code_index.json` 的当前状态重建 `progress.json`，确保进度文件与实际分析状态一致。

```bash
python rebuild_progress.py
```

**使用场景**：
- 怀疑 `progress.json` 不准确
- 需要查看当前分析进度统计
- 清理进度文件后重建

## 故障排查

### 1. 解析 API 响应失败

如果遇到 JSON 解析错误，脚本会自动尝试多种修复策略：
- 去除 Markdown 代码块标记
- 修复双引号转义问题
- 使用 JSONDecoder 扫描多个 JSON 对象
- 正则表达式提取关键字段

失败的响应会保存为 `debug_response_*.txt` 文件供人工检查。

### 2. 速度变慢

如果脚本速度明显变慢，可能原因：
- 待处理类数较少，API 调用间隔导致
- 大量批次分析失败，重试频繁

**解决方法**：
- 检查 `code_index.json` 中已分析类的数量
- 使用 `--no-sleep` 禁用请求间隔（注意 API 限流）
- 运行 `rebuild_progress.py` 查看实际进度

### 3. 断点续传不准确

如果断点续传行为异常：

1. 检查 `code_index.json` 中类的 `business_summary` 字段长度
2. 运行 `rebuild_progress.py` 重建进度统计
3. 如需强制重新分析，使用 `--reset` 参数

## 性能调优

### 批次大小 (`-b`)

- **较小批次 (5-10)**：适合复杂类，API 响应更稳定
- **标准批次 (20)**：平衡效率和稳定性
- **大批次 (50+)**：API 可能超时或限流

### 并发数 (`-w`)

- **低并发 (10-20)**：稳定，适合有严格限流的场景
- **标准并发 (50)**：较快，需要良好网络环境
- **高并发 (100+)**：可能触发 API 限流

## 示例

### 分析新项目

```bash
python java_code_indexer.py \
  -s "/path/to/java/project" \
  -k "sk-cp-xxxxxxxx" \
  -u "https://api.minimaxi.com/anthropic" \
  -b 20 \
  -w 50 \
  -o "./my_project_index"
```

### 继续中断的分析

```bash
python java_code_indexer.py \
  -s "/path/to/java/project" \
  -k "sk-cp-xxxxxxxx" \
  -u "https://api.minimaxi.com/anthropic" \
  -b 20 \
  -w 50
```

### 强制重新分析

```bash
python java_code_indexer.py \
  -s "/path/to/java/project" \
  -k "sk-cp-xxxxxxxx" \
  -u "https://api.minimaxi.com/anthropic" \
  -b 20 \
  -w 50 \
  --reset
```

### 快速分析（减少延迟）

```bash
python java_code_indexer.py \
  -s "/path/to/java/project" \
  -k "sk-cp-xxxxxxxx" \
  -u "https://api.minimaxi.com/anthropic" \
  -b 20 \
  -w 50 \
  --no-sleep
```

## 架构说明

### 核心类

- **`JavaFileScanner`**：扫描源代码目录，解析基础类信息
- **`JavaClassInfo`**：数据类，存储单个 Java 类的完整信息
- **`BatchAnalyzer`**：批量分析器，调用 API 进行智能分析
- **`CodeIndexer`**：索引构建器，生成最终 JSON 和 Markdown 报告
- **`ProgressManager`**：进度管理器，记录处理状态

### 并发安全

- `index_lock`：保护内存中的索引数据
- `file_lock`：保护文件写入操作
- `save_counter`：控制保存频率（每 10 批次）

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request 改进工具。
