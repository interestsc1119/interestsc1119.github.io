"""
数据抓取脚本
抓取 GitHub Trending AI 项目 + 科技新闻
"""

import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime
import time

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
        'vector', 'rag', 'fine-tuning', 'agent', 'diffusion',
        'artificial-intelligence', 'tensorflow', 'keras', 'huggingface',
        'ollama', 'vllm', 'tgi', 'llama', 'mistral', 'gemma'
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

def fetch_zhihu_hot():
    """抓取知乎热榜"""
    news = []
    try:
        url = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=10"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            for i, item in enumerate(data.get('data', [])[:10], 1):
                news.append({
                    'rank': i,
                    'title': item.get('target', {}).get('title', ''),
                    'url': f"https://www.zhihu.com/question/{item.get('target', {}).get('id', '')}",
                    'source': '知乎',
                    'hot_value': item.get('detail_text', ''),
                    'is_hot': i <= 3
                })
    except Exception as e:
        print(f"抓取知乎失败: {e}")
    return news

def fetch_weibo_hot():
    """抓取微博热搜"""
    news = []
    try:
        url = "https://weibo.com/ajax/statuses/hot_band"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'https://weibo.com'
        }
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            band_list = data.get('data', {}).get('band_list', [])
            for i, item in enumerate(band_list[:10], 1):
                if isinstance(item, dict):
                    news.append({
                        'rank': i,
                        'title': item.get('word', ''),
                        'url': f"https://s.weibo.com/weibo?q={item.get('word', '')}",
                        'source': '微博',
                        'hot_value': item.get('num', ''),
                        'is_hot': i <= 3
                    })
    except Exception as e:
        print(f"抓取微博失败: {e}")
    return news

def fetch_36kr_news():
    """抓取 36氪科技新闻"""
    news = []
    try:
        url = "https://36kr.com/api/newsflash/index?per_page=10&page=1"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            items = data.get('data', {}).get('items', [])
            for i, item in enumerate(items[:10], 1):
                news.append({
                    'rank': i,
                    'title': item.get('title', ''),
                    'url': item.get('news_url', ''),
                    'source': '36氪',
                    'hot_value': '',
                    'is_hot': False
                })
    except Exception as e:
        print(f"抓取36氪失败: {e}")
    return news

def save_data(projects, ai_projects, news_list):
    """保存数据到 JSON 文件"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    # AI 项目数据
    ai_data = {
        'date': today,
        'updated_at': datetime.now().isoformat(),
        'count': len(ai_projects),
        'projects': ai_projects
    }
    
    # 全部项目数据
    all_data = {
        'date': today,
        'updated_at': datetime.now().isoformat(),
        'total_count': len(projects),
        'ai_count': len(ai_projects),
        'projects': projects
    }
    
    # 新闻数据
    news_data = {
        'date': today,
        'updated_at': datetime.now().isoformat(),
        'count': len(news_list),
        'news': news_list
    }
    
    # 历史数据（追加）
    history_file = 'data/history.json'
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except:
        history = []
    
    # 检查今天是否已有记录，有则更新，无则追加
    today_exists = False
    for i, h in enumerate(history):
        if h['date'] == today:
            history[i]['ai_count'] = len(ai_projects)
            history[i]['news_count'] = len(news_list)
            history[i]['ai_projects'] = [{'name': p['full_name'], 'stars': p['stars'], 'url': p['url']} for p in ai_projects[:5]]
            history[i]['top_news'] = [{'title': n['title'][:30], 'source': n['source']} for n in news_list[:5]]
            today_exists = True
            break
    
    if not today_exists:
        history.append({
            'date': today,
            'ai_count': len(ai_projects),
            'news_count': len(news_list),
            'ai_projects': [{'name': p['full_name'], 'stars': p['stars'], 'url': p['url']} for p in ai_projects[:5]],
            'top_news': [{'title': n['title'][:30], 'source': n['source']} for n in news_list[:5]]
        })
    
    # 只保留最近 30 天数据
    history = history[-30:]
    
    # 保存文件
    with open('data/daily.json', 'w', encoding='utf-8') as f:
        json.dump(ai_data, f, ensure_ascii=False, indent=2)
    
    with open('data/all.json', 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    
    with open('data/news.json', 'w', encoding='utf-8') as f:
        json.dump(news_data, f, ensure_ascii=False, indent=2)
    
    with open('data/history.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 数据已保存:")
    print(f"   - AI 项目: {len(ai_projects)} 个")
    print(f"   - 科技新闻: {len(news_list)} 条")

def main():
    print("🚀 开始抓取数据...")
    
    # 抓取 GitHub Trending
    print("📦 抓取 GitHub Trending...")
    html = fetch_github_trending()
    projects = parse_trending_data(html)
    ai_projects = [p for p in projects if p['is_ai_related']]
    
    # 抓取新闻（多个源）
    print("📰 抓取科技新闻...")
    all_news = []
    
    zhihu_news = fetch_zhihu_hot()
    all_news.extend(zhihu_news)
    print(f"   - 知乎: {len(zhihu_news)} 条")
    
    time.sleep(0.5)
    
    weibo_news = fetch_weibo_hot()
    all_news.extend(weibo_news)
    print(f"   - 微博: {len(weibo_news)} 条")
    
    time.sleep(0.5)
    
    kr36_news = fetch_36kr_news()
    all_news.extend(kr36_news)
    print(f"   - 36氪: {len(kr36_news)} 条")
    
    # 按热度排序，取前 20 条
    all_news.sort(key=lambda x: x['rank'])
    news_list = all_news[:20]
    
    # 更新排名
    for i, news in enumerate(news_list, 1):
        news['rank'] = i
    
    save_data(projects, ai_projects, news_list)
    print(f"📊 抓取完成! AI 项目: {len(ai_projects)}/{len(projects)}, 新闻: {len(news_list)}")

if __name__ == '__main__':
    main()
