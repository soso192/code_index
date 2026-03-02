# Java Code Batch Analysis and Indexing Tool

An intelligent Java code analysis tool based on the Minimax API (Claude-compatible interface), supporting batch processing, concurrent API calls, resumable execution, and automatic generation of detailed code business indexes and summary reports.

## Features

- **Batch Aggregation Analysis**: Groups classes by package/directory, processing multiple classes per batch to significantly reduce API call overhead
- **Smart Resumable Execution**: Automatically identifies unanalyzed classes based on `code_index.json` status and re-batches them for processing
- **Concurrent Processing**: Multi-threaded concurrent API calls for improved throughput
- **Robust JSON Parsing**: Multi-layer fault tolerance for handling Markdown code blocks, concatenated JSON, and malformed responses
- **Incremental Saving**: Auto-saves progress after each batch to prevent data loss
- **Detailed Business Analysis**: Generates class-level business summaries, core responsibilities, business flows, method details, and related class relationships

## Requirements

- Python 3.8+
- `anthropic` Python SDK (>=0.39.0)

## Installation

```bash
pip install "anthropic>=0.39.0"
```

## Quick Start

### 1. Basic Usage

```bash
python java_code_indexer.py \
  -s "/path/to/java/source" \
  -k "your-api-key" \
  -u "https://api.minimaxi.com/anthropic" \
  -b 20 \
  -w 50
```

### 2. Using Environment Variables

```bash
export MINIMAX_API_KEY="your-api-key"
export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"

python java_code_indexer.py -s "/path/to/java/source" -b 20 -w 50
```

## Command Line Arguments

| Argument | Short | Description | Default |
|----------|-------|-------------|---------|
| `--source` | `-s` | Java source code root directory | Required |
| `--api-key` | `-k` | Minimax API Key | Read from env |
| `--base-url` | `-u` | API Base URL | Read from env |
| `--batch-size` | `-b` | Number of classes per batch | 20 |
| `--workers` | `-w` | Concurrent thread count | 10 |
| `--output` | `-o` | Output directory | `./code_index` |
| `--no-sleep` | - | Disable request throttling | False |
| `--reset` | - | Reset progress, re-analyze all | False |

## How It Works

### Processing Pipeline

1. **Scan Phase**: Recursively scans the source directory, parses all `.java` files, extracts class names, package names, imports, method signatures, and other basic metadata

2. **Load Existing Index**: If `code_index.json` exists, loads previously analyzed business data and filters classes without a valid `business_summary` as the pending list

3. **Smart Batching**: Groups pending classes by package, sorts by class name within each package, and creates batches

4. **Concurrent Analysis**: Uses a thread pool to concurrently call the Minimax API, sending multiple classes per batch for batch analysis

5. **Incremental Saving**: Auto-saves `code_index.json` every 10 batches, updating `progress.json` to track progress

6. **Generate Report**: Generates `code_summary.md` summary report after completion

### Resumable Execution Mechanism

The script no longer relies on `progress.json`'s `batch_id` to skip batches. Instead, it checks the `business_summary` field length for each class in `code_index.json` to determine if analysis is complete. This approach is more reliable because:

- Unaffected by changes in batching logic
- Accurately identifies truly analyzed classes
- Supports dynamic re-batching of incomplete classes

### Output Files

| File | Description |
|------|-------------|
| `code_index/code_index.json` | Complete code index data, including detailed analysis for each class |
| `code_index/code_summary.md` | Human-readable summary report, organized by package |
| `code_index/progress.json` | Progress record (for reference only; resumption primarily relies on `code_index.json`) |

### code_index.json Structure

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
      "business_summary": "Business summary...",
      "core_responsibility": "Core responsibility...",
      "business_flow": "Business flow...",
      "related_classes": [...],
      "method_details": [
        {
          "name": "methodName",
          "signature": "public void methodName(String arg)",
          "description": "Method description..."
        }
      ]
    }
  },
  "package_index": {...},
  "dependency_graph": {...}
}
```

## Utility Tools

### rebuild_progress.py

Rebuilds `progress.json` based on the current state of `code_index.json` to ensure the progress file matches the actual analysis status.

```bash
python rebuild_progress.py
```

**Use Cases**:
- Suspect `progress.json` is inaccurate
- Need to view current analysis progress statistics
- Rebuild after cleaning progress files

## Troubleshooting

### 1. API Response Parsing Failures

If JSON parsing errors occur, the script automatically attempts multiple repair strategies:
- Removes Markdown code block markers
- Fixes double-quote escaping issues
- Uses JSONDecoder to scan multiple JSON objects
- Regex extraction of key fields

Failed responses are saved as `debug_response_*.txt` for manual inspection.

### 2. Slow Performance

If the script is noticeably slower, possible causes:
- Fewer remaining classes to process, API call intervals causing delays
- Many batch analysis failures, frequent retries

**Solutions**:
- Check the number of analyzed classes in `code_index.json`
- Use `--no-sleep` to disable request throttling (watch for API rate limits)
- Run `rebuild_progress.py` to check actual progress

### 3. Inaccurate Resumable Execution

If resumable execution behaves unexpectedly:

1. Check the `business_summary` field length for classes in `code_index.json`
2. Run `rebuild_progress.py` to rebuild progress statistics
3. Use `--reset` flag to force re-analysis if needed

## Performance Tuning

### Batch Size (`-b`)

- **Small batches (5-10)**: For complex classes, more stable API responses
- **Standard batches (20)**: Balance of efficiency and stability
- **Large batches (50+)**: May cause API timeouts or rate limiting

### Concurrency (`-w`)

- **Low concurrency (10-20)**: Stable, suitable for strict rate limiting
- **Standard concurrency (50)**: Faster, requires good network conditions
- **High concurrency (100+)**: May trigger API rate limits

## Examples

### Analyze New Project

```bash
python java_code_indexer.py \
  -s "/path/to/java/project" \
  -k "sk-cp-xxxxxxxx" \
  -u "https://api.minimaxi.com/anthropic" \
  -b 20 \
  -w 50 \
  -o "./my_project_index"
```

### Continue Interrupted Analysis

```bash
python java_code_indexer.py \
  -s "/path/to/java/project" \
  -k "sk-cp-xxxxxxxx" \
  -u "https://api.minimaxi.com/anthropic" \
  -b 20 \
  -w 50
```

### Force Re-analysis

```bash
python java_code_indexer.py \
  -s "/path/to/java/project" \
  -k "sk-cp-xxxxxxxx" \
  -u "https://api.minimaxi.com/anthropic" \
  -b 20 \
  -w 50 \
  --reset
```

### Fast Analysis (Reduced Throttling)

```bash
python java_code_indexer.py \
  -s "/path/to/java/project" \
  -k "sk-cp-xxxxxxxx" \
  -u "https://api.minimaxi.com/anthropic" \
  -b 20 \
  -w 50 \
  --no-sleep
```

## Architecture

### Core Classes

- **`JavaFileScanner`**: Scans source directories, parses basic class information
- **`JavaClassInfo`**: Data class storing complete information for a single Java class
- **`BatchAnalyzer`**: Batch analyzer, calls API for intelligent analysis
- **`CodeIndexer`**: Index builder, generates final JSON and Markdown reports
- **`ProgressManager`**: Progress manager, tracks processing status

### Thread Safety

- `index_lock`: Protects in-memory index data
- `file_lock`: Protects file write operations
- `save_counter`: Controls save frequency (every 10 batches)

## License

MIT License

## Contributing

Issues and Pull Requests are welcome to improve the tool.
