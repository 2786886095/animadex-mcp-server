<img width="1672" height="941" alt="ChatGPT Image 2026年5月31日 18_41_15" src="https://github.com/user-attachments/assets/085bd5c3-ca3a-4326-a0ad-448d9802febb" />
# AnimaDex MCP Server 🎨

[![在线体验](https://img.shields.io/badge/在线体验-HF_Space-%23FF9D00)](https://langbai666-animadex-mcp.hf.space)
[![GitHub](https://img.shields.io/badge/GitHub-仓库-181717)](https://github.com/2786886095/animadex-mcp-server)

基于 [animadex.net](https://animadex.net) 的 AI 角色提示词搜索工具。搜索 36,000+ 动漫游戏角色，一键复制提示词和标签。

## 🌐 在线体验

无需安装，直接访问：
**https://langbai666-animadex-mcp.hf.space**

## ✨ 功能

| 功能 | 说明 |
|------|------|
| 🔍 **角色搜索** | 支持中文/英文名搜索 36,492 个角色 |
| 🎯 **提示词复制** | 一键复制 Trigger / 标签 / 全部 |
| 🏷️ **标签展示** | 头发颜色、眼睛颜色、服装等特征标签 |
| 🖼️ **缩略图预览** | 每个角色带生成图预览 |
| 📋 **批量复制** | 多选角色，批量复制提示词 |
| 🔌 **MCP 协议** | 支持 Claude Code 等 MCP 客户端 |
| 🤖 **AI 翻译** | 可配置 DeepSeek / OpenAI / Ollama 翻译 |
| 📦 **离线可用** | 首次下载后本地 SQLite 数据库搜索 |
| ⚙️ **网页设置** | 模型选择、API Key 配置等 |

## 🚀 安装与启动

### 方式一：本地运行

```bash
# 1. 克隆仓库
git clone https://github.com/2786886095/animadex-mcp-server.git
cd animadex-mcp-server

# 2. 安装依赖
install.bat

# 3. 启动服务
run.bat
```

启动后自动打开 http://127.0.0.1:11451

### 方式二：Hugging Face Spaces

[![Deploy to HF](https://img.shields.io/badge/Deploy%20to-HuggingFace%20Spaces-blue)](https://huggingface.co/spaces)

1. 在 [hf.co/spaces](https://huggingface.co/spaces) 创建新 Space，SDK 选 Docker
2. 推送本仓库代码即可

## 💻 使用方法

### 搜索角色

在搜索框输入角色名（中文或英文），选择搜索模式：

- **角色** — 搜索角色，显示触发词和标签
- **画师** — 搜索画师
- **系列** — 搜索作品系列，点击可查看该系列所有角色

### 复制提示词

每个角色卡片有 3 个复制按钮：

| 按钮 | 复制内容 |
|------|---------|
| 🎯 **角色** | Trigger（AI 绘图触发词） |
| 🏷️ **特征** | 所有特征标签 |
| 📋 **全部** | Trigger + 标签 |

也可以多选角色后通过底部栏批量复制。

### 查看详情

点击角色卡片选中/取消，**双击图片** 打开详情弹窗，查看完整信息。

## 🖼️ 缩略图

- 缩略图来自 animadex.net CDN
- 首次访问后自动缓存到 `cache/thumbs/` 目录
- 启动时后台预缓存热门角色缩略图
- 缓存过的图片无需重复下载

## ⚙️ 配置

### 切换端口

编辑 `run.bat`，修改 `set PORT=11451` 为想要的端口。

### AI 翻译

在网页右上角 **⚙️ 设置** 中配置：

| 选项 | 说明 |
|------|------|
| 翻译方式 | Google（默认）或 AI |
| API 地址 | 如 `https://api.deepseek.com` |
| API Key | 你的 API 密钥 |
| 模型 | 点击「检测模型」自动获取 |

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `11451` | 服务端口 |
| `ANIMADEX_TRANSLATOR` | `google` | 翻译后端 (`google` / `ai`) |
| `ANIMADEX_AI_TRANSLATE_URL` | - | AI 翻译 API 地址 |
| `ANIMADEX_AI_MODEL` | `qwen2.5:7b` | AI 模型名 |
| `ANIMADEX_AI_API_KEY` | - | API Key |
| `ANIMADEX_API_BASE` | `https://animadex.net` | API 镜像地址 |
| `ANIMADEX_API_TIMEOUT` | `30` | API 超时秒数 |

## 🗄️ 数据存储

```
animadex-mcp-server/
├── app.py              # 主程序
├── requirements.txt    # 依赖
├── install.bat         # 安装脚本
├── run.bat             # 启动脚本
├── cache/
│   ├── animadex.db     # SQLite 数据库（36,492 角色）
│   └── thumbs/         # 缩略图缓存
└── .venv/              # Python 虚拟环境
```

## 🔌 MCP 接口

支持两种传输方式：

| 传输 | 端点 | 说明 |
|------|------|------|
| **SSE** | `http://127.0.0.1:11451/sse` | Server-Sent Events |
| **Streamable HTTP** | `http://127.0.0.1:11451/mcp` | 流式 HTTP 传输 |

### SSE 配置示例

```json
{
  "mcpServers": {
    "animadex": {
      "type": "sse",
      "url": "http://127.0.0.1:11451/sse"
    }
  }
}
```

### Streamable HTTP 配置示例

```json
{
  "mcpServers": {
    "animadex": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:11451/mcp"
    }
  }
}
```

### MCP 工具

| 工具 | 说明 |
|------|------|
| `search-characters` | 搜索角色 |
| `get-character` | 获取角色详情 |
| `search-artists` | 搜索画师 |
| `search-copyrights` | 搜索系列 |
| `get-character-facets` | 获取筛选条件 |

## 📄 开源协议

MIT
