"""
GitHub Trending AI 项目抓取脚本
抓取 GitHub Trending 页面中与 AI/ML 相关的热门项目
"""

import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

def fetch_github_trending():
    """抓取 GitHub Trending 页面"""
    url = "https://github.com/trending"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text

def parse_trending_data(html):
    """解析 Trending 页面，提取项目信息"""
    soup = BeautifulSoup(html, 'lxml')
    articles = soup.find_all('article', class_='Box-row')
    
    projects = []
    # AI 相关关键词
    ai_keywords = [
        'ai', 'machine-learning', 'ml', 'deep-learning', 'neural',
        'gpt', 'llm', 'transformer', 'nlp', 'cv', 'computer-vision',
        'stable-diffusion', 'langchain', 'pytorch', 'tensorflow',
        'chatbot', 'openai', 'claude', 'gemini', 'embedding',
        'vector', 'rag', 'fine-tuning', 'agent', 'diffusion'
    ]
    
    for article in articles:
        try:
            # 项目名称
            repo_link = article.find('h2', class_='h3')
            if not repo_link:
                continue
            repo_link = repo_link.find('a')
            repo_path = repo_link.get('href', '').strip('/')
            
            # 获取完整项目信息
            owner, name = repo_path.split('/') if '/' in repo_path else ('', repo_path)
            
            # 描述
            desc_elem = article.find('p', class_='col-9')
            description = desc_elem.get_text(strip=True) if desc_elem else ''
            
            # Star 数量
            star_elem = article.find('a', class_='Link--muted')
            stars = star_elem.get_text(strip=True).replace(',', '') if star_elem else '0'
            
            # 检查是否为 AI 相关项目
            repo_text = f"{name} {description} {repo_path}".lower()
            is_ai_related = any(keyword in repo_text for keyword in ai_keywords)
            
            # 今天 star 数增长（如果有）
            star_today = ''
            star_today_elem = article.find('span', class_='d-inline-block')
            if star_today_elem:
                star_today = star_today_elem.get_text(strip=True)
            
            project = {
                'owner': owner,
                'name': name,
                'full_name': repo_path,
                'description': description,
                'stars': stars,
                'stars_today': star_today,
                'url': f'https://github.com/{repo_path}',
                'is_ai_related': is_ai_related
            }
            projects.append(project)
            
        except Exception as e:
            print(f"解析项目出错: {e}")
            continue
    
    return projects

def get_ai_projects(projects):
    """筛选 AI 相关项目"""
    return [p for p in projects if p['is_ai_related']]

def save_data(projects, ai_projects):
    """保存数据到 JSON 文件"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 全部项目数据
    all_data = {
        'date': today,
        'updated_at': datetime.now().isoformat(),
        'total_count': len(projects),
        'ai_count': len(ai_projects),
        'projects': projects
    }
    
    # AI 项目数据（主要展示）
    ai_data = {
        'date': today,
        'updated_at': datetime.now().isoformat(),
        'count': len(ai_projects),
        'projects': ai_projects
    }
    
    # 历史数据（追加）
    history_file = 'data/history.json'
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except:
        history = []
    
    history.append({
        'date': today,
        'count': len(ai_projects),
        'ai_projects': [{'name': p['full_name'], 'stars': p['stars'], 'url': p['url']} for p in ai_projects[:10]]
    })
    
    # 只保留最近 30 天数据
    history = history[-30:]
    
    with open(f'data/daily.json', 'w', encoding='utf-8') as f:
        json.dump(ai_data, f, ensure_ascii=False, indent=2)
    
    with open(f'data/all.json', 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    
    with open('data/history.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 数据已保存: 今日 AI 项目 {len(ai_projects)} 个，总项目 {len(projects)} 个")

def main():
    print("🚀 开始抓取 GitHub Trending...")
    html = fetch_github_trending()
    projects = parse_trending_data(html)
    ai_projects = get_ai_projects(projects)
    save_data(projects, ai_projects)
    print(f"📊 抓取完成! AI 相关项目: {len(ai_projects)}/{len(projects)}")

if __name__ == '__main__':
    main()
