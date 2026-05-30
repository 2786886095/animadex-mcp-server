# AnimaDex MCP Server

基于 animadex.net 的角色提示词搜索工具。

## 国内加速配置

### 1. 翻译加速（Google Translate 被墙）

使用 DeepSeek API（国内可访问）：

```batch
set ANIMADEX_TRANSLATOR=ai
set ANIMADEX_AI_TRANSLATE_URL=https://api.deepseek.com/v1/chat/completions
set ANIMADEX_AI_MODEL=deepseek-chat
set ANIMADEX_AI_API_KEY=sk-your-key
```

### 2. API 镜像

```batch
set ANIMADEX_API_BASE=https://animadex.net
set ANIMADEX_API_TIMEOUT=60
```

### 3. 图片缓存

图片首次访问后自动缓存到 `cache/thumbs/` 目录，下次无需重复下载。

## 快速启动

```batch
install.bat   # 首次安装
run.bat       # 启动服务
```

访问 http://127.0.0.1:11451
