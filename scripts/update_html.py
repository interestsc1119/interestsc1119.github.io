"""
更新 index.html 脚本
将今日数据嵌入到网页中
"""

import json
import os

def update_html():
    """读取今日数据并更新 HTML"""
    
    # 读取今日数据
    with open('data/daily.json', 'r', encoding='utf-8') as f:
        daily_data = json.load(f)
    
    # 读取历史数据
    try:
        with open('data/history.json', 'r', encoding='utf-8') as f:
            history = json.load(f)
    except:
        history = []
    
    # 生成项目卡片 HTML
    projects_html = ''
    for i, project in enumerate(daily_data['projects'][:20], 1):
        stars_display = project.get('stars', '0')
        stars_today = project.get('stars_today', '')
        
        projects_html += f'''
        <div class="project-card">
            <div class="project-header">
                <span class="project-rank">#{i}</span>
                <h3 class="project-name">
                    <a href="{project['url']}" target="_blank">{project['full_name']}</a>
                </h3>
            </div>
            <p class="project-desc">{project.get('description', '暂无描述')}</p>
            <div class="project-stats">
                <span class="stat">
                    <svg class="star-icon" viewBox="0 0 16 16" width="16" height="16">
                        <path d="M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.75.75 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z"/></svg>
                    {stars_display}
                </span>
                {f'<span class="stat today">📈 今日 +{stars_today}</span>' if stars_today else ''}
                <a href="{project['url']}" class="view-btn" target="_blank">查看 →</a>
            </div>
        </div>
        '''
    
    # 生成历史趋势图数据
    history_chart_data = {
        'labels': [h['date'] for h in history[-14:]],
        'values': [h['count'] for h in history[-14:]]
    }
    
    # 读取 HTML 模板
    with open('index.template.html', 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # 替换占位符
    html_content = html_content.replace('{{PROJECTS_HTML}}', projects_html)
    html_content = html_content.replace('{{UPDATE_DATE}}', daily_data['date'])
    html_content = html_content.replace('{{PROJECT_COUNT}}', str(daily_data['count']))
    html_content = html_content.replace('{{HISTORY_DATA}}', json.dumps(history_chart_data))
    html_content = html_content.replace('{{RECENT_DATES}}', json.dumps(history[-7:] if len(history) >= 7 else history))
    
    # 保存更新后的 HTML
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✅ index.html 已更新: {daily_data['count']} 个 AI 项目")

if __name__ == '__main__':
    update_html()
