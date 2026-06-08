# 📊 每日精选

每日自动更新 AI 热门项目 + 科技热点资讯

## 📋 功能特点

- **🤖 AI 项目模块**：每日抓取 GitHub Trending 中 AI/ML 相关热门项目
- **📰 科技新闻模块**：聚合知乎热榜、36氪、IT之家、搜狐科技等科技资讯
- **📈 趋势可视化**：展示近 14 天数据趋势
- **📅 历史记录**：保留最近 30 天数据
- **🔄 自动更新**：北京时间每天 9:00 自动抓取

## 🌐 访问地址

**https://interestsc1119.github.io**

## 🛠️ 技术架构

- **数据源**：GitHub Trending + 知乎/36氪/IT之家/搜狐科技
- **自动化**：GitHub Actions
- **托管**：GitHub Pages
- **语言**：Python + HTML/CSS/JS

## 📁 项目结构

```
├── .github/workflows/     # GitHub Actions 配置
├── scripts/
│   ├── fetch_trending.py  # 抓取 AI 项目 + 新闻
│   └── update_html.py     # 更新网页
├── data/                  # JSON 数据文件
│   ├── daily.json         # 今日 AI 项目
│   ├── news.json          # 今日科技新闻
│   └── history.json       # 历史记录
├── index.template.html    # 网页模板
└── README.md             # 说明文档
```

## 🚀 手动触发更新

1. 进入 Actions 页面
2. 选择 "Daily AI & News Update"
3. 点击 "Run workflow"
